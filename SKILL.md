---
name: bili-qr-subtitle
description: 用 B 站官方扫码登录取得登录态（cookies.txt），再以 wbi 签名零依赖取官方 AI 字幕，生成基于真实字幕的中文总结。当用户要总结 bilibili 视频、给出 BV 号或 b23.tv 链接、技能返回 need_login / 浏览器 Cookie 读不出来、或不装依赖就要字幕时使用；也可为 bilibili-video-summary 补登录态。Do NOT 用于 YouTube、抖音、本地视频，或用简介评论凑总结。
license: MIT
metadata: {"version": "1.0.0", "author": "luoluojinyu", "homepage": "https://github.com/luoluojinyu/bili-qr-subtitle", "repository": "https://github.com/luoluojinyu/bili-qr-subtitle", "tags": ["bilibili", "subtitle", "video-summary", "qr-login", "wbi"], "category": "productivity", "platforms": ["workbuddy", "claude-code"]}
---

# B站扫码登录 → 官方字幕 → 总结

本技能把「读浏览器 Cookie」这一步整个绕过去：运行中的 Chromium 系浏览器会独占锁住
Cookie 数据库且常有 app_bound 加密，撬它既费时又需要管理员权限。改用 B 站官方二维码
登录一次，登录态持久化到 cookies.txt，之后所有取字幕请求都走纯 HTTP。

## 必须遵守的约束

1. **只用真实字幕（或用户提供的文字稿 / ASR 结果）总结。** 拿不到字幕就明确报失败，
   绝不用标题、简介、评论、弹幕或外部报道拼出一份「看起来像总结」的内容。
2. **二维码只在本地生成。** 绝不调用在线二维码 API、不把登录 URL 发往第三方 ——
   登录二维码 URL 本身就是一次性登录凭据。
3. **不输出、不索要凭据明文。** cookies.txt 含 SESSDATA / bili_jct，等同账号登录态；
   日志里只允许出现 cookie 的**字段名**，不出现值。
4. **不擅自安装依赖或做不可逆外部写入**（例如 IMA 知识库归档），除非用户明确确认。
5. 二维码渲染自检失败（`QR_RENDER_FAILED` 或解码结果与原文不一致）时停止，
   不要展示一个扫不出来的码。

## 权限声明

| 能力类别 | 是否使用 | 说明 |
|---|---|---|
| 网络访问 | ✅ | 仅 `api.bilibili.com`、`passport.bilibili.com`、`www.bilibili.com` 及接口返回的字幕 CDN（`*.hdslb.com`）；不调用在线二维码服务，不向第三方发送视频链接或登录信息 |
| 文件读写 | ✅ | 读本技能目录脚本；写 `cookies.txt`（默认 `~/.workbuddy/data/bilibili-video-summary/`）与当前工作区 `_bili_login/` 下的二维码、字幕临时文件；登录成功后自动删除含登录 URL 的 `session.json`，`--clean` 可清理 |
| 环境变量 | ❌ | 不读取任何环境变量，不需要 API key |
| subprocess | ❌ | 三个脚本均不调用外部命令、不启动子进程；`python` 脚本本身由智能体执行 |
| 外部 API | ✅ | 仅 B 站官方 web 接口：`x/web-interface/nav`、`x/player/wbi/v2`、二维码生成/轮询接口与字幕 CDN |

**用户警告**：扫码会以用户本人的 B 站账号建立登录态，`cookies.txt` 会落盘且等同账号凭据。
执行前必须告知用户，绝不提交到仓库、绝不明文输出或外传。

## 决策流程

```
B站链接 / BV号
  → bili_login.py --check
      有效 ──────────────────────────────┐
      无效 → --prepare（前台）           │
             → --poll（后台，立刻启动）  │
             → 展示二维码 → 等 LOGIN_OK ─┤
                                        ↓
                        fetch_subtitle.py <url>
                          OK → 通读全文 → 核查 → 成文
                          NEED_LOGIN / NO_SUBTITLE / RISK_CONTROL → 按状态表处理
```

## Step 0 · 定位脚本

`SKILL_DIR` = 本 SKILL.md 所在目录（本机为
`C:/Users/Admin/.workbuddy/skills/bili-qr-subtitle`）。
用系统 `python`（Windows 上不要写 `python3`）。二维码渲染需要 `cv2` / `segno` /
`qrcode` 三者之一；本机 `cv2` 已验证可用，取字幕部分只用标准库。

把二维码临时文件放到当前工作区：`OUT="<CWD>/_bili_login"`。

## Step 1 · 先查已有登录态

```bash
python "$SKILL_DIR/scripts/bili_login.py" --check --out-dir "$OUT"
```

