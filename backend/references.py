"""Explicit, read-only wuxianwow.com integration. Never sends character snapshots."""
from __future__ import annotations

import json
import asyncio
from pathlib import Path
import re
import time

import httpx

from .db import Database
from .models import Item, Recipe, Snapshot
from .rules import STAT_NAMES
from . import reference_world as world
from . import reference_loot as loot

BASE = "https://wuxianwow.com"
DATASETS = ("manifest", "items", "recipes", "professions", "stat_names")
MAX_BYTES = 8 * 1024 * 1024
MCP_TOOLS = {"search", "fetch", "recipes", "gear_items", "item_usage", "instances", "npcs", "quests", "atlas"}
PRODUCTS = {"wowf", "wow_cn_beta"}
ITEM_CLASSES = {0: "消耗品", 1: "容器", 2: "武器", 3: "宝石", 4: "护甲", 5: "材料", 6: "弹药",
                7: "商品", 8: "物品强化", 9: "配方", 10: "货币", 11: "箭袋", 12: "任务", 13: "钥匙",
                15: "杂项", 16: "雕文", 17: "战斗宠物", 18: "时光徽章", 19: "专业装备"}
QUALITY_NAMES = {0: "粗糙", 1: "普通", 2: "优秀", 3: "精良", 4: "史诗", 5: "传说", 6: "神器", 7: "传家宝"}


def icon_url(record):
    """Only construct a known public icon URL; raw records cannot supply arbitrary URLs."""
    icon = record.get("icon")
    return f"{BASE}/share/{icon}.jpg" if type(icon) is int and 0 < icon <= 2_147_483_647 else None


class ReferenceError(ValueError):
    pass


