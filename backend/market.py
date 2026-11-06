"""Versioned public auction observations; no purchases or in-game queries."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json
import time

import httpx

from .references import BASE, ReferenceError

MARKET_PATH = "/ah/data/index.json"
MARKET_URL = BASE + MARKET_PATH
QUOTE_MAX_AGE = 24 * 3600


def normalize_faction(value):
    return {"联盟": "Alliance", "部落": "Horde", "Alliance": "Alliance", "Horde": "Horde"}.get(value, "unknown")


def game_scope(snapshot):
    return f"game:{snapshot.character.realm}:{normalize_faction(snapshot.character.faction)}"


def normalize_market(payload, now=None):
    now = int(time.time()) if now is None else now
    if not isinstance(payload, dict) or payload.get("v") != 7:
        raise ReferenceError("拍卖资料版本尚不支持，保留已有记录")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ReferenceError("拍卖资料缺少市场与采集时间")
    observed, realm, side = snapshot.get("time"), snapshot.get("realm"), snapshot.get("side")
    if type(observed) is not int or not 1577836800 < observed <= now + 300:
        raise ReferenceError("拍卖资料时间无效")
    if not isinstance(realm, str) or not realm or len(realm) > 100 or normalize_faction(side) == "unknown":
        raise ReferenceError("拍卖资料市场范围无效")
    records = payload.get("items")
    if not isinstance(records, list) or len(records) > 100000:
        raise ReferenceError("拍卖物品列表无效")
    prices, names = [], {}
    for record in records:
        if not isinstance(record, dict) or record.get("b") not in ("", None):
            continue  # Random-enchantment variants cannot be collapsed into the base item.
        ident, median = record.get("id"), record.get("med")
        if type(ident) is not int or ident <= 0 or type(median) not in (int, float):
            continue
        amount = Decimal(str(median))
        if not amount.is_finite() or not 0 <= amount <= 10**14:
            continue
        copper = int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        prices.append({"item_id": ident, "copper": copper, "observed_at": observed})
        if isinstance(record.get("n"), str):
            names[str(ident)] = record["n"][:300]
    if records and not prices:
        raise ReferenceError("拍卖资料没有可识别的报价")
    return {
        "scope": f"wuxian:{realm}:{normalize_faction(side)}", "realm": realm, "faction": normalize_faction(side),
        "observed_at": observed, "source": MARKET_URL, "page_url": BASE + "/ah", "count": len(prices),
        "prices": prices, "names": names,
        "note": "定时采集的挂单单价中位数，四舍五入至铜；不代表成交价。仅覆盖来源标明的服务器与阵营。",
    }


class Market:
    def __init__(self, service):
        self.service = service

    async def sync(self):
        refs = self.service.refs
        if not refs.enabled:
            raise ReferenceError("外部资料已关闭")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, transport=refs.transport,
                                     headers={"User-Agent": "ForeverAI-Companion/0.1 (read-only)", "Accept": "application/json"}) as client:
            payload = await refs._json(client, "GET", MARKET_PATH)
        normalized = normalize_market(payload)
        self.service.db.save_market_prices("live", normalized["scope"], normalized["prices"], MARKET_URL, "assumption")
        metadata = {k: v for k, v in normalized.items() if k != "prices"}
        self.service.db.set("market:public", json.dumps(metadata, ensure_ascii=False))
        self.service.db.set("market:last_sync", str(int(time.time())))
        return metadata

    def ingest_snapshot(self, snapshot):
        if snapshot.data_mode != "live":
            return
        for quote in snapshot.auction_quotes or []:
            provenance = "verified" if quote.basis == "unit_price" else "calculated"
            self.service.db.save_market_prices("live", game_scope(snapshot), [quote.model_dump()], quote.source, provenance)

    def metadata(self):
        raw = self.service.db.get("market:public")
        try:
            return json.loads(raw) if raw else None
        except (TypeError, json.JSONDecodeError):
            return None

    def available(self, snapshot):
        now = int(time.time())
        if snapshot.data_mode == "mock":
            rows = [{**p, "observed_at": p["recorded_at"], "source": "mock-fixture", "scope": "mock",
                     "provenance": "assumption", "scope_matches": False}
                    for p in self.service.db.prices("mock", snapshot.character.realm)]
            status = {"status": "mock", "source": "合成演示报价", "observed_at": snapshot.captured_at,
                      "realm": snapshot.character.realm, "scope_matches": False,
                      "note": "自动生成的演示报价与 5% 费率情景，不是真实市场。", "errors": {}}
            return {row["item_id"]: row for row in rows}, status, ["mock"]
        local_scope = game_scope(snapshot)
        metadata = self.metadata()
        rows, scopes = {}, [local_scope]
        status = {"status": "unknown", "source": "等待自动采集", "observed_at": None,
                  "realm": snapshot.character.realm, "scope_matches": False,
                  "note": "尚无报价。系统将自动重试公开资料，并读取玩家正常浏览拍卖行时的被动观察。", "errors": {}}
        if metadata:
            scopes.append(metadata["scope"])
            exact_market = metadata["realm"].casefold() == snapshot.character.realm.casefold() and metadata["faction"] == normalize_faction(snapshot.character.faction)
            public_rows = self.service.db.market_prices("live", [metadata["scope"]])
            for row in public_rows:
                if row["observed_at"] != metadata["observed_at"] or now - row["observed_at"] > QUOTE_MAX_AGE:
                    continue
                rows[row["item_id"]] = {**row, "recorded_at": row["observed_at"], "scope_matches": exact_market}
            status = {"status": "reference" if rows else "stale", "source": metadata["page_url"],
                      "observed_at": metadata["observed_at"], "realm": f"{metadata['realm']} · {metadata['faction']}",
                      "scope_matches": exact_market,
                      "note": metadata["note"] + (" 这是其他市场的参考报价，与当前角色市场不一致或未能确认。" if not exact_market else " 市场标识匹配，仍需注意采集时间。"), "errors": {}}
        local_rows = self.service.db.market_prices("live", [local_scope])
        fresh_local = [row for row in local_rows if now - row["observed_at"] <= QUOTE_MAX_AGE]
        for row in fresh_local:
            rows[row["item_id"]] = {**row, "recorded_at": row["observed_at"], "scope_matches": True}
        if fresh_local:
            status["status"] = "observed" if all(row["scope"] == local_scope for row in rows.values()) else "mixed"
            status["note"] = "优先使用本角色被动观察的本服报价；缺项可用公开市场参考。每项保留来源与采集时间，超过 24 小时不参与计算。"
            status["scope_matches"] = status["status"] == "observed"
        return rows, status, scopes
