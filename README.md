# bili-qr-subtitle

> 用 B 站官方扫码登录取得登录态，零依赖提取官方 AI 字幕，产出基于**真实字幕**的中文视频总结。
> **v1.0.0** · 2026-11-12 · MIT · 适用 WorkBuddy / Claude Code / Codex 等读取 `SKILL.md` 的智能体

源码仓库：<https://github.com/luoluojinyu/bili-qr-subtitle>　·　在线介绍页与下载：<https://bili-qr-subtitle.app.workbuddy.host/?sharecode=UYG4JQN2TP>

> ⚠️ **用户警告**
> 本技能会请求你用手机 B 站 App **扫码登录**，并在本机写入 `cookies.txt`（含 `SESSDATA`，等同账号登录态）。
> 扫码是用户主动授权的动作；技能不会自动读取浏览器凭据、不会上传登录态、不会自动安装依赖，
> 也不会执行知识库归档等不可逆外部写入。**请勿把 `cookies.txt` 提交到任何仓库或发给他人**，
> 不再需要时直接删除该文件即可退出登录。

## 一、它解决什么问题

给 AI 一个 B 站链接，最常见的失败是「拿不到视频正文」：匿名接口只给标题和简介，
官方 AI 字幕与 AI 总结都要登录态。而「用户说自己已经登录了」并不等于脚本能读到——
运行中的 Chromium 系浏览器会**独占锁住** `Network/Cookies` 数据库，新版 Edge 还有
`app_bound` 加密，复制、SQLite 直连、共享读、卷影复制、备份模式全都会失败（后两者
还需要管理员权限）。

本技能不再撬浏览器，改为让用户用手机 B 站 App **扫一次官方二维码**，把登录态
持久化成 `cookies.txt`，之后所有请求走纯 HTTP：

| 常见路线 | 代价 |
|---|---|
| 读浏览器 Cookie | 独占锁 + 加密，实测四种绕过方式全失败 |
| 下载视频 + 本地 ASR | 要装 yt-dlp / ffmpeg / faster-whisper，模型数百 MB，12 分钟视频约跑 10 分钟 |
| 第三方解析服务 | 需要 API key，且把链接交给第三方 |
| 匿名抓字幕 | B 站无匿名可取的字幕轨，只能拿到元数据 |
| **本技能：扫码 + wbi 签名** | **一次扫码，之后零安装、零下载视频、零 ASR** |

## 二、工作流程

```
B站链接 / BV号 / b23.tv 短链
   ↓  ① bili_login.py --check        检查已有登录态是否有效
   ↓  ② --prepare → --poll（后台）   本地生成二维码 → 手机扫码 → 写 cookies.txt
   ↓  ③ fetch_subtitle.py            cookies.txt + wbi 签名 → player/wbi/v2 → AI 字幕
   ↓  ④ 通读全文 → 核查 → 成文       结构化中文 Markdown 总结
```

三条硬约束贯穿全程：

1. **只用真实字幕总结。** 拿不到字幕就明确返回状态码，绝不用标题、简介、评论、
   弹幕或外部报道拼一份「看起来像总结」的内容。
2. **二维码只在本地生成。** 登录二维码 URL 是一次性登录凭据，绝不调用在线二维码
   服务；生成后做解码自检（解码结果必须等于原 URL）才允许展示。
3. **先启动轮询，再展示二维码。** 二维码有效期约 180 秒，实测过因中间穿插工具
   调用耗掉 90 秒导致过期。

## 三、安装

### 方式 A：下载安装包

下载 `bili-qr-subtitle.skill`（zip 格式），解压到用户级技能目录：

```
~/.workbuddy/skills/bili-qr-subtitle/     # WorkBuddy
~/.claude/skills/bili-qr-subtitle/        # Claude Code
~/.codex/skills/bili-qr-subtitle/         # Codex
```

### 方式 B：从源码

```bash
git clone https://github.com/luoluojinyu/bili-qr-subtitle.git \
  ~/.workbuddy/skills/bili-qr-subtitle
```

仓库根目录本身就是技能目录（`SKILL.md` 在根），可直接供 `clawhub skill publish` 使用。

