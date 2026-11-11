#!/usr/bin/env python3
"""把文本编码成二维码，并产出三种可展示形式。

输出：
  *.svg   —— 纯 SVG fragment，直接作为 show_widget 的 widget_code
  *.png   —— 本地图片，可 present_files 作为备用
  *.html  —— 内嵌 base64 图片的自包含预览页，可 present_files 打开

安全约束：只在本地编码。绝不调用任何在线二维码生成服务 —— 登录二维码 URL
本身就是一次性登录凭据，发给第三方等同于把账号登录权交出去。

后端优先级：cv2(OpenCV) → segno → qrcode。三者都缺失时明确报错。
"""
from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path


def encode_matrix(text: str) -> tuple[list[list[int]], str]:
    """返回 1=深色模块 / 0=浅色模块 的方阵，以及所用后端名。

    坑：OpenCV QRCodeEncoder.encode() 的返回值里 0 才是深色、255 是浅色。
    写成 `> 0` 会得到黑底白块的反色二维码，手机基本扫不出来。
    """
    errors: list[str] = []

    try:
        import cv2
        raw = cv2.QRCodeEncoder_create().encode(text)
        return [[1 if v < 128 else 0 for v in row] for row in raw], "cv2"
    except ImportError:
        errors.append("cv2: 未安装")
    except Exception as e:
        errors.append(f"cv2: {type(e).__name__}: {e}")

    try:
        import segno
        qr = segno.make(text, error="m")
        return [[1 if bit else 0 for bit in row] for row in qr.matrix], "segno"
    except ImportError:
        errors.append("segno: 未安装")
    except Exception as e:
        errors.append(f"segno: {type(e).__name__}: {e}")

    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
        q = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=1, border=0)
        q.add_data(text)
        q.make(fit=True)
        return [[1 if bit else 0 for bit in row] for row in q.get_matrix()], "qrcode"
    except ImportError:
        errors.append("qrcode: 未安装")
    except Exception as e:
        errors.append(f"qrcode: {type(e).__name__}: {e}")

    raise RuntimeError(
        "无可用二维码编码后端。请安装任一：opencv-python-headless / segno / qrcode。"
        "禁止改用在线二维码服务。详情：" + "; ".join(errors)
    )


def _add_quiet_zone(matrix: list[list[int]], quiet: int = 4) -> list[list[int]]:
    n = len(matrix)
    size = n + quiet * 2
    canvas = [[0] * size for _ in range(size)]
    for y, row in enumerate(matrix):
        canvas[y + quiet][quiet:quiet + n] = row
    return canvas


def _write_png(canvas: list[list[int]], path: Path, scale: int = 9) -> None:
    flat = [[0 if v else 255 for v in row] for row in canvas]
    try:
        import cv2
        import numpy as np
        arr = np.kron(np.array(flat, dtype=np.uint8),
                      np.ones((scale, scale), dtype=np.uint8))
        cv2.imwrite(str(path), arr)
        return
    except Exception:
        pass
    from PIL import Image
    size = len(canvas)
    img = Image.new("L", (size, size))
    img.putdata([v for row in flat for v in row])
    img = img.resize((size * scale, size * scale), Image.NEAREST)
    img.save(path)