读 `LOGIN_STATUS` 后的 JSON：`valid: true` 直接跳到 Step 3。`valid: false` 才需要扫码。
默认 cookies 路径是 `~/.workbuddy/data/bilibili-video-summary/bilibili_cookies.txt`，
与已装的 `bilibili-video-summary` 共用，登录一次两边都能用；可用 `--cookies` 覆盖。

## Step 2 · 扫码（严格按此顺序，低自由度）

```bash
python "$SKILL_DIR/scripts/bili_login.py" --prepare --out-dir "$OUT"
```

这条命令约 1 秒返回 `QR_READY`，内含 `svg` / `png` / `html` 路径与 `selfcheck`。
**下一个工具调用就必须是在后台启动轮询** —— 二维码有效期约 180 秒，中间穿插多轮
工具调用会把有效期耗光（实测曾白白耗掉 90 秒）：

```bash
python "$SKILL_DIR/scripts/bili_login.py" --poll --out-dir "$OUT" --timeout 180
```

轮询启动后再展示：
- 读 `$OUT/bili_login_qr.svg` 的**文件内容**，原样作为 `show_widget` 的 `widget_code`
  （纯 SVG 图形，不引用任何本地图片路径）。
- 用 `present_files` 打开 `$OUT/bili_login_qr.html`（内嵌 base64 图片的独立预览页）
  和 `$OUT/bili_login_qr.png` 作为备用。

然后等后台任务结果：`LOGIN_OK` → Step 3；`LOGIN_EXPIRED` → 重新 prepare + poll 一次；
`LOGIN_TIMEOUT` → 询问用户是否重试，不要自动反复生成。成功后脚本会自行删除含登录
URL 的 `session.json`。收尾可跑 `--clean` 清掉二维码临时文件。

## Step 3 · 取官方 AI 字幕

```bash
python "$SKILL_DIR/scripts/fetch_subtitle.py" "<B站链接或BV号>" \
  --out "$OUT/subtitle.txt"
```

stdout 只有一行 `SUBTITLE_RESULT {...}`，按 `status` 处理：

| status | 含义与下一步 |
|---|---|
| `OK` | 用 Read **通读** `text_file` 全文，不要只看 `preview` |
| `NEED_LOGIN` | 登录态缺失/过期，回到 Step 2 重新扫码 |
| `NO_SUBTITLE` | 该视频无字幕轨；如实告知，给出「用户提供文字稿」或「装 yt-dlp+ffmpeg+whisper 做本地 ASR」两个选项，不要用简介凑总结 |
| `RISK_CONTROL` | nav 未返回 wbi 密钥，稍后重试或换网络 |
| `ERROR` | 打印 error 字段给用户，不要猜 |

脚本内部要点：非签名的 `player/v2` 会返回**空** `subtitle_url`，必须走
`player/wbi/v2` 并带 `w_rid`；字幕轨优先 `ai-zh`；支持 `?p=N` / `--page N` 选分 P
和 b23.tv 短链。

## Step 4 · 核查与成文

1. 通读字幕全文后，对片中**可验证**的数字、产品名、发布方、时间线做检索核查；
   区分「视频口播内容」与「外部背景资料」，后者只能作为背景，不得写成视频讲了什么。
2. 明确标注需要打折的地方：厂商自测样本与口径、指标口径（如读缓存 token ≠ 总账单）、
   研究原型被说成正式产品、简介里的推广/利益关系。
3. 输出结构化中文 Markdown：一句话结论 / 分段梳理 / 关键机制与数据 / 逐条事实核查 /
   可迁移应用 / 信息来源与局限。写清字幕来源、条数、字数，让读者能判断依据强度。
4. 若已装 `bilibili-video-summary`，可选用它的 `check_output_format.py`、
   `garbled_check.py`、`check_body_asr_free.py` 做机械校验；**不要**执行它的
   Step 5（IMA 知识库归档，属不可逆外部写入）。

## 边界

- 只处理 B 站。YouTube / 抖音 / 本地视频不在本技能范围。
- 涉及第三方解析服务（TikHub / BibiGPT 等）需要 API key，本技能不使用。
- 详细排障记录（浏览器 Cookie 锁、二维码反色、内联图片不显示、wbi 签名）见
  [references/pitfalls.md](references/pitfalls.md)，遇到异常时再读。
- 批量抓取多 P 合集（`--all-pages`）尚未内置，见 [CHANGELOG.md](CHANGELOG.md) 的 Unreleased。

## 版本与许可

v1.0.0（2026-11-12）· MIT · 源码、说明与更新记录见
<https://github.com/luoluojinyu/bili-qr-subtitle>。
