"""v0.4 management behavior against disposable clients, never the real game."""
from copy import deepcopy
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from backend.addon_management import AddonManagement
from backend.addon_profiles import Profiles, parse_addon_state
from backend.platform_io import manifest, write_json
from backend.web import create_app
from test_platform import addon, bundle, stage, platform as platform  # noqa: F401


def character(platform, name="Hero-Surname", realm="123", account="test"):
    path = platform.game() / "WTF/Account" / account / realm / name / "AddOns.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"# Saved by game\r\nOther: disabled\r\nCore: disabled\r\nChild: disabled\r\n")
    profiles = Profiles(platform)
    ident = next(c["id"] for c in profiles.characters() if profiles.character_path(c["id"]) == path)
    return path, ident


def test_character_enablement_requires_explicit_storage_identity_and_closes_dependencies(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "Core")
    addon(root, "Child", dependencies="Core")
    addon(root, "Other")
    path, ident = character(platform)
    other_path, other_id = character(platform, account="another")
    assert ident != other_id
    management = AddonManagement(platform)
    characters = management.profiles.characters()
    assert characters[0]["snapshot_identity"] == characters[1]["snapshot_identity"] == "123:Hero-Surname"
    assert management.enablement()["needs_character"]
    assert all(p["status"] == "unknown" for p in management.enablement()["packages"])
    original, unrelated = path.read_bytes(), other_path.read_bytes()
    plan = management.prepare("enable", ["local-Child"], ident)
    assert plan["can_apply"] and plan["character"]["id"] == ident
    assert plan["dependencies"] == [{"directory": "Core", "before": False, "after": True}]
    assert path.read_bytes() == original
    result = management.apply(plan["id"])
    assert result["status"] == "applied"
    states = parse_addon_state(path.read_bytes())[2]
    assert states["Core"] and states["Child"] and states["Other"] is False
    assert other_path.read_bytes() == unrelated
    assert b"# Saved by game\r\nOther: disabled\r\n" in path.read_bytes()
    assert next(p for p in management.enablement(ident)["packages"] if p["id"] == "local-Child")["status"] == "enabled"
    with pytest.raises(ValueError, match="已使用"):
        management.apply(plan["id"])
    platform.rollback(result["items"][0]["operation_id"])
    assert path.read_bytes() == original


def test_disable_never_silently_disables_reverse_dependencies(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "Core")
    addon(root, "Child", dependencies="Core")
    path, ident = character(platform)
    path.write_text("Core: enabled\nChild: enabled\nOther: disabled\n")
    management = AddonManagement(platform)
    blocked = management.prepare("disable", ["local-Core"], ident)
    assert not blocked["can_apply"] and any("Child 正在使用 Core" in b for b in blocked["blockers"])
    with pytest.raises(ValueError, match="不会自动停用"):
        management.apply(blocked["id"])
    assert parse_addon_state(path.read_bytes())[2]["Child"]
    reviewed = management.prepare("disable", ["local-Core", "local-Child"], ident)
    assert reviewed["can_apply"]
    assert management.apply(reviewed["id"])["status"] == "applied"
    assert not parse_addon_state(path.read_bytes())[2]["Child"]


def test_enable_missing_dependency_and_changed_code_or_character_are_blocked(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "Child", dependencies="Missing")
    path, ident = character(platform)
    management = AddonManagement(platform)
    assert any("缺少依赖 Missing" in x for x in management.prepare("enable", ["local-Child"], ident)["blockers"])
    addon(root, "Missing")
    plan = management.prepare("enable", ["local-Child"], ident)
    assert plan["can_apply"]
    (root / "Missing/Core.lua").write_text("local modified = true")
    with pytest.raises(ValueError, match="文件发生变化"):
        management.apply(plan["id"])
    plan = management.prepare("enable", ["local-Child"], ident)
    path.write_bytes(path.read_bytes() + b"Added: enabled\n")
    with pytest.raises(ValueError, match="角色启用状态已变化"):
        management.apply(plan["id"])


