# 本地接口与快照协议

服务基址 `http://127.0.0.1:18761`。交互文档 `/api/docs`；返回 JSON，未知数据是 `null`，不是零、空字符串或编造值。Web 使用同一业务服务的 HTMX 片段接口。

## 主要接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/health` | 模式、模型配置及服务状态，不返回密钥 |
| GET | `/api/automation/status` | 自动扫描、导入、资料/报价同步与错误历史 |
| POST | `/api/automation/run` | 无参数立即执行一轮自动同步；后台也会定时执行 |
| GET | `/api/sources` | 自动发现的角色来源，仅公开来源 ID、角色和服务器 |
| GET | `/api/characters` | 当前模式的已有角色 |
| GET | `/api/snapshots/latest` | 当前角色最新快照、快照 ID 和过期状态 |
| GET | `/api/equipment/automatic` | 自动匹配的背包同槽位属性比较 |
| GET | `/api/economy/automatic` | 自动配方估算、报价覆盖、来源与历史 |
| POST | `/api/ai/plan` | 当前快照的三项行动，结果持久化 |
| POST | `/api/ai/ask` | `{ "question": "当前装备有哪些缺口？" }` |
| GET | `/api/tasks` | 自动建议与任务日志待办 |
| PATCH | `/api/tasks/{id}` | `{ "done": true }`，仅可主动标记一般建议；游戏任务状态只读 |
| GET | `/api/providers` | 数据源、缓存和官方接口兼容性状态 |
| GET | `/api/references/status` | 缓存版本、时间和校验摘要 |
| POST | `/api/references/sync` | 无参数同步公开物品/配方资料 |
| GET | `/api/references/search?q=黑色魔纹&kind=items` | 本地缓存检索，kind 为 items 或 recipes |
| POST | `/api/references/mcp` | 只读白名单工具和参数；当前网络下 403 会明确返回错误 |

保留 `/api/snapshots/import`、`/api/settings/path`、`/api/characters/select`、`/api/equipment/compare`、`/api/economy/quote`、价格和待办 CRUD，供测试或其他本地客户端使用；产品主界面不要求逐项录入。

状态：输入结构错误 `422`，数据不可用/校验失败 `400`，不匹配本机来源 `403`，请求体过大 `413`。HTMX 表单错误以带错误状态的 HTML 片段显示。

## SnapshotV1

外层 SavedVariables 是唯一变量赋值：

```lua
ForeverAICharDB = {
    schema_version = 1,
    snapshot_json = "<合法 JSON 字符串>",
}
```

JSON 包含：`schema_version`、`addon_version`、`captured_at`（UNIX 秒）、`data_mode`、`client`、`character`、`equipment`、`bags`、`professions`、`recipes`、`talents`、`quests`、`auction_quotes`、`unavailable`、`capabilities`。

- `character`：角色名、服务器、等级、职业/种族 token、可用专精名称与阵营；不导出账号名或 GUID。
- `equipment`/`bags`：itemID、名称、位置、数量、装等、品质、属性映射、可用穿戴位置。空装备槽与未知状态明确区分。
- `unavailable`：以零基路径记录原因，例如 `equipment.0.stats.HIDDEN: secret_or_inaccessible`。整个分区未知时可在父路径给出原因。
- `capabilities`：每项 API 的 `runtime_verified`、`unsupported`、`unavailable` 或 `restricted`。这里表示该次插件采集结果；Mock 不能当成游戏实测。
- `auction_quotes`：仅被动观察的商品 unitPrice，或普通物品 buyoutAmount/quantity 向上取整的单价；后一种标为 calculated。无卖家、竞价人或聊天身份。
- 新增的可选阵营、穿戴位置、报价字段缺失时，旧 V1 快照补 `null + not_in_older_snapshot`；不推断值。

游戏存档只能导入 `data_mode=live`；Mock 固定走项目的合成 fixture 初始化入口。快照时间晚于本机五分钟、身份与目录不符、重复 JSON 键、未知字段、数值类型错误均拒绝导入。

