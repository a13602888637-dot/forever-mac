"""Isolated client acceptance: never write to the user's real WoW installation."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import os
import plistlib
import stat
import sys
import uuid
import zipfile

from fastapi.testclient import TestClient
import pytest

from backend.addon_platform import AddonPlatform
from backend.addon_profiles import Profiles, parse_addon_state
from backend.addon_workshop import Workshop
from backend.config import Settings
from backend.paths import game_flavors
from backend.platform_io import manifest, operation_lock
from backend.web import create_app


def addon(root, name, version="1.0", dependencies="", extra="", code="local ready = true\n", interface=16001):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / (name + ".toc")).write_text(f"## Interface: {interface}\n## Title: {name}\n## Version: {version}\n## Dependencies: {dependencies}\n{extra}\nCore.lua\n")
    (path / "Core.lua").write_text(code)
    return path


def archive(tmp_path, members, name=None):
    path = tmp_path / (name or (uuid.uuid4().hex + ".zip"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for file, value in members.items():
            z.writestr(file, value)
    return path


def bundle(tmp_path, names, version="2.0", dependency=""):
    members = {}
    for name in names:
        members[name + "/" + name + ".toc"] = f"## Interface: 16001\n## Title: {name}\n## Version: {version}\n## Dependencies: {dependency}\nCore.lua\n"
        members[name + "/Core.lua"] = f"local version = '{version}'\n"
    return archive(tmp_path, members)


@pytest.fixture
def platform(tmp_path):
    game = tmp_path / "WoW/_forever_"
    (game / "Interface/AddOns").mkdir(parents=True)
    (game / "WTF/Account").mkdir(parents=True)
    (game.parent / ".build.info").write_text("Active!DEC:1|Version!STRING:0|Product!STRING:0\n1|1.60.1.70790|wowf\n")
    return AddonPlatform(Settings(mode="live", data_dir=tmp_path / "data", game_path=str(game), auto_sync=False, references_enabled=False))


def stage(platform, zip_path, key="custom"):
    return platform.stage(zip_path, package_id=key, provenance={"declaration": "workshop", "version": "2.0"})


def test_discovery_migrates_old_path_without_touching_it(platform):
    game = platform.game()
    beta = game.parent / "_cn_beta_"
    (beta / "WTF").mkdir(parents=True)
    (beta / "Interface/AddOns").mkdir(parents=True)
    (beta / "keep.txt").write_text("old")
    before = manifest(beta)
    assert game_flavors(game.parent) == [game]
    assert game_flavors(beta) == [game]
    assert manifest(beta) == before


def test_inventory_camelot_identity_groups_and_missing_dependency(platform):
    root = platform.game() / "Interface/AddOns"
    addon(root, "EllesmereUI", extra="## X-Curse-Project-ID: 1477613")
    addon(root, "EllesmereUIChat", dependencies="EllesmereUI", extra="## Group: EllesmereUI")
    details = addon(root, "Details", interface=120105)
    (details / "Details_Camelot.toc").write_text("## Interface: 16001\n## Version: forever\nCore.lua\n")
    addon(root, "LittleWigs", dependencies="BigWigs", extra="## X-Curse-Project-ID: 4383")
    before = manifest(platform.game())
    found = platform.inventory()
    assert found["client"]["build"] == "1.60.1.70790"
    assert found["module_count"] == 4
    assert len(next(g for g in found["packages"] if g["id"] == "ellesmere")["modules"]) == 2
    detail = next(g for g in found["packages"] if g["id"] == "local-Details")["modules"][0]
    assert detail["toc"] == "Details_Camelot.toc" and detail["compatibility"] == "toc_supported"
    assert any("LittleWigs 缺少依赖 BigWigs" in d["message"] for d in found["diagnostics"])
    assert manifest(platform.game()) == before
    addon(root, "BigWigs", extra="## X-Curse-Project-ID: 2382")
    assert not any("缺少依赖 BigWigs" in d["message"] for d in platform.inventory()["diagnostics"])


def test_source_binding_never_guesses_by_name(platform):
    addon(platform.game() / "Interface/AddOns", "EllesmereUI", version="9.7.7")
    group = platform.inventory()["packages"][0]
    assert group["id"] == "local-EllesmereUI"
    assert group["source"] == "unbound"


def test_multidir_apply_retire_and_rollback(platform, tmp_path):
    a = stage(platform, bundle(tmp_path, ["Main", "Child"]), "custom")
    assert a["can_apply"]
    first = platform.apply(a["id"])
    installed = platform.game() / "Interface/AddOns"
    addon(installed, "Other", code="keep = true")
    config = platform.game() / "WTF/unchanged.txt"
    config.write_text("never touch")
    before = manifest(installed)
    second = stage(platform, bundle(tmp_path, ["Main", "NewChild"], version="3.0"))
    assert {c["directory"]: c["action"] for c in second["changes"]} == {"Child": "remove", "Main": "update", "NewChild": "install"}
    applied = platform.apply(second["id"])
    assert not (installed / "Child").exists()
    assert (installed / "NewChild").is_dir()
    assert not list(installed.glob("*.backup*"))
    platform.rollback(applied["id"])
    assert manifest(installed) == before
    assert config.read_text() == "never touch"
    platform.rollback(first["id"])
    assert set(p.name for p in installed.iterdir()) == {"Other"}


def test_untracked_and_modified_addons_pause_updates(platform, tmp_path):
    root = platform.game() / "Interface/AddOns"
    path = addon(root, "Mine")
    blocked = stage(platform, bundle(tmp_path, ["Mine"]), "local-Mine")
    assert not blocked["can_apply"] and any("尚未接管" in b for b in blocked["blockers"])
    before = manifest(root)
    platform.adopt("local-Mine")
    assert manifest(root) == before
    plan = stage(platform, bundle(tmp_path, ["Mine"]), "local-Mine")
    assert plan["can_apply"]
    (path / "Core.lua").write_text("local custom = true")
    with pytest.raises(ValueError, match="发生变化|本地修改"):
        platform.apply(plan["id"])
    next_plan = stage(platform, bundle(tmp_path, ["Mine"]), "local-Mine")
    assert any("本地修改" in b for b in next_plan["blockers"])
    assert (path / "Core.lua").read_text() == "local custom = true"


@pytest.mark.parametrize("bad", ["../Escape/a.lua", "/tmp/Escape.lua", "X/../../a.lua", "X\\a.lua", "C:/evil.lua", "X/./a.lua"])
def test_zip_rejects_escaping_paths(platform, tmp_path, bad):
    before = manifest(platform.game())
    with pytest.raises(ValueError):
        stage(platform, archive(tmp_path, {bad: "x"}))
    assert manifest(platform.game()) == before


def test_zip_symlink_case_duplicate_bomb_and_reference(platform, tmp_path):
    zpath = tmp_path / "symlink.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        entry = zipfile.ZipInfo("X/Core.lua")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(entry, "/etc/passwd")
    with pytest.raises(ValueError, match="符号链接"):
        stage(platform, zpath)
    with pytest.raises(ValueError, match="大小写冲突"):
        stage(platform, archive(tmp_path, {"X/Core.lua": "x", "X/core.lua": "y"}))
    with pytest.raises(ValueError, match="压缩率异常"):
        stage(platform, archive(tmp_path, {"X/Core.lua": b"a" * (2 * 1024 * 1024)}))
    plan = stage(platform, archive(tmp_path, {"X/X.toc": "## Interface: 16001\n../outside.lua\n"}))
    assert not plan["can_apply"] and any("缺失" in b for b in plan["blockers"])
    xml = stage(platform, archive(tmp_path, {"X/X.toc": "## Interface: 16001\nLoad.xml\n", "X/Load.xml": '<Ui><Script file="../../outside.lua"/></Ui>'}))
    assert any("越界" in b for b in xml["blockers"])


def test_release_declaration_dependencies_and_version_fail_closed(platform, tmp_path):
    file = bundle(tmp_path, ["Unverified"])
    p = platform.stage(file)
    assert not p["can_apply"] and any("Forever 支持声明" in b for b in p["blockers"])
    p = stage(platform, bundle(tmp_path, ["Little"], dependency="BigWigs"))
    assert p["missing_dependencies"] == ["BigWigs"] and not p["can_apply"]
    p = stage(platform, archive(tmp_path, {"Retail/Retail.toc": "## Interface: 120105\nCore.lua", "Retail/Core.lua": "local x = 1"}))
    assert not p["can_apply"]


def test_failed_apply_restores_all_directories(platform, tmp_path, monkeypatch):
    first = stage(platform, bundle(tmp_path, ["A", "B"]))
    platform.apply(first["id"])
    root = platform.game() / "Interface/AddOns"
    before, state = manifest(root), platform.tx.state()
    second = stage(platform, bundle(tmp_path, ["A", "B"], version="3.0"))
    replace = os.replace
    failed = False
    def fail_once(source, target):
        nonlocal failed
        if Path(target) == root / "B" and "/new/" in str(source) and not failed:
            failed = True
            raise OSError("simulated disk failure")
        return replace(source, target)
    monkeypatch.setattr(os, "replace", fail_once)
    with pytest.raises(ValueError, match="已恢复原文件"):
        platform.apply(second["id"])
    assert manifest(root) == before and platform.tx.state() == state
    assert platform.history()[0]["status"] == "recovered"


def test_interruption_journal_survives_restart(platform, tmp_path, monkeypatch):
    original = stage(platform, bundle(tmp_path, ["A", "B"]))
    platform.apply(original["id"])
    root = platform.game() / "Interface/AddOns"
    before, state = manifest(root), platform.tx.state()
    second = stage(platform, bundle(tmp_path, ["A", "B"], version="3.0"))
    replace = os.replace
    def interrupt(source, target):
        if Path(target) == root / "B" and "/new/" in str(source):
            raise KeyboardInterrupt("power loss simulation")
        return replace(source, target)
    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        platform.apply(second["id"])
    monkeypatch.setattr(os, "replace", replace)
    restarted = AddonPlatform(platform.settings)
    pending = restarted.tx.pending()
    assert len(pending) == 1
    restarted.recover(pending[0]["id"])
    assert manifest(root) == before and restarted.tx.state() == state


def test_game_running_and_shared_lock_block_writes(platform, tmp_path, monkeypatch):
    plan = stage(platform, bundle(tmp_path, ["A"]))
    import backend.platform_io as file_io
    monkeypatch.setattr(file_io, "game_running", lambda: True)
    with pytest.raises(ValueError, match="游戏仍在运行"):
        platform.apply(plan["id"])
    monkeypatch.setattr(file_io, "game_running", lambda: False)
    with operation_lock(platform.root):
        with pytest.raises(ValueError, match="另一个插件操作"):
            platform.apply(plan["id"])


def test_rollback_preserves_later_unrelated_adoption(platform, tmp_path):
    plan = stage(platform, bundle(tmp_path, ["A"]))
    operation = platform.apply(plan["id"])
    addon(platform.game() / "Interface/AddOns", "Other")
    platform.adopt("local-Other")
    baseline = platform.tx.state()["installs"]["local-Other"]
    platform.rollback(operation["id"])
    assert platform.tx.state()["installs"]["local-Other"] == baseline
    assert (platform.game() / "Interface/AddOns/Other/Core.lua").is_file()


def test_multi_flavor_author_modules_are_inactive_not_incompatible(platform, tmp_path):
    zip_path = archive(tmp_path, {"Core/Core.toc": "## Interface: 16001\nCore.lua", "Core/Core.lua": "local x=1",
        "Retail/Retail.toc": "## Interface: 120105\n## AllowLoadGameType: standard\nCore.lua", "Retail/Core.lua": "local x=1"})
    plan = stage(platform, zip_path)
    assert plan["can_apply"]
    assert next(m for m in plan["toc"] if m["directory"] == "Retail")["compatibility"] == "inactive_flavor"
    inactive_only = stage(platform, archive(tmp_path, {"Retail/Retail.toc": "## Interface: 120105\n## AllowLoadGameType: standard\nCore.lua", "Retail/Core.lua": "local x=1"}))
    assert not inactive_only["can_apply"] and any("活动模块" in b for b in inactive_only["blockers"])


def test_toc_loader_filename_tokens_are_checked_for_chinese_forever(platform, tmp_path):
    plan = stage(platform, archive(tmp_path, {"Token/Token.toc": "## Interface: 16001\nInit_[Game].lua\nLocales/[TextLocale].lua",
        "Token/Init_Camelot.lua": "local x = true", "Token/Locales/zhCN.lua": "local locale = 'zhCN'"}))
    assert plan["can_apply"]


def setup_profiles(platform):
    addons = platform.game() / "Interface/AddOns"
    addon(addons, "EllesmereUI", extra="## X-Curse-Project-ID: 1477613")
    addon(addons, "EllesmereUIChat", dependencies="EllesmereUI", extra="## Group: EllesmereUI")
    addon(addons, "EllesmereUICooldownManager", dependencies="EllesmereUI", extra="## Group: EllesmereUI")
    addon(addons, "ForeverUI")
    addon(addons, "Other")
    character = platform.game() / "WTF/Account/private/Realm/Character"
    character.mkdir(parents=True)
    (character / "AddOns.txt").write_bytes(b"\xef\xbb\xbfOther: disabled\r\nBlizzard_ObjectiveTracker: enabled\r\nEllesmereUIChat: enabled\r\n")
    saved = character.parent.parent / "SavedVariables"
    saved.mkdir()
    (saved / "EllesmereUI.lua").write_text("EllesmereUIDB = {original = true}")
    (saved / "ForeverUI.lua").write_text("ForeverUIDB = {original = true}")
    (saved / "Other.lua").write_text("keep")
    return Profiles(platform), character, saved


def test_profiles_roundtrip_preserves_independent_configs(platform):
    profiles, character, saved = setup_profiles(platform)
    ident = profiles.characters()[0]["id"]
    originals = manifest(saved)
    before_other = (saved / "Other.lua").read_bytes()
    eui = profiles.backup_config(ident, "EllesmereUI")
    fui = profiles.backup_config(ident, "ForeverUI")
    for combo in ["ForeverUI", "EllesmereUI", "ForeverUI"]:
        plan = profiles.prepare_switch(ident, combo)
        profiles.apply_switch(plan["id"])
        raw = (character / "AddOns.txt").read_bytes()
        _, _, states, _ = parse_addon_state(raw)
        assert states["Other"] is False and states["Blizzard_ObjectiveTracker"] is True
        assert states["ForeverUI"] is (combo == "ForeverUI")
        assert states["EllesmereUIChat"] is (combo == "EllesmereUI")
        assert b"Other: disabled\r\nBlizzard_ObjectiveTracker: enabled\r\n" in raw
        assert raw.startswith(b"\xef\xbb\xbf")
    assert manifest(saved) == originals
    (saved / "EllesmereUI.lua").write_text("modified")
    (saved / "ForeverUI.lua").write_text("another-layout")
    profiles.restore_config(eui["id"], ident)
    assert (saved / "EllesmereUI.lua").read_text().endswith("{original = true}")
    assert (saved / "ForeverUI.lua").read_text() == "another-layout"
    profiles.restore_config(fui["id"], ident)
    assert manifest(saved) == originals
    assert (saved / "Other.lua").read_bytes() == before_other


@pytest.mark.parametrize("raw", [b"Unknown=1\n", b"A: true\n", b"A: enabled\nA: disabled\n", b"\xff\xfe", b""])
def test_unknown_client_state_never_written(platform, raw):
    profiles, character, _ = setup_profiles(platform)
    path = character / "AddOns.txt"
    path.write_bytes(raw)
    ident = profiles.characters()[0]["id"]
    with pytest.raises(ValueError):
        profiles.prepare_switch(ident, "ForeverUI")
    assert path.read_bytes() == raw


def test_workshop_compile_only_hash_guard_pack_and_plan(platform):
    workshop = Workshop(platform)
    project = workshop.create("Hello", "a natural-language idea")
    file = "addons/Hello/Core.lua"
    before = manifest(platform.game())
    original = workshop.read(project["id"], file)
    # Executing this Lua would raise. Successful validation proves compile-only.
    content = 'error("MUST NEVER EXECUTE")\n'
    revision = workshop.write(project["id"], file, content, original["sha256"])
    with pytest.raises(ValueError, match="文件已变化"):
        workshop.write(project["id"], file, "x=1", original["sha256"])
    assert workshop.validate(project["id"])["passed"]
    assert not workshop.validate(project["id"])["executed"]
    assert "MUST NEVER EXECUTE" in workshop.diff(project["id"])["diff"]
    packed = workshop.pack(project["id"])
    plan = workshop.install_plan(packed["id"])
    assert plan["can_apply"]
    assert manifest(platform.game()) == before
    platform.apply(plan["id"])
    managed = next(g for g in platform.inventory()["packages"] if g["id"] == "local-Hello")
    assert managed["source"] == "workshop" and managed["update_status"] == "local_only"
    workshop.revert(project["id"], revision["id"])
    assert workshop.read(project["id"], file)["content"] == original["content"]
    original = workshop.read(project["id"], file)
    workshop.write(project["id"], file, "local = invalid", original["sha256"])
    assert not workshop.validate(project["id"])["passed"]
    with pytest.raises(ValueError, match="检查未通过"):
        workshop.pack(project["id"])


def test_workshop_rejects_path_traversal_and_links(platform):
    workshop = Workshop(platform)
    project = workshop.create("Bounded")
    for name in ["../oops.lua", "/tmp/oops.lua", "addons/Bounded/../../../oops.lua", "project.json", "addons/evil.py"]:
        with pytest.raises(ValueError):
            workshop.write(project["id"], name, "x")
    (workshop.root / project["id"] / "addons/link").symlink_to(platform.game(), target_is_directory=True)
    with pytest.raises(ValueError):
        workshop.write(project["id"], "addons/link/oops.lua", "x")


def test_new_http_flow_upload_has_separate_limit(platform, tmp_path):
    app = create_app(platform.settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for route in ("/", "/profiles", "/workshop", "/overview"):
            assert client.get(route).status_code == 200
        project = client.post("/api/workshop/projects", json={"name": "HTTPExample"}).json()
        packed = client.post(f"/api/workshop/projects/{project['id']}/pack").json()
        plan = client.post(f"/api/workshop/exports/{packed['id']}/plan").json()
        assert client.get('/addons/plans/' + plan['id']).status_code == 200
        assert client.post('/api/addons/plans/' + plan['id'] + '/apply').json()["status"] == "applied"
        # >64 KiB, incompressible ZIP payload: accepted by the separate upload stream.
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as z:
            z.writestr("Imported/Imported.toc", "## Interface: 16001\nCore.lua")
            z.writestr("Imported/Core.lua", "local v=1")
            z.writestr("Imported/media.bin", os.urandom(100000))
        uploaded = client.post("/api/addons/import", files={"file": ("example.zip", archive_buffer.getvalue(), "application/zip")},
                               data={"source_url": "https://www.curseforge.com/wow/addons/example/files/123", "forever_confirmed": "true"})
        assert uploaded.status_code == 200 and uploaded.json()["can_apply"]
        assert uploaded.json()["provenance"]["declaration"] == "user_confirmed_curseforge"
        assert client.post("/api/workshop/projects", content=b"x" * 65537).status_code == 413
        assert client.post("/api/addons/import", headers={"Origin": "https://evil.example"}).status_code == 403


def test_author_manifest_requires_matching_forever_asset(monkeypatch):
    import backend.addon_sources as sources
    base = "https://github.com/EllesmereGaming/EllesmereUI/releases/download/v1/"
    release = {"assets": [{"name": "release.json", "browser_download_url": base + "release.json"},
                           {"name": "EUI.zip", "browser_download_url": base + "EUI.zip", "size": 100}], "tag_name": "v1"}
    metadata = {"releases": [{"version": "1", "filename": "EUI.zip", "metadata": [{"flavor": "forever", "interface": 16001}]}]}
    monkeypatch.setattr(sources, "fetch", lambda url, limit: json.dumps(release if "api.github.com" in url else metadata).encode())
    assert sources.author_release("ellesmere")["filename"] == "EUI.zip"
    metadata["releases"][0]["metadata"][0]["flavor"] = "mainline"
    with pytest.raises(ValueError, match="Forever"):
        sources.author_release("ellesmere")
    assert sources.CurseForgeAdapter().status["status"] == "website_required"


def test_official_mcp_client_roundtrip_and_cross_process_lock(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    root = Path(__file__).resolve().parents[1]
    async def run():
        server = StdioServerParameters(command=sys.executable, args=[str(root / "scripts/mcp_serve.py"), "--mode", "mock", "--data-dir", str(tmp_path)])
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                names = {t.name for t in (await client.list_tools()).tools}
                assert {"create_project", "write_file", "validate_project", "package_project", "create_install_plan"} <= names
                assert not {"apply", "execute_lua", "install_addon"} & names
                async def call(tool, arguments):
                    result = await client.call_tool(tool, arguments)
                    assert not result.isError, result
                    return result.structuredContent
                created = await call("create_project", {"name": "MCPExample", "description": "show a reminder at login"})
                ident = created["id"]
                file = await call("read_file", {"project_id": ident, "path": "addons/MCPExample/Core.lua"})
                await call("write_file", {"project_id": ident, "path": file["path"], "content": "error('compile only')", "expected_sha256": file["sha256"]})
                assert (await call("validate_project", {"project_id": ident}))["passed"]
                packed = await call("package_project", {"project_id": ident})
                plan = await call("create_install_plan", {"export_id": packed["id"]})
                assert plan["can_apply"]
                bad = await client.call_tool("write_file", {"project_id": ident, "path": "../oops.lua", "content": "oops"})
                assert bad.isError
                with operation_lock(tmp_path / "platform/mock"):
                    locked = await client.call_tool("create_project", {"name": "Blocked"})
                    assert locked.isError
                assert not (tmp_path / "platform/mock/game/_forever_/Interface/AddOns/MCPExample").exists()
    asyncio.run(run())


def fake_game_application(platform, monkeypatch):
    app = platform.game() / "World of Warcraft.app"
    executable = app / "Contents/MacOS/World of Warcraft"
    executable.parent.mkdir(parents=True)
    executable.write_text("test stub - never executed")
    executable.chmod(0o755)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.blizzard.worldofwarcraft", "CFBundleShortVersionString": "1.60.1"}))
    battle = platform.settings.data_dir / "Battle.net.app"
    executable = battle / "Contents/MacOS/Battle.net"
    executable.parent.mkdir(parents=True)
    executable.write_text("test stub - never executed")
    executable.chmod(0o755)
    (battle / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "net.battle.app"}))
    import backend.addon_platform as module
    monkeypatch.setattr(module, "BATTLE_NET_APPS", (battle,))
    return battle


def test_launch_game_hands_off_to_battlenet_and_keeps_addon_updates_available(platform, tmp_path, monkeypatch):
    app = fake_game_application(platform, monkeypatch)
    plan = stage(platform, bundle(tmp_path, ["A"]))
    import backend.addon_platform as module
    calls, run = [], module.subprocess.run
    def launch(command, **kwargs):
        if command[0] == "/usr/bin/open":
            calls.append(command)
            return module.subprocess.CompletedProcess(command, 0)
        return run(command, **kwargs)
    monkeypatch.setattr(module.subprocess, "run", launch)
    assert platform.launch_status()["available"]
    assert platform.launch_game()["status"] == "battlenet_opened"
    assert calls == [["/usr/bin/open", str(app)]]
    assert all("World of Warcraft.app" not in value for value in calls[0])
    assert not platform.launch_status()["starting"]
    assert platform.review(plan["id"])["can_apply"]
    assert platform.apply(plan["id"])["status"] == "applied"


def test_launch_game_rejects_demo_missing_client_busy_lock_and_pending_recovery(platform, monkeypatch):
    assert platform.launch_status()["available"] is False
    with pytest.raises(ValueError, match="完整的无限"):
        platform.launch_game()
    fake_game_application(platform, monkeypatch)
    with platform.lock():
        with pytest.raises(ValueError, match="另一个插件操作"):
            platform.launch_game()
    monkeypatch.setattr(platform.tx, "pending", lambda: [{"id": "interrupted"}])
    with pytest.raises(ValueError, match="等待恢复"):
        platform.launch_game()
    demo = AddonPlatform(Settings(mode="mock", data_dir=platform.settings.data_dir / "demo"))
    with pytest.raises(ValueError, match="演示模式"):
        demo.launch_game()


def test_launch_game_os_failure_allows_retry_and_api_is_same_origin_only(platform, monkeypatch):
    fake_game_application(platform, monkeypatch)
    import backend.addon_platform as module
    run = module.subprocess.run
    def fail(command, **kwargs):
        if command[0] == "/usr/bin/open":
            raise OSError("simulated LaunchServices failure")
        return run(command, **kwargs)
    monkeypatch.setattr(module.subprocess, "run", fail)
    with TestClient(create_app(platform.settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/addons/game-status").json()["available"]
        assert client.get("/api/addons/launch-game").status_code == 405
        assert client.post("/api/addons/launch-game", headers={"Origin": "https://evil.example"}).status_code == 403
        failed = client.post("/api/addons/launch-game")
        assert failed.status_code == 400 and "未能打开战网" in failed.json()["detail"]
        assert not client.get("/api/addons/game-status").json()["starting"]


def test_missing_battlenet_never_falls_back_to_direct_game(platform, monkeypatch):
    fake_game_application(platform, monkeypatch)
    import backend.addon_platform as module
    monkeypatch.setattr(module, "BATTLE_NET_APPS", ())
    assert not platform.launch_status()["available"]
    with pytest.raises(ValueError, match="未找到战网"):
        platform.launch_game()