def test_uninstall_requires_ownership_preserves_savedvariables_and_restores(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "Mine")
    saved = platform.game() / "WTF/SavedVariables"
    saved.mkdir()
    (saved / "Mine.lua").write_text("settings = {kept = true}")
    before, settings = manifest(root), manifest(saved)
    management = AddonManagement(platform)
    assert not management.prepare("uninstall", ["local-Mine"])["can_apply"]
    platform.adopt("local-Mine")
    plan = management.prepare("uninstall", ["local-Mine"])
    assert plan["can_apply"]
    assert [c["directory"] for c in plan["items"][0]["changes"]] == ["Mine"]
    result = management.apply(plan["id"])
    assert result["status"] == "applied" and not (root / "Mine").exists()
    assert manifest(saved) == settings
    platform.rollback(result["items"][0]["operation_id"])
    assert manifest(root) == before and manifest(saved) == settings


def test_uninstall_dependency_shared_ownership_and_local_changes_block(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "Core")
    addon(root, "Child", dependencies="Core")
    platform.adopt("local-Core")
    platform.adopt("local-Child")
    management = AddonManagement(platform)
    assert any("仍被 Child 依赖" in b for b in management.prepare("uninstall", ["local-Core"])["blockers"])
    plan = management.prepare("uninstall", ["local-Core", "local-Child"])
    assert plan["can_apply"] and plan["package_ids"] == ["local-Child", "local-Core"]
    state = platform.tx.state()
    state["installs"]["foreign"] = deepcopy(state["installs"]["local-Core"])
    platform.tx.save_state(state)
    with pytest.raises(ValueError, match="共享目录"):
        management.apply(plan["id"])
    with pytest.raises(ValueError, match="共享目录"):
        platform.adopt("local-Core")
    state["installs"].pop("foreign")
    platform.tx.save_state(state)
    (root / "Core/Core.lua").write_text("changed")
    assert any("本地修改" in b for b in management.prepare("uninstall", ["local-Core", "local-Child"])["blockers"])


def prepare_batch(platform, tmp_path, monkeypatch, names=("A", "B", "C")):
    for name in names:
        platform.apply(stage(platform, bundle(tmp_path, [name]), "local-" + name)["id"])
    inventory = platform.inventory

    def author_inventory():
        result = inventory()
        for group in result["packages"]:
            group.update(repo="fixture/" + group["id"], source="github")
        return result

    monkeypatch.setattr(platform, "inventory", author_inventory)
    monkeypatch.setattr(platform, "download", lambda key: platform.stage(
        bundle(tmp_path, [key.removeprefix("local-")], version="3.0"), package_id=key,
        provenance={"declaration": "workshop", "version": "3.0"}))
    management = AddonManagement(platform)
    return management, management.prepare("update", ["local-" + name for name in names])


def test_batch_failure_stops_restores_failed_item_and_allows_independent_rollback(platform, tmp_path, monkeypatch):
    management, plan = prepare_batch(platform, tmp_path, monkeypatch)
    assert plan["can_apply"] and all(i["to_version"] == "3.0" for i in plan["items"])
    root = platform.game() / "Interface/AddOns"
    before_b, before_c = manifest(root / "B"), manifest(root / "C")
    replace = os.replace
    failed = False

    def fail_once(source, target):
        nonlocal failed
        if Path(target) == root / "B" and "/new/" in str(source) and not failed:
            failed = True
            raise OSError("simulated disk full")
        return replace(source, target)

    monkeypatch.setattr(os, "replace", fail_once)
    result = management.apply(plan["id"])
    assert result["status"] == "failed"
    assert [i["status"] for i in result["items"]] == ["applied", "failed", "skipped"]
    assert manifest(root / "B") == before_b and manifest(root / "C") == before_c
    assert "已恢复原文件" in result["items"][1]["error"]
    assert not platform.tx.pending()
    # A later unrelated installation must not force rollback of that package.
    unrelated = platform.apply(stage(platform, bundle(tmp_path, ["Unrelated"]), "local-Unrelated")["id"])
    platform.rollback(result["items"][0]["operation_id"])
    assert "2.0" in (root / "A/A.toc").read_text()
    assert (root / "Unrelated").is_dir()
    assert platform.tx.get(unrelated["id"])["status"] == "applied"
    with pytest.raises(ValueError, match="已使用"):
        management.apply(plan["id"])


def test_batch_consumed_child_and_expiry_cannot_be_replayed(platform, tmp_path, monkeypatch):
    management, plan = prepare_batch(platform, tmp_path, monkeypatch, ("A", "B"))
    platform.apply(plan["items"][0]["plan_id"])
    with pytest.raises(ValueError, match="已被单独使用|管理记录|基线已变化"):
        management.apply(plan["id"])
    plan = management.prepare("update", ["local-B"])
    saved = management.load(plan["id"])
    saved["expires_at"] = time.time() - 1
    write_json(management._path(plan["id"]), saved)
    with pytest.raises(ValueError, match="已过期"):
        management.apply(plan["id"])


