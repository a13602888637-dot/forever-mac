import asyncio
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.addon_catalog import Catalog
from backend.addon_metadata import package_id
from backend.config import Settings
from backend.db import Database
from backend.media import MediaCache, validate_url
from backend.references import References, ReferenceError
from backend.web import create_app
from test_reference_v04 import reference_data


def world_data():
    data = reference_data()
    data["manifest"]["counts"].update(instances=1, npcs=3, bosses=2, atlas_maps=1, quests=3, questlines=1)
    data.update(
        instances=[{"id": 1, "name": "测试地城", "kind": "地下城", "players": [5], "level": {"min": 10},
                    "bosses": [{"id": 7, "name": "测试首领", "order": 1}], "loading": "loading/1.webp",
                    "entrance": {"zone_ui_map": 11, "approx": True, "source": "WorldMapOverlay", "confidence": "medium",
                                 "atlas": [{"ui_map": 11, "name": "测试区域", "x": .25, "y": .75}]}}],
        npcs={"npcs": [{"id": 900007, "name": "测试首领", "source": "encounter", "map": 1, "encounter": 7,
                        "zone": "测试地城", "portrait": "bosses/7.webp", "tmp": {"src": "questie", "level": [15, 16]}},
                       {"id": 900008, "name": "另一个首领", "source": "encounter", "map": 999, "encounter": 8},
                       {"id": 8, "name": "普通宠物", "source": "creature"}]},
        atlas={"maps": [{"id": 11, "name": "测试区域", "type_name": "区域", "art": "maps/11.webp",
                         "instances": [{"id": 1, "name": "测试地城", "x": .25, "y": .75, "approx": True},
                                       {"id": 2, "name": "坏坐标", "x": 1.1, "y": .5}]}],
               "quest_maps": {"400": [{"map": 11, "marks": [{"k": "start", "name": "接取者", "src": "questie", "x": .2, "y": .3}]}]}},
        quests={"quests": [
            {"id": 400, "title": "测试任务", "source": "cache", "zone": {"id": 42, "name": "测试地城", "instance": 1},
             "prev": [399], "next": 401, "goals": [{"id": 10, "name": "材料甲", "n": 2}],
             "reward": {"items": [[20, 1]], "xp": 200}, "cache_texts": ["任务正文$B第二行 <script>alert(1)</script>"]},
            {"id": 401, "title": "测试后续", "source": "cache"},
            {"id": 500, "source": "db2", "hint": "某件起始物品", "tmp": {"name": "参考任务名", "giver": "参考人", "src": "questie"}}]},
        questlines={"lines": [{"id": 9, "name": "测试任务线", "quests": [400, 401]}]},
    )
    return data


def transport(data):
    def respond(request):
        if request.url.path == "/mcp":
            body = json.loads(request.content)
            assert body["params"]["name"] == "npcs"
            ident = body["params"]["arguments"]["id"]
            boss = next(b for b in data["npcs"]["npcs"] if b["id"] == ident)
            value = {"outcome": "ok", "npc_id": ident, "source": "encounter", "encounter": {"id": boss["encounter"]},
                     "instance": {"id": boss["map"]}, "temporary_drops": None}
            if ident == 900007:
                value["temporary_drops"] = {"source": "Spyglass", "note": "无限参考掉落；掉率未知", "items": [
                    {"item_id": 20, "name": "过时的物品名", "quality": 3},
                    {"item_id": 999, "name": "未收录物品", "quality": 2, "not_in_client": True}]}
            return httpx.Response(200, json={"result": {"content": [{"type": "text", "text": json.dumps(value)}]}})
        return httpx.Response(200, json=data[request.url.path.rsplit("/", 1)[-1][:-5]])
    return httpx.MockTransport(respond)


def synced(tmp_path):
    data = world_data()
    refs = References(Database(tmp_path / "world.sqlite3"), transport=transport(data))
    report = asyncio.run(refs.sync())
    assert report["world_counts"] == {"instances": 1, "bosses": 2, "maps": 1, "quests": 3}
    return refs, data


def test_world_browse_relationships_and_unknown_boundaries(tmp_path):
    refs, _ = synced(tmp_path)
    assert refs.browse(kind="bosses")["total"] == 2
    assert refs.browse(kind="quests", category="clues")["results"][0]["record"]["name"] == "任务 #500"
    assert refs.browse("参考任务名", "quests")["total"] == 1
    assert refs.browse(kind="quests", page=100)["page"] == 1
    instance = refs.detail("instances", 1)
    assert instance["groups"][0]["items"][0]["url"] == "/references/bosses/900007"
    assert instance["groups"][1]["items"][0]["url"] == "/references/quests/400"
    assert instance["maps"][0]["markers"][0]["x_percent"] == 25
    assert instance["maps"][0]["markers"][0]["approx"]
    assert "地下城内部地图" in instance["notes"][0]
    assert len(refs.detail("maps", 11)["maps"][0]["markers"]) == 1
    boss = refs.detail("bosses", 900007)
    assert boss["source"]["url"].endswith("/data/npcs.json")
    assert boss["source"]["provenance"] == "assumption"
    assert boss["supplements"] == [{"label": "参考等级", "value": "15–16"}]
    quest = refs.detail("quests", 400)
    assert "\n第二行" in quest["paragraphs"][1]
    groups = {g["title"]: g["items"] for g in quest["groups"]}
    assert groups["前置任务"][0]["url"] is None
    assert groups["后续任务"][0]["url"] == "/references/quests/401"
    assert groups["奖励物品"][0]["url"] == "/references/items/20"
    assert "QuestieDB" in quest["maps"][0]["markers"][0]["source"]
    assert groups["任务线 · 测试任务线"][1]["id"] == 401
    assert refs.detail("quests", 500)["coverage"] == "仅编号 / 补充线索"
    context = refs.context_matches("测试地城有哪些首领？", None)
    assert any(r["value"].get("reference_kind") == "instances" for r in context)
    assert all(r["provenance"] == "assumption" for r in context)


