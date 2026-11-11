#!/usr/bin/env python3
"""B站官方扫码登录：拿一次性登录态并存成 Netscape 格式 cookies.txt。

为什么需要它：运行中的 Chromium 系浏览器会独占锁住 Network/Cookies，
普通复制、SQLite 直连、CreateFileW 共享读都报 ERROR_SHARING_VIOLATION(32)；
卷影复制 / 备份模式又要管理员权限；新版 Edge 还有 app_bound 加密。
与其去撬浏览器，不如让用户用手机 App 扫一次官方二维码 —— 纯 HTTP、零第三方依赖，
登录态持久化后长期复用。

三个子命令（务必按 prepare → poll → check 的顺序使用）：
  --check              检查已有 cookies.txt 是否仍然有效（先跑这个，有效就不用扫码）
  --prepare            生成二维码三种展示文件 + session.json，立刻返回
  --poll               立刻开始轮询扫码结果，成功后写 cookies.txt
  --clean              删除本脚本生成的临时文件（仅 4 个已知文件名）

关键时序：--prepare 之后必须**立刻**在后台启动 --poll，再去展示二维码。
二维码有效期约 180 秒，中间穿插多轮工具调用会把有效期耗光。
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qr_render  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")
GEN_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header"
POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key="
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"

DEFAULT_COOKIES = (Path.home() / ".workbuddy" / "data" /
                   "bilibili-video-summary" / "bilibili_cookies.txt")
DEFAULT_OUT = Path.cwd() / "_bili_login"

STATES = {86101: "等待扫码", 86090: "已扫码，等待手机确认",
          86038: "二维码已过期", 0: "登录成功"}


def _headers(referer: str = "https://www.bilibili.com/") -> dict:
    return {"User-Agent": UA, "Referer": referer,
            "Accept": "application/json, text/plain, */*"}


def _get_json(opener, url: str, referer: str = "https://www.bilibili.com/") -> dict:
    with opener.open(urllib.request.Request(url, headers=_headers(referer)), timeout=15) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def cmd_check(cookies: Path) -> int:
    result = {"valid": False, "has_SESSDATA": False, "file": str(cookies)}
    if cookies.exists():
        try:
            jar = http.cookiejar.MozillaCookieJar(str(cookies))
            jar.load(ignore_discard=True, ignore_expires=True)
            result["has_SESSDATA"] = any(c.name == "SESSDATA" for c in jar)
            if result["has_SESSDATA"]:
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
                d = _get_json(opener, NAV_URL)
                data = d.get("data") or {}
                result["valid"] = bool(data.get("isLogin")) or bool(data.get("mid"))
                result["nav_code"] = d.get("code")
        except Exception as e:
            result["error"] = f"{type(e).__name__}: {e}"
    if not result["valid"]:
        result["hint"] = "跑一遍 --prepare 然后立刻 --poll 扫码登录"
    print("LOGIN_STATUS " + json.dumps(result, ensure_ascii=False), flush=True)
    return 0


def cmd_prepare(out_dir: Path) -> int:
    try:
        d = _get_json(urllib.request.build_opener(), GEN_URL,
                      "https://passport.bilibili.com/login")
    except Exception as e:
        print("QR_GEN_FAILED " + json.dumps(
            {"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False), flush=True)
        return 1
    data = d.get("data") or {}
    key, url = data.get("qrcode_key"), data.get("url")
    if not key or not url:
        print("QR_GEN_FAILED " + json.dumps(
            {"code": d.get("code"), "message": d.get("message")}, ensure_ascii=False), flush=True)
        return 1

    try:
        rendered = qr_render.render(url, out_dir)
    except Exception as e:
        print("QR_RENDER_FAILED " + json.dumps(
            {"error": str(e)}, ensure_ascii=False), flush=True)
        return 1

    session = out_dir / "session.json"
    session.write_text(json.dumps(
        {"qrcode_key": key, "url": url, "ts": time.time()}, ensure_ascii=False),
        encoding="utf-8")
    print("QR_READY " + json.dumps(
        {**rendered, "session": str(session), "expires_in_sec": 180},
        ensure_ascii=False), flush=True)
    return 0


def cmd_poll(out_dir: Path, cookies: Path, timeout: int) -> int:
    session = out_dir / "session.json"
    if not session.exists():
        print("POLL_FAILED " + json.dumps(
            {"error": "session.json 不存在，请先跑 --prepare"}, ensure_ascii=False), flush=True)
        return 1
    sess = json.loads(session.read_text(encoding="utf-8"))
    key = sess["qrcode_key"]

    jar = http.cookiejar.MozillaCookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        # 预热游客 Cookie（buvid3 / b_nut 等），登录响应会基于它们补齐
        with opener.open(urllib.request.Request(
                "https://www.bilibili.com/", headers=_headers()), timeout=15) as r:
            r.read(512)
    except Exception:
        pass

    poll = POLL_URL + urllib.parse.quote(key)
    last = None
    for i in range(max(1, timeout // 2)):
        try:
            d = _get_json(opener, poll, "https://passport.bilibili.com/login")
        except Exception as e:
            print(f"[{i * 2}s] 网络异常 {type(e).__name__}，重试", flush=True)
            time.sleep(2)
            continue
        data = d.get("data") if isinstance(d.get("data"), dict) else {}
        code = data.get("code", d.get("code"))
        if code != last:
            print(f"[{i * 2}s] {STATES.get(code, code)}", flush=True)
            last = code

        if code == 0:
            gourl = data.get("url") or ""
            if isinstance(gourl, str) and gourl.startswith("http"):
                try:
                    with opener.open(urllib.request.Request(
                            gourl, headers=_headers()), timeout=15) as r:
                        r.read(512)
                except Exception:
                    pass
            names = sorted({c.name for c in jar})
            cookies.parent.mkdir(parents=True, exist_ok=True)
            jar.save(str(cookies), ignore_discard=True, ignore_expires=True)
            print("LOGIN_OK " + json.dumps({
                "has_SESSDATA": "SESSDATA" in names,
                "cookie_names": names, "file": str(cookies),
                "bytes": cookies.stat().st_size,
            }, ensure_ascii=False), flush=True)
            # 二维码已消费，立刻抹掉含登录 URL 的临时会话文件
            try:
                session.unlink()
            except OSError:
                pass
            return 0
        if code == 86038:
            print("LOGIN_EXPIRED 二维码已过期，重新跑 --prepare", flush=True)
            return 2
        time.sleep(2)
    print("LOGIN_TIMEOUT 未检测到扫码确认", flush=True)
    return 3


def cmd_clean(out_dir: Path) -> int:
    removed = []
    for name in ("bili_login_qr.png", "bili_login_qr.svg",
                 "bili_login_qr.html", "session.json"):
        p = out_dir / name
        if p.exists():
            p.unlink()
            removed.append(name)
    print(json.dumps({"removed": removed}, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="B站扫码登录（本地二维码 + cookies.txt）")
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument("--check", action="store_true", help="检查已有登录态是否有效")
    m.add_argument("--prepare", action="store_true", help="生成二维码与 session.json")
    m.add_argument("--poll", action="store_true", help="立即开始轮询扫码结果")
    m.add_argument("--clean", action="store_true", help="清除本脚本生成的临时文件")
    ap.add_argument("--cookies", default=str(DEFAULT_COOKIES), help="cookies.txt 路径")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT), help="二维码临时文件目录")
    ap.add_argument("--timeout", type=int, default=180, help="轮询总时长（秒）")
    a = ap.parse_args()

    out_dir, cookies = Path(a.out_dir), Path(a.cookies)
    if a.check:
        return cmd_check(cookies)
    if a.prepare:
        return cmd_prepare(out_dir)
    if a.poll:
        return cmd_poll(out_dir, cookies, a.timeout)
    return cmd_clean(out_dir)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("INTERRUPTED", flush=True)
        raise SystemExit(130)
