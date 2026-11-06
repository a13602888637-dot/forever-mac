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
