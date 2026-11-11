#!/usr/bin/env python3
"""用 cookies.txt + wbi 签名取 B站官方 AI 字幕（仅标准库，零第三方依赖）。

设计红线：
  拿不到字幕就返回明确的状态码（NEED_LOGIN / NO_SUBTITLE / RISK_CONTROL / ERROR）。
  绝不用标题、简介、评论、弹幕或外部资料拼一份「看起来像总结」的东西 —— 那不是视频内容。

输出：字幕全文写到 --out（默认 _bili_login/subtitle.txt），stdout 只给一行
`SUBTITLE_RESULT {...}` 的结构化摘要，方便调用方判断下一步。
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import http.cookiejar
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")
DEFAULT_COOKIES = (Path.home() / ".workbuddy" / "data" /
                   "bilibili-video-summary" / "bilibili_cookies.txt")
VIEW_URL = "https://api.bilibili.com/x/web-interface/view?bvid="
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
WBI_URL = "https://api.bilibili.com/x/player/wbi/v2"

MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]


def emit(status: str, **kw) -> int:
    print("SUBTITLE_RESULT " + json.dumps(
        {"status": status, **kw}, ensure_ascii=False), flush=True)
    return 0 if status == "OK" else 1


def parse_input(s: str) -> tuple[str, int]:
    """返回 (bvid, page)。支持完整链接、裸 BV 号、b23.tv 短链、?p=N。"""
    page = 1
    m = re.search(r"[?&]p=(\d+)", s)
    if m:
        page = max(1, int(m.group(1)))
    if "b23.tv" in s:
        try:
            req = urllib.request.Request(s, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                s = r.geturl()
        except Exception as e:
            raise ValueError(f"短链解析失败: {type(e).__name__}: {e}")
    m = re.search(r"BV[0-9A-Za-z]{10}", s)
    if not m:
        raise ValueError("无法从输入中解析 BV 号")
    return m.group(0), page


def get_json(opener, url: str, referer: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    })
    with opener.open(req, timeout=20) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def ts(sec: float) -> str:
    t = int(sec or 0)
    return f"[{t // 60:02d}:{t % 60:02d}]"


def main() -> int:
    ap = argparse.ArgumentParser(description="取 B站官方 AI 字幕")
    ap.add_argument("url", help="B站链接 / BV号 / b23.tv 短链")
    ap.add_argument("--page", type=int, default=0, help="分P序号（覆盖 URL 的 p=）")
    ap.add_argument("--cookies", default=str(DEFAULT_COOKIES))
    ap.add_argument("--out", default="", help="字幕文本输出路径")
    ap.add_argument("--no-timestamps", action="store_true", help="只输出纯文本")
    a = ap.parse_args()

    try:
        bvid, page = parse_input(a.url)
    except ValueError as e:
        return emit("ERROR", error=str(e))
    if a.page:
        page = a.page

    cookies = Path(a.cookies)
    out = Path(a.out) if a.out else Path.cwd() / "_bili_login" / "subtitle.txt"
    page_url = f"https://www.bilibili.com/video/{bvid}/"

    if not cookies.exists():
        return emit("NEED_LOGIN", error="cookies.txt 不存在",
                    hint="先跑 bili_login.py --check；无效则 --prepare 后立刻 --poll 扫码")
    jar = http.cookiejar.MozillaCookieJar(str(cookies))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as e:
        return emit("NEED_LOGIN", error=f"cookies.txt 读取失败: {e}")
    if not any(c.name == "SESSDATA" for c in jar):
        return emit("NEED_LOGIN", error="cookies.txt 无 SESSDATA",
                    hint="登录态已失效，重新扫码")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    # 1) 视频元数据 + 分P
    try:
        v = get_json(opener, VIEW_URL + bvid, page_url)
    except Exception as e:
        return emit("ERROR", error=f"view 接口失败: {type(e).__name__}: {e}")
    if v.get("code") != 0 or not (v.get("data") or {}):
        return emit("ERROR", error=f"view 返回 {v.get('code')}: {v.get('message')}")
    d = v["data"]
    pages = d.get("pages") or []
    if page > len(pages):
        return emit("ERROR", error=f"分P {page} 不存在，共 {len(pages)} P")
    p = pages[page - 1]
    aid, cid = d.get("aid"), p.get("cid")
    meta = {
        "bvid": bvid, "aid": aid, "cid": cid, "title": d.get("title"),
        "owner": (d.get("owner") or {}).get("name"),
        "duration": p.get("duration") or d.get("duration"),
        "page": page, "page_title": p.get("part"), "pages_total": len(pages),
    }

    # 2) wbi 密钥（nav 同时可确认登录态有效）
    try:
        nav = get_json(opener, NAV_URL, page_url)
        nd = nav.get("data") or {}
        if not (nd.get("isLogin") or nd.get("mid")):
            return emit("NEED_LOGIN", error="B站返回未登录（SESSDATA 已过期）",
                        hint="重新扫码登录")
        wbi = nd.get("wbi_img") or {}
        img_key = Path(wbi.get("img_url", "")).stem
        sub_key = Path(wbi.get("sub_url", "")).stem
        if not img_key or not sub_key:
            return emit("RISK_CONTROL", error="nav 未返回 wbi 密钥",
                        hint="稍后重试，或换网络出口")
        mixin_key = "".join((img_key + sub_key)[i] for i in MIXIN_TAB)[:32]
    except Exception as e:
        return emit("ERROR", error=f"nav 接口失败: {type(e).__name__}: {e}")

    # 3) 签名请求 player/wbi/v2（非签名的 player/v2 会返回空 subtitle_url）
    def safe(v):
        return re.sub(r"[!'()*]", "", str(v))

    params = {"bvid": bvid, "aid": aid, "cid": cid, "wts": int(time.time())}
    query = urllib.parse.urlencode(
        sorted((k, safe(v)) for k, v in params.items()))
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    try:
        pd = get_json(opener, f"{WBI_URL}?{query}&w_rid={w_rid}", page_url)
        pdata = pd.get("data") or {}
    except Exception as e:
        return emit("ERROR", error=f"wbi/v2 请求失败: {type(e).__name__}: {e}")

    subs = (pdata.get("subtitle") or {}).get("subtitles") or []
    if not subs:
        return emit("NO_SUBTITLE", error="该视频没有可用字幕轨", meta=meta,
                    hint="只能走本地 ASR（yt-dlp + ffmpeg + whisper）或让用户提供文字稿；"
                         "不要用简介/评论凑总结")
    pick = next((s for s in subs if s.get("lan") == "ai-zh"), None)
    if not pick:
        pick = next((s for s in subs if "zh" in (s.get("lan") or "").lower()), subs[0])
    sub_url = pick.get("subtitle_url") or ""
    if not sub_url:
        return emit("NO_SUBTITLE", error=f"字幕轨 {pick.get('lan')} 的 URL 为空",
                    meta=meta, hint="换一条字幕轨，或重新登录后再试")
    if sub_url.startswith("//"):
        sub_url = "https:" + sub_url

    try:
        body = (get_json(opener, sub_url, page_url) or {}).get("body") or []
    except Exception as e:
        return emit("ERROR", error=f"字幕下载失败: {type(e).__name__}: {e}")

    lines = []
    for it in body:
        content = (it.get("content") or "").strip()
        if not content:
            continue
        lines.append(content if a.no_timestamps
                     else f"{ts(it.get('from', 0))} {content}")
    if not lines:
        return emit("NO_SUBTITLE", error="字幕文件内容为空", meta=meta)

    text = "\n".join(lines)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (f"# {meta['title']}\n"
              f"# UP: {meta['owner']} | 分P: {page}/{len(pages)}"
              f" | 时长: {meta['duration']}s\n"
              f"# 字幕来源: {pick.get('lan')} (player/wbi/v2) | {len(lines)} 条\n\n")
    out.write_text(header + text + "\n", encoding="utf-8")

    return emit("OK", meta=meta, track=pick.get("lan"), lines=len(lines),
                chars=len(text), text_file=str(out), preview=text[:160])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
