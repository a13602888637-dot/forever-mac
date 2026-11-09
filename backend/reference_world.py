"""Read-only world reference views; source gaps and supplemental data stay explicit."""
from __future__ import annotations

import math

from . import reference_loot as loot

WORLD_DATASETS = {"instances": (None, "instances"), "npcs": ("npcs", "npcs"),
                  "atlas": ("maps", "atlas_maps"), "quests": ("quests", "quests"),
                  "questlines": ("lines", "questlines")}
WORLD_KINDS = {"instances": "instances", "bosses": "npcs", "maps": "atlas", "quests": "quests"}
KIND_LABELS = {"items": "物品", "recipes": "配方", "instances": "副本", "bosses": "首领",
               "maps": "地图与入口", "quests": "任务"}
MAP_GAP = "当前来源没有地下城内部地图；这里展示区域地图与副本入口。"
ENTRANCE_SOURCES = {"Map.Corpse": "副本外复活落点", "AreaPOI": "客户端地图标记",
                    "WorldMapOverlay": "子区域中心（近似）", "UiMap": "区域中心（近似）"}


def validate_world(name, payload, manifest):
    key, count_key = WORLD_DATASETS[name]
    rows = payload.get(key) if isinstance(payload, dict) and key else payload
    if not isinstance(rows, list):
        raise ValueError(f"{name} 资料结构异常，保留已有缓存")
    expected = manifest.get("counts", {}).get(count_key)
    if type(expected) is not int or expected != len(rows):
        raise ValueError(f"{name} 数量与来源声明不符，保留已有缓存")
    if isinstance(payload, dict):
        meta = payload.get("_meta", {})
        if not isinstance(meta, dict) or meta.get("build", manifest["build"]) != manifest["build"]:
            raise ValueError(f"{name} 与版本清单不一致，保留已有缓存")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0
                or row["id"] in seen or (name != "quests" and not isinstance(row.get("name"), str))):
            raise ValueError(f"{name} 记录校验失败，保留已有缓存")
        if name == "quests" and "title" in row and not isinstance(row["title"], str):
            raise ValueError("任务标题格式异常，保留已有缓存")
        object_fields = {"instances": ("level", "entrance", "boss_difficulty"), "npcs": ("tmp",),
                         "quests": ("tmp", "zone", "category", "reward"), "atlas": (), "questlines": ()}[name]
        list_fields = {"instances": ("bosses", "players"), "npcs": (), "quests": ("prev", "cache_texts", "goals"),
                       "atlas": ("instances",), "questlines": ("quests",)}[name]
        if (any(row.get(k) is not None and not isinstance(row[k], dict) for k in object_fields)
                or any(row.get(k) is not None and not isinstance(row[k], list) for k in list_fields)):
            raise ValueError(f"{name} 关联字段异常，保留已有缓存")
        if name == "npcs" and row.get("source") == "encounter":
            if type(row.get("map")) is not int or type(row.get("encounter")) is not int:
                raise ValueError("首领缺少副本或战斗编号，保留已有缓存")
        seen.add(row["id"])
    if name == "npcs" and "bosses" in manifest.get("counts", {}):
        bosses = sum(row.get("source") == "encounter" for row in rows)
        if manifest["counts"]["bosses"] != bosses:
            raise ValueError("首领数量与来源声明不符，保留已有缓存")


def records(kind, payload):
    dataset = WORLD_KINDS[kind]
    key = WORLD_DATASETS[dataset][0]
    values = payload.get(key, []) if key and isinstance(payload, dict) else payload
    result = []
    for raw in values if isinstance(values, list) else []:
        if not isinstance(raw, dict) or type(raw.get("id")) is not int:
            continue
        if kind == "bosses" and raw.get("source") != "encounter":
            continue
        row = dict(raw)
        if kind == "quests":
            # A Questie name or an item hint is not a server-confirmed quest title.
            row["name"] = row.get("title") or f"任务 #{row['id']}"
            row["coverage"] = "有任务正文" if row.get("title") else "仅编号 / 补充线索"
        if isinstance(row.get("name"), str):
            result.append(row)
    return result


def category(record, kind):
    if kind == "quests":
        if not record.get("title"):
            return "clues", "仅编号 / 补充线索"
        zone = record.get("zone") or record.get("category") or {}
        if isinstance(zone, dict) and zone.get("name"):
            return str(zone.get("id", zone["name"])), zone["name"]
        return "unknown", "区域未收录"
    field = {"instances": "kind", "bosses": "zone", "maps": "type_name"}[kind]
    value = record.get(field) or "未分类"
    return str(value), str(value)


