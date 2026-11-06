# Forever · 无限插件平台与离线开发工作台

面向 Intel Mac、个人使用的《魔兽世界：无限》国服插件平台。首页管理已有插件，提供作者更新、ZIP 导入、变更预览、备份回滚、双界面组合和离线开发工作台。原角色助手、图鉴、专业与收益功能保留。

游戏数据从普通插件单向导出，本地服务计算并展示。所有战斗、移动、物品操作和交易由玩家在游戏中完成。

## 在这台 Mac 上启动

双击项目根目录的 **`Forever AI Companion.app`**，打开独立的 macOS 应用窗口。它使用定制图标，自动启动或复用本地服务，界面在窗口内部显示。`启动.command` 是保留的终端/网页入口：

```bash
cd "/path/to/forever-mac"
./启动.command
```

启动入口使用项目内 Python 3.12，优先发现 `_forever_` 并启动真实模式。启动只扫描；安装或更新必须先生成计划，再点击“备份并应用”。旧测试版目录、已有插件和配置保持原样。没有唯一客户端时进入隔离演示。

`.app` 使用 AppKit + WKWebView，和整个项目文件夹一起保留，也可固定到 Dock。菜单支持刷新、复制粘贴和返回总览。图标原稿和 `.icns` 位于 `assets/app-icon`，生成说明见 [应用图标](APP_ICON.md)。

2026-11-06 本机核对：`/Applications/World of Warcraft/_forever_`，安装元数据 `1.60.1.70790`，65 个插件目录。当前 Interface `16001`；游戏内实际行为仍待人工验收。已安装 BigWigs，当前不再报告 LittleWigs 缺少 BigWigs。

默认本地地址：**http://127.0.0.1:18761**；有占用时自动选择其他本地端口。桌面 App 自动连接相应地址，重复打开复用服务。关闭桌面窗口后，共享本地服务继续同步；终端模式可用 `Ctrl+C` 停止该实例。没有安装登录启动项或系统定时任务。

只体验演示：

```bash
./启动.command --demo
```

一键入口遇到端口占用会尝试下一个端口，也可明确指定 `--port 18762`。不需要同时启动多个相同模式的服务。

## 直接启动游戏

首页右上角“通过战网启动”打开已安装的战网，使用战网已有登录态。选择《无限》后点击“进入游戏”。仅打开战网时仍可准备与更新插件；游戏运行后阻止实际替换。演示模式不会启动真实游戏。

## 插件管理

- 按活动 `_Camelot.toc`、通用 TOC、项目 ID、Group、依赖与标题归类插件包；未知来源和未知版本保留“待绑定”。其他客户端专属模块单独标记为不加载。
- DBM、EllesmereUI、LittleWigs 和依赖修复用 BigWigs 从作者 GitHub Releases 读取 `release.json`，必须有 Forever / 16001 声明。真实模式约每 6 小时检查一次，仅提示；也可手动检查。
- 已装插件先点“接管文件基线”。内容哈希变化会暂停覆盖；可先复制到工作区保留修改。接管不写游戏目录，不会开启自动应用。
- CurseForge 无官方 API 授权时显示“需官网检查”，不显示“已是最新”。官网入口使用 Forever 搜索；进入官网后选择 Forever 文件。ZIP 导入需要文件内发布声明，或由你提供官网文件页面并确认 Forever，后者明确标注为用户确认。
- ZIP 上传单独限制为 128 MiB，普通请求仍为 64 KiB；检查越界、符号链接、重复/大小写路径、异常体积、活动 TOC 和本地引用。
- 每次应用在客户端 `.forever-backups/<操作编号>/` 保留原文件，位于 AddOns 外。历史可回滚；异常退出后明确显示“恢复中断”，不会在下次启动时偷偷改写文件。
- 游戏运行时允许检查和准备；替换、回滚、配置恢复与组合切换等待退出。所有修改由桌面与 MCP 共用的文件锁协调。

“界面组合”按角色预览切换。EllesmereUI 启用已装模块并停用 ForeverUI；ForeverUI 只停用重叠模块，保留其他插件。正常切换保留两套配置，不转换布局。配置备份/恢复是独立操作，包含该组合的账号共享存档与选定角色存档；恢复前保留当前文件。未知 AddOns.txt 格式停止写入。

## 离线开发与 MCP