@pytest.mark.parametrize("invalid", ["count", "build", "duplicate", "nested", "boss_link", "shape"])
def test_world_sync_is_atomic_on_invalid_advertised_dataset(tmp_path, invalid):
    refs, data = synced(tmp_path)
    old = {name: refs.db.reference(name)["sha256"] for name in ("items", "instances", "quests")}
    data["items"]["10"]["name"] = "不得部分更新"
    if invalid == "count":
        data["manifest"]["counts"]["quests"] = 100
    elif invalid == "build":
        data["quests"]["_meta"] = {"build": "other"}
    elif invalid == "duplicate":
        data["quests"]["quests"][1]["id"] = 400
    elif invalid == "nested":
        data["quests"]["quests"][0]["zone"] = "invalid"
    elif invalid == "boss_link":
        data["npcs"]["npcs"][0]["map"] = "invalid"
    else:
        data["atlas"]["maps"] = {}
    refs.transport = transport(data)
    with pytest.raises(ReferenceError):
        asyncio.run(refs.sync())
    assert {name: refs.db.reference(name)["sha256"] for name in old} == old


def test_legacy_source_and_stale_world_data_are_not_mixed(tmp_path):
    refs, data = synced(tmp_path)
    legacy = reference_data()
    legacy["manifest"]["build"] = "1.60.2.99999"
    refs.transport = transport(legacy)
    asyncio.run(refs.sync())
    assert refs.browse(kind="instances")["cached"] is False
    assert refs.browse(kind="instances")["total"] == 0
    assert refs.browse(kind="items")["total"] == 3


def test_world_pages_api_and_media_links(tmp_path):
    app = create_app(Settings(mode="mock", data_dir=tmp_path, auto_sync=False))
    refs = app.state.service.refs
    refs.transport = transport(world_data())
    refs.addon_catalog_path = None
    asyncio.run(refs.sync())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for kind, ident in (("instances", 1), ("bosses", 900007), ("maps", 11), ("quests", 400), ("quests", 500)):
            browse = client.get("/api/references/browse", params={"kind": kind})
            assert browse.status_code == 200
            assert client.get(f"/references?kind={kind}").status_code == 200
            detail = client.get(f"/references/{kind}/{ident}")
            assert detail.status_code == 200, detail.text
            assert "<script>alert(1)</script>" not in detail.text
        data = client.get("/api/references/details/instances/1").json()
        assert data["art_url"].startswith("/api/media/world-loading-1")
        assert data["maps"][0]["image_url"].startswith("/api/media/world-maps-11")
        assert client.get("/api/references/details/bosses/8").status_code == 400
        assert client.get("/api/references/browse?kind=unknown").status_code == 400


def test_world_art_only_accepts_known_data_paths(tmp_path):
    media = MediaCache(tmp_path)
    assert media.reference_image("maps/1454.webp").startswith("/api/media/world-maps-1454")
    assert media.reference_image("bosses/2732.webp")
    assert media.reference_image("loading/389.webp")
    for path in ("../data/maps/1.webp", "https://evil.test/a.webp", "maps/1.svg", "maps/1.webp?token=x", "maps/0.webp"):
        assert media.reference_image(path) is None
    with pytest.raises(ValueError):
        validate_url("https://wuxianwow.com/data/maps/../quests.json")


def test_dungeon_pack_identity_precedes_dbm_core_namespace():
    core = {"directory": "DBM-Core", "metadata": {"x-curse-project-id": "3358"}}
    dungeon = {"directory": "DBM-Party-Forever", "metadata": {"x-curse-project-id": "314994", "group": "DBM-Core"},
               "dependencies": ["DBM-Core"]}
    modules = {r["directory"]: r for r in [core, dungeon]}
    assert package_id(dungeon, modules) == "dbm-dungeons"
    unknown = deepcopy(dungeon)
    unknown["metadata"] = {}
    assert package_id(unknown, {unknown["directory"]: unknown}) == "local-DBM-Party-Forever"


def test_discovery_adds_maps_dungeon_pack_and_quest_projects(tmp_path):
    class Inventory:
        def inventory(self):
            return {"packages": []}
    catalog = Catalog(Inventory(), MediaCache(tmp_path))
    assert {i["id"] for i in catalog.browse(category="地图")["items"]} == {"atlas", "atlas-classic", "atlas-forever"}
    assert "questie" in {i["id"] for i in catalog.browse(category="任务")["items"]}
    assert catalog.detail("dbm-dungeons")["dependencies"] == ["DBM-Core"]
    assert "download" in catalog.detail("dbm-dungeons")["actions"]
    assert "download" not in catalog.detail("questie")["actions"]
    assert catalog.detail("atlas-classic")["related"][0]["id"] == "atlas"
    assert catalog.detail("dungeonjournal")["support"]["checked_at"] == "2026-11-07"
