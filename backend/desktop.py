"""Presentation helpers keep optional reference data separate from saved character facts."""
from __future__ import annotations

from .rules import STAT_NAMES

SLOTS = {1: "头部", 2: "颈部", 3: "肩部", 4: "衬衣", 5: "胸部", 6: "腰部", 7: "腿部",
         8: "脚部", 9: "手腕", 10: "手部", 11: "手指一", 12: "手指二", 13: "饰品一", 14: "饰品二",
         15: "背部", 16: "主手", 17: "副手", 18: "远程", 19: "战袍"}
EQUIP_SLOTS = {"INVTYPE_HEAD": (1,), "INVTYPE_NECK": (2,), "INVTYPE_SHOULDER": (3,), "INVTYPE_BODY": (4,),
               "INVTYPE_CHEST": (5,), "INVTYPE_ROBE": (5,), "INVTYPE_WAIST": (6,), "INVTYPE_LEGS": (7,),
               "INVTYPE_FEET": (8,), "INVTYPE_WRIST": (9,), "INVTYPE_HAND": (10,), "INVTYPE_FINGER": (11, 12),
               "INVTYPE_TRINKET": (13, 14), "INVTYPE_CLOAK": (15,), "INVTYPE_WEAPON": (16, 17),
               "INVTYPE_2HWEAPON": (16,), "INVTYPE_WEAPONMAINHAND": (16,), "INVTYPE_WEAPONOFFHAND": (17,),
               "INVTYPE_SHIELD": (17,), "INVTYPE_HOLDABLE": (17,), "INVTYPE_RANGED": (18,),
               "INVTYPE_RANGEDRIGHT": (18,), "INVTYPE_THROWN": (18,), "INVTYPE_TABARD": (19,)}
CLASSES = {"MAGE": "法师", "WARRIOR": "战士", "PALADIN": "圣骑士", "HUNTER": "猎人", "ROGUE": "潜行者",
           "PRIEST": "牧师", "SHAMAN": "萨满祭司", "WARLOCK": "术士", "DRUID": "德鲁伊", "DEATHKNIGHT": "死亡骑士",
           "MONK": "武僧", "DEMONHUNTER": "恶魔猎手", "EVOKER": "唤魔师"}
RACES = {"Human": "人类", "Orc": "兽人", "Dwarf": "矮人", "NightElf": "暗夜精灵", "Scourge": "亡灵",
         "Undead": "亡灵", "Tauren": "牛头人", "Gnome": "侏儒", "Troll": "巨魔", "BloodElf": "血精灵",
         "Draenei": "德莱尼", "Goblin": "地精", "Worgen": "狼人", "Pandaren": "熊猫人"}
QUALITY = {0: "粗糙", 1: "普通", 2: "优秀", 3: "精良", 4: "史诗", 5: "传说", 6: "神器", 7: "传家宝"}
ITEM_CLASSES = {0: "消耗品", 1: "容器", 2: "装备", 3: "宝石", 4: "装备", 7: "材料", 9: "配方", 12: "任务", 15: "其他"}
STAT_LABELS = {**STAT_NAMES, "ITEM_MOD_DAMAGE_PER_SECOND_SHORT": "武器每秒伤害",
               "ITEM_MOD_ATTACK_POWER_SHORT": "攻击强度", "ITEM_MOD_SPELL_POWER_SHORT": "法术强度","ITEM_MOD_INTELLECT_SHORT": "智力", "ITEM_MOD_STRENGTH_SHORT": "力量", "ITEM_MOD_AGILITY_SHORT": "敏捷",
               "ITEM_MOD_STAMINA_SHORT": "耐力", "ITEM_MOD_SPIRIT_SHORT": "精神", "RESISTANCE0_NAME": "护甲",
               "ITEM_MOD_CRIT_RATING_SHORT": "暴击", "ITEM_MOD_HASTE_RATING_SHORT": "急速",
               "ITEM_MOD_HIT_RATING_SHORT": "命中", "ITEM_MOD_MASTERY_RATING_SHORT": "精通"}


def character_view(snapshot, refs, media):
    if not snapshot:
        return {}
    dataset = refs.dataset("items")
    payload = (dataset or {}).get("payload", {})
    records = {row["id"]: row for row in (payload.values() if isinstance(payload, dict) else payload)
               if isinstance(row, dict) and "id" in row}
    equipped = {i.slot: i for i in snapshot.equipment or []}

    def item_view(item, index=None):
        result = item.model_dump()
        record = records.get(item.item_id, {})
        result.update(index=index, icon_url=media.item_icon(record) if record else None,
                      quality_name=QUALITY.get(item.quality, "品质未读取"),
                      category="装备" if item.equip_location else ITEM_CLASSES.get(record.get("cls"), "其他"),
                      reference_url=f"/references/items/{item.item_id}" if record else None,
                      stats_display=[{"label": STAT_LABELS.get(key, key), "value": value, "display": f"{value:,.2f}".rstrip("0").rstrip(".") if value is not None else "未知"}
                                     for key, value in (item.stats or {}).items()],
                      compare_slots=[{"id": slot, "name": SLOTS[slot]} for slot in EQUIP_SLOTS.get(item.equip_location, ())
                                     if slot in equipped and equipped[slot].item_id and equipped[slot].status == "available"])
        return result

    slots = [{"slot": slot, "label": label, "item": item_view(equipped[slot]) if slot in equipped else None}
             for slot, label in SLOTS.items()]
    bag_items = [item_view(item, index) for index, item in enumerate(snapshot.bags or [])]
    totals = {}
    for item in snapshot.equipment or []:
        if item.status == "available":
            for key, value in (item.stats or {}).items():
                if value is not None and key in STAT_NAMES:
                    totals[key] = totals.get(key, 0) + value
    return {"equipment_slots": slots, "bag_items": bag_items, "bag_categories": sorted({i["category"] for i in bag_items}),
            "bag_numbers": sorted({i["bag"] for i in bag_items if i["bag"] is not None}),
            "equipment_stats": [{"label": STAT_LABELS.get(key, key), "value": value, "display": f"{value:,.2f}".rstrip("0").rstrip(".")} for key, value in totals.items()],
            "class_name": CLASSES.get(snapshot.character.class_token, snapshot.character.class_token or "职业未读取"),
            "race_name": RACES.get(snapshot.character.race_token, snapshot.character.race_token or "种族未读取"),
            "character_art": media.character_art(snapshot.character.class_token, snapshot.character.race_token)}


def selected_profile(characters, snapshot):
    if not snapshot:
        return ""
    matches = [c["id"] for c in characters if c.get("snapshot_identity") == snapshot.character.identity and not c.get("format_error")]
    return matches[0] if len(matches) == 1 else ""