工作台可创建插件、复制已装插件包、编辑文本、看差异、检查 Lua 5.1、打包 ZIP、生成安装计划及撤销源码修改。Lua 只编译，不执行第三方源码。HTTP 编辑仍受普通请求大小限制；大于 64 KiB 的修改使用 MCP。API 查询使用公开资料缓存，当前缓存版本 `1.60.1.70450`，与客户端 `70790` 不一致时明确提示。未收录的 API 不作为“明确缺失”处理。

在“开发工作台 → 连接已有 AI 工具”复制 `command` / `args` 到 Codex、Claude Code 或 Cursor 的本地 MCP 设置。使用官方 Python MCP SDK 与 stdio，不增加模型对话或额外模型 API Key，不自动修改这些工具的全局配置。

```bash
uv run foreverai mcp-serve --mode live
# 原远端资料命令仍保留：
uv run foreverai mcp --tool <白名单工具> --arguments '{}'
```

MCP 提供 16 项工具，包括列出插件/项目、读取源码、创建/复制项目、读取/写入工作区文件、查询 API、检查、比较差异、打包、生成安装计划和历史。AI 工具没有安装应用、运行 Lua 或修改游戏配置的入口，最终应用在平台完成。源文件保存需要读取时的 SHA256，避免覆盖另一个编辑器的修改。

## 第一次进入游戏

1. 安装新插件后，完整重启客户端，在插件列表启用 **ForeverAI** 和 **ForeverUI**。
2. ForeverAI 自动记录登录、升级、装备、背包、专业、天赋和任务变化；普通变化合并约 5 秒后采集，战斗中延后。
3. 正常退出游戏或手动 `/reload` 后，SavedVariables 才会写入磁盘。本地服务每 5 秒发现变化并自动导入。无需执行 `/fai export`，该命令仍可用于诊断。
4. 输入 `/fui`，点击应用亡灵奥术主题。`/fui edit` 调整布局，`/fui reset` 重置布局；配置面板可恢复原生界面。首次安装不会立即接管原生 UI。

`/fai` 打开采集说明面板；`/fai diagnose` 查看诊断入口。采集失败、战斗锁定或身份不可读时保留上一份快照。

**插件内置离线资料库：**已把无限图鉴的 15,496 件物品和 2,594 条配方灌入 `addons/ForeverAI/CatalogData.lua`。完整重启游戏后，通过 `/fai catalog` 或面板的“离线资料库”查询，保留来源与客户端版本。它不代表角色已拥有物品或学会配方，也不会混入角色 SavedVariables。

以后每次公开资料同步完成，会自动更新这份数据文件；游戏在下一次加载插件时使用新资料。只从已缓存数据重新导出可运行 `uv run python scripts/export_addon_catalog.py`。

**同步边界：**普通插件不能随意写磁盘，因此网页不是逐秒同步。在服务运行时，每份落盘快照自动入库；未落盘的内存变化不能被外部服务读取。专业窗口未打开、技能列表折叠、物品尚未缓存或接口不可读时，字段显示未知并保存原因。

## 不用录入的数据流程

| 数据 | 自动来源与处理 |
| --- | --- |
| 角色、装备、背包、专业、任务 | ForeverAI 读取允许访问的接口，角色级保存；本地服务自动发现和校验 |
| 装备比较 | 根据快照中的装备槽位自动匹配背包候选，列出属性变化，不推算 DPS |
| 物品与配方资料 | 无限图鉴公开 JSON，启动后按需同步，之后约每 6 小时更新，保留版本和来源 |
| 公开报价 | 无限图鉴拍卖快照约每 30 分钟检查一次，报价按其原始采集时间归档 |
| 本服报价 | 玩家正常浏览拍卖行已有搜索结果时，插件被动读取可用报价；不发送搜索、扫描或交易请求 |
| 成本与收益 | 自动匹配配方、材料与报价；手续费未知时只计算毛差和盈亏平衡费率，净利润保持未知 |
| 成长建议与待办 | 快照变化后自动生成并保存；游戏任务目标状态自动跟随快照，个人建议可主动勾选 |

公开拍卖源当前标明 **`CAMWOW CN5 Realm 3 PvP · 联盟`**，与亡灵部落角色通常不匹配。系统明确把它作为其他市场的参考情景，优先使用本角色被动观察的报价。超过 24 小时的报价不参与自动计算；随机附魔变体不合并成基础物品报价。挂单不是成交记录。

没有报价、费率或配方材料时，系统自动重试并保留未知，不要求手工补录，不生成替代数字。Mock 使用合成角色、合成物品与模拟费率，数据和真实模式隔离。

## AI

