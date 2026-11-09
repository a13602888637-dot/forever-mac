# v0.4 图片来源

登记日期：2026-11-06。完整逐文件 SHA256、来源和缩略图对应关系见 `frontend/static/media/manifest.json`。只保存公开项目素材，不含用户截图、账号目录或 SavedVariables。

| 资源 | 核对依据 | 处理 |
| --- | --- | --- |
| DBM、EllesmereUI、BigWigs、LittleWigs、Details!、BagBrother 图标 | 对应已安装发布包 TOC 的 `IconTexture`；素材相对路径记在 manifest 的 `source_asset` | TGA/BLP 转 PNG，保留透明度；图标来源链接指向作者项目 |
| VEM 语音包图标 | `DBM-VPVEM.toc` 明确复用 `DBM-Core/textures/dbm_airhorn` | 复用 DBM 已登记图标 |
| ForeverUI / ForeverAI 图标 | 本项目 `frontend/static/app-icon.png` | 生成 160px 缩略图 |
| EllesmereUI 布局、编辑器 | [作者 CurseForge 图集](https://www.curseforge.com/wow/addons/ellesmereui) 中 1.png、2.png | 来源图片分别为 [布局](https://media.forgecdn.net/attachments/1664/341/1-png.png)、[编辑器](https://media.forgecdn.net/attachments/1663/775/2-png.png)；1600px 大图及 640×360 缩略图，标明客户端版本未提供 |
| Details! 窗口 | [作者 CurseForge 图集](https://www.curseforge.com/wow/addons/details) | [原图](https://media.forgecdn.net/attachments/215/323/mainwindow.png)，标明客户端版本未提供 |
| DBM 警告 | [作者 CurseForge 图集](https://www.curseforge.com/wow/addons/deadly-boss-mods) | [历史原图](https://media.forgecdn.net/attachments/76/27/dbm-warnings1.png)，明确不能代表当前无限版本外观 |
| ForeverUI 布局示意 | 当前 `addons/ForeverUI/Modules/ActionBars.lua`、`Units.lua`、`Chat.lua`、`Minimap.lua`、`Tracker.lua` | 自制 SVG：三排各 12 个动作按钮、下方玩家/目标框、左侧队伍/聊天、右侧地图/任务；明确“布局示意，不是游戏截图” |
| 职业、种族 | [classes.json](https://wuxianwow.com/data/classes.json)、[races.json](https://wuxianwow.com/data/races.json) 与 [种族页](https://wuxianwow.com/races) 的图片元数据 | 9 个职业及 8 个唯一可识别种族的公开图片内置；`Skyborne` 对应两个种族时不根据 token 猜测 |
| 物品、配方 | [无限图鉴](https://wuxianwow.com/about) 原始记录的数值 `icon` 字段 | 经服务器登记后，读取 `https://wuxianwow.com/share/<iconID>.jpg`；保留源图片，无改画；没有 icon ID 时明确缺图 |

图集仅用于展示；是否能安装仍由当前客户端、作者 Forever 发布声明和事务预览决定。没有核实到截图的插件显示缺失状态，不以其他插件图片填充。

所有页面图片通过 `/api/media/<registered-id>` 同源提供。接口不接收 URL。媒体缓存限制来源、协议、路径、重定向、字节数及图像类型；下载失败不替换已有缓存。大图由页面按需加载，内置截图缩略图预先生成，数字图标源本身为 300×300 的分享图片。缓存目录在用户 `data` 下，不进入公开仓库。
