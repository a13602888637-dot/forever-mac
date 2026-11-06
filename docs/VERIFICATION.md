# 验证记录与当前边界

## 自动与隔离验证

- Python 回归覆盖插件扫描与包归类、TOC 优先级、版本和依赖、多目录安装/退役、恶意 ZIP、越界引用、本地修改保护、失败恢复、意外中断恢复和历史回滚。
- 组合切换测试验证往返后配置可独立恢复，其他插件和配置保持原样；未知客户端状态格式停止写入。
- 使用官方 MCP SDK 的 `ClientSession`，通过真实 stdio 子进程跑通创建、读写、Lua 编译、打包、安装计划、越界拒绝和跨进程共享锁。
- 战网入口测试验证只打开 Battle.net，不调用游戏程序；缺少战网时拒绝回退，保留本地来源检查、操作锁、同源检查与失败重试。
- 真实作者发布 ZIP 的下载、发布声明、静态引用检查与安装已在隔离客户端验证。
- Playwright 检查桌面 / 窄屏页面、创建与编辑、语法拒绝、打包、计划、应用和回滚，以及 ZIP 导入与资料查询。

## Intel Mac 实机检查

- AppKit / WKWebView App 启动、重复打开时服务复用、任务状态与界面渲染已验证。
- 通过应用启动方法打开 Battle.net，原有登录态正常恢复；游戏由用户在战网中点击“进入游戏”。测试没有输入、读取或保存战网账号密码。
- 仓库截图使用合成角色和演示项目，不包含真实战网页面、好友列表或本机目录。

## 仍需人工验收

- 游戏内加载、布局、动作条、污染与战斗保护，需要在实际客户端逐项确认。本地编译和隔离目录验证不等于这些通过。
- 原生文件选择 / 保存面板已编译，点击验收尚未覆盖。
- Apple Silicon 和 Windows 没有完成实机验收；产品当前定位 macOS，并已在 Intel Mac 验证。
- SDK stdio 客户端联调不代表用户的 Codex / Claude Code / Cursor 已完成配置；连接参数由工作台提供。
- 公开 API 缓存可能早于客户端；来源版本不一致会提示，未收录不等于 API 缺失。

## 复现

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check backend tests scripts
uv run python addons/ForeverUI/selfcheck/run.py
```

浏览器验证可使用 `scripts/verify_browser.py`，应用及游戏内表现按上述边界单独验收。运行时数据库、日志、浏览器会话及本机 checkpoint 不进入公开仓库。
