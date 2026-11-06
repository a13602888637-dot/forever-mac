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

BASE = "https://wuxianwow.com"
DATASETS = ("manifest", "items", "recipes", "professions", "stat_names")
MAX_BYTES = 8 * 1024 * 1024
MCP_TOOLS = {"search", "fetch", "recipes", "gear_items", "item_usage"}


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
                                     headers={"User-Agent": "ForeverAI-Companion/0.1 (read-only)", "Accept": "application/json"}) as client:
            manifest = await self._json(client, "GET", "/data/manifest.json")
            if not isinstance(manifest, dict) or not isinstance(manifest.get("build"), str) or manifest.get("product") != "wow_cn_beta" or not isinstance(manifest.get("built_at"), str):
                raise ReferenceError("远端 manifest 缺少国服无限版本信息")
            datasets = {"manifest": manifest}
            for name in DATASETS[1:]:
                value = await self._json(client, "GET", f"/data/{name}.json")
                expected = list if name in ("recipes", "professions") else dict
                if not isinstance(value, expected) or not value:
                    raise ReferenceError(f"{name} 数据结构异常，未替换缓存")
                datasets[name] = value
            # Reject a rolling-site rebuild rather than mixing datasets across versions.
            final = await self._json(client, "GET", "/data/manifest.json")
            if not isinstance(final, dict) or (final.get("build"), final.get("built_at")) != (manifest["build"], manifest["built_at"]):
                raise ReferenceError("网站资料在下载期间更新，请重新同步")
        counts = manifest.get("counts", {})
        if not isinstance(counts, dict):
            raise ReferenceError("版本资料的数量声明无效")
        for name in ("items", "recipes"):
            if name in counts and (type(counts[name]) is not int or counts[name] != len(datasets[name])):
                raise ReferenceError("资料数量与来源声明不符，保留已有缓存与插件资料")
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
                "items": len(datasets["items"]), "recipes": len(datasets["recipes"]), "source": BASE + "/about"}

    def dataset(self, name):
        # A single process owns the service; sync invalidates all local indexes.
        if name not in self._cache:
            self._cache[name] = self.db.reference(name)
        return self._cache[name]

    def source(self, dataset, snapshot: Snapshot | None, entity_id):
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
        if kind not in ("items", "recipes"):
            raise ReferenceError("仅支持物品和配方检索")
        if not query.strip() or len(query) > 100:
            raise ReferenceError("请输入 1–100 字的名称或 ID")
        dataset = self.dataset(kind)
        if not dataset:
            raise ReferenceError("尚无资料缓存，请先点击同步无限图鉴")
        data = dataset["payload"]
        values = data.values() if isinstance(data, dict) else data
        query = query.casefold().strip()
        result = []
        for value in values:
            if not isinstance(value, dict):
                continue
            ident, name = value.get("id"), value.get("name")
            if type(ident) is not int or not isinstance(name, str):
                continue
            if query != str(ident) and query not in name.casefold():
                continue
            # Do not promote explicit third-party/unknown supplementation to verified.
            source = self.source(kind, snapshot, ident)
            if any(value.get(k) for k in ("inferred", "prediction", "third_party", "unverified", "tp", "hidden")):
                source["provenance"] = "assumption"
                source["origin"] += "；存在补充来源或可用性标记，需要核实"
            result.append({"record": value, "source": source})
            if len(result) >= limit:
                break
        return result

    def context_matches(self, question, snapshot, limit=6):
        """Match explicit names/IDs inside natural-language questions; no speculative recommendations."""
        ids = set(re.findall(r"(?<!\d)\d{2,10}(?!\d)", question))
        result = []
        for kind in ("items", "recipes"):
            dataset = self.dataset(kind)
            if not dataset:
                continue
            data = dataset["payload"]
            for record in data.values() if isinstance(data, dict) else data:
                if not isinstance(record, dict):
                    continue
                name, ident = record.get("name"), record.get("id")
                if isinstance(name, str) and type(ident) is int and (name in question or str(ident) in ids):
                    hit = next((h for h in self.search(str(ident), kind, snapshot) if h["record"]["id"] == ident), None)
                    if hit:
                        result.append({**hit["source"], "value": hit["record"]})
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