无限 `1.60.x / Interface 16001` 支持 `Account/<账号>/<数字服务器ID>/<名-姓>/SavedVariables/ForeverAI.lua`。桌面从已发现的存档目录补充 `character.storage_name` 和 `character.storage_realm_id`，以二者作为稳定角色标识；不改写游戏报告的 `name/realm`，不信任 JSON 自带的存储标识。完整姓名须匹配；旧快照仅含名时，必须在账号内唯一，跨服同名也拒绝自动归并。传统目录仍校验名字与服务器。两个存储字段在旧快照中可缺省，不要求游戏 API 的 unavailable 原因，且与角色名、服务器一起从 AI 上下文剔除。

## 计算

所有金额以整数铜币存储。材料成本为 `材料数量 × 单价 × 批次`；销售收入为 `固定产量 × 批次 × 成品单价`。缺价或产量未知则对应结果为 null。已知费率时使用 Decimal 四舍五入至铜进行估算；未核实费率时净利润保持 null，仅计算未扣费用毛差和盈亏平衡费率。

建议采用 Pydantic `Advice`：summary、claims、恰好三项 actions、unknowns。每条 claim/action reason 都有 provenance 和 evidence_ids；不允许伪造引用或把 assumption 证据提升为 verified。


## 0.2 插件平台与离线工作台

所有接口继承 loopback / 同源检查。普通请求 64 KiB；只有 `POST /api/addons/import` 独立流式接收 ZIP，128 MiB + 64 KiB 表单开销。文件落入隔离暂存区。

| 接口 | 用途 |
| --- | --- |
| `GET /api/addons/game-status`、`POST /api/addons/launch-game` | 读取启动状态 / 打开已验证的战网应用，由战网登录并进入《无限》 |
| `GET /api/addons` | 只读扫描当前客户端、插件包、模块、兼容、依赖与来源 |
| `POST /api/addons/adopt` | `{package_id}`，记录当前文件基线，不写游戏 |
| `POST /api/addons/check-updates` | `{package_id: 可选}`，核对作者发布，不自动应用 |
| `POST /api/addons/download` | `{package_id}`，下载并生成计划 |
| `POST /api/addons/bundled` | `{name: ForeverAI 或 ForeverUI}`，生成内置安装计划 |
| `POST /api/addons/import` | multipart：file、source_url、forever_confirmed |
| `GET /api/addons/plans[/{id}]` | 查看计划及实时阻断原因 |
| `POST /api/addons/plans/{id}/apply` | 退出游戏后重新检查、备份并应用 |
| `GET /api/addons/history`、`GET /api/addons/tasks` | 操作记录与后台任务状态 |
| `POST /api/addons/operations/{id}/rollback` 或 `/recover` | 回滚 / 中断恢复 |
| `GET /api/profiles` | 可选角色、组合、配置备份 |
| `POST /api/profiles/plans` | `{character_id, combo}`，生成启用状态预览 |
| `POST /api/profiles/plans/{id}/apply` | 仅切换相关启用状态 |
| `POST /api/profiles/snapshots` | `{character_id, combo}`，备份独立配置 |
| `POST /api/profiles/snapshots/{id}/restore` | `{character_id}`，校验备份并恢复 |
| `GET/POST /api/workshop/projects` | 列项目 / `{name, description}` 创建项目 |
| `POST /api/workshop/clone` | `{package_id}`，复制完整插件包 |
| `GET /api/workshop/projects/{id}/files` | 源码清单与哈希 |
| `GET/PUT /api/workshop/projects/{id}/file` | 查询参数 path / `{path, content, expected_sha256}` |
| `GET /api/workshop/projects/{id}/diff` 或 `/history` | 差异与修改历史 |
| `POST /api/workshop/projects/{id}/validate` 或 `/pack` | 编译检查 / ZIP 打包 |
| `POST /api/workshop/projects/{id}/revisions/{revision}/revert` | 撤销工作区修改 |
| `GET /api/workshop/exports/{id}` | 下载 ZIP |
| `POST /api/workshop/exports/{id}/plan` | 从已打包产物生成安装计划 |
| `GET /api/workshop/api?q=…`、`GET /api/workshop/mcp-config` | 版本化 API 缓存 / MCP 启动配置 |

所有应用操作使用同一 `operations.lock` 和持久化事务，原文件在客户端 `.forever-backups`。回滚只恢复该事务改动的管理记录，保留之后接管的无关插件。已修改文件、未知状态格式、损坏备份或不匹配客户端会阻止覆盖。MCP 无“应用安装”工具。


## 0.3 问答与伤害统计选择