目录内容：

```
bili-qr-subtitle/
├── SKILL.md                    # 触发条件、约束、权限声明、四步流程
├── README.md                   # 本说明（同时作为仓库首页）
├── LICENSE                     # MIT
├── CHANGELOG.md                # 版本变更记录
├── scripts/
│   ├── qr_render.py            # 二维码渲染：cv2 → segno → qrcode 回退 + 自检
│   ├── bili_login.py           # --check / --prepare / --poll / --clean
│   └── fetch_subtitle.py       # cookies.txt + wbi 签名取字幕（纯标准库）
└── references/
    └── pitfalls.md             # 排障与已验证的坑
```

**依赖**：Python 3.9+。二维码渲染需要 `opencv-python-headless` / `segno` / `qrcode`
**三者之一**；字幕提取只用标准库。不需要 yt-dlp、ffmpeg、whisper、playwright，
也不需要 B 站登录浏览器的 Cookie。新装的技能通常需要**新开一个对话**才会被加载。

## 四、使用

直接对智能体说：

- 「总结这个 B 站视频 + 链接」
- 「我已经登录 B 站了，但还是取不到字幕」
- 「别装依赖，帮我把这个 BV 号的内容提炼成要点」

手动执行（Windows 用 `python`，不是 `python3`）：

```bash
SKILL_DIR="~/.workbuddy/skills/bili-qr-subtitle"
OUT="./_bili_login"

python "$SKILL_DIR/scripts/bili_login.py" --check --out-dir "$OUT"
# valid: false 时：
python "$SKILL_DIR/scripts/bili_login.py" --prepare --out-dir "$OUT"
python "$SKILL_DIR/scripts/bili_login.py" --poll   --out-dir "$OUT" --timeout 180  # 后台立即启动
# 然后用内联 SVG / 内嵌 base64 的 HTML 展示二维码
python "$SKILL_DIR/scripts/fetch_subtitle.py" "<B站链接>" --out "$OUT/subtitle.txt"
```

`fetch_subtitle.py` 只输出一行 `SUBTITLE_RESULT {...}`，按 `status` 处理：

| status | 处理 |
|---|---|
| `OK` | 通读 `text_file` 全文（含时间戳），再做事实核查与成文 |
| `NEED_LOGIN` | 登录态缺失/过期 → 重新扫码 |
| `NO_SUBTITLE` | 该视频无字幕轨 → 让用户提供文字稿，或另走本地 ASR |
| `RISK_CONTROL` | nav 未返回 wbi 密钥 → 稍后重试或换网络 |
| `ERROR` | 如实报出错误，不猜测 |

支持 `?p=N` / `--page N` 选分 P、`--no-timestamps` 输出纯文本、b23.tv 短链。
字幕轨优先 `ai-zh`。

## 五、隐私与安全

- `cookies.txt` 默认写在 `~/.workbuddy/data/bilibili-video-summary/bilibili_cookies.txt`，
  含 `SESSDATA` / `bili_jct` / `DedeUserID`，**等同账号登录态**：不外传、不提交到仓库、
  日志里只打印字段名不打印值。它与已装技能 `bilibili-video-summary` 共用，登录一次两边可用。
- 不主动读取浏览器凭据、不主动索要 Cookie 明文；扫码是用户主动授权的动作。
- `session.json`（含登录 URL）在登录成功后自动删除；`--clean` 可清除二维码临时文件。
- 不执行任何不可逆外部写入。若同时装了 `bilibili-video-summary`，不要触发它的
  「强制归档到 IMA 知识库」步骤，除非用户明确确认。
- 脚本只访问 B 站官方域名（`api.bilibili.com` / `passport.bilibili.com` /
  `*.hdslb.com` 字幕 CDN），不向第三方发送视频链接或登录信息。
- 脚本内无 `subprocess`、无环境变量读取、无 `eval` / `exec`；完整的权限披露见
  `SKILL.md` 的「权限声明」表格。

## 六、已知限制

