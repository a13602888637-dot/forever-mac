import asyncio
from html.parser import HTMLParser
import time

from fastapi.testclient import TestClient
import pytest

from backend.automation import Automation
from backend.config import Settings
from backend.market import normalize_market
from backend.models import Snapshot
from backend.references import ReferenceError
from backend.service import Companion
from backend.web import create_app
from conftest import savedvariables


def test_zero_entry_mock_pages_and_calculations(tmp_path):
    app = create_app(Settings(mode="mock", data_dir=tmp_path, auto_sync=False))
    with TestClient(app, base_url="http://127.0.0.1:18761") as client:
        equipment = client.get("/api/equipment/automatic").json()["comparisons"]
        assert len(equipment) == 1
        economy = client.get("/api/economy/automatic").json()
        assert economy["auto_quotes"][0]["result"]["profit_copper"] == 600
        assert economy["auto_quotes"][0]["learning_status"] == "mock"
        tasks = client.get("/api/tasks").json()["tasks"]
        assert len(tasks) >= 3
        assert any(t["auto_key"].startswith("quest:") for t in tasks)
        for page in ("/", "/equipment", "/economy", "/growth", "/tasks", "/ask", "/settings", "/references"):
            response = client.get(page)
            assert response.status_code == 200, page
            assert 'name="price_gold"' not in response.text
            assert 'name="manual_stats"' not in response.text
            assert 'name="manual_recipe"' not in response.text
            assert ('name="game_path"' in response.text) == (page == "/settings")


def test_automatic_import_history_and_recovery(tmp_path, live_raw):
    character = live_raw["character"]
    flavor = tmp_path / "game/_cn_beta_"
    path = flavor / "WTF/Account/private" / character["realm"] / character["name"] / "SavedVariables/ForeverAI.lua"
    path.parent.mkdir(parents=True)
    (flavor / "Interface").mkdir()
    path.write_text(savedvariables(live_raw))
    service = Companion(Settings(mode="live", data_dir=tmp_path / "data", game_path=str(flavor), references_enabled=False))
    auto = Automation(service)
    asyncio.run(auto.run_once())
    first_id = service.latest()[0]
    assert auto.status()["last_import"]
    assert service.db.last_advice(first_id)
    initial_tasks = service.task_context()["tasks"]
    assert len(initial_tasks) >= 3
    assert all(t["provenance"] in ("verified", "calculated", "assumption") for t in initial_tasks)
    asyncio.run(auto.run_once())
    assert service.latest()[0] == first_id
    assert len(service.task_context()["tasks"]) == len(initial_tasks)
    path.write_text("ForeverAICharDB = {broken(")
    asyncio.run(auto.run_once())
    assert service.latest()[0] == first_id
    assert auto.status()["errors"]
    live_raw["captured_at"] += 1
    live_raw["quests"][0]["is_complete"] = True
    path.write_text(savedvariables(live_raw))
    asyncio.run(auto.run_once())
    assert service.latest()[0] != first_id
    assert not auto.status()["errors"]
    quest = next(t for t in service.task_context()["tasks"] if t["auto_key"].startswith("quest:"))
    assert quest["done"] == 1
    assert quest["provenance"] == "verified" and quest["evidence_ids"]
    assert not service.db.update_task(quest["id"], "live", character["realm"] + ":" + character["name"], False)
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM snapshots WHERE mode='live'").fetchone()[0] == 2