def _svg_fragment(canvas: list[list[int]], caption: str, note: str) -> str:
    caption, note = escape(caption), escape(note)
    size = len(canvas)
    segs: list[str] = []
    for y, row in enumerate(canvas):
        x = 0
        while x < size:
            if row[x]:
                x0 = x
                while x < size and row[x]:
                    x += 1
                w = x - x0
                segs.append(f"M{x0} {y}h{w}v1h-{w}z")
            else:
                x += 1
    dpath = "".join(segs)
    sc = 260 / size
    return (
        '<svg role="img" viewBox="0 0 680 380" width="100%" '
        'xmlns="http://www.w3.org/2000/svg">\n'
        f'<title>{caption}</title><desc>{note}</desc>\n'
        '<rect x="40" y="40" width="600" height="320" rx="12" '
        'fill="var(--color-background-secondary)" '
        'stroke="var(--color-border-tertiary)" stroke-width="0.5"/>\n'
        '<rect x="70" y="70" width="260" height="260" fill="#ffffff"/>\n'
        f'<g transform="translate(70 70) scale({sc:.4f})" fill="#000000">'
        f'<path d="{dpath}"/></g>\n'
        '<text x="360" y="112" font-family="var(--font-sans)" font-size="15" '
        'font-weight="500" fill="var(--color-text-primary)">'
        f'{caption}</text>\n'
        '<text x="360" y="152" font-family="var(--font-sans)" font-size="13" '
        'fill="var(--color-text-primary)">用手机 B 站 App 扫一扫，点「确认登录」</text>\n'
        '<text x="360" y="180" font-family="var(--font-sans)" font-size="13" '
        'fill="var(--color-text-primary)">确认后自动继续取字幕</text>\n'
        '<text x="360" y="226" font-family="var(--font-sans)" font-size="12" '
        'fill="var(--color-text-secondary)">二维码约 3 分钟内有效，仅在本机生成</text>\n'
        '<text x="360" y="252" font-family="var(--font-sans)" font-size="12" '
        'fill="var(--color-text-secondary)">不想扫码可手动提供 SESSDATA</text>\n'
        '</svg>'
    )


def render(text: str, out_dir: Path, prefix: str = "bili_login_qr") -> dict:
    """生成三种展示文件并做可扫性自检，返回路径与状态字典。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix, backend = encode_matrix(text)
    canvas = _add_quiet_zone(matrix)

    png = out_dir / f"{prefix}.png"
    svg = out_dir / f"{prefix}.svg"
    html = out_dir / f"{prefix}.html"

    _write_png(canvas, png)
    svg.write_text(
        _svg_fragment(canvas, "B站扫码登录", "用手机 B 站 App 扫描并确认登录"),
        encoding="utf-8",
    )

    b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    html.write_text(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>B站扫码登录</title><style>'
        'body{margin:0;padding:36px;background:#f7f7f8;color:#1f1f22;'
        'font-family:system-ui,"Microsoft YaHei",sans-serif;display:flex;justify-content:center}'
        '.card{background:#fff;border:1px solid #e5e5e8;border-radius:16px;'
        'padding:28px 32px;display:flex;gap:28px;align-items:center;max-width:760px}'
        'img{width:320px;height:320px;image-rendering:pixelated;background:#fff}'
        'h1{font-size:20px;font-weight:600;margin:0 0 14px}'
        'p{font-size:15px;line-height:1.8;margin:0 0 10px}'
        '.muted{color:#777;font-size:13px;margin-top:18px}'
        '</style></head><body><div class="card">'
        f'<img alt="B站登录二维码" src="data:image/png;base64,{b64}"/>'
        '<div><h1>用手机 B 站 App 扫一扫</h1>'
        '<p>打开 App 里的「扫一扫」，扫描左侧二维码。</p>'
        '<p>在手机上点「确认登录」后，本机自动继续取字幕。</p>'
        '<p class="muted">二维码约 3 分钟内有效，仅在本机生成，不会上传。<br>'
        '不想扫码，也可以手动提供 cookies.txt。</p>'
        '</div></div></body></html>',
        encoding="utf-8",
    )

    # 自检：解码结果必须与原文完全一致，否则宁可报错也不展示一个扫不出来的码。
    selfcheck = "skipped"
    try:
        import cv2
        decoded = cv2.QRCodeDetector().detectAndDecode(cv2.imread(str(png)))[0]
        if decoded != text:
            raise RuntimeError(
                f"二维码自检失败：解码结果与原文不一致（decoded={decoded[:60]!r}）"
            )
        selfcheck = "passed"
    except RuntimeError:
        raise
    except Exception:
        # 无 cv2 时无法解码自检；segno / qrcode 的输出本身可信。
        selfcheck = "skipped"

    return {
        "svg": str(svg), "png": str(png), "html": str(html),
        "backend": backend, "modules": len(canvas), "selfcheck": selfcheck,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python qr_render.py <text> [out_dir]", file=sys.stderr)
        raise SystemExit(2)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd() / "_bili_login"
    print(json.dumps(render(sys.argv[1], out), ensure_ascii=False))
