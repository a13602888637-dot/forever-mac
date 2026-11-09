"""Versioned public auction observations; no purchases or in-game queries."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
import asyncio
import json
import re
import time

import httpx

from .references import BASE, ReferenceError

MARKET_PATH = "/mcp"
MARKET_URL = BASE + MARKET_PATH
QUOTE_MAX_AGE = 24 * 3600
HOUSE_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def normalize_faction(value):
    return {"联盟": "Alliance", "部落": "Horde", "Alliance": "Alliance", "Horde": "Horde"}.get(value, "unknown")


def game_scope(snapshot):
    return f"game:{snapshot.character.realm}:{normalize_faction(snapshot.character.faction)}"


def normalize_market(payload, now=None):
    """Read historical v7 observations without requesting the retired JSON endpoint."""
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


def mcp_payload(envelope):
    if not isinstance(envelope, dict) or envelope.get("error"):
        raise ReferenceError("拍卖接口未返回可用资料，保留已有记录")
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise ReferenceError("拍卖 MCP 返回格式无效")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for content in result.get("content", []):
        if isinstance(content, dict) and content.get("type") == "text":
            try:
                payload = json.loads(content.get("text", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
    raise ReferenceError("拍卖 MCP 缺少结构化资料")


def normalize_auction(payload, now=None):
    """Normalize the documented auction_house prices response (copper units)."""
    now = int(time.time()) if now is None else now
    if not isinstance(payload, dict) or payload.get("outcome") != "ok" or payload.get("view") != "prices":
        raise ReferenceError("拍卖行暂不可用，请重新选择市场或稍后重试")
    house, snapshot = payload.get("house"), payload.get("snapshot")
    if not isinstance(house, dict) or not isinstance(snapshot, dict):
        raise ReferenceError("拍卖资料缺少市场与采集时间")
    key, label = house.get("key"), house.get("label")
    if not isinstance(key, str) or not HOUSE_KEY.fullmatch(key) or not isinstance(label, str) or not 1 <= len(label) <= 100:
        raise ReferenceError("拍卖资料市场标识无效")
    collected = snapshot.get("collected_at")
    if not isinstance(collected, str) or not re.fullmatch(r"北京时间 \d{4}-\d{2}-\d{2} \d{2}:\d{2}", collected):
        raise ReferenceError("拍卖资料采集时间格式未知，保留已有记录")
    try:
        observed = int(datetime.strptime(collected, "北京时间 %Y-%m-%d %H:%M").replace(
            tzinfo=timezone(timedelta(hours=8))).timestamp())
    except ValueError:
        raise ReferenceError("拍卖资料采集时间无效") from None
    if not 1577836800 < observed <= now + 300 or house.get("day") != snapshot.get("day") or collected[5:15] != snapshot.get("day"):
        raise ReferenceError("拍卖资料采集时间或日期不一致")
    if type(payload.get("reliable")) is not bool:
        raise ReferenceError("拍卖资料缺少可靠性标记")
    records, total = payload.get("results"), payload.get("total")
    if not isinstance(records, list) or type(total) is not int or not 0 <= total <= 100000 or len(records) > total:
        raise ReferenceError("拍卖物品数量声明无效")
    prices, names = [], {}
    for record in records:
        if not isinstance(record, dict) or record.get("bonus") not in (None, ""):
            continue
        ident, amount = record.get("item_id"), record.get("guidance")
        if type(ident) is not int or ident <= 0 or type(amount) not in (int, float):
            continue
        amount = Decimal(str(amount))
        if not amount.is_finite() or not 0 <= amount <= 10**14:
            continue
        prices.append({"item_id": ident, "copper": int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                       "observed_at": observed})
        if isinstance(record.get("name"), str):
            names[str(ident)] = record["name"][:300]
    faction = "Horde" if key.endswith("-horde") else "Alliance" if key.endswith("-alliance") else "unknown"
    reliable = payload["reliable"] and not bool(house.get("stale"))
    return {"scope": f"wuxian:house:{key}", "house_key": key, "house_label": label,
            "realm": label, "faction": faction, "observed_at": observed, "source": MARKET_URL,
            "page_url": f"{BASE}/ah?h={key}", "count": len(prices), "total": total, "prices": prices,
            "names": names, "reliable": reliable, "stale": now - observed > QUOTE_MAX_AGE,
            "note": "无限图鉴的公开参考市场；按数量加权的挂单单价中位数，四舍五入至铜，不代表成交价。市场按规则集与阵营区分。"}


class Market:
    def __init__(self, service):
        self.service = service
        self._syncing = False

    def _client(self):
        return httpx.AsyncClient(timeout=30, follow_redirects=False, transport=self.service.refs.transport,
                                 headers={"User-Agent": "Forever/0.4 (read-only)",
                                          "Accept": "application/json, text/event-stream"})

    async def _request(self, arguments, client=None):
        refs = self.service.refs
        if not refs.enabled:
            raise ReferenceError("外部资料已关闭")
        if client is None:
            async with self._client() as opened:
                return await self._request(arguments, opened)
        for attempt in range(2):
            try:
                envelope = await refs._json(client, "POST", MARKET_PATH, {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "auction_house", "arguments": arguments}})
                return mcp_payload(envelope)
            except ReferenceError as exc:
                retryable = any(text in str(exc) for text in ("网络", "HTTP 429", "HTTP 502", "HTTP 503", "HTTP 504"))
                if attempt or not retryable:
                    raise
                await asyncio.sleep(0.4)

    def markets(self):
        try:
            values = json.loads(self.service.db.get("market:houses", "[]"))
        except (TypeError, json.JSONDecodeError):
            values = []
        selected = self.service.db.get("market:selected_house") or None
        return {"markets": values if isinstance(values, list) else [], "selected_house": selected,
                "needs_selection": selected is None, "source": MARKET_URL, "syncing": self._syncing}

    async def discover_markets(self):
        # The public contract returns its full market list for an unknown house.
        # This query deliberately requests only that catalog, never a guessed default market.
        payload = await self._request({"view": "prices", "house": "__forever_market_catalog__", "limit": 1})
        houses = payload.get("houses")
        if payload.get("outcome") != "not_found" or not isinstance(houses, list) or not 1 <= len(houses) <= 100:
            raise ReferenceError("公开市场列表暂不可用，保留已有选择")
        clean = []
        for house in houses:
            if not isinstance(house, dict) or not isinstance(house.get("key"), str) or not HOUSE_KEY.fullmatch(house["key"]) or not isinstance(house.get("label"), str):
                raise ReferenceError("公开市场标识无效，保留已有选择")
            clean.append({"key": house["key"], "label": house["label"][:100], "day": house.get("day")})
        self.service.db.set("market:houses", json.dumps(clean, ensure_ascii=False))
        return self.markets()

    def select(self, house):
        if house is not None and house != "" and not any(row["key"] == house for row in self.markets()["markets"]):
            raise ReferenceError("请从已发现的公开市场中选择")
        self.service.db.set("market:selected_house", house or "")
        self.service.db.set("market:last_sync", "0")
        return self.markets()

    async def sync(self):
        if not self.service.refs.enabled:
            raise ReferenceError("外部资料已关闭")
        if self._syncing:
            raise ReferenceError("公开市场正在同步，请稍候")
        self._syncing = True
        try:
            house = self.markets()["selected_house"]
            if not house:
                await self.discover_markets()
                self.service.db.set("market:last_sync", str(int(time.time())))
                return {"status": "selection_required", "count": 0, **self.markets(),
                        "syncing": False,
                        "note": "请选择公开参考市场；未选择前不下载或使用公开报价。"}
            async with self._client() as client:
                return await self._collect(house, client)
        finally:
            self._syncing = False

    async def _collect(self, house, client):
        first = await self._request({"view": "prices", "house": house, "limit": 100, "offset": 0}, client)
        normalized = normalize_auction(first)
        if normalized["house_key"] != house:
            raise ReferenceError("接口返回了其他市场，保留已有记录")
        total = normalized["total"]
        if len(first["results"]) != min(total, 100):
            raise ReferenceError("拍卖分页数量不一致，未替换缓存")
        prices = {p["item_id"]: p for p in normalized["prices"]}
        names = dict(normalized["names"])
        # Limited concurrency shortens a full-market sync while preserving source consistency.
        offsets = list(range(100, total, 100))
        for start in range(0, len(offsets), 4):
            batch = offsets[start:start + 4]
            responses = await asyncio.gather(*(self._request({"view": "prices", "house": house,
                "limit": 100, "offset": offset}, client) for offset in batch), return_exceptions=True)
            for response in responses:
                if isinstance(response, BaseException):
                    raise response
            for offset, payload in zip(batch, responses):
                page = normalize_auction(payload)
                if any(page[k] != normalized[k] for k in ("house_key", "observed_at", "total", "reliable")):
                    raise ReferenceError("市场资料在下载期间更新，请重新同步；已有记录保留")
                if len(payload["results"]) != min(100, total - offset) or payload.get("offset") != offset:
                    raise ReferenceError("拍卖分页不完整，未替换缓存")
                for quote in page["prices"]:
                    previous = prices.get(quote["item_id"])
                    if previous is not None and previous != quote:
                        raise ReferenceError("同一普通物品出现冲突报价，未替换缓存")
                    prices[quote["item_id"]] = quote
                names.update(page["names"])
        metadata = {k: v for k, v in normalized.items() if k != "prices"}
        metadata.update(count=len(prices), names=names, fetched_at=int(time.time()))
        # Selection may change while pages are downloading. Archive the requested market;
        # metadata()/available() always use the currently selected market.
        self.service.db.save_market_snapshot("live", metadata, list(prices.values()))
        if self.markets()["selected_house"] == house:
            self.service.db.set("market:last_sync", str(int(time.time())))
        return metadata

    def ingest_snapshot(self, snapshot):
        if snapshot.data_mode != "live":
            return
        for quote in snapshot.auction_quotes or []:
            provenance = "verified" if quote.basis == "unit_price" else "calculated"
            self.service.db.save_market_prices("live", game_scope(snapshot), [quote.model_dump()], quote.source, provenance)

    def metadata(self):
        house = self.markets()["selected_house"]
        if house:
            return self.service.db.market_snapshot("live", f"wuxian:house:{house}")
        return None

    def legacy_metadata(self):
        """Keep old cached scope/time visible as history without silently choosing it."""
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
                  "note": "尚无报价。可选择公开参考市场，或读取角色正常浏览拍卖行时的被动观察。", "errors": {},
                  "selected_house": self.markets()["selected_house"], "needs_selection": self.markets()["needs_selection"]}
        if metadata:
            scopes.append(metadata["scope"])
            # A public ruleset/faction key does not prove the character's market identity.
            exact_market = False
            public_rows = self.service.db.market_prices("live", [metadata["scope"]])
            for row in public_rows:
                if not metadata.get("reliable", False) or row["observed_at"] != metadata["observed_at"] or now - row["observed_at"] > QUOTE_MAX_AGE or row["observed_at"] > now + 300:
                    continue
                rows[row["item_id"]] = {**row, "recorded_at": row["observed_at"], "scope_matches": exact_market}
            status = {"status": "reference" if rows else "unreliable" if not metadata.get("reliable", False) else "stale",
                      "source": metadata["page_url"], "selected_house": self.markets()["selected_house"], "needs_selection": False,
                      "observed_at": metadata["observed_at"], "realm": metadata["realm"],
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
