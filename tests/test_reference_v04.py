import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from backend.catalog_export import export_catalog
from backend.db import Database
from backend.market import Market, normalize_auction
from backend.models import Snapshot
from backend.reference_routes import router
from backend.references import References, ReferenceError


def reference_data(product="wowf"):
    return {
        "manifest": {"build": "1.60.1.70790", "built_at": "2026-11-06T12:00:00+08:00", "product": product,
                     "counts": {"items": 3, "recipes": 2}},
        "items": {"10": {"id": 10, "name": "材料甲", "cls": 7, "icon": 134414},
                  "20": {"id": 20, "name": "护甲乙", "cls": 4, "icon": 132538, "q": 2, "stats": [[5, 8]]},
                  "30": {"id": 30, "name": "材料丙", "cls": 7}},
        "recipes": [{"id": 100, "name": "配方乙", "skill": 197, "icon": 132538,
                     "products": [[20, 1]], "reagents": [[10, 2], [999, 1]]},
                    {"id": 200, "name": "配方丙", "skill": 165, "products": [[30, 1]], "reagents": [[20, 2]]}],
        "professions": [{"id": 197, "name": "裁缝"}, {"id": 165, "name": "制皮"}],
        "stat_names": {"5": "智力"},
    }


def refs_fixture(tmp_path, data=None):
    data = data or reference_data()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=data[request.url.path.split("/")[-1][:-5]]))
    refs = References(Database(tmp_path / "refs.sqlite3"), transport=transport)
    asyncio.run(refs.sync())
    return refs


def auction_payload(observed=None, rows=None, house="normal-alliance", reliable=True):
    observed = int(time.time()) - 60 if observed is None else observed
    dt = datetime.fromtimestamp(observed, timezone(timedelta(hours=8)))
    day = dt.strftime("%Y-%m-%d")
    rows = rows if rows is not None else [{"item_id": 10, "name": "材料甲", "guidance": 100.5},
                                         {"item_id": 20, "name": "护甲乙", "guidance": 400}]
    return {"outcome": "ok", "view": "prices", "reliable": reliable,
            "house": {"key": house, "label": "普通 · 联盟" if house == "normal-alliance" else "普通 · 部落", "day": day},
            "snapshot": {"day": day, "collected_at": dt.strftime("北京时间 %Y-%m-%d %H:%M")},
            "total": len(rows), "results": rows, "offset": 0}


def envelope(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def auction_transport(payload, requests=None):
    def respond(request):
        body = json.loads(request.content)
        assert request.method == "POST" and request.url.path == "/mcp"
        assert body["method"] == "tools/call" and body["params"]["name"] == "auction_house"
        arguments = body["params"]["arguments"]
        if requests is not None:
            requests.append(arguments)
        if arguments["house"] == "__forever_market_catalog__":
            value = {"outcome": "not_found", "houses": [{"key": "normal-alliance", "label": "普通 · 联盟", "day": "2026-11-06"},
                                                        {"key": "normal-horde", "label": "普通 · 部落", "day": "2026-11-06"}]}
        else:
            value = deepcopy(payload)
            offset = arguments.get("offset", 0)
            value["results"] = payload["results"][offset:offset + arguments.get("limit", 100)]
            value["offset"] = offset
        return httpx.Response(200, json=envelope(value))
    return httpx.MockTransport(respond)


def market_fixture(tmp_path, payload=None):
    db = Database(tmp_path / "market.sqlite3")
    refs = References(db, transport=auction_transport(payload or auction_payload()))
    service = SimpleNamespace(db=db, refs=refs)
    market = Market(service)
    service.market = market
    asyncio.run(market.discover_markets())
    return market


@pytest.mark.parametrize("product", ["wowf", "wow_cn_beta"])
def test_new_and_legacy_product_sync_and_lua_export(tmp_path, product):
    refs = refs_fixture(tmp_path, reference_data(product))
    assert refs.dataset("manifest")["payload"]["product"] == product
    report = export_catalog(refs.db, tmp_path / "CatalogData.lua")
    assert report["item_count"] == 3
    assert "134414" in (tmp_path / "CatalogData.lua").read_text()


def test_sync_rejects_rolling_source_or_bad_count_without_replacing_cache(tmp_path):
    refs = refs_fixture(tmp_path)
    old = refs.db.reference("items")["sha256"]
    data = reference_data()
    data["manifest"]["counts"]["items"] = 4
    refs.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=data[r.url.path.split("/")[-1][:-5]]))
    with pytest.raises(ReferenceError, match="数量"):
        asyncio.run(refs.sync())
    assert refs.db.reference("items")["sha256"] == old
    data = reference_data()
    calls = 0
    def rolling(request):
        nonlocal calls
        name = request.url.path.split("/")[-1][:-5]
        value = deepcopy(data[name])
        if name == "manifest":
            calls += 1
            if calls == 2:
                value["product"] = "other_product"
        return httpx.Response(200, json=value)
    refs.transport = httpx.MockTransport(rolling)
    with pytest.raises(ReferenceError, match="下载期间"):
        asyncio.run(refs.sync())
    assert refs.db.reference("items")["sha256"] == old
    refs.transport = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(ReferenceError, match="503"):
        asyncio.run(refs.sync())
    assert refs.browse()["total"] == 3