class References:
    def __init__(self, db: Database, enabled=True, transport=None, addon_catalog_path: Path | None = None):
        self.db, self.enabled, self.transport = db, enabled, transport
        self.addon_catalog_path = addon_catalog_path
        self._cache = {}

    async def _json(self, client, method, path, body=None):
        try:
            async with client.stream(method, BASE + path, json=body) as response:
                if response.status_code != 200:
                    raise ReferenceError(f"无限图鉴返回 HTTP {response.status_code}；已有缓存仍可使用")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES:
                        raise ReferenceError("远端资料超过 8 MiB 限制")
            return json.loads(content)
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeError):
            raise ReferenceError("无限图鉴网络或资料格式异常；已有缓存仍可使用") from None

    async def sync(self):
        if not self.enabled:
            raise ReferenceError("外部资料已关闭")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport,
                                     headers={"User-Agent": "Forever/0.4 (read-only)", "Accept": "application/json"}) as client:
            manifest = await self._json(client, "GET", "/data/manifest.json")
            if not isinstance(manifest, dict) or not isinstance(manifest.get("build"), str) or manifest.get("product") not in PRODUCTS or not isinstance(manifest.get("built_at"), str):
                raise ReferenceError("远端 manifest 缺少国服无限版本信息")
            if not isinstance(manifest.get("counts", {}), dict):
                raise ReferenceError("版本资料的数量声明无效")
            datasets = {"manifest": manifest}
            for name in DATASETS[1:]:
                value = await self._json(client, "GET", f"/data/{name}.json")
                expected = list if name in ("recipes", "professions") else dict
                if not isinstance(value, expected) or not value:
                    raise ReferenceError(f"{name} 数据结构异常，未替换缓存")
                datasets[name] = value
            # Older manifests may predate the world catalog. Advertised datasets
            # are validated and committed with the same snapshot as items/recipes.
            for name, (_, count_key) in world.WORLD_DATASETS.items():
                if count_key not in manifest.get("counts", {}):
                    continue
                value = await self._json(client, "GET", f"/data/{name}.json")
                try:
                    world.validate_world(name, value, manifest)
                except ValueError as exc:
                    raise ReferenceError(str(exc)) from exc
                datasets[name] = value
            if "npcs" in datasets:
                try:
                    bosses = [b for b in datasets["npcs"]["npcs"] if b.get("source") == "encounter"]
                    datasets["boss_loot"] = await loot.fetch_catalog(self, client, bosses)
                except ValueError as exc:
                    raise ReferenceError(str(exc)) from exc
            # Reject a rolling-site rebuild rather than mixing datasets across versions.
            final = await self._json(client, "GET", "/data/manifest.json")
            if not isinstance(final, dict) or (final.get("product"), final.get("build"), final.get("built_at"), final.get("counts")) != (manifest["product"], manifest["build"], manifest["built_at"], manifest.get("counts")):
                raise ReferenceError("网站资料在下载期间更新，请重新同步")
        counts = manifest.get("counts", {})
        if not isinstance(counts, dict):
            raise ReferenceError("版本资料的数量声明无效")
        for name in ("items", "recipes"):
            if name in counts and (type(counts[name]) is not int or counts[name] != len(datasets[name])):
                raise ReferenceError("资料数量与来源声明不符，保留已有缓存与插件资料")
        for key, item in datasets["items"].items():
            if not isinstance(item, dict) or type(item.get("id")) is not int or str(item["id"]) != key or not isinstance(item.get("name"), str):
                raise ReferenceError("物品记录校验失败，保留已有缓存")
        recipe_ids = set()
        for recipe in datasets["recipes"]:
            if not isinstance(recipe, dict) or type(recipe.get("id")) is not int or not isinstance(recipe.get("name"), str) or recipe["id"] in recipe_ids:
                raise ReferenceError("配方记录校验失败，保留已有缓存")
            recipe_ids.add(recipe["id"])
        self.db.cache_references(datasets, manifest["build"], manifest["built_at"])
        self._cache.clear()
        catalog = None
        if self.addon_catalog_path:
            from .catalog_export import export_catalog
            try:
                catalog = await asyncio.to_thread(export_catalog, self.db, self.addon_catalog_path)
            except (ValueError, OSError) as exc:
                raise ReferenceError("资料缓存已更新，但插件离线资料库导出失败；已有插件文件保留。") from exc
        return {"build": manifest["build"], "built_at": manifest["built_at"], "datasets": list(datasets), "addon_catalog": catalog,
                "items": len(datasets["items"]), "recipes": len(datasets["recipes"]),
                "world_counts": {kind: len(self._records(kind)) for kind in world.WORLD_KINDS},
                "loot": loot.report(datasets["boss_loot"]) if "boss_loot" in datasets else None,
                "source": BASE + "/about"}

    def dataset(self, name):
        # A single process owns the service; sync invalidates all local indexes.
        name = world.WORLD_KINDS.get(name, name)
        if name not in self._cache:
            self._cache[name] = self.db.reference(name)
        row = self._cache[name]
        if row and (name in world.WORLD_DATASETS or name == "boss_loot"):
            current = self.dataset("manifest")
            if current and (row["build"], row["built_at"]) != (current["build"], current["built_at"]):
                return None
        return row

    def source(self, dataset, snapshot: Snapshot | None, entity_id):
        dataset = world.WORLD_KINDS.get(dataset, dataset)
        row = self.dataset(dataset)
        if not row:
            raise ReferenceError("尚未同步无限图鉴资料")
        client = snapshot.client if snapshot else None
        expected_build = f"{client.version}.{client.build}" if client and client.version and client.build else None
        matches = expected_build == row["build"]
        # Extraction is traceable, but not a claim of local in-game UAT.
        return {"evidence_id": f"wuxian:{row['build']}:{dataset}:{entity_id}",
                "provenance": "verified" if matches and snapshot.data_mode == "live" else "assumption",
                "url": BASE + f"/data/{dataset}.json", "build": row["build"],
                "built_at": row["built_at"], "fetched_at": row["fetched_at"],
                "version_matches": matches, "origin": "第三方客户端资料提取；未在本机游戏内复测"}

    def search(self, query, kind="items", snapshot=None, limit=20):
        if not query.strip() or len(query) > 100:
            raise ReferenceError("请输入 1–100 字的名称或 ID")
        dataset = self.dataset(kind)
        if not dataset:
            raise ReferenceError("尚无资料缓存，请先点击同步无限图鉴")
        values = self._records(kind)
        query = query.casefold().strip()
        result = []
        for value in values:
            if not isinstance(value, dict):
                continue
            ident, name = value.get("id"), value.get("name")
            if type(ident) is not int or not isinstance(name, str):
                continue
            if query != str(ident) and query not in world.search_text(value, kind):
                continue
            # Do not promote explicit third-party/unknown supplementation to verified.
            hit = self._hit(value, kind, snapshot)
            result.append({"record": value, "source": hit["source"]})
            if len(result) >= limit:
                break
        return result

    def _records(self, kind):
        if kind not in world.KIND_LABELS:
            raise ReferenceError("不支持的资料类型")
        row = self.dataset(kind)
        data = row["payload"] if row else {}
        if kind in world.WORLD_KINDS:
            return world.records(kind, data)
        return [value for value in (data.values() if isinstance(data, dict) else data)
                if isinstance(value, dict) and type(value.get("id")) is int and isinstance(value.get("name"), str)]

    def _category(self, record, kind):
        if kind in world.WORLD_KINDS:
            return world.category(record, kind)
        key = record.get("cls" if kind == "items" else "skill")
        if kind == "items":
            name = ITEM_CLASSES.get(key, f"类别 {key}" if key is not None else "未分类")
        else:
            professions = self.dataset("professions")
            values = professions["payload"] if professions else []
            name = next((p["name"] for p in values if isinstance(p, dict) and p.get("id") == key
                         and isinstance(p.get("name"), str)), f"专业 {key}" if key is not None else "未分类")
        return str(key) if key is not None else "unknown", name

    def _hit(self, record, kind, snapshot=None):
        source = self.source(kind, snapshot, record["id"])
        if (any(record.get(k) for k in ("inferred", "prediction", "third_party", "unverified", "tp", "hidden"))
                or world.supplement(record, kind) or (kind == "quests" and not record.get("title"))):
            source["provenance"] = "assumption"
            source["origin"] += "；存在补充来源或可用性标记，需要核实"
        return {"record": record, "source": source, "kind": kind, "icon_id": record.get("icon"),
                "icon_url": icon_url(record), "url": f"/references/{kind}/{record['id']}",
                "category_label": self._category(record, kind)[1], "art_path": world.artwork(record, kind),
                "coverage": record.get("coverage"), "kind_label": world.KIND_LABELS[kind]}

    def browse(self, query="", kind="items", snapshot=None, category="", page=1, page_size=24):
        if not isinstance(query, str) or len(query) > 100:
            raise ReferenceError("搜索内容不能超过 100 字")
        if type(page) is not int or not 1 <= page <= 10000 or type(page_size) is not int or not 1 <= page_size <= 100:
            raise ReferenceError("页码或每页数量无效")
        records = self._records(kind)
        category = str(category or "")
        query = query.strip().casefold()
        categories = {}
        for record in records:
            key, name = self._category(record, kind)
            categories.setdefault(key, {"id": key, "name": name, "count": 0})["count"] += 1
        matching = [r for r in records if (not query or query == str(r["id"]) or query in world.search_text(r, kind))
                    and (not category or self._category(r, kind)[0] == category)]
        matching.sort(key=lambda r: r["id"])
        total = len(matching)
        pages = max(1, (total + page_size - 1) // page_size)
        # Clamp stale pagination after changing filters, retaining a usable browse view.
        page = min(page, pages)
        return {"kind": kind, "kind_label": world.KIND_LABELS[kind], "kinds": world.KIND_LABELS,
                "notice": world.MAP_GAP if kind in ("instances", "maps") else
                    "任务标题与正文以服务器记录为准；仅编号与第三方线索单独标注。" if kind == "quests" else "",
                "query": query, "category": category, "page": page, "page_size": page_size,
                "total": total, "pages": pages, "cached": self.dataset(kind) is not None,
                "categories": sorted(categories.values(), key=lambda row: (row["id"] == "unknown", row["name"])),
                "results": [self._hit(r, kind, snapshot) for r in matching[(page - 1) * page_size:page * page_size]]}

    def _related(self, record, kind, quantity=None):
        return {"id": record["id"], "name": record["name"], "kind": kind, "quantity": quantity,
                "icon_id": record.get("icon"), "icon_url": icon_url(record),
                "url": f"/references/{kind}/{record['id']}", "known": True}

    def detail(self, kind, entity_id, snapshot=None):
        if type(entity_id) is not int or entity_id <= 0:
            raise ReferenceError("资料 ID 无效")
        record = next((r for r in self._records(kind) if r["id"] == entity_id), None)
        if record is None:
            raise ReferenceError("缓存中没有这条资料，请同步后重试")
        result = self._hit(record, kind, snapshot)
        if kind in world.WORLD_KINDS:
            return world.detail(self, kind, record, result)
        fields = []
        for key, label in (("ilvl", "物品等级"), ("req", "需求等级"), ("slot", "装备位置"),
                           ("weapon_type", "武器类型"), ("armor", "护甲"), ("rank", "专业技能要求"),
                           ("spell", "法术 ID"), ("desc", "介绍"), ("effect", "效果")):
            value = record.get(key)
            if value is not None and value != "":
                fields.append({"label": label, "value": value})
        if type(record.get("q")) is int:
            fields.insert(0, {"label": "品质", "value": QUALITY_NAMES.get(record["q"], str(record["q"]))})
        stats = record.get("stats")
        pairs = stats.items() if isinstance(stats, dict) else stats if isinstance(stats, list) else []
        labels = self.dataset("stat_names")
        labels = labels["payload"] if labels else {}
        for pair in pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2 and type(pair[1]) in (int, float):
                fields.append({"label": labels.get(str(pair[0]), f"属性 {pair[0]}"), "value": pair[1]})
        result.update(fields=fields, materials=[], products=[], used_by=[], created_by=[],
                      dropped_by=loot.dropped_by(self, entity_id) if kind == "items" else [])
        if kind == "recipes":
            items = {item["id"]: item for item in self._records("items")}
            for key, target in (("reagents", "materials"), ("products", "products")):
                for pair in record.get(key) or []:
                    if not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int:
                        continue
                    item = items.get(pair[0])
                    relation = self._related(item, "items", pair[1]) if item else {
                        "id": pair[0], "name": f"未知物品 · {pair[0]}", "quantity": pair[1], "kind": "items",
                        "icon_id": None, "icon_url": None, "url": None, "known": False}
                    result[target].append(relation)
        else:
            for recipe in self._records("recipes"):
                for key, target in (("reagents", "used_by"), ("products", "created_by")):
                    if any(isinstance(p, list) and len(p) == 2 and p[0] == entity_id for p in recipe.get(key) or []):
                        result[target].append(self._related(recipe, "recipes"))
        return result

    def context_matches(self, question, snapshot, limit=6):
        """Match explicit names/IDs inside natural-language questions; no speculative recommendations."""
        ids = set(re.findall(r"(?<!\d)\d{2,10}(?!\d)", question))
        result = []
        for kind in world.KIND_LABELS:
            dataset = self.dataset(kind)
            if not dataset:
                continue
            for record in self._records(kind):
                if not isinstance(record, dict):
                    continue
                name, ident = record.get("name"), record.get("id")
                if isinstance(name, str) and type(ident) is int and (name in question or str(ident) in ids):
                    hit = next((h for h in self.search(str(ident), kind, snapshot) if h["record"]["id"] == ident), None)
                    if hit:
                        value = hit["record"]
                        if kind in world.WORLD_KINDS:
                            value = {k: value[k] for k in ("id", "name", "kind", "level", "min_level", "players",
                                     "zone", "bosses", "coverage", "cache_texts", "goals", "tmp") if k in value}
                            value["reference_kind"] = kind
                            value["limitations"] = world.MAP_GAP if kind in ("maps", "instances") else "第三方补充不代表实机或角色进度"
                            if kind == "bosses":
                                drop_view = loot.view(self, record)
                                value["temporary_drops"] = {"source": drop_view["source_label"], "note": drop_view["note"],
                                    "items": [{"id": i["id"], "name": i["name"]} for i in drop_view["items"]]}
                                hit["source"]["provenance"] = "assumption"
                        result.append({**hit["source"], "value": value})
                    if len(result) >= limit:
                        return result
        return result

    def get_item(self, item_id, snapshot=None):
        hits = self.search(str(item_id), "items", snapshot)
        hit = next((h for h in hits if h["record"]["id"] == item_id), None)
        if hit is None:
            raise ReferenceError("缓存中没有该物品；属性保持未知")
        raw = hit["record"]
        stats_raw = raw.get("stats")
        stats = None
        if isinstance(stats_raw, list) and all(isinstance(pair, list) and len(pair) == 2 for pair in stats_raw):
            stats_raw = {str(pair[0]): pair[1] for pair in stats_raw}
        if isinstance(stats_raw, dict):
            stats = {}
            labels_row = self.dataset("stat_names")
            labels = labels_row["payload"] if labels_row else {}
            inverse = {v: k for k, v in STAT_NAMES.items()}
            for key, value in stats_raw.items():
                label = labels.get(str(key), str(key))
                stat_key = inverse.get(label, "wuxian_stat_" + str(key))
                if type(value) in (int, float):
                    stats[stat_key] = value
            if type(raw.get("armor")) in (int, float):
                stats["RESISTANCE0_NAME"] = raw["armor"]
        item = Item(item_id=item_id, name=raw["name"], item_level=raw.get("ilvl"), quality=raw.get("q"), stats=stats)
        return item, hit["source"]

    def get_recipe(self, recipe_id, snapshot=None):
        hits = self.search(str(recipe_id), "recipes", snapshot)
        hit = next((h for h in hits if h["record"]["id"] == recipe_id), None)
        if hit is None:
            raise ReferenceError("缓存中没有该配方")
        raw = hit["record"]
        products = raw.get("products")
        product = products[0] if isinstance(products, list) and len(products) == 1 else None
        # A fixed scalar quantity is required. Ranges/chances remain unknown.
        valid = isinstance(product, list) and len(product) == 2 and type(product[0]) is int and type(product[1]) is int and product[1] > 0
        reagents = raw.get("reagents")
        normalized = None
        if isinstance(reagents, list) and all(isinstance(r, list) and len(r) == 2 and type(r[0]) is int and type(r[1]) is int and r[1] > 0 for r in reagents):
            normalized = [{"item_id": r[0], "quantity": r[1]} for r in reagents]
        recipe = Recipe(recipe_id=raw["id"], name=raw["name"], output_item_id=product[0] if valid else None,
                        output_quantity=product[1] if valid else None, reagents=normalized)
        return recipe, hit["source"]

    async def mcp(self, tool, arguments):
        if not self.enabled:
            raise ReferenceError("外部资料已关闭")
        if tool not in MCP_TOOLS:
            raise ReferenceError("该 MCP 工具不在只读资料白名单中")
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 2000:
            raise ReferenceError("MCP 参数过大或类型无效")
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, transport=self.transport,
                                     headers={"Accept": "application/json, text/event-stream"}) as client:
            result = await self._json(client, "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                              "params": {"name": tool, "arguments": arguments}})
        if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("result"), dict):
            raise ReferenceError("MCP 未返回可用资料；可继续使用 JSON 缓存")
        return {"tool": tool, "result": result["result"], "source": BASE + "/mcp", "fetched_at": int(time.time()),
                "provenance": "assumption", "note": "原始远端查询结果，尚未完成版本与字段核对"}
