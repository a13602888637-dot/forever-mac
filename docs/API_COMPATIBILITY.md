# 《无限》API 兼容性与证据边界

2026-11-06 实机安装元数据已更新为 `_forever_ / 1.60.1.70790`。下面 `70450` 的签名是保留的公开资料缓存，开发工作台会标记版本差异；尚未进行新客户端游戏内验证。

核对基线：本机 `.build.info` 与应用 Info.plist 为 **1.60.1.70450**；[无限 API 手册](https://wuxianwow.com/api/) 同版本资料；[Atraeau/WoW-Addons](https://github.com/Atraeau/WoW-Addons) 参考提交 `d8c9be3635e756fd90284e02b5a800c796b337a0`。

选择的只读签名保存在 `api-evidence.json`（341 项，含新增的阵营与被动报价读取）。这是文档证据，不是本机游戏内调用证据。Interface 16001 仍须由实际 `GetBuildInfo()` 校准；没有修改客户端版本检查开关。

| 能力 | 采用接口 | 不可用时 |
| --- | --- | --- |
| 版本、角色 | GetBuildInfo、UnitName、GetRealmName、UnitClass、UnitRace、UnitLevel、UnitFactionGroup | 无身份则拒绝覆盖旧快照；其他字段 null + reason |
| 装备 | GetInventoryItemID/Link、C_Item.GetItemInfo/GetItemStats | 未缓存或受限属性保留未知；空槽单独标记 |
| 背包 | C_Container.GetContainerNumSlots/GetContainerItemInfo | 缺少枚举或数量接口则不声称完整扫描 |
| 专精/天赋 | C_SpecializationInfo、C_ClassTalents.GetActiveConfigID、C_Traits | 当前规则集不支持时 null；不由职业推断奥术天赋 |
| 专业 | C_SkillInfo.GetNumSkillLines/GetSkillLineInfo、C_TradeSkillUI.GetAllProfessionTradeSkillLines | 折叠或不可读时提示打开专业/技能界面后自动重试 |
| 配方 | C_TradeSkillUI.GetProfessionInfoBySkillLineID/GetProfessionSpells/GetRecipeInfo/GetRecipeSchematic | 枚举失败保持未知；固定产量、必选材料或替代材料不明确时不计算完整利润 |
| 任务 | C_QuestLog.GetNumQuestLogEntries/GetInfo/GetQuestObjectives/IsComplete | 不可读时 null；未知不作为“无任务” |
| 被动拍卖观察 | C_AuctionHouse.GetNumCommoditySearchResults/GetCommoditySearchResultInfo、GetNumItemSearchResults/GetItemSearchResultInfo | 没有玩家已有查询结果就没有本服报价；不主动查询或扫描 |
| 单位框 | SecureUnitButtonTemplate、RegisterUnitWatch、RegisterStateDriver、UnitHealth/Power 等 | 结构初始化失败恢复原生；secret 仅传递给允许的显示 setter |
| 动作条 | 原生动作按钮/原生控制框架的皮肤和布局 | 原生框架不完整或不能安全恢复时保留原生 |
| 小地图/聊天/任务追踪 | 运行时检测原生框架及公开方法 | 独立模块降级，保留原生可用性 |

`GetAllRecipeIDs`、`GetFilteredRecipeIDs`、传统 `GetProfessions` 和 `GetNumTradeSkills` 等未在此次手册中找到，不作为采集器的必需接口。资料中存在的函数也可能受当前游戏规则、UI 状态或机密值限制，必须运行时检测。

## 外部数据接口

| 来源 | 当前状态 |
| --- | --- |
| `/data/manifest.json`、items、recipes、professions、stat_names | 已真实 HTTP 读取并写入本地缓存，版本绑定与异常响应有测试 |
| `/ah/data/index.json` | 已核对真实 v7 结构；按市场、阵营、采集时间保存，忽略随机变体合并 |
| `https://wuxianwow.com/mcp` | 已实现白名单只读适配，当前环境实测 HTTP 403；不宣称真实联调通过 |
| Blizzard Web API | 尚未核实《无限》国服命名空间及访问条件；不请求其他版本来替代 |
| 无限工坊 App | Windows 工具，Mac 不依赖；仅参考其公开说明与 API 边界 |

全部实际客户端表现（包括 UI 加载、污染、保护状态、专业返回结构和 SavedVariables 落盘）必须由游戏内验收补充。源码、Lua 模拟测试和手册不能代替这一步。