真实模型连接使用 **Responses API + Pydantic Structured Outputs**，默认 `gpt-6-luna`，可通过环境变量改为 `gpt-6.1-sol`。

`OPENAI_API_KEY` 从进程环境或本地 `.env` 加载。仓库只有空值示例，不包含密钥；没有密钥时全部本地功能和自动规则继续工作，问答明确显示离线模式。当前交付未创建密钥，也未执行真实 OpenAI 请求。

建议和引用区分 `verified`（已读快照或已核对的同版本资料）、`calculated`（确定性计算）、`assumption`（推断、模拟或需要确认的来源）。模型输出引用必须对应实际提供的证据。角色名、服务器名、账号路径、聊天及邮件不会放入模型上下文；请求设置 `store=False`。

## macOS 手动安装方式

已安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 后：

```bash
cd "/path/to/forever-mac"
uv python install 3.12
uv sync --extra dev
uv run python scripts/install_addons.py --game-path "/Applications/World of Warcraft/_forever_"
uv run python scripts/install_addons.py --game-path "/Applications/World of Warcraft/_forever_" --apply
uv run foreverai serve --mode live
```

安装器默认只预览，`--apply` 才通过统一锁和备份事务安装。建议从平台查看安装计划。新版本不再创建源码链接；已有链接保留并暂停覆盖。已有同名目录默认拒绝覆盖。

## 旧助手的 Windows 入口（本次平台仅验收 Intel Mac）

把完整项目放到任意工作目录，按 uv 官方指南安装 uv，然后在 PowerShell 中执行：

```powershell
cd "C:\Projects\ForeverAICompanion"
uv python install 3.12
uv sync --extra dev
uv run python scripts/first_run.py
```

旧助手保留常见目录和 Windows 注册表发现代码；本次新插件平台只支持 Intel Mac，不把旧 Windows 入口计入已验证范围。

```powershell
uv run python scripts/install_addons.py --game-path "C:\Program Files (x86)\World of Warcraft\_cn_beta_" --apply
uv run foreverai serve --mode live
```

真实安装目录可能不同，实际包含 `Interface` 和 `WTF` 的版本目录优先。本版已经测试 Windows 形状的目录与数据流程，尚未在 Windows 实机运行。

## 开发与命令

```bash
uv run foreverai serve --mode mock
uv run foreverai inspect
uv run foreverai sync-references
uv run pytest -q
uv run ruff check backend tests scripts
uv run python addons/ForeverUI/selfcheck/run.py
```

接口文档运行后位于 `/api/docs`。项目结构：

```text
addons/ForeverAI/   只读采集、自动快照、被动报价与导出
addons/ForeverUI/   独立亡灵奥术界面及 Lua 自检
backend/           插件平台、事务、组合、工作台、stdio MCP、原助手服务
frontend/          Jinja2、HTMX、本地样式与脚本
fixtures/          合成演示快照
tests/             安全解析、Lua、规则、接口与自动化回归
docs/              架构、接口、兼容清单、验证与 checkpoint
scripts/           安装及启动入口
data/              运行时数据库与缓存，自动生成且不纳入源码
```

配置项见 `.env.example`。`WOW_PATH` 可作为非标准安装位置的可选覆盖值；不填写时自动发现。`FAI_AUTO_SYNC=false` 只用于关闭服务内自动同步。服务固定绑定 `127.0.0.1`，不提供公网监听参数。

## 数据来源与验证

- [无限 1.60 API 手册](https://wuxianwow.com/api/)：采集与 UI 的接口依据；已保存选取的签名证据。
- [Atraeau/WoW-Addons](https://github.com/Atraeau/WoW-Addons)：客户端参考实现及生成的接口说明。
- [无限图鉴：数据与 MCP](https://wuxianwow.com/about)：公开资料缓存与来源说明。
- [无限图鉴拍卖快照](https://wuxianwow.com/ah)：带服务器、阵营和采集时间的公开挂单资料。
- [无限工坊](https://wuxianwow.com/workshop)：开发方法参考；其 Windows 程序不是本项目 Mac 运行依赖。
- [Blizzard 开发者接口](https://community.developer.battle.net/documentation/world-of-warcraft/guides/namespaces)：尚未核实《无限》国服命名空间，当前不导入正式服或怀旧服资料。

具体已验证项和待游戏内验收项见 [验证记录](VERIFICATION.md)。本地测试和模拟 API 不等于真实游戏 UAT。宝马坐骑需求按当前决定保留为待验证，本版没有模型替换。
