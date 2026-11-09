"""Desktop behavior contracts: presentation preserves identity and missing-data boundaries."""
from pathlib import Path
import time

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.desktop import character_view, selected_profile
from backend.media import MediaCache
from backend.models import Snapshot
from backend.web import create_app


def test_character_equipment_bags_and_identity(raw_snapshot, tmp_path):
    app = create_app(Settings(data_dir=tmp_path, auto_sync=False, ai_provider="rules"))
    service = app.state.service
    service.db.cache_references({"items": {
        "1900000003": {"id": 1900000003, "name": "演示·织法者兜帽", "icon": 135274, "cls": 4},
        "1900000101": {"id": 1900000101, "name": "演示·丝绸", "icon": 132905, "cls": 7},
    }}, "1.60.1.70450", "2026-11-01T00:00:00Z")
    snapshot = Snapshot.model_validate(raw_snapshot)
    view = character_view(snapshot, service.refs, MediaCache(tmp_path / "pictures"))
    assert len(view["equipment_slots"]) == 19
    assert view["equipment_slots"][1]["item"] is None
    assert view["bag_items"][0]["compare_slots"] == [{"id": 1, "name": "头部"}]
    assert view["bag_items"][0]["icon_url"].startswith("/api/media/wow-icon-135274")
    assert view["bag_items"][1]["count"] == 20
    assert view["bag_items"][1]["category"] == "材料"
    assert view["bag_items"][1]["stats_display"] == []
    assert view["bag_items"][1]["compare_slots"] == []
    characters = [{"id": "a", "snapshot_identity": snapshot.character.identity}]
    assert selected_profile(characters, snapshot) == "a"
    assert selected_profile(characters + [{"id": "b", "snapshot_identity": snapshot.character.identity}], snapshot) == ""
    assert selected_profile([{"id": "wrong", "snapshot_identity": "another:identity"}], snapshot) == ""
    other = snapshot.model_copy(update={"character": snapshot.character.model_copy(update={"class_token": "WARRIOR", "race_token": "Orc"})})
    art = character_view(other, service.refs, app.state.media)
    assert art["class_name"] == "战士" and art["race_name"] == "兽人"
    assert art["character_art"]["class"]["url"] != view["character_art"]["class"]["url"]


def test_desktop_routes_browsable_without_snapshot(tmp_path):
    app = create_app(Settings(mode="live", data_dir=tmp_path, auto_sync=False, ai_provider="rules"))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for path in ("/", "/discover", "/downloads", "/overview?tab=bags", "/profiles", "/references", "/settings", "/addons/dbm"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert '<b>Forever</b>' in response.text
            assert "AI COMPANION" not in response.text
        assert "本地图鉴尚未同步" in client.get("/references").text
        assert "尚无角色快照" in client.get("/overview?tab=bags").text


def test_legacy_snapshot_and_reference_detail_links(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, auto_sync=False, ai_provider="rules"))
    app.state.service.db.cache_references({
        "items": {"10": {"id": 10, "name": "材料甲", "icon": 135274, "cls": 7},
                  "20": {"id": 20, "name": "产物乙", "icon": 135274, "cls": 4, "ilvl": 10}},
        "recipes": [{"id": 30, "name": "制作乙", "skill": 197, "products": [[20, 1]], "reagents": [[10, 2], [99, 1]]}],
        "professions": [{"id": 197, "name": "裁缝"}], "stat_names": {}}, "1.60.1.70450", "2026-11-01T00:00:00Z")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/references").status_code == 200
        detail = client.get("/references/recipes/30")
        assert detail.status_code == 200
        assert '/references/items/10' in detail.text and '/references/items/20' in detail.text
        assert 'href="None"' not in detail.text
        assert '/references/recipes/30' in client.get('/references/items/20').text
        bag = client.get('/overview?tab=bags')
        assert bag.status_code == 200 and 'id="bag-browser"' in bag.text
        assert 'id="bag-compare-form"' in bag.text


def test_current_quote_does_not_use_expired_manual_price(tmp_path):
    from backend.service import EconomyInput
    app = create_app(Settings(data_dir=tmp_path, auto_sync=False, ai_provider="rules"))
    service = app.state.service
    with service.db.connect() as conn:
        conn.execute("UPDATE prices SET recorded_at=?", (int(time.time()) - 90000,))
    # A stale fixture/public row must not become a current cost through the manual route.
    service.market.available = lambda snapshot: ({}, {"status": "stale"}, [])
    result = service.quote(EconomyInput(recipe_id=1900000201, sale_unit_copper=1000, fee_percent="5"))
    assert result["material_cost_copper"] is None


def test_frontend_scripts_parse():
    import shutil
    import subprocess
    node = shutil.which("node")
    if node:
        for filename in ("app.js", "platform.js", "desktop.js"):
            subprocess.run([node, "--check", str(Path(__file__).resolve().parents[1] / "frontend/static" / filename)], check=True)


def test_bag_comparison_rejects_changed_snapshot(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, auto_sync=False, ai_provider="rules"))
    service = app.state.service
    old_id, snapshot = service.latest()
    changed_item = snapshot.bags[0].model_copy(update={"name": "新的行囊位置物品", "item_id": 1900000999})
    changed = snapshot.model_copy(update={"captured_at": snapshot.captured_at + 1, "bags": [changed_item, *snapshot.bags[1:]]})
    service.db.save_snapshot(changed)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        stale = client.post('/api/equipment/compare', json={"slot": 1, "candidate_kind": "bag", "bag_index": 0,
                                                         "expected_snapshot_id": old_id})
        assert stale.status_code == 400 and "快照已更新" in stale.json()["detail"]
        current = client.post('/api/equipment/compare', json={"slot": 1, "candidate_kind": "bag", "bag_index": 0,
                                                           "expected_snapshot_id": service.latest()[0]})
        assert current.status_code == 200 and current.json()["candidate"]["name"] == "新的行囊位置物品"


def test_profile_preview_lists_pending_and_detects_new_character_state(tmp_path, monkeypatch):
    import backend.platform_io as io_module
    monkeypatch.setattr(io_module, 'game_running', lambda: False)
    app = create_app(Settings(data_dir=tmp_path, auto_sync=False, ai_provider="rules"))
    platform, profiles = app.state.platform, app.state.profiles
    addon = platform.game() / 'Interface/AddOns/ForeverUI'
    addon.mkdir()
    (addon / 'ForeverUI.toc').write_text('## Interface: 16001\n## Version: 0.2.1\n')
    state = platform.game() / 'WTF/Account/isolated/Realm/Tester/AddOns.txt'
    state.parent.mkdir(parents=True)
    state.write_text('ForeverUI: disabled\n')
    character_id = profiles.characters()[0]['id']
    plan = profiles.prepare_switch(character_id, 'ForeverUI')
    with TestClient(app, base_url='http://127.0.0.1') as client:
        preview = client.get('/profiles/plans/' + plan['id'])
        assert preview.status_code == 200 and '确认应用' in preview.text
        assert '/profiles/plans/' + plan['id'] in client.get('/downloads').text
        state.write_text('ForeverUI: enabled\n# user changed\n')
        stale = client.get('/profiles/plans/' + plan['id'])
        assert stale.status_code == 200 and '角色启用状态已变化' in stale.text