def test_management_running_game_and_shared_lock_stop_apply(platform, monkeypatch):
    addon(platform.game() / "Interface/AddOns", "Mine")
    platform.adopt("local-Mine")
    management = AddonManagement(platform)
    plan = management.prepare("uninstall", ["local-Mine"])
    import backend.platform_io as io
    monkeypatch.setattr(io, "game_running", lambda: True)
    with pytest.raises(ValueError, match="游戏仍在运行"):
        management.apply(plan["id"])
    monkeypatch.setattr(io, "game_running", lambda: False)
    with platform.lock():
        with pytest.raises(ValueError, match="另一个插件操作"):
            management.apply(plan["id"])
    assert (platform.game() / "Interface/AddOns/Mine").is_dir()


def test_interrupted_batch_recovery_is_explicit_and_remaining_items_never_run(platform, tmp_path, monkeypatch):
    management, plan = prepare_batch(platform, tmp_path, monkeypatch, ("A", "B"))
    root = platform.game() / "Interface/AddOns"
    original = manifest(root)
    replace = os.replace

    def interrupt(source, target):
        if Path(target) == root / "A" and "/new/" in str(source):
            raise KeyboardInterrupt("power loss simulation")
        return replace(source, target)

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        management.apply(plan["id"])
    monkeypatch.setattr(os, "replace", replace)
    restarted = AddonManagement(platform)
    assert restarted.review(plan["id"])["status"] == "interrupted"
    pending = platform.tx.pending()
    assert len(pending) == 1
    platform.recover(pending[0]["id"])
    assert manifest(root) == original
    receipt = restarted.review(plan["id"])
    assert receipt["items"][0]["status"] == "recovered"
    assert receipt["items"][1]["status"] == "skipped"
    assert restarted.plans()[0]["items"][0]["status"] == "recovered"
    with pytest.raises(ValueError, match="已使用"):
        restarted.apply(plan["id"])


