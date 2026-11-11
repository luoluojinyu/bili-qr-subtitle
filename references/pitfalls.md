# 排障与已验证的坑

只在出现异常时读本文件。以下均为 2026-11-11/12 在 Windows 本机实测结论。

## 1. 别在「读浏览器 Cookie」上耗时间

用户说「我已经登录 B 站了」并不等于脚本能拿到登录态。运行中 Chromium 系浏览器
（Edge / WebView2 / 360se6 / Quark）把 `User Data/Default/Network/Cookies` 独占锁死：

| 尝试 | 结果 |
|---|---|
| `shutil.copy2` 复制后 SQLite 只读 | ERROR_SHARING_VIOLATION (32) |
| `sqlite3` 直连 `mode=ro&immutable=1` | 同样被锁 |
| `CreateFileW` + FILE_SHARE_READ/WRITE/DELETE 共享读 | 错误 32 |
| `esentutl /y /vss`（卷影复制） | 0x80070005，需管理员/备份权限 |
| `robocopy /B`（备份模式） | 同上，被拒 |

新版 Edge 还启用 `app_bound_encrypted_key`，即使拿到库也解不出明文。可读的其它库
（Quark / Steam htmlcache / 百度网盘）里只有游客 Cookie，没有 SESSDATA。
**结论：直接走官方扫码登录，一次投入、长期复用。**

## 2. 二维码反色

`cv2.QRCodeEncoder_create().encode(url)` 返回的矩阵里 **0 = 深色模块、255 = 浅色**。
写成 `> 0` 判断会得到黑底白块，手机基本扫不出（曾导致用户反馈「扫不了」）。
正确做法：`1 if v < 128 else 0`；生成 PNG 后用
`cv2.QRCodeDetector().detectAndDecode()` 解码，**要求解码结果 == 原 URL**，
不一致就中止，绝不展示一个可能扫不出的码。

## 3. 内联组件里的本地图片不显示

Visualizer 的 HTML widget 中 `<img src="C:/绝对路径">` 实测不渲染
（用户反馈「二维码看不到」）。可靠组合：
① 把二维码画成纯 SVG `<path>`，直接作为 `show_widget` 的 `widget_code`；
② 另生成内嵌 base64 图片的 `.html`，用 `present_files` 打开独立预览页；
③ PNG 作为备用文件一并 `present_files`。
二维码区域必须白底黑块（`fill="#ffffff"` 硬编码），周围卡片/文字用主题 CSS 变量。

## 4. 时序：先启动轮询，再展示

二维码有效期约 180 秒。曾出现「生成二维码 → 穿插若干工具调用 → 才开始轮询」，
中间耗掉约 90 秒，轮询到 88 秒时二维码过期、全程没检测到扫码。
正确顺序：`--prepare`（前台，约 1 秒）→ **下一个调用立刻在后台启动 `--poll`**
→ 再 `show_widget` / `present_files` → 最后等后台结果。
`--poll` 状态：86101 等待扫码 / 86090 已扫待确认 / 86038 过期 / 0 成功。
成功时务必带着同一个 cookiejar 访问一次 `data.url`，否则拿不到 Set-Cookie。

## 5. wbi 签名

- 非签名的 `x/player/v2` 在需要登录的 AI 字幕上会返回**空** `subtitle_url`，
  必须用 `x/player/wbi/v2` + `w_rid`。
- 密钥来自 `x/web-interface/nav` 的 `wbi_img.img_url` / `sub_url` 的**文件名（不含扩展名）**，
  拼接后按固定 64 位置换表取前 32 位得 `mixin_key`；
  再对 `wts + 参数字典序 + mixin_key` 做 MD5。参数值需过滤 `!'()*`。
- `subtitle_url` 常以 `//` 开头，要补 `https:`。
- 字幕 JSON 的 `body[].content` / `body[].from` 即逐条文本与起始秒数。

## 6. 隐私与安全边界

- 登录二维码 URL 是一次性凭据，**只在本地编码**，绝不调用在线二维码服务。
- `session.json` 含该 URL，登录成功后脚本自动删除；`--clean` 可清掉其余临时文件。
- `cookies.txt` 含 `SESSDATA` / `bili_jct` / `DedeUserID`，等同账号登录态：
  不外传、不提交到仓库、不在日志里打印值，只打印字段名。
- 不主动读取用户浏览器凭据，不主动索要 Cookie 明文；扫码是用户主动授权的动作。
- 已有技能里的「强制归档到 IMA 知识库」是不可逆外部写入，未经用户确认不要执行。

## 7. 已验证环境

系统 Python 3.13.14 + cv2 5.0.0 + numpy 2.5.4 + Pillow；`segno` / `qrcode` 未装。
`fetch_subtitle.py` 只用标准库。实测 `ai-zh` 字幕 349 条 / 4502 字（12 分 19 秒视频），
全程不需要 yt-dlp / ffmpeg / faster-whisper / playwright / 浏览器 Cookie。
