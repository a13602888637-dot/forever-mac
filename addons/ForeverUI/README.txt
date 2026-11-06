ForeverUI 0.2.0 · 亡灵奥术

独立插件，无 ForeverAI 依赖。TOC Interface: 16001，目标客户端为
《魔兽世界：无限》1.60.1.70790；游戏内实际兼容性尚待玩家实机验收。
安装和更新通过桌面平台备份后应用。

使用：
  将完整 ForeverUI 文件夹安装到对应版本的 Interface/AddOns/ 中。
  第一次进入游戏时保留原生界面；/fui 打开面板，由玩家点击“应用亡灵奥术”。
  /fui edit  编辑布局，再次执行结束编辑。
  /fui reset 重置当前角色布局，保留模块选择。
  /fui off   恢复原生界面，保留已保存的角色布局。
  /fui layout compact  应用紧凑布局，保留上一次位置备份。
  /fui layout undo     找回上一次布局位置。
  /fui icons off       隐藏动作条外的悬浮技能冷却，保留任务特殊技能。
  /fui icons on        重新显示悬浮技能冷却。
  /fui bags  打开只读聚合行囊。B 键继续保留原生背包操作。

模块：
  单位框：48 个安全单位按钮覆盖玩家、目标、目标的目标、宠物、队伍与40人团队。
  动作条：给原生安全按钮和原生条框体换肤及定位；不重写动作、按键、分页、冷却或提示。
  行囊：自动读取、分类和搜索；无使用、移动、排序、售卖、摧毁物品的点击处理。
  小地图：保留原生地图操作；添加区域、时间、主题入口与边框。
  任务：装饰并定位原生追踪框，保留任务物品和目标交互。
  聊天：给原生窗口换肤；不发送、过滤、拦截或保存聊天内容。

布局保存在 SavedVariablesPerCharacter: ForeverUICharDB。
战斗中禁止模块或布局变更，编辑拖动的是独立影子标签；战斗开始关闭标签。
原生单位框只在全部替代安全按钮和可见性驱动初始化成功后隐藏。
模块失败会撤回已做的改动；原生恢复失败时保留恢复记录并提示 /fui off 重试或 /reload。
原生锚点必须完整可读后才允许变更。无法读取袋数时只扫描已知的背包0并标记部分读取。

API 核对：
  https://wuxianwow.com/api/ 的 1.60.1.70450 文档；Lua 5.1.4。
  UnitHealth/Power 等受限值先检测，只原样送入文档标记允许机密参数的显示setter：
  StatusBar:SetValue/SetMinMaxValues、FontString:SetText/SetFormattedText。
  不对机密值计算、比较、拼接、序列化或持久化。
  其余接口运行时检测；原生框体、模板、可见性驱动与污染边界仍需游戏内验收。
  仅参考 https://github.com/Atraeau/WoW-Addons 的开发环境说明；没有复制第三方插件源码。
  不依赖 Windows 无限工坊、MCP 桥、外来 Lua、内存读取或按键模拟。

本地自检（项目根目录）：
  uv run python addons/ForeverUI/selfcheck/run.py
  使用 lupa.lua51 模拟 API；这不等于真实客户端的安全执行、污染、战斗或视觉验证。