def test_management_http_contract_and_schema(platform):
    addon(platform.game() / "Interface/AddOns", "Mine")
    platform.adopt("local-Mine")
    platform.settings.ai_provider = "rules"
    with TestClient(create_app(platform.settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/addons/enablement").json()["needs_character"]
        assert client.post("/api/addons/management/plans", json={"action": "delete-everything", "package_ids": []}).status_code == 422
        prepared = client.post("/api/addons/management/plans", json={"action": "uninstall", "package_ids": ["local-Mine"]})
        assert prepared.status_code == 200
        plan = prepared.json()
        assert plan["can_apply"]
        assert client.get("/api/addons/management/plans").json()[0]["id"] == plan["id"]
        assert client.get("/api/addons/management/plans/" + plan["id"]).json()["action"] == "uninstall"
        result = client.post("/api/addons/management/plans/" + plan["id"] + "/apply").json()
        assert result["status"] == "applied"
        assert client.post("/api/addons/management/plans/" + plan["id"] + "/apply").status_code == 400


def test_enable_dependency_cycle_and_case_mismatch_are_explicit(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "Core", dependencies="Child")
    addon(root, "Child", dependencies="Core")
    _, ident = character(platform)
    management = AddonManagement(platform)
    assert any("循环依赖" in b for b in management.prepare("enable", ["local-Child"], ident)["blockers"])
    with pytest.raises(ValueError, match="循环依赖"):
        management.prepare("enable", ["local-Core", "local-Child"], ident)
    addon(root, "Core")
    addon(root, "Child", dependencies="core")
    assert any("大小写不一致" in b for b in management.prepare("enable", ["local-Child"], ident)["blockers"])
    platform.adopt("local-Core")
    assert any("仍被 Child 依赖" in b for b in management.prepare("uninstall", ["local-Core"])["blockers"])


def test_simultaneous_apply_only_consumes_confirmation_once(platform, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    addon(platform.game() / "Interface/AddOns", "Mine")
    platform.adopt("local-Mine")
    management = AddonManagement(platform)
    plan = management.prepare("uninstall", ["local-Mine"])
    started, release = Event(), Event()
    execute = platform.tx.execute

    def hold(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return execute(*args, **kwargs)

    monkeypatch.setattr(platform.tx, "execute", hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        applying = pool.submit(management.apply, plan["id"])
        assert started.wait(5)
        try:
            with pytest.raises(ValueError, match="另一个插件操作"):
                management.apply(plan["id"])
        finally:
            release.set()
        assert applying.result()["status"] == "applied"
    assert len([j for j in platform.history() if j["kind"] == "uninstall:local-Mine"]) == 1


def test_fetch_reports_received_bytes_without_changing_default_contract(tmp_path, monkeypatch):
    import httpx
    from backend import addon_sources
    real_client = httpx.Client
    payload = b"a" * 300000
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
    monkeypatch.setattr(addon_sources.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    counts = []
    target = tmp_path / "download.zip"
    assert addon_sources.fetch("https://api.github.com/fixture", 300001, target, progress=counts.append) == b""
    assert target.read_bytes() == payload and counts == [0, 131072, 262144, len(payload)]
    assert addon_sources.fetch("https://api.github.com/fixture", 300001) == payload


def test_profile_switch_blocks_reverse_dependency_at_preview_and_apply(platform):
    from test_platform import setup_profiles
    profiles, character_path, _ = setup_profiles(platform)
    root = platform.game() / "Interface/AddOns"
    addon(root, "EllesmereUIActionBars", dependencies="EllesmereUI", extra="## Group: EllesmereUI")
    ident = profiles.characters()[0]["id"]
    plan = profiles.prepare_switch(ident, "ForeverUI")
    addon(root, "External", dependencies="EllesmereUIActionBars")
    before = manifest(platform.game())
    with pytest.raises(ValueError, match="External 依赖 EllesmereUIActionBars"):
        profiles.prepare_switch(ident, "ForeverUI")
    with pytest.raises(ValueError, match="External 依赖 EllesmereUIActionBars"):
        profiles.apply_switch(plan["id"])
    assert manifest(platform.game()) == before
    with (character_path / "AddOns.txt").open("ab") as stream:
        stream.write(b"External: disabled\r\n")
    ready = profiles.prepare_switch(ident, "ForeverUI")
    assert profiles.apply_switch(ready["id"])["status"] == "applied"
    states = parse_addon_state((character_path / "AddOns.txt").read_bytes())[2]
    assert states["External"] is False and states["EllesmereUIActionBars"] is False


def test_rollback_restoring_child_requires_restoring_core_first(platform, tmp_path):
    platform.apply(stage(platform, bundle(tmp_path, ["Core"]), "local-Core")["id"])
    platform.apply(stage(platform, bundle(tmp_path, ["Child"], dependency="Core"), "local-Child")["id"])
    management = AddonManagement(platform)
    removed = management.apply(management.prepare("uninstall", ["local-Core", "local-Child"])["id"])
    child_id, core_id = [i["operation_id"] for i in removed["items"]]
    preview = platform.tx.rollback_preview(child_id)
    assert preview["kind"] == "rollback" and not preview["can_apply"]
    assert any("Child 依赖 Core" in b for b in preview["blockers"])
    with pytest.raises(ValueError, match="Child 依赖 Core"):
        platform.rollback(child_id)
    assert platform.tx.rollback_preview(core_id)["can_apply"]
    platform.rollback(core_id)
    assert platform.tx.rollback_preview(child_id)["can_apply"]
    platform.rollback(child_id)
    assert (platform.game() / "Interface/AddOns/Child").is_dir()
    assert (platform.game() / "Interface/AddOns/Core").is_dir()


def test_rollback_cannot_remove_a_newly_used_dependency(platform, tmp_path):
    installed = platform.apply(stage(platform, bundle(tmp_path, ["Core"]), "local-Core")["id"])
    platform.apply(stage(platform, bundle(tmp_path, ["Child"], dependency="Core"), "local-Child")["id"])
    preview = platform.tx.rollback_preview(installed["id"])
    assert not preview["can_apply"]
    with pytest.raises(ValueError, match="Child 依赖 Core"):
        platform.rollback(installed["id"])


def test_rollback_http_preview_is_readonly_and_token_rechecks_state(platform, tmp_path):
    installed = platform.apply(stage(platform, bundle(tmp_path, ["Mine"]), "local-Mine")["id"])
    platform.settings.ai_provider = "rules"
    with TestClient(create_app(platform.settings), base_url="http://127.0.0.1") as client:
        before_game, before_data = manifest(platform.game()), manifest(platform.root)
        path = "/api/addons/operations/" + installed["id"]
        preview = client.get(path + "/rollback-preview").json()
        assert preview["can_apply"] and preview["targets"] == ["Interface/AddOns/Mine"]
        assert preview["before_after"][0]["action"] == "remove"
        assert manifest(platform.game()) == before_game and manifest(platform.root) == before_data
        state = platform.tx.state()
        state["profiles"]["new-role"] = "ForeverUI"
        platform.tx.save_state(state)
        stale = client.post(path + "/rollback", json={"precondition_token": preview["precondition_token"]})
        assert stale.status_code == 400 and "预览后" in stale.text
        assert manifest(platform.game()) == before_game
        fresh = client.get(path + "/rollback-preview").json()
        result = client.post(path + "/rollback", json={"precondition_token": fresh["precondition_token"]})
        assert result.status_code == 200 and result.json()["status"] == "rollback_applied"
        assert client.post(path + "/rollback", json={"precondition_token": fresh["precondition_token"]}).status_code == 400


def test_config_restore_preview_scopes_files_and_rejects_post_preview_changes(platform):
    from test_platform import setup_profiles
    profiles, character_path, saved = setup_profiles(platform)
    ident = profiles.characters()[0]["id"]
    snapshot = profiles.backup_config(ident, "ForeverUI")
    (saved / "ForeverUI.lua").write_text("account new layout")
    character_config = character_path / "SavedVariables/ForeverUI.lua"
    character_config.parent.mkdir()
    character_config.write_text("character new layout")
    before_game, before_data = manifest(platform.game()), manifest(platform.root)
    preview = profiles.restore_preview(snapshot["id"], ident)
    assert preview["can_apply"] and preview["kind"] == "config_restore"
    assert preview["character"]["id"] == ident and preview["combo"] == "ForeverUI"
    actions = {(f["scope"], f["filename"]): f["action"] for f in preview["files"]}
    assert actions["account", "ForeverUI.lua"] == "replace"
    assert actions["character", "ForeverUI.lua"] == "remove"
    assert manifest(platform.game()) == before_game and manifest(platform.root) == before_data
    character_config.write_text("changed after preview")
    with pytest.raises(ValueError, match="恢复预览后"):
        profiles.restore_config(snapshot["id"], ident, preview["precondition_token"])
    assert (saved / "ForeverUI.lua").read_text() == "account new layout"
    fresh = profiles.restore_preview(snapshot["id"], ident)
    result = profiles.restore_config(snapshot["id"], ident, fresh["precondition_token"])
    assert result["status"] == "applied" and not character_config.exists()
    assert (saved / "ForeverUI.lua").read_text() == "ForeverUIDB = {original = true}"
    with pytest.raises(ValueError, match="恢复预览后"):
        profiles.restore_config(snapshot["id"], ident, fresh["precondition_token"])
    # Even a no-content-change restore consumes its preview once.
    unchanged = profiles.restore_preview(snapshot["id"], ident)
    assert all(f["action"] == "unchanged" for f in unchanged["files"])
    profiles.restore_config(snapshot["id"], ident, unchanged["precondition_token"])
    with pytest.raises(ValueError, match="恢复预览后"):
        profiles.restore_config(snapshot["id"], ident, unchanged["precondition_token"])


def historical_profile_fixture(platform):
    from test_platform import setup_profiles
    from backend.addon_metadata import scan_addons
    profiles, character_path, _ = setup_profiles(platform)
    root = platform.game() / "Interface/AddOns"
    addon(root, "EllesmereUIDamageMeters", dependencies="EllesmereUI", extra="## Group: EllesmereUI")
    addon(root, "ForeverAI")
    platform.adopt("local-ForeverAI")
    ident = profiles.characters()[0]["id"]
    old = profiles.prepare_switch(ident, "ForeverUI", keep_ellesmere_dps=True)
    profiles.apply_switch(old["id"])
    addon(root, "NewPlugin")
    addon(root, "NewActive")
    raw = b"\xef\xbb\xbf# Current user comment must survive\r\n"
    raw += b"".join((m["directory"] + ": disabled\r\n").encode() for m in scan_addons(root)
                    if m["directory"] != "NewActive")
    raw += b"NewActive: enabled\r\n# Final user comment\r\n"
    (character_path / "AddOns.txt").write_bytes(raw)
    return profiles, character_path, old


def test_history_restore_switch_prepares_exact_diff_and_preserves_new_modules(platform):
    profiles, character_path, old = historical_profile_fixture(platform)
    target = character_path / "AddOns.txt"
    game_before = manifest(platform.game())
    source_before = (profiles.root / "profile-plans" / (old["id"] + ".txt")).read_bytes()
    plan = profiles.prepare_restore_switch(old["id"])
    assert plan["can_apply"] and plan["restore_from"] == old["id"]
    assert plan["character"]["display_name"]
    assert plan["enabled_count"] == 4 and plan["disabled_count"] == 0
    assert plan["updates"] == {"ForeverUI": True, "ForeverAI": True, "EllesmereUIDamageMeters": True, "EllesmereUI": True}
    assert "ForeverAI" in plan["historical_default_enabled"]
    assert plan["dependencies"] == [{"directory": "EllesmereUI", "required_by": ["EllesmereUIDamageMeters"],
                                     "before": False, "after": True, "reason": "恢复已选模块所需的额外依赖"}]
    assert {m["directory"] for m in plan["unchanged_modules"]} == {"NewPlugin", "NewActive"}
    assert manifest(platform.game()) == game_before
    assert (profiles.root / "profile-plans" / (old["id"] + ".txt")).read_bytes() == source_before
    assert profiles.apply_switch(plan["id"])["status"] == "applied"
    current = target.read_bytes()
    assert current.startswith(b"\xef\xbb\xbf# Current user comment must survive\r\n")
    assert current.endswith(b"# Final user comment\r\n")
    states = parse_addon_state(current)[2]
    assert states["ForeverUI"] and states["ForeverAI"] and states["EllesmereUI"] and states["EllesmereUIDamageMeters"]
    assert not states["NewPlugin"] and states["NewActive"]
    assert not states["Other"] and not states["EllesmereUIChat"]
    again = profiles.prepare_restore_switch(old["id"])
    assert not again["can_apply"] and not again["updates"]
    with pytest.raises(ValueError, match="无需重复应用"):
        profiles.apply_switch(again["id"])


def test_history_restore_switch_verifies_historical_file_and_current_precondition(platform):
    profiles, character_path, old = historical_profile_fixture(platform)
    plan = profiles.prepare_restore_switch(old["id"])
    target = character_path / "AddOns.txt"
    target.write_bytes(target.read_bytes() + b"# Changed after review\r\n")
    with pytest.raises(ValueError, match="状态文件已变化"):
        profiles.apply_switch(plan["id"])
    source = profiles.root / "profile-plans" / (old["id"] + ".txt")
    source.write_bytes(source.read_bytes() + b"# Corrupted history\r\n")
    with pytest.raises(ValueError, match="历史方案状态文件校验失败"):
        profiles.prepare_restore_switch(old["id"])


def test_history_restore_switch_blocks_missing_or_unknown_dependencies(platform):
    profiles, character_path, old = historical_profile_fixture(platform)
    root = platform.game() / "Interface/AddOns"
    addon(root, "EllesmereUIDamageMeters", dependencies="MissingDependency", extra="## Group: EllesmereUI")
    before = (character_path / "AddOns.txt").read_bytes()
    blocked = profiles.prepare_restore_switch(old["id"])
    assert not blocked["can_apply"] and any("MissingDependency" in b for b in blocked["blockers"])
    with pytest.raises(ValueError, match="MissingDependency"):
        profiles.apply_switch(blocked["id"])
    assert (character_path / "AddOns.txt").read_bytes() == before
    addon(root, "EllesmereUIDamageMeters", dependencies="EllesmereUI", extra="## Group: EllesmereUI", interface=120105)
    blocked = profiles.prepare_restore_switch(old["id"])
    assert not blocked["can_apply"] and any("兼容声明未知" in b for b in blocked["blockers"])


def test_history_restore_switch_http_only_prepares_until_confirmed(platform):
    profiles, character_path, old = historical_profile_fixture(platform)
    platform.settings.ai_provider = "rules"
    before = (character_path / "AddOns.txt").read_bytes()
    with TestClient(create_app(platform.settings), base_url="http://127.0.0.1") as client:
        response = client.post("/api/profiles/plans/" + old["id"] + "/restore-plan")
        assert response.status_code == 200
        plan = response.json()
        assert plan["can_apply"] and plan["status"] == "prepared" and plan["character"]["display_name"]
        assert (character_path / "AddOns.txt").read_bytes() == before
        assert client.post("/api/profiles/plans/" + plan["id"] + "/apply").json()["status"] == "applied"
