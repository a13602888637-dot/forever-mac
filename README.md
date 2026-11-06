<p align="center">
  <img src="assets/app-icon/forever-ai-icon.png" alt="Forever for Mac 图标" width="112">
</p>

<h1 align="center">Forever for Mac</h1>
<p align="center"><strong>为 macOS 定制的一站式魔兽插件助手</strong></p>
<p align="center">插件管理 · 备份回滚 · 界面组合 · 离线开发 · MCP</p>
<p align="center">A macOS-first, all-in-one addon companion for WoW Forever.</p>

<p align="center">
  <img alt="macOS 12 or later" src="https://img.shields.io/badge/macOS-12%2B-1b1723?logo=apple&logoColor=white">
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-9b78ce?logo=python&logoColor=white">
  <img alt="WoW Forever CN" src="https://img.shields.io/badge/WoW-国服无限-6d998a">
  <img alt="Local MCP" src="https://img.shields.io/badge/MCP-本地_stdio-9b78ce">
</p>

把插件管理、界面切换和离线开发放进一个 Mac 窗口。

**Forever for Mac** 面向国服《魔兽世界：无限》玩家：接管已有插件，检查作者更新，预览每次变更，备份后应用；再把 Codex、Claude Code 或 Cursor 接进本地开发工作台。原有角色助手与图鉴也在同一个应用里。

> 当前为 **v0.2.1 源码预览版**。已在 Intel Mac 验证；Apple Silicon 可编译，尚未完成实机验收。只支持国服《无限》，游戏内加载与战斗保护仍需人工验收。

![插件管理首页，使用合成演示数据](docs/images/addon-manager.png)

## 为 Mac 玩家准备了什么

| 你要做的事 | 在 Forever 里怎么做 |
| --- | --- |
| 从助手进入游戏 | **通过战网启动**，沿用战网登录态，再点击“进入游戏” |
| 接管已有插件 | 识别 `_forever_`，按插件包组织模块，显示版本、依赖、来源与兼容信息 |
| 检查与更新 | 从作者发布清单核对 Forever 支持；先预览目录与文件变更，再备份应用 |
| 找回更新前的状态 | 安装历史、失败恢复与回滚，备份保留在 AddOns 外 |
| 换一套界面 | 按角色选择 EllesmereUI / ForeverUI，分别保留配置，独立备份与恢复 |
| 让 AI 帮写插件 | 创建或复制到离线工作区，编辑、看差异、检查 Lua、打包、生成安装计划 |
| 查看角色和资料 | 原角色助手、装备比较、专业与收益、图鉴和待办保留为辅助功能 |

### Mac 原生窗口，战网负责登录

使用 AppKit + WKWebView 独立窗口，保留菜单、快捷键和应用图标。重复打开复用本地服务。

首页“通过战网启动”打开已安装的 Battle.net。选择《无限》并点击“进入游戏”，使用战网已有登录态。插件准备与更新可以在战网打开时继续；游戏运行后暂停实际替换。

### 每次更新都能看清、找回

- **按包管理**：EllesmereUI、DBM、LittleWigs 等的模块归在一起，避免几十个目录分别变成更新任务。
- **核对真实声明**：优先读取 `_Camelot.toc`，并检查作者发布清单的 Forever / Interface 16001 声明。
- **保留本地修改**：接管时记录文件哈希，内容变化后暂停覆盖，可以先复制到工作区保留修改。
- **暂存检查**：ZIP 先进入隔离区，检查越界路径、符号链接、大小写冲突、异常体积和文件引用。
- **备份与恢复**：多目录更新共用操作锁与记录；失败恢复，意外退出后可继续恢复。

首批作者来源：**DBM、EllesmereUI、LittleWigs**，另支持 BigWigs 依赖修复。CurseForge 提供官网入口和 ZIP 导入；没有获批 API 授权时明确显示“需官网检查”。

### 两套界面，各自保留习惯

EllesmereUI 组合启用已装模块、停用 ForeverUI；ForeverUI 组合只停用功能重叠的 EllesmereUI 模块。正常切换仅调整选定角色的启用状态，不转换布局，不改动其他插件。

配置备份与恢复是独立操作。首次使用 ForeverUI，进游戏运行 `/fui` 应用主题。

![界面组合，使用合成角色](docs/images/interface-profiles.png)

