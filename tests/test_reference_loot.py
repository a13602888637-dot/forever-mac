import asyncio
from copy import deepcopy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.reference_loot import normalize
from backend.references import ReferenceError
from backend.web import create_app
from test_reference_world import synced, transport, world_data


def test_loot_links_use_current_items_and_do_not_invent_rates(tmp_path):
    refs, _ = synced(tmp_path)
    boss = refs.detail("bosses", 900007)
    drop = boss["loot_groups"][0]
    assert drop["cached"] and drop["provenance"] == "assumption"
    assert drop["source_label"] == "Spyglass · 无限参考"
    known, unknown = drop["items"]
    assert known["name"] == "护甲乙" and known["url"] == "/references/items/20"
    assert unknown["url"] is None and unknown["source_url"].endswith("/item/999")
    assert "drop_rate" not in known and "chance" not in known
    assert refs.detail("instances", 1)["loot_groups"][0]["boss_id"] == 900007
    assert refs.detail("items", 20)["dropped_by"][0]["url"] == "/references/bosses/900007"
    empty = refs.detail("bosses", 900008)["loot_groups"][0]
    assert empty["cached"] and empty["items"] == []
    assert "不代表" in empty["note"]
    context = refs.context_matches("测试首领掉落什么？", None)
    hit = next(h for h in context if h["value"].get("reference_kind") == "bosses")
    assert hit["provenance"] == "assumption" and hit["value"]["temporary_drops"]["source"] == "Spyglass · 无限参考"


@pytest.mark.parametrize("field", ["npc_id", "instance", "encounter", "items"])
def test_mismatched_or_invalid_loot_does_not_replace_cache(tmp_path, field):
    refs, data = synced(tmp_path)
    previous = refs.db.reference("boss_loot")["sha256"]
    original = transport(data)
    def respond(request):
        response = original.handle_request(request)
        if request.url.path != "/mcp":
            return response
        envelope = response.json()
        value = json.loads(envelope["result"]["content"][0]["text"])
        if value["npc_id"] == 900007:
            if field == "npc_id":
                value["npc_id"] = 123
            elif field == "instance":
                value["instance"] = {"id": 999}
            elif field == "encounter":
                value["encounter"] = {"id": 999}
            else:
                value["temporary_drops"]["items"] = [{"item_id": "invalid", "name": "invalid"}]
            envelope["result"]["content"][0]["text"] = json.dumps(value)
        return httpx.Response(200, json=envelope)
    refs.transport = httpx.MockTransport(respond)
    with pytest.raises(ReferenceError):
        asyncio.run(refs.sync())
    assert refs.db.reference("boss_loot")["sha256"] == previous


def test_classic_loot_is_separately_labelled_and_stale_cache_is_hidden(tmp_path):
    refs, data = synced(tmp_path)
    row = deepcopy(refs.dataset("boss_loot")["payload"])
    row["900007"]["source"] = "QuestieDB"
    refs.db.cache_references({"boss_loot": row}, data["manifest"]["build"], data["manifest"]["built_at"])
    refs._cache.clear()
    assert refs.detail("bosses", 900007)["loot_groups"][0]["source_label"] == "QuestieDB · 经典旧世参考"
    refs.db.cache_references({"boss_loot": row}, "other", "old")
    refs._cache.clear()
    assert refs.detail("bosses", 900007)["loot_groups"][0]["cached"] is False


def test_loot_normalization_deduplicates_and_does_not_trust_remote_links():
    boss = {"id": 900007, "encounter": 7, "map": 1}
    item = {"item_id": 20, "name": "测试物品", "url": "javascript:alert(1)"}
    raw = {"outcome": "ok", "npc_id": 900007, "source": "encounter", "encounter": {"id": 7},
           "instance": {"id": 1}, "temporary_drops": {"source": "Spyglass", "items": [item, item]}}
    clean = normalize(raw, boss)
    assert len(clean["items"]) == 1 and "url" not in clean["items"][0]


def test_boss_instance_item_pages_show_loot_and_api_images(tmp_path):
    app = create_app(Settings(mode="mock", data_dir=tmp_path, auto_sync=False))
    refs = app.state.service.refs
    refs.transport = transport(world_data())
    refs.addon_catalog_path = None
    asyncio.run(refs.sync())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for path in ("/references/bosses/900007", "/references/instances/1"):
            page = client.get(path)
            assert page.status_code == 200
            assert 'href="/references/items/20"' in page.text
            assert "Spyglass · 无限参考" in page.text and "首领掉落" in page.text
        page = client.get("/references/items/20")
        assert "可能掉落的首领" in page.text and 'href="/references/bosses/900007"' in page.text
        detail = client.get("/api/references/details/bosses/900007").json()
        assert detail["loot_groups"][0]["items"][0]["icon_url"].startswith("/api/media/wow-icon-")