- `GET /api/ai/status` 返回当前回答引擎的 readiness、provider、label 与说明，不包含认证信息。
- `POST /api/ai/ask` 保留 `{question}` 输入，Codex 登录可用时通过只读 CLI 返回结构化建议。没有角色快照时允许先问通用插件问题，不创建虚假角色快照。
- `POST /api/profiles/plans` 可传 `keep_ellesmere_dps: true`。计划启用 EllesmereUIDamageMeters，并停用已核验 Details 包的所有模块，配置文件保留。新增模块或文件变化后仍会阻断陈旧计划。
- ForeverUI 组合会停用重叠的 EllesmereUICooldownManager；实际游戏内主题仍由 `/fui` 面板启用。


## 0.4 桌面与管理接口

旧页面地址与原16项 MCP 契约保留。新增页面 `/discover`、`/addons/{package_id}`、`/downloads`、`/addons/management/{id}`、`/profiles/plans/{id}`，角色标签使用 `/overview?tab=overview|equipment|bags|professions|quests`。

| 方法 | 路径 | 输入 / 作用 |
| --- | --- | --- |
| GET | `/api/catalog` | `q`、`category`，仅具体项目，返回作者、版本、图标、截图和来源 |
| GET | `/api/catalog/{package_id}` | 项目详情与已安装状态 |
| GET | `/api/media/{resource_id}` | 已登记同源资源；`size=thumb|full`，不接受任意URL |
| GET | `/api/addons/enablement` | `character_id`为存档位置ID，未提供时明确返回unknown |
| POST | `/api/addons/management/plans` | `{action,package_ids,character_id?}`；action为update/enable/disable/uninstall |
| GET / POST | `/api/addons/management/plans/{id}` / `.../apply` | 汇总预览与一次确认；失败停止剩余包 |
| GET | `/api/addons/operations/{id}/rollback-preview` | 当前文件到备份文件的具体影响、依赖阻止原因与precondition_token |
| POST | `/api/addons/operations/{id}/rollback` | 可选 `{precondition_token}`；新UI必须发送预览令牌 |
| GET | `/api/profiles/snapshots/{id}/restore-preview` | `character_id`，账号/角色配置的具体文件影响 |
| POST | `/api/profiles/snapshots/{id}/restore` | `{character_id,precondition_token?}`，提交时重算预览条件 |
| POST | `/api/profiles/plans/{old_id}/restore-plan` | 从已应用方案和成功事务证据生成新预览；不写游戏 |
| GET | `/api/references/browse` | kind/q/category/page/page_size，返回分类、分页与结构化记录 |
| GET | `/api/references/details/{kind}/{id}` | 属性、材料、配方，或副本、首领、地图、任务详情与关联 |
| GET | `/api/market/markets` | 可用市场、selected_house、采集状态；refresh可刷新清单 |
| POST | `/api/market/selection` | `{house}`；null关闭公开参考市场，不删除历史 |
| POST | `/api/market/refresh` | 对明确选择的市场完整分页同步，失败保留旧缓存 |

`ComparisonInput`新增可选`expected_snapshot_id`，保留旧调用兼容。桌面行囊和装备比较必须传页面快照ID；角色或快照变化返回400并要求刷新，不静默使用旧索引。

恢复令牌是内容条件哈希，不是认证凭据。提交期间再次检查游戏进程、文件、管理记录、依赖以及相关事务；重复消费或预览过期拒绝应用。

### 0.4.2 世界资料与首领掉落

`/api/references/browse` 和详情接口的 `kind` 支持 `items`、`recipes`、`instances`、`bosses`、`maps`、`quests`。副本与首领详情提供 `loot_groups`，物品详情提供 `dropped_by`。掉落记录始终标记为第三方参考，区分 Spyglass《无限》与 QuestieDB 经典旧世来源；物品属性仍来自当前物品缓存。`cached=false` 表示尚未同步，已同步的空列表表示来源未收录。

`POST /api/references/sync` 同步基础资料与首领详情补充，返回 `world_counts` 和 `loot` 覆盖统计。首领详情限制并发和速率，并以目录的 NPC、首领战及副本编号核对；最终版本核对通过后整体提交缓存。新同步可能需要一至数分钟；失败保留上次完整缓存。公开 MCP 只读白名单另外支持 `instances`、`npcs`、`quests`、`atlas`。