### 接上已有 AI 工具，做自己的插件

开发工作台提供完整离线路径：

**需求 → 创建或复制插件 → 修改工作区 → 检查 Lua → ZIP → 安装计划 → 在平台应用**

本地 MCP 使用官方 Python SDK 与 `stdio`，提供 16 项工具。AI 默认修改副本；读取和修改限制在插件源码与工作区内。Lua 5.1 只编译，不执行第三方源码。API 查询附带公开资料版本，未命中保留待验证状态。

不需要为开发工作台额外配置模型 API Key。你可以继续使用已有的 Codex、Claude Code 或 Cursor，在工作台复制 MCP 的 `command` / `args` 进行连接。

![离线插件编辑器，使用合成项目](docs/images/workshop.png)

## 在 Mac 上运行

需要 macOS 12+、[uv](https://docs.astral.sh/uv/getting-started/installation/)；构建原生 App 还需要 Xcode Command Line Tools。

```bash
git clone https://github.com/a13602888637-dot/forever-mac.git
cd forever-mac
uv sync --extra dev
uv run python scripts/build_macos_app.py
open "Forever AI Companion.app"
```

也可以直接打开本地网页入口：

```bash
./启动.command
# 离线演示，不接管实际客户端：
./启动.command --demo
```

启动默认只扫描，安装和更新由你在平台点击应用。自动优先发现 `/Applications/World of Warcraft/_forever_`；非标准路径可通过 `WOW_PATH` 指定。服务只监听 `127.0.0.1`，没有开机启动项或系统计划任务。

首次使用采集插件时，在平台准备并应用 ForeverAI 的安装计划，重启游戏后启用。角色数据在游戏正常退出或手动 `/reload` 后落盘，助手读取最近一次存档。

## 开发与验证

```bash
uv run pytest -q
uv run ruff check backend tests scripts
uv run python addons/ForeverUI/selfcheck/run.py
uv run foreverai mcp-serve --mode live
```

验证覆盖多目录更新、恶意 ZIP、本地修改保护、失败与中断恢复、组合往返、真实 stdio MCP 客户端以及战网启动入口。桌面与窄屏交互、Intel App 启动和服务复用也已检查。游戏内加载、布局、动作条与战斗保护单独进行人工验收。

| 目录 | 内容 |
| --- | --- |
| `backend/` | 插件管理、事务、界面组合、工作台、MCP 与原助手服务 |
| `frontend/` | 插件管理与亡灵奥术界面 |
| `native/macos/` | AppKit / WKWebView 客户端 |
| `addons/` | ForeverAI 只读采集与独立 ForeverUI |
| `tests/` | 隔离客户端与接口回归 |
| `scripts/` | 启动、安装、原生构建与验证入口 |

配置说明见 [.env.example](.env.example)，原助手细节见 [使用指南](docs/COMPANION_GUIDE.md)，接口见 [API](docs/API.md)，验证边界见 [验证记录](docs/VERIFICATION.md)。

## 当前边界

- 当前聚焦 **macOS + 国服《无限》**。不是 Blizzard 官方产品，不承诺其他服系或 Windows 的兼容性。
- 不注入游戏进程，不在游戏中远程执行 Lua，不自动操作角色或交易。
- CurseForge 官方 API 授权尚未接入实际配置；官网文件支持可由用户确认，界面会标注来源。
- API 缓存版本可能早于客户端，界面保留版本差异和需要游戏内验证的行为。
- 本次提供源码构建，没有把本机账号、SavedVariables、数据库、运行日志或模型密钥放进仓库。

## 来源与致谢

- [无限图鉴](https://wuxianwow.com/about)与[公开 API 资料](https://wuxianwow.com/api/)：内置公开物品/配方资料与 API 缓存，保留原始来源和版本；不包含玩家存档。
- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk)：本地 MCP 服务。
- [HTMX](https://htmx.org/)：原助手页面交互，随附 [许可证](frontend/static/HTMX-LICENSE.txt)。
- 各插件由其作者维护，作者发布 ZIP 只在用户选择后下载，仓库不附带第三方插件安装包。

欢迎在 [Issues](https://github.com/a13602888637-dot/forever-mac/issues) 反馈 Mac 使用问题。提交日志时请移除账号、角色存档和密钥。
