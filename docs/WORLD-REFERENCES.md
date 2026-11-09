# 副本、地图、首领与任务来源

数据入口为 [无限图鉴公开数据说明](https://wuxianwow.com/about)。本地同步读取 `instances.json`、`npcs.json`、`atlas.json`、`quests.json`、`questlines.json`，与物品、配方共用版本清单和原子缓存；来源更新中或数量、版本、记录结构异常时保留原缓存。旧版清单未声明这些数据时继续支持物品与配方。

副本与首领使用来源给出的副本 ID、首领战 ID 关联，不按相同名称猜测。任务标题与正文来自服务器记录；编号、起始物品线索与 QuestieDB 参考名称不冒充任务标题。第三方等级、接取者与任务标记另列为参考，并注明 [QuestieDB / Questie 团队](https://github.com/Questie/QuestieDB)。本项目不包含该项目数据副本，远端资料只保存在本机缓存。

地图使用来源的 `data/maps/*.webp` 区域底图和比例坐标，近似入口与第三方任务坐标有单独标记。当前来源明确缺少地下城内部地图，不将加载画面、入口图或区域底图标作内部地图。首领技能攻略暂未接入。掉落从同站 MCP `npcs {id}` 详情的 `temporary_drops` 单独同步：Spyglass 为《无限》整理的参考，QuestieDB 为经典旧世参考；两者均保持第三方标记，不将版本一致的物品属性等同于掉落关系已核实。空列表表示来源未收录，不推断该首领没有掉落。素材来源为无限图鉴提取的游戏资源，游戏素材版权归原权利人；图片同源缓存仅限登记的地图、加载画面和首领图片路径。

插件目录核对日期：2026-11-07。作者支持声明不等于本机游戏内验收，也不授权自动安装。

| 项目 | 用途与依赖 | 核对依据 |
| --- | --- | --- |
| Atlas | 地图浏览器核心，需搭配地图模块 | [作者 v1.54.04 发布](https://github.com/arithmandar/Atlas/releases/tag/v1.54.04)，清单与 TOC 包含 Forever / 16001 |
| Atlas Kalimdor & Eastern Kingdoms | 地下城地图包；依赖 Atlas | [作者 v1.54.03 发布](https://github.com/arithmandar/Atlas-Kalimdor-and-Eastern-Kingdoms/releases/tag/v1.54.03)，清单与 TOC 包含 Forever / 16001 |
| Atlas Forever (fork) | 地图、入口、路线；与 Atlas 主版择一 | [作者文件页](https://www.curseforge.com/wow/addons/atlas-forever/files/all)，3.18.6 标注 Forever / 1.60.1 |
| DBM Dungeons | 地下城首领警告；依赖 DBM-Core | [作者 270 发布](https://github.com/DeadlyBossMods/DBM-Dungeons/releases/tag/270)，发布清单与 Forever 模块 TOC |
| Questie | 任务目标、位置与历史 | [作者发布](https://github.com/Questie/Questie/releases)，v12.6.2 / QuestieDB v1.0.11 组合清单声明 Forever / 16001；当前走官网 ZIP 导入 |
| DungeonJournal | 副本任务与作者维护的掉落资料 | [作者项目页](https://www.curseforge.com/wow/addons/dungeonjournal)，1.7.0 标注 Forever / 1.60.1；当前走官网 ZIP 导入 |

本项目图鉴与这些游戏内插件是独立入口。插件源码和安装包不随公开仓库分发；下载与应用继续经过现有预览、备份、游戏进程保护及本地修改检查。

首领掉落与静态目录共用一次同步和最终版本核对，限制并发和请求频率；中途失败保留上一份完整缓存。关联使用 NPC、首领战、副本、物品编号，不按名称猜测。掉率未核实，不填入估计值。

[AtlasLoot Classic Forever](https://www.curseforge.com/wow/addons/atlasloot-forever/files/9467191)（Sliccer，1.3.1-061126-16001，核对日期 2026-11-07）已加入发现目录，通过作者 Forever ZIP 导入。