def search_text(record, kind):
    text = [record["name"], str(record["id"])]
    if kind in WORLD_KINDS:
        text.append(category(record, kind)[1])
        if isinstance(record.get("zone"), str):
            text.append(record["zone"])
        if kind == "quests":
            text += [record.get("hint", ""), record.get("type", ""), (record.get("tmp") or {}).get("name", "")]
    return " ".join(s for s in text if isinstance(s, str)).casefold()


def artwork(record, kind):
    return record.get({"instances": "loading", "bosses": "portrait", "maps": "art"}.get(kind, ""))


def supplement(record, kind):
    return kind in ("bosses", "quests") and bool(record.get("tmp"))


def detail(refs, kind, record, result):
    fields, paragraphs, groups, maps, notes, loot_groups = [], [], [], [], [], []

    def field(label, value):
        if value is not None and value != "" and value != []:
            fields.append({"label": label, "value": value})

    def relation(target_kind, ident, name=None, quantity=None):
        target = next((r for r in refs._records(target_kind) if r["id"] == ident), None)
        return {"id": ident, "kind": target_kind, "name": target["name"] if target else name or f"未收录 · {ident}",
                "url": f"/references/{target_kind}/{ident}" if target else None, "quantity": quantity,
                "known": target is not None}

    def group(title, values):
        if values:
            groups.append({"title": title, "items": values})

    map_records = {m["id"]: m for m in refs._records("maps")}

    def map_view(map_id, markers, caption):
        atlas = map_records.get(map_id)
        if not atlas:
            return
        pins = []
        for mark in markers:
            x, y = mark.get("x"), mark.get("y")
            if (type(x) not in (float, int) or type(y) not in (float, int)
                    or not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1):
                continue
            pins.append({**mark, "x_percent": round(x * 100, 2), "y_percent": round(y * 100, 2)})
        maps.append({"id": map_id, "name": atlas["name"], "art_path": atlas.get("art"),
                     "url": f"/references/maps/{map_id}", "caption": caption, "markers": pins})

    if kind == "instances":
        level = record.get("level") or {}
        field("类型", record.get("kind"))
        field("所在区域", record.get("zone"))
        field("人数", " / ".join(str(n) for n in record.get("players", [])))
        field("最低进入等级", level.get("min"))
        field("目标等级", level.get("target"))
        field("组队等级范围", "–".join(str(n) for n in level.get("group") or []))
        if record.get("description"):
            paragraphs.append(record["description"])
        boss_index = {b.get("encounter"): b for b in refs._records("bosses") if b.get("map") == record["id"]}
        ordered = []
        for boss in sorted(record.get("bosses") or [], key=lambda b: b.get("order", 0)):
            target = boss_index.get(boss["id"])
            value = relation("bosses", target["id"], boss.get("name")) if target else {
                "name": boss.get("name"), "url": None, "known": False}
            value["order"] = boss.get("order")
            ordered.append(value)
            if target:
                loot_groups.append(loot.view(refs, target))
        group("首领顺序", ordered)
        group("副本任务", [relation("quests", q["id"]) for q in refs._records("quests")
                           if isinstance(q.get("zone"), dict) and q["zone"].get("instance") == record["id"]])
        entrance = record.get("entrance") or {}
        locations = entrance.get("atlas") or []
        chosen = next((m for m in locations if m.get("ui_map") == entrance.get("zone_ui_map")),
                      locations[0] if locations else None)
        if chosen:
            label = "近似入口" if entrance.get("approx") else "入口标记"
            map_view(chosen["ui_map"], [{**chosen, "label": label, "source": ENTRANCE_SOURCES.get(entrance.get("source"), "来源未注明"),
                                        "approx": bool(entrance.get("approx"))}], "区域入口地图 · " + label)
            field("入口依据", ENTRANCE_SOURCES.get(entrance.get("source"), "来源未注明"))
            field("入口可信度", {"high": "高", "medium": "中", "low": "低"}.get(entrance.get("confidence"), "未注明"))
        else:
            notes.append(record.get("entrance_missing") or "来源尚未提供可定位的入口。")
        notes += [MAP_GAP, "首领掉落来自单独标注的第三方参考；当前资料不含已核实的技能攻略。"]
    elif kind == "bosses":
        field("所属副本", record.get("zone"))
        field("难度", "通用" if record.get("difficulty_id") == 0 else record.get("difficulty") or "待核实")
        group("所属副本", [relation("instances", record["map"])])
        loot_groups.append(loot.view(refs, record))
        notes.append("首领顺序以所属副本页面为准；掉落来源和适用版本在下方列出，掉率与实际掉落仍待核实。")
    elif kind == "maps":
        field("地图类型", record.get("kind") or record.get("type_name"))
        pins = []
        for entry in record.get("instances") or []:
            value = relation("instances", entry["id"], entry.get("name"))
            pins.append({**entry, "label": value["name"], "url": value["url"],
                         "source": ENTRANCE_SOURCES.get(entry.get("source"), "来源未注明")})
        map_view(record["id"], pins, "区域地图 · 点击入口标记查看副本")
        group("此图的副本入口", [relation("instances", p["id"], p.get("name")) for p in pins])
        if record.get("parent"):
            group("上级地图", [relation("maps", record["parent"])])
        notes.append(MAP_GAP)
    elif kind == "quests":
        field("资料状态", record["coverage"])
        field("任务等级", record.get("level"))
        field("最低等级", record.get("min_level"))
        field("阵营", record.get("side"))
        field("类型", record.get("type"))
        zone = record.get("zone") or {}
        field("所在区域", zone.get("name"))
        paragraphs += [text.replace("$B", "\n") for text in record.get("cache_texts") or [] if isinstance(text, str)]
        goals = [f"{g.get('name') or '目标 #' + str(g.get('id', '未知'))} × {g.get('n', '未知')}"
                 for g in record.get("goals") or [] if isinstance(g, dict)]
        if goals:
            paragraphs.insert(0, "任务目标：\n" + "\n".join(goals))
        group("前置任务", [relation("quests", i) for i in record.get("prev") or [] if type(i) is int])
        if type(record.get("next")) is int:
            group("后续任务", [relation("quests", record["next"])])
        if zone.get("instance"):
            group("关联副本", [relation("instances", zone["instance"])])
        reward = record.get("reward") or {}
        field("经验奖励", reward.get("xp"))
        group("奖励物品", [relation("items", p[0], quantity=p[1]) for p in reward.get("items") or []
                           if isinstance(p, list) and len(p) == 2 and type(p[0]) is int])
        if record.get("hint"):
            field("客户端线索（非任务标题）", record["hint"])
        atlas = refs.dataset("atlas")
        locations = ((atlas or {}).get("payload", {}).get("quest_maps") or {}).get(str(record["id"]), [])
        for location in locations[:3]:
            markers = []
            for mark in location.get("marks", [])[:30]:
                label = {"start": "接取", "end": "交付", "obj": "目标"}.get(mark.get("k"), "任务标记")
                markers.append({**mark, "label": label + (" · " + mark["name"] if mark.get("name") else ""),
                                "source": "QuestieDB · 第三方补充，待核实" if mark.get("src") == "questie" else "客户端任务标记",
                                "approx": mark.get("src") == "questie"})
            map_view(location.get("map"), markers, "任务位置 · 第三方标记单独标注，不代表当前角色进度")
        lines = refs.dataset("questlines")
        for line in (lines or {}).get("payload", {}).get("lines", []):
            if record["id"] in line.get("quests", []):
                group("任务线 · " + line["name"], [relation("quests", i) for i in line["quests"]])
        if not record.get("title"):
            notes.append("当前只有任务编号或线索，尚无《无限》服务器确认的任务标题与正文。")
        notes.append("资料库记录不代表角色已接取、完成或满足前置条件。")
    tmp = record.get("tmp") or {}
    extra = []
    for key, label in (("name", "参考名称"), ("giver", "参考接取者"), ("level", "参考等级"),
                       ("min_level", "参考最低等级"), ("side", "参考阵营")):
        if key in tmp:
            value = "–".join(map(str, tmp[key])) if isinstance(tmp[key], list) else tmp[key]
            extra.append({"label": label, "value": value})
    result.update(fields=fields, paragraphs=paragraphs, groups=groups, maps=maps, notes=notes, loot_groups=loot_groups,
                  supplements=extra, kind_label=KIND_LABELS[kind],
                  source_page="https://wuxianwow.com/" + {"instances": "instance", "bosses": "npc",
                                                         "maps": "atlas", "quests": "quest"}[kind] + f"/{record['id']}")
    return result