def test_forever_connection_survives_polling_reimport_and_ambiguous_save(tmp_path, live_raw):
    live_raw["character"].update(name="测试名", realm="CN Test Realm PvE")
    live_raw["client"].update(version="1.60.1", interface=16001)
    game = tmp_path / "game/_forever_"
    path = game / "WTF/Account/local-account/97/测试名-甲/SavedVariables/ForeverAI.lua"
    path.parent.mkdir(parents=True)
    (game / "Interface").mkdir()
    path.write_text(savedvariables(live_raw))
    settings = Settings(mode="live", data_dir=tmp_path / "data", game_path=str(game),
                        references_enabled=False, auto_sync=False, ai_provider="rules")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:18761") as client:
        assert client.get("/api/snapshots/latest").status_code == 400
        status = client.post("/api/automation/run").json()
        assert status["sources_count"] == 1 and status["last_import"]
        assert status["errors"] == {}
        latest = client.get("/api/snapshots/latest").json()
        assert latest["snapshot"]["character"]["storage_name"] == "测试名-甲"
        assert client.get("/api/characters").json()[0]["character_id"] == "97:测试名-甲"
        tasks = client.get("/api/tasks").json()["tasks"]
        assert tasks
        source_id = client.get("/api/sources").json()["sources"][0]["id"]
        assert client.post("/api/snapshots/import", json={"source_id": source_id}).json()["id"] == latest["id"]
        assert client.get("/api/tasks").json()["tasks"] == tasks

        class PollTarget(HTMLParser):
            url = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if attrs.get("id") == "overview-auto":
                    self.url = attrs.get("hx-get")

        overview = client.get("/overview")
        assert "测试名 甲" in overview.text
        assert "测试名 甲" in client.get("/ask").text
        poll = PollTarget()
        poll.feed(overview.text)
        refreshed = client.get(poll.url, headers={"HX-Request": "true"})
        assert 'id="overview-auto"' in refreshed.text
        assert "测试名 甲" in refreshed.text

        # A new sibling makes a later first-name-only save ambiguous. Retain
        # the accepted snapshot and tasks instead of merging another character.
        (path.parents[2] / "测试名-乙/SavedVariables").mkdir(parents=True)
        live_raw["captured_at"] += 1
        path.write_text(savedvariables(live_raw))
        assert client.post("/api/automation/run").json()["errors"]
        assert client.get("/api/snapshots/latest").json()["id"] == latest["id"]
        live_raw["character"]["name"] = "测试名 甲"
        path.write_text(savedvariables(live_raw))
        assert client.post("/api/automation/run").json()["errors"] == {}
        assert client.get("/api/snapshots/latest").json()["id"] != latest["id"]
        assert len(client.get("/api/characters").json()) == 1
        assert {t["id"] for t in client.get("/api/tasks").json()["tasks"]} == {t["id"] for t in tasks}


def market_fixture():
    return {"v": 7, "snapshot": {"time": int(time.time()), "day": "2026-10-26", "realm": "其他服务器", "side": "联盟"},
            "items": [{"id": item_id, "b": "", "n": "测试物品", "med": price}
                      for item_id, price in ((1900000101, 100.5), (1900000102, 50), (1900000202, 1000))]}


def test_public_price_scope_fee_unknown_and_history(tmp_path, live_raw):
    from test_reference_v04 import auction_payload, auction_transport

    service = Companion(Settings(mode="live", data_dir=tmp_path))
    snapshot = Snapshot.model_validate(live_raw)
    service.db.save_snapshot(snapshot)
    payload = market_fixture()
    public = auction_payload(observed=payload["snapshot"]["time"], rows=[
        {"item_id": r["id"], "name": r["n"], "guidance": r["med"]} for r in payload["items"]])
    service.refs.transport = auction_transport(public)
    asyncio.run(service.market.discover_markets())
    service.market.select("normal-alliance")
    report = asyncio.run(service.market.sync())
    assert report["count"] == 3
    asyncio.run(service.market.sync())
    with service.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM market_prices").fetchone()[0] == 3
    result = service.auto_economy()
    quote = result["auto_quotes"][0]["result"]
    assert quote["material_cost_copper"] == 353
    assert quote["gross_margin_copper"] == 647
    assert quote["profit_copper"] is None
    assert result["market_status"]["scope_matches"] is False
    assert all(p["provenance"] == "assumption" for p in quote["price_sources"])
    assert any("其他服务器或阵营" in text for text in quote["assumptions"])


def test_stale_quotes_and_unknown_variants_are_not_used(tmp_path, live_raw):
    from test_reference_v04 import auction_payload, auction_transport

    service = Companion(Settings(mode="live", data_dir=tmp_path))
    snapshot = Snapshot.model_validate(live_raw)
    service.db.save_snapshot(snapshot)
    payload = market_fixture()
    payload["snapshot"]["time"] -= 90000
    payload["items"].append({"id": 555, "b": "random-enchant", "med": 1})
    normalized = normalize_market(payload)
    assert len(normalized["prices"]) == 3
    public = auction_payload(observed=payload["snapshot"]["time"], rows=[
        {"item_id": r["id"], "guidance": r["med"], "bonus": r.get("b")} for r in payload["items"]])
    service.refs.transport = auction_transport(public)
    asyncio.run(service.market.discover_markets())
    service.market.select("normal-alliance")
    asyncio.run(service.market.sync())
    data = service.auto_economy()
    assert data["market_status"]["status"] == "stale"
    assert data["auto_quotes"][0]["result"]["material_cost_copper"] is None
    payload["v"] = 8
    with pytest.raises(ReferenceError, match="版本"):
        normalize_market(payload)


def test_model_public_provider_never_claims_official_forever_compatibility(tmp_path):
    app = create_app(Settings(mode="mock", data_dir=tmp_path, auto_sync=False))
    with TestClient(app, base_url="http://127.0.0.1:18761") as client:
        provider = client.get("/api/providers").json()["providers"][0]
        assert provider["status"] == "unverified_for_forever_cn"
        assert "正式服" in provider["note"]
