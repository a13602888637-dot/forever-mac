import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from backend.ai import Advisor, AIError, evidence_context, validate_evidence
from backend.config import Settings
from backend.db import Database
from backend.models import Advice, Snapshot
from backend.references import References, ReferenceError
from backend.rules import compare_items, economy_quote, rule_plan


def test_database_isolation_idempotency_and_persistence(tmp_path, raw_snapshot, live_raw):
    db = Database(tmp_path / "app.sqlite3")
    mock = Snapshot.model_validate({**raw_snapshot, "data_mode": "mock"})
    live = Snapshot.model_validate(live_raw)
    one = db.save_snapshot(mock)
    assert db.save_snapshot(mock) == one
    two = db.save_snapshot(live)
    assert two != one
    assert db.latest("live")[0] == two
    assert db.latest("mock")[0] == one
    db.add_price("mock", "A", 1, 50)
    db.add_price("mock", "A", 1, 60)
    assert db.prices("mock", "A")[0]["copper"] == 60
    assert db.prices("live", "A") == []
    assert db.prices("mock", "B") == []
    task_id = db.add_task("mock", mock.character.identity, "团本清单", "需求待核实")
    assert not db.update_task(task_id, "live", mock.character.identity, True)
    assert db.update_task(task_id, "mock", mock.character.identity, True)
    reopened = Database(db.path)
    assert reopened.tasks("mock", mock.character.identity)[0]["done"] == 1


def test_rules_and_stat_delta(raw_snapshot):
    snapshot = Snapshot.model_validate(raw_snapshot)
    advice = rule_plan(snapshot, "abc")
    assert len(advice.actions) == 3
    assert all(c.provenance != "verified" for c in advice.claims)
    result = compare_items(snapshot.equipment[0], snapshot.bags[0])
    deltas = {r["stat"]: r["delta"] for r in result["deltas"]}
    assert deltas["ITEM_MOD_INTELLECT_SHORT"] == 4
    assert deltas["ITEM_MOD_STAMINA_SHORT"] == -1
    candidate = snapshot.bags[0].model_copy(update={"stats": {"ITEM_MOD_INTELLECT_SHORT": None}})
    result = compare_items(snapshot.equipment[0], candidate, weights={"ITEM_MOD_INTELLECT_SHORT": 2})
    assert result["weighted_delta"] is None
    assert result["unknowns"]


def test_exact_profit_and_missing_prices(raw_snapshot):
    recipe = Snapshot.model_validate(raw_snapshot).recipes[0]
    prices = {1900000101: 100, 1900000102: 50}
    result = economy_quote(recipe, prices, 1000, Decimal("5"))
    assert result["material_cost_copper"] == 350
    assert result["fee_copper"] == 50
    assert result["profit_copper"] == 600
    assert result["roi_percent"] == "171.43"
    missing = economy_quote(recipe, {}, 1000, None)
    assert missing["profit_copper"] is None
    assert missing["material_cost_copper"] is None
    assert missing["unknowns"]
    zero = economy_quote(recipe, {k: 0 for k in prices}, 0, Decimal(0))
    assert zero["profit_copper"] == 0 and zero["roi_percent"] is None


def test_sdk_responses_contract_and_privacy(raw_snapshot, tmp_path):
    snapshot = Snapshot.model_validate(raw_snapshot)
    expected = rule_plan(snapshot, "id")
    calls = []
    class Responses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_parsed=expected)
    client = SimpleNamespace(responses=Responses())
    settings = Settings(mode="live", data_dir=tmp_path, api_key="not-a-real-key")
    result, engine = asyncio.run(Advisor(settings, client).generate(snapshot, "id", "如何准备团本？"))
    assert result == expected and engine == "gpt-6-luna"
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is Advice
    assert snapshot.character.name not in calls[0]["input"][1]["content"]
    assert snapshot.character.realm not in calls[0]["input"][1]["content"]
    assert "not-a-real-key" not in str(calls)


def test_invalid_ai_evidence_rejected(raw_snapshot):
    snapshot = Snapshot.model_validate(raw_snapshot)
    advice = rule_plan(snapshot, "id")
    advice.claims[0].provenance = "verified"
    with pytest.raises(AIError, match="分类"):
        validate_evidence(advice, evidence_context(snapshot, "id"))
    advice.claims[0].provenance = "assumption"
    advice.claims[0].evidence_ids = ["fabricated"]
    with pytest.raises(AIError, match="不存在"):
        validate_evidence(advice, evidence_context(snapshot, "id"))


def reference_transport(status=200):
    def respond(request):
        name = request.url.path.split("/")[-1].removesuffix(".json")
        data = {"manifest": {"build": "1.60.1.70450", "built_at": "2026-10-26", "product": "wow_cn_beta"},
                "items": {"100": {"id": 100, "name": "测试法帽", "ilvl": 20, "q": 2, "stats": [[5, 8]], "armor": 10}},
                "recipes": [{"id": 200, "name": "测试配方", "products": [[100, 1]], "reagents": [[300, 2]]}],
                "professions": [{"id": 197, "name": "裁缝"}], "stat_names": {"5": "智力"}}
        return httpx.Response(status, json=data.get(name, {"result": {"content": [{"type": "text", "text": "只读资料"}]}}))
    return httpx.MockTransport(respond)


def test_reference_cache_versions_and_mcp_allowlist(tmp_path, live_raw):
    db = Database(tmp_path / "db.sqlite3")
    refs = References(db, transport=reference_transport())
    report = asyncio.run(refs.sync())
    assert report["items"] == 1
    snap = Snapshot.model_validate(live_raw)
    item, source = refs.get_item(100, snap)
    assert item.stats == {"ITEM_MOD_INTELLECT_SHORT": 8, "RESISTANCE0_NAME": 10}
    assert source["provenance"] == "verified"
    assert refs.context_matches("测试法帽适合我吗？", snap)[0]["value"]["id"] == 100
    snap.client.build = "different"
    assert refs.get_item(100, snap)[1]["provenance"] == "assumption"
    recipe, _ = refs.get_recipe(200, snap)
    assert recipe.reagents[0].quantity == 2
    with pytest.raises(ReferenceError, match="白名单"):
        asyncio.run(refs.mcp("stage", {}))
    result = asyncio.run(refs.mcp("search", {"query": "法师"}))
    assert result["provenance"] == "assumption"
    refs.transport = reference_transport(403)
    with pytest.raises(ReferenceError, match="403"):
        asyncio.run(refs.sync())
    assert refs.get_item(100)[0].name == "测试法帽"


def test_unknown_quantity_and_invalid_amounts(raw_snapshot):
    recipe = Snapshot.model_validate(raw_snapshot).recipes[0]
    recipe.output_quantity = None
    assert economy_quote(recipe, {1900000101: 100, 1900000102: 10}, 1000, Decimal(0))["profit_copper"] is None
    for rate in (Decimal("NaN"), Decimal("101"), Decimal("-1")):
        with pytest.raises(ValueError):
            economy_quote(recipe, {}, 10, rate)
