"""Display facts for concrete addon projects, separate from install authorization."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .addon_metadata import SOURCES, plain, read_toc

PROJECTS = {
    "ellesmere": {
        "name": "EllesmereUI", "author": "Ellesmere", "category": "界面", "icon": "ellesmere-icon",
        "description": "模块化界面组合，提供可视化布局编辑、动作条、单位框、背包、聊天及战斗统计。",
        "source_url": "https://github.com/EllesmereGaming/EllesmereUI/releases",
        "homepage": "https://www.curseforge.com/wow/addons/ellesmereui",
        "screenshots": ["ellesmere-preview", "ellesmere-editor"],
    },
    "dbm": {
        "name": "Deadly Boss Mods", "author": "MysticalOS, QartemisT", "category": "副本", "icon": "dbm-icon",
        "description": "首领战计时条、机制警告与语音提示；安装时检查当前无限客户端的作者发布。",
        "source_url": "https://github.com/DeadlyBossMods/DeadlyBossMods/releases",
        "homepage": "https://www.curseforge.com/wow/addons/deadly-boss-mods", "screenshots": ["dbm-preview"],
    },
    "bigwigs": {
        "name": "BigWigs", "author": "Funkeh, Nebula, Justwait, Delk", "category": "副本", "icon": "bigwigs-icon",
        "description": "模块化首领计时与团队提示，也是 LittleWigs 的核心依赖。",
        "source_url": "https://github.com/BigWigsMods/BigWigs/releases",
        "homepage": "https://www.curseforge.com/wow/addons/bigwigs", "screenshots": [],
    },
    "littlewigs": {
        "name": "LittleWigs", "author": "Funkeh, Delk", "category": "副本", "icon": "littlewigs-icon",
        "description": "为 BigWigs 补充小队副本等内容的机制提示；需要同时安装 BigWigs。",
        "source_url": "https://github.com/BigWigsMods/LittleWigs/releases",
        "homepage": "https://www.curseforge.com/wow/addons/littlewigs", "screenshots": [], "dependencies": ["BigWigs"],
    },
    "details": {
        "name": "Details!", "author": "Terciob", "category": "战斗", "icon": "details-icon",
        "description": "伤害、治疗与战斗数据统计。可与界面方案配合使用，注意避免重复统计窗口。",
        "source_url": "https://www.curseforge.com/wow/addons/details", "screenshots": ["details-preview"],
    },
    "local-ForeverUI": {
        "name": "ForeverUI", "author": "Forever", "category": "界面", "icon": "forever-icon",
        "description": "内置界面方案：原生动作条换肤、单位框、只读行囊、地图、任务与聊天。动作条布局由游戏管理。",
        "source_url": None, "screenshots": ["forever-layout"], "bundled": "ForeverUI",
    },
    "local-ForeverAI": {
        "name": "ForeverAI", "author": "Forever", "category": "角色", "icon": "forever-icon",
        "description": "只读采集角色装备、背包、专业和任务，在游戏存档落盘后同步至桌面客户端。",
        "source_url": None, "screenshots": [], "bundled": "ForeverAI",
    },
    "local-BagBrother": {
        "name": "BagBrother", "author": "Jaliborc", "category": "背包", "icon": "bagbrother-icon",
        "description": "Bagnon 与 Bagnonium 使用的共享背包引擎。它是具体组件，界面由关联插件提供。",
        "source_url": "https://www.curseforge.com/wow/addons/bagbrother", "screenshots": [],
    },
    "local-DBM-VPVEM": {
        "name": "DBM · VEM 语音包", "author": "Iceoven", "category": "副本", "icon": "dbm-icon",
        "description": "DBM 的 VEM 英文女声语音包；使用前需要启用 DBM 核心。",
        "source_url": "https://www.curseforge.com/wow/addons/dbm-voicepack-vem", "screenshots": [],
        "dependencies": ["DBM-Core"],
    },
    "atlas": {
        "name": "Atlas", "author": "arithmandar", "category": "地图", "icon": "category-addon",
        "description": "地下城地图浏览器核心。地图由独立地图包提供，需要搭配 Atlas Kalimdor & Eastern Kingdoms 等模块。",
        "source_url": "https://www.curseforge.com/wow/addons/atlas", "screenshots": [],
        "related": ["atlas-classic"], "reference_url": "/references?kind=maps",
        "support": {"version": "v1.54.04", "checked_at": "2026-11-07", "basis": "作者 release.json 声明 Forever / Interface 16001"},
    },
    "atlas-classic": {
        "name": "Atlas Kalimdor & Eastern Kingdoms", "author": "arithmandar", "category": "地图", "icon": "category-addon",
        "description": "Atlas 的卡利姆多与东部王国地下城地图包。需安装 Atlas 核心；地图覆盖范围以作者说明为准。",
        "source_url": "https://www.curseforge.com/wow/addons/atlas-classicwow", "screenshots": [],
        "dependencies": ["Atlas"], "related": ["atlas"], "reference_url": "/references?kind=instances",
        "support": {"version": "v1.54.03", "checked_at": "2026-11-07", "basis": "作者文件页列出 Forever 版本"},
    },
    "atlas-forever": {
        "name": "Atlas Forever (fork)", "author": "Lizerius", "category": "地图", "icon": "category-addon",
        "description": "面向 Forever 的 Atlas 分支，提供副本地图、入口与交通路线。与 Atlas 主版功能重叠，请选择一套地图方案。",
        "source_url": "https://www.curseforge.com/wow/addons/atlas-forever", "screenshots": [],
        "reference_url": "/references?kind=maps",
        "support": {"version": "3.18.6", "checked_at": "2026-11-07", "basis": "作者文件页标注 Forever / 1.60.1"},
    },
    "dbm-dungeons": {
        "name": "DBM · 地下城首领模块", "author": "MysticalOS", "category": "副本", "icon": "dbm-icon",
        "description": "为 DBM 核心补充地下城机制警告与计时，含 Forever 和经典地下城模块。需要 DBM-Core；与 LittleWigs 按需选择。",
        "source_url": "https://www.curseforge.com/wow/addons/deadly-boss-mods-dbm-dungeons", "screenshots": [],
        "dependencies": ["DBM-Core"], "related": ["dbm", "littlewigs"], "reference_url": "/references?kind=bosses",
        "support": {"version": "270", "checked_at": "2026-11-07", "basis": "作者 release.json 与 Forever 模块 TOC 均声明 Interface 16001"},
    },
    "questie": {
        "name": "Questie", "author": "Questie 团队", "category": "任务", "icon": "category-addon",
        "description": "任务辅助：可接任务、目标位置、追踪与任务历史。作者提供 Forever 版本；任务覆盖与位置以当前版本和游戏内为准。",
        "source_url": "https://www.curseforge.com/wow/addons/questie", "screenshots": [],
        "reference_url": "/references?kind=quests",
        "support": {"version": "v12.6.2 / QuestieDB v1.0.11", "checked_at": "2026-11-07", "basis": "作者组合发布清单声明 Forever / Interface 16001"},
    },
    "dungeonjournal": {
        "name": "DungeonJournal", "author": "ExehnTV", "category": "任务", "icon": "category-addon",
        "description": "地下城资料手册，汇总副本任务、接取位置与首领掉落。提供 Forever 文件；资料覆盖和掉落由作者维护。",
        "source_url": "https://www.curseforge.com/wow/addons/dungeonjournal", "screenshots": [],
        "reference_url": "/references?kind=instances",
        "support": {"version": "1.7.0", "checked_at": "2026-11-07", "basis": "作者文件页标注 Forever / 1.60.1"},
    },
    "atlasloot-forever": {
        "name": "AtlasLoot Classic Forever", "author": "Sliccer", "category": "副本", "icon": "category-addon",
        "description": "《无限》首领掉落查询与装备资料，覆盖作者维护的地下城和团队副本掉落表。请下载 Forever 文件；作者推荐与实机掉落分开核实。",
        "source_url": "https://www.curseforge.com/wow/addons/atlasloot-forever", "screenshots": [],
        "reference_url": "/references?kind=bosses", "related": ["dungeonjournal", "dbm-dungeons"],
        "support": {"version": "1.3.1-061126-16001", "checked_at": "2026-11-07", "basis": "作者文件页标注 Forever / 1.60.1"},
    },
}
ALIASES = {"foreverui": "local-ForeverUI", "foreverai": "local-ForeverAI", "combat": "details"}


class Catalog:
    def __init__(self, platform, media):
        self.platform, self.media = platform, media

    def screenshot(self, resource_id):
        record = self.media.metadata(resource_id)
        return {"id": resource_id, "url": self.media.url(resource_id, "full"),
                "thumbnail_url": self.media.url(resource_id), "caption": record.get("caption", "作者公开截图"),
                "source_url": record.get("source_url"), "kind": record.get("kind", "author_screenshot")}

    def profile_media(self, name):
        return self.screenshot("ellesmere-preview" if name == "EllesmereUI" else "forever-layout")

    def present(self, group: dict | None, key: str):
        spec = PROJECTS.get(key, {})
        result = deepcopy(group or {"id": key, "modules": [], "version": None, "managed": False,
                                   "source": "github" if SOURCES.get(key, {}).get("repo") else "bundled" if spec.get("bundled")
                                   else "curseforge", "update_status": "unchecked" if key in SOURCES and SOURCES[key].get("repo")
                                   else "local_only" if spec.get("bundled") else "website_required"})
        modules = result.get("modules", [])
        meta = next((m.get("metadata", {}) for m in modules if m.get("metadata", {}).get("author")), {})
        update = result.get("update", {})
        release = update.get("release") or {}
        own_names = {m["directory"] for m in modules}
        dependencies = sorted({d for m in modules for d in m.get("dependencies", []) if d not in own_names}
                              | set(spec.get("dependencies", [])))
        available = release.get("version")
        if spec.get("bundled"):
            folder = Path(__file__).resolve().parents[1] / "addons" / spec["bundled"]
            available = read_toc(folder).get("version")
        actions = ["download"] if SOURCES.get(key, {}).get("repo") else ["bundled"] if spec.get("bundled") else []
        if spec.get("source_url") or result.get("source_url"):
            actions.append("website")
        if group:
            actions += ["enable", "disable"]
            actions.append("uninstall" if result["managed"] else "adopt")
        result.update(
            name=spec.get("name", result.get("name", key)), author=plain(meta.get("author", "")) or spec.get("author") or "作者未注明",
            description=spec.get("description") or plain(meta.get("notes-zhcn", meta.get("notes", ""))) or "本地插件，项目介绍尚未提供。",
            category=spec.get("category", result.get("category", "其他")),
            source_url=spec.get("source_url") or result.get("source_url"), homepage=spec.get("homepage") or spec.get("source_url"),
            icon_url=self.media.url(spec.get("icon", "category-addon")),
            icon_source=self.media.metadata(spec.get("icon", "category-addon")).get("source_url"),
            screenshots=[self.screenshot(s) for s in spec.get("screenshots", [])],
            screenshot_status="available" if spec.get("screenshots") else "作者未提供已核实截图",
            available_version=available, published_at=release.get("published_at"),
            changelog=release.get("changelog") or "更新记录尚未缓存，可前往作者发布页查看。",
            dependencies=dependencies, actions=actions, bundled=spec.get("bundled"), installed=group is not None,
            recognized=key in PROJECTS, checked_at=update.get("checked_at"),
            support=spec.get("support"), reference_url=spec.get("reference_url"),
            related=[{"id": i, "name": PROJECTS[i]["name"]} for i in spec.get("related", [])],
        )
        return result

    def inventory(self):
        inventory = self.platform.inventory()
        inventory["packages"] = [self.present(g, g["id"]) for g in inventory["packages"]]
        return inventory

    def browse(self, q="", category="全部"):
        installed = {g["id"]: g for g in self.platform.inventory()["packages"]}
        items = [self.present(installed.get(key), key) for key in PROJECTS]
        categories = sorted({item["category"] for item in items})
        query = q.casefold().strip()[:150]
        items = [i for i in items if (category == "全部" or i["category"] == category)
                 and (not query or query in " ".join((i["name"], i["author"], i["description"])).casefold())]
        return {"items": items, "categories": categories, "total": len(items)}

    def detail(self, key):
        key = ALIASES.get(key, key)
        installed = next((g for g in self.platform.inventory()["packages"] if g["id"] == key), None)
        if not installed and key not in PROJECTS:
            raise ValueError("没有找到这个插件项目")
        return self.present(installed, key)
