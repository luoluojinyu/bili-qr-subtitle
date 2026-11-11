# Changelog

`bili-qr-subtitle` 的所有显著变更都记录在这里。格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 计划中

- `--all-pages`：一次抓取多 P 合集的全部官方字幕。当前 `fetch_subtitle.py`
  只支持单集（`?p=N` / `--page N`）；2026-11-12 用一个复用 wbi 实现的临时脚本
  完成了 62 集合集的批量抓取验证，计划把该能力正式收进脚本。
- 更多回归用例：b23.tv 短链、无字幕视频、登录态过期后的重扫流程。
- 可选的字幕轨优先级配置（当前固定优先 `ai-zh`）。

## [1.0.0] - 2026-11-12

首个公开发布版本，面向 GitHub 开源分发与技能市场上架。

### 新增

- `scripts/qr_render.py`：本地渲染 B 站官方登录二维码，支持
  `cv2` → `segno` → `qrcode` 三级回退；输出纯内联 SVG、内嵌 base64 的独立预览页
  与 PNG 三种形态；**强制解码自检**，解码结果必须逐字等于登录 URL 才允许展示。
- `scripts/bili_login.py`：`--check` / `--prepare` / `--poll` / `--clean` 四段式流程，
  登录态持久化为 Netscape 格式 `cookies.txt`，成功后自动删除含登录 URL 的
  `session.json`。
- `scripts/fetch_subtitle.py`：`cookies.txt` + wbi 签名请求 `player/wbi/v2`，
  提取官方 AI 字幕（优先 `ai-zh`），纯 Python 标准库实现；支持 BV 号、完整链接、
  b23.tv 短链、`?p=N` 分 P 与 `--no-timestamps`；输出单行 JSON 状态码。
- `SKILL.md`：触发条件、五条硬约束、权限声明、四步操作指令与状态处理表。
- `references/pitfalls.md`：浏览器 Cookie 独占锁与 app_bound 加密、二维码反色、
  内联图片不显示、二维码有效期被工具调用耗光、wbi 签名等实战排障记录。
- `README.md`、`LICENSE`（MIT）、`.gitignore`，以及可分发安装包
  `bili-qr-subtitle.skill`。
- 完整 front matter 元数据：版本号、作者、许可、仓库地址、标签、分类与平台。

### 设计决策（源自实测踩坑）

- 不再尝试读取 Chrome/Edge 的 Cookie 数据库：运行中的 Chromium 系浏览器会独占
  锁定该文件，普通复制、SQLite 直连、共享读、卷影复制、备份模式五种方式全部失败，
  后两者还需管理员权限。改为由用户主动扫码授权一次。
- `--prepare` 之后**下一个调用必须后台启动 `--poll`**，再展示二维码：曾因中间
  穿插多轮工具调用耗掉约 90 秒，导致二维码在无人扫码的情况下过期。
- 二维码颜色按 OpenCV 的 `0 = 深色模块` 处理，避免生成黑底白块扫不出的码。
- 展示方式改为内联 SVG + 内嵌 base64 的 HTML，不再引用本地图片路径（实测不显示）。

### 安全

- 二维码只在本地生成，不调用任何在线二维码服务（登录 URL 本身是一次性凭据）。
- 日志只输出 Cookie 的**字段名**，不输出值；不索要、不打印 Cookie 明文。
- 不读取浏览器凭据、不安装依赖、不执行 IMA 知识库归档等不可逆外部写入。
- 拿不到字幕时明确返回 `NEED_LOGIN` / `NO_SUBTITLE` / `RISK_CONTROL` / `ERROR`，
  绝不用标题、简介、评论或外部报道拼凑「看起来像总结」的内容。
- 网络请求仅限 B 站官方域名与其字幕 CDN，脚本内无 `subprocess`、无环境变量读取。

### 验证

- `--check` 复用已有登录态 → `valid: true`。
- 取 `BV1kr4h6fExw` → `OK`，`ai-zh` 349 条 / 7294 字（含时间戳）。
- 二维码渲染 → `selfcheck: passed`；错误分支 `NEED_LOGIN` / `ERROR` /
  `LOGIN_TIMEOUT` 均按预期明确失败。
- 技能规范校验 → `✅ Skill is valid!`。
- 实战：62 集合集全部取到官方 AI 字幕（62/62，15609 条，约 30.8 万字），
  由复用 wbi 实现的临时脚本完成，非本版本内置功能。