- 只支持 B 站；YouTube / 抖音 / 本地文件不在范围。
- 依赖 B 站未公开的 web 接口（`nav` / `player/wbi/v2`），站内改版可能需要同步更新。
- 没有 AI 字幕的视频无法总结；技能会明确报 `NO_SUBTITLE`，不会拿简介凑内容。
- `SESSDATA` 会过期，过期后重扫一次即可。
- 二维码渲染若无 cv2 且未装 segno/qrcode，会明确报错并提示安装，不会静默降级。
- `fetch_subtitle.py` 目前只支持单集；多 P 合集需逐集调用或用临时脚本复用其 wbi 实现
  （`--all-pages` 已列入 CHANGELOG 的 Unreleased）。
- 本技能不对视频观点做真伪背书；总结中的数字与产品信息应另行核查。

## 七、验证记录（2026-11-12，Windows / Python 3.13.14 / cv2 5.0.0）

| 项目 | 结果 |
|---|---|
| `--check` 复用已有登录态 | `valid: true` |
| 取 BV1kr4h6fExw 字幕 | `OK`，`ai-zh` 349 条 / 7294 字（含时间戳），12 分 19 秒视频 |
| 二维码本地生成与自检 | `selfcheck: passed`，解码结果与登录 URL 一致 |
| 错误分支 | `NEED_LOGIN` / `ERROR`（非法 BV）/ `LOGIN_TIMEOUT` 均按预期明确失败 |
| 技能规范校验 | `✅ Skill is valid!`（skill-creator 打包器） |
| 62 集合集实战 | 62/62 集全部取到官方 AI 字幕，15609 条、约 30.8 万字（由复用 wbi 实现的临时脚本完成，非本版本内置功能） |

全程未安装任何额外依赖，未读取浏览器 Cookie，未执行外部写入。

## 八、发布与上架状态

| 渠道 | 状态 |
|---|---|
| GitHub 公开仓库 | ✅ 源码、说明、LICENSE、CHANGELOG 已公开在 `luoluojinyu/bili-qr-subtitle`（main 分支） |
| 在线介绍页 + `.skill` 下载 | ✅ 可访问（已同步 v1.0.0 上架包），随时可下线 |
| ClawHub / SkillHub 等技能市场 | ⚠️ 物料已备齐，需**发布者本人**登录并提交，本仓库不代持任何市场凭据 |

上架前检查清单（本版本已满足）：

- [x] `SKILL.md` frontmatter 含 `name` / `description` / `license` 与 `metadata` 版本号、作者、标签
- [x] `description` 精简且含 `Do NOT` 范围声明；`SKILL.md` 正文行数远低于 300 行
- [x] 「权限声明」表格（网络 / 文件 / 环境变量 / subprocess / 外部 API）
- [x] README 含用户警告与隐私边界
- [x] `LICENSE`（MIT）、`CHANGELOG.md`、SemVer 版本号、`README.md` 齐全
- [x] `.gitignore` 排除 cookies.txt、二维码临时文件与本地构建产物
- [x] 包内不含任何凭据、二进制或私有配置；路径分隔符已统一为 `/`
- [x] 仓库为 public（`luoluojinyu/bili-qr-subtitle`），9 个文件已推送并逐文件校验

市场侧提交由本人完成，典型流程：

```bash
npm i -g clawhub
clawhub login                       # GitHub 授权，需本人账号
clawhub skill publish . \
  --slug bili-qr-subtitle \
  --name "B站扫码登录与字幕总结" \
  --version 1.0.0 \
  --changelog "Initial release" \
  --dry-run                         # 先自检，去掉该参数即正式发布
```

平台一般还要求 GitHub 账号注册满一定时间、Git 已配置 `user.name` / `user.email`，
并经过社区审核；具体以各市场当前规则为准。

## 九、许可协议

**MIT License** · Copyright (c) 2026 luoluojinyu。
完整条款见 [LICENSE](LICENSE)。免责声明：本技能依赖 B 站未公开的 web 接口，
按「现状」提供，不对接口可用性或字幕准确性作任何担保；使用者需自行遵守
B 站服务条款与相关平台规则。

## 十、变更记录

见 [CHANGELOG.md](CHANGELOG.md)。
