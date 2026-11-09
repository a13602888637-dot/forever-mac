"""Boss detail supplements from the public NPC API, never inferred drop tables."""
from __future__ import annotations

import asyncio
import json
import time


def normalize(payload, boss):
    if (not isinstance(payload, dict) or payload.get("outcome") != "ok"
            or payload.get("npc_id") != boss["id"] or payload.get("source") != "encounter"
            or (payload.get("encounter") or {}).get("id") != boss["encounter"]):
        raise ValueError("首领掉落详情与目录编号不一致，保留已有缓存")
    instance = payload.get("instance") or {}
    if instance.get("id") is not None and instance["id"] != boss["map"]:
        raise ValueError("首领掉落所属副本不一致，保留已有缓存")
    drops = payload.get("temporary_drops")
    result = {"boss_id": boss["id"], "instance_id": boss["map"], "encounter_id": boss["encounter"],
              "source": None, "note": "来源未收录此首领的掉落；不代表它没有掉落。", "items": []}
    if drops is None:
        return result
    if (not isinstance(drops, dict) or not isinstance(drops.get("source"), str)
            or not drops["source"].strip() or not isinstance(drops.get("items"), list)):
        raise ValueError("首领掉落结构异常，保留已有缓存")
    seen = set()
    for item in drops["items"]:
        if (not isinstance(item, dict) or type(item.get("item_id")) is not int or item["item_id"] <= 0
                or not isinstance(item.get("name"), str)):
            raise ValueError("首领掉落物品无有效编号或名称，保留已有缓存")
        if item["item_id"] in seen:
            continue
        seen.add(item["item_id"])
        result["items"].append({"item_id": item["item_id"], "name": item["name"],
                                "quality": item.get("quality"), "not_in_client": bool(item.get("not_in_client")),
                                "shared": bool(item.get("shared"))})
    result.update(source=drops["source"][:100], note=str(drops.get("note") or "第三方临时掉落，待游戏内核实")[:2000])
    return result


async def fetch_catalog(refs, client, bosses):
    semaphore, rate_lock = asyncio.Semaphore(6), asyncio.Lock()
    last_start = 0.0

    async def fetch(boss):
        nonlocal last_start
        async with semaphore:
            async with rate_lock:
                # Published service limit is 600/min; leave room for other queries.
                await asyncio.sleep(max(0, .16 - (time.monotonic() - last_start)))
                last_start = time.monotonic()
            result = await refs._json(client, "POST", "/mcp", {"jsonrpc": "2.0", "id": boss["id"],
                "method": "tools/call", "params": {"name": "npcs", "arguments": {"id": boss["id"]}}})
            envelope = result.get("result") if isinstance(result, dict) else None
            if not isinstance(envelope, dict) or envelope.get("isError"):
                raise ValueError("首领详情接口未返回可用资料，保留已有缓存")
            content = envelope.get("content")
            if not isinstance(content, list):
                raise ValueError("首领详情响应格式异常，保留已有缓存")
            texts = [block.get("text") for block in content if isinstance(block, dict) and block.get("type") == "text"]
            if len(texts) != 1 or not isinstance(texts[0], str):
                raise ValueError("首领详情响应格式异常，保留已有缓存")
            try:
                payload = json.loads(texts[0])
            except (ValueError, TypeError):
                raise ValueError("首领详情不是有效 JSON，保留已有缓存") from None
            return str(boss["id"]), normalize(payload, boss)

    return dict(await asyncio.gather(*(fetch(boss) for boss in bosses)))


def report(payload):
    sources = {}
    for row in payload.values():
        if row["items"]:
            sources[row["source"]] = sources.get(row["source"], 0) + 1
    return {"bosses": len(payload), "with_loot": sum(bool(r["items"]) for r in payload.values()),
            "item_relations": sum(len(r["items"]) for r in payload.values()), "sources": sources}


def view(refs, boss):
    row = refs.dataset("boss_loot")
    cached = row["payload"].get(str(boss["id"])) if row else None
    result = {"boss_id": boss["id"], "name": boss["name"], "url": f"/references/bosses/{boss['id']}",
              "cached": cached is not None, "items": [], "source": cached.get("source") if cached else None,
              "source_url": f"https://wuxianwow.com/npc/{boss['id']}", "provenance": "assumption",
              "fetched_at": row["fetched_at"] if row else None,
              "note": cached["note"] if cached else "掉落尚未同步，点击同步资料加载。"}
    result["source_label"] = {"Spyglass": "Spyglass · 无限参考", "QuestieDB": "QuestieDB · 经典旧世参考"}.get(
        result["source"], (result["source"] + " · 第三方参考") if result["source"] else "尚无来源记录")
    items = {i["id"]: i for i in refs._records("items")}
    for value in cached["items"] if cached else []:
        item = items.get(value["item_id"])
        result["items"].append({**value, "id": value["item_id"], "kind": "items",
            "name": item["name"] if item else value["name"], "q": item.get("q") if item else value["quality"],
            "icon_id": item.get("icon") if item else None,
            "item_level": item.get("ilvl") if item else None, "required_level": item.get("req") if item else None,
            "slot": item.get("slot") if item else None, "known": item is not None,
            "url": f"/references/items/{value['item_id']}" if item else None,
            "source_url": f"https://wuxianwow.com/item/{value['item_id']}"})
    return result


def dropped_by(refs, item_id):
    row = refs.dataset("boss_loot")
    if not row:
        return []
    bosses = {b["id"]: b for b in refs._records("bosses")}
    result = []
    for loot in row["payload"].values():
        if loot["boss_id"] in bosses and any(i["item_id"] == item_id for i in loot["items"]):
            boss = bosses[loot["boss_id"]]
            result.append({"id": boss["id"], "name": boss["name"], "url": f"/references/bosses/{boss['id']}",
                           "source_label": f"{loot['source']} · 第三方参考", "kind": "bosses"})
    return result