def test_catalog_browse_pagination_filters_and_bidirectional_details(tmp_path):
    refs = refs_fixture(tmp_path)
    first = refs.browse(page_size=2)
    assert first["total"] == 3 and first["pages"] == 2
    assert [r["record"]["id"] for r in first["results"]] == [10, 20]
    assert refs.browse(page=2, page_size=2)["results"][0]["record"]["id"] == 30
    assert refs.browse(category="4", page=99)["page"] == 1
    assert refs.browse(category="4")["total"] == 1
    assert refs.browse(kind="recipes", category="197")["results"][0]["record"]["id"] == 100
    assert refs.browse("材料")["total"] == 2
    recipe = refs.detail("recipes", 100)
    assert recipe["materials"][0]["url"] == "/references/items/10"
    assert recipe["materials"][1]["known"] is False and recipe["materials"][1]["url"] is None
    assert recipe["products"][0]["id"] == 20
    item = refs.detail("items", 20)
    assert item["created_by"][0]["id"] == 100 and item["used_by"][0]["id"] == 200
    assert {"label": "智力", "value": 8} in item["fields"]
    assert item["icon_url"] == "https://wuxianwow.com/share/132538.jpg"
    with pytest.raises(ReferenceError):
        refs.detail("items", 999)


def test_empty_and_old_cache_browsing_keeps_unknowns_explicit(tmp_path):
    refs = References(Database(tmp_path / "empty.sqlite3"))
    assert refs.browse()["cached"] is False and refs.browse()["results"] == []
    refs.db.cache_references({"items": {"2": {"id": 2, "name": "旧物品", "image": "http://localhost/private"}}}, "1.60.1.70450", "old")
    refs._cache.clear()
    row = refs.browse()["results"][0]
    assert row["icon_url"] is None and row["category_label"] == "未分类"
    assert refs.detail("items", 2)["fields"] == []


def test_market_requires_explicit_selection_and_preserves_legacy_history(tmp_path, live_raw):
    calls = []
    market = market_fixture(tmp_path)
    market.service.refs.transport = auction_transport(auction_payload(), calls)
    market.service.db.set("market:public", json.dumps({"scope": "wuxian:old:Alliance", "observed_at": int(time.time())}))
    report = asyncio.run(market.sync())
    assert report["status"] == "selection_required"
    assert all(c["house"] == "__forever_market_catalog__" for c in calls)
    assert market.metadata() is None and market.legacy_metadata()["scope"] == "wuxian:old:Alliance"
    rows, status, _ = market.available(Snapshot.model_validate(live_raw))
    assert rows == {} and status["needs_selection"] is True
    with pytest.raises(ReferenceError, match="已发现"):
        market.select("unknown")
    market.select("normal-alliance")
    report = asyncio.run(market.sync())
    assert report["count"] == 2 and report["house_key"] == "normal-alliance"
    rows, status, _ = market.available(Snapshot.model_validate(live_raw))
    assert rows[10]["copper"] == 101 and status["scope_matches"] is False
    market.select(None)
    assert market.available(Snapshot.model_validate(live_raw))[0] == {}


def test_market_pagination_variants_and_market_history_are_isolated(tmp_path):
    payload = auction_payload(rows=[{"item_id": i, "guidance": i + .5} for i in range(1, 207)] +
                             [{"item_id": 999, "guidance": 1, "bonus": "random-enchant"}])
    market = market_fixture(tmp_path, payload)
    market.select("normal-alliance")
    report = asyncio.run(market.sync())
    assert report["count"] == 206 and report["total"] == 207
    asyncio.run(market.sync())
    with market.service.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM market_prices").fetchone()[0] == 206
        assert conn.execute("SELECT count(*) FROM market_snapshots").fetchone()[0] == 1
    market.select("normal-horde")
    market.service.refs.transport = auction_transport(auction_payload(house="normal-horde"))
    asyncio.run(market.sync())
    assert market.metadata()["count"] == 2
    market.select("normal-alliance")
    assert market.metadata()["count"] == 206


@pytest.mark.parametrize("stale,reliable", [(True, True), (False, False)])
def test_stale_or_unreliable_public_observations_never_enter_current_quote(tmp_path, live_raw, stale, reliable):
    payload = auction_payload(observed=int(time.time()) - (90000 if stale else 60), reliable=reliable)
    market = market_fixture(tmp_path, payload)
    market.select("normal-alliance")
    asyncio.run(market.sync())
    rows, status, scopes = market.available(Snapshot.model_validate(live_raw))
    assert rows == {} and status["status"] == ("stale" if stale else "unreliable")
    assert len(market.service.db.market_history("live", scopes)) == 2


def test_partial_or_changing_market_keeps_previous_snapshot(tmp_path):
    market = market_fixture(tmp_path)
    market.select("normal-alliance")
    before = asyncio.run(market.sync())
    payload = auction_payload(rows=[{"item_id": i, "guidance": 100} for i in range(1, 102)])
    base = auction_transport(payload)
    def fail_second(request):
        if json.loads(request.content)["params"]["arguments"].get("offset") == 100:
            return httpx.Response(503)
        return base.handle_request(request)
    market.service.refs.transport = httpx.MockTransport(fail_second)
    with pytest.raises(ReferenceError):
        asyncio.run(market.sync())
    assert market.metadata() == before
    def changed_second(request):
        response = base.handle_request(request)
        if json.loads(request.content)["params"]["arguments"].get("offset") == 100:
            value = deepcopy(payload)
            value.update(results=payload["results"][100:], offset=100)
            value["house"]["key"] = "normal-horde"
            return httpx.Response(200, json=envelope(value))
        return response
    market.service.refs.transport = httpx.MockTransport(changed_second)
    with pytest.raises(ReferenceError, match="下载期间"):
        asyncio.run(market.sync())
    assert market.metadata() == before


def test_market_invalid_time_and_repeat_sync_rejected(tmp_path):
    payload = auction_payload(observed=int(time.time()) + 1000)
    with pytest.raises(ReferenceError, match="采集时间"):
        normalize_auction(payload)
    market = market_fixture(tmp_path)
    market._syncing = True
    with pytest.raises(ReferenceError, match="正在同步"):
        asyncio.run(market.sync())


def test_catalog_api_maps_trusted_icons_to_same_origin(tmp_path):
    refs = refs_fixture(tmp_path)
    media = SimpleNamespace(item_icon=lambda record: f"/api/media/icon-{record.get('icon', record.get('icon_id'))}" if record.get("icon", record.get("icon_id")) else None)
    service = SimpleNamespace(refs=refs, latest=lambda: None)
    app = FastAPI()
    app.include_router(router(service, media))
    with TestClient(app) as client:
        listing = client.get("/api/references/browse").json()
        assert listing["results"][0]["icon_url"] == "/api/media/icon-134414"
        detail = client.get("/api/references/details/recipes/100").json()
        assert detail["materials"][0]["icon_url"] == "/api/media/icon-134414"
        assert client.get("/api/references/browse?page=0").status_code == 422
