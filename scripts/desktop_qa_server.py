"""Explicit isolated desktop QA. Never starts from the normal application entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def create_fixture(root):
    from backend.config import Settings
    from backend.models import Snapshot
    from backend.web import create_app
    import backend.addon_platform as platform_module
    import backend.platform_io as io_module

    game = root / "WoW/_forever_"
    addons = game / "Interface/AddOns"
    addons.mkdir(parents=True)
    (game / "WTF").mkdir()
    (game.parent / ".build.info").write_text("Active!DEC:1|Version!STRING:0|Product!STRING:0\n1|1.60.1.70790|wowf\n")
    packages = [
        ("DBM-Core", "Deadly Boss Mods", "3358", "", "MysticalOS"),
        ("BigWigs", "BigWigs", "2382", "", "BigWigsMods"),
        ("LittleWigs", "LittleWigs", "4383", "BigWigs", "BigWigsMods"),
        ("EllesmereUI", "EllesmereUI", "1477613", "", "Ellesmere"),
        ("Details", "Details!", "61284", "", "Terciob"),
        ("BagBrother", "BagBrother", "", "", "Jaliborc"),
        ("DBM-VPVEM", "VEM Voicepack", "", "DBM-Core", "Iceoven"),
        ("ForeverAI", "ForeverAI", "", "", "Forever"),
        ("ForeverUI", "ForeverUI", "", "", "Forever"),
    ]
    for directory, title, curse, deps, author in packages:
        path = addons / directory
        path.mkdir()
        (path / (directory + ".toc")).write_text(f"## Interface: 16001\n## Title: {title}\n## Author: {author}\n## Version: 1.0\n## X-Curse-Project-ID: {curse}\n## Dependencies: {deps}\nCore.lua\n")
        (path / "Core.lua").write_text("local isolated_fixture = true\n")
    # The process guard is disabled ONLY inside this explicitly invoked QA process,
    # whose client and data roots were created above in a new temporary directory.
    io_module.game_running = lambda: False
    platform_module.game_running = lambda: False
    app = create_app(Settings(mode="mock", data_dir=root / "data", game_path=str(game), auto_sync=False, ai_provider="rules"))
    service, platform = app.state.service, app.state.platform
    service.refs.addon_catalog_path = None
    raw = json.loads((ROOT / "fixtures/mock_snapshot.json").read_text())
    raw["captured_at"] = int(time.time())
    raw["client"]["build"] = "70790"
    snapshot = Snapshot.model_validate(raw)
    service.db.save_snapshot(snapshot)
    second = snapshot.model_copy(update={"character": snapshot.character.model_copy(update={
        "name": "战士（演示）", "class_token": "WARRIOR", "race_token": "Orc", "specialization": "武器（演示设定）"})})
    service.db.save_snapshot(second)
    service.select_character(snapshot.character.identity)
    for character in (snapshot.character, second.character):
        folder = game / "WTF/Account/isolated" / character.realm / character.name
        folder.mkdir(parents=True)
        (folder / "AddOns.txt").write_text("".join(f"{p[0]}: enabled\n" for p in packages))
    for group in platform.inventory()["packages"]:
        platform.adopt(group["id"])
    state = platform.tx.state()
    state["updates"] = {
        "dbm": {"status": "release_differs", "installed_version": "1.0", "checked_at": time.time(),
                "release": {"version": "2.0", "published_at": "2026-11-06", "changelog": "隔离验收的版本变化记录。"}},
        "bigwigs": {"status": "unknown", "installed_version": "1.0", "note": "隔离验收：来源暂时不可用"},
    }
    platform.tx.save_state(state)
    archive = root / "DesktopFixture.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("DesktopFixture/DesktopFixture.toc", "## Interface: 16001\n## Version: 1.0\nCore.lua\n")
        stream.writestr("DesktopFixture/Core.lua", "local desktop_qa = true\n")
        stream.writestr("release.json", json.dumps({"releases": [{"filename": archive.name, "version": "1.0", "metadata": [{"flavor": "forever", "interface": 16001}]}]}))
    return app, archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18774)
    parser.add_argument("--sync-references", action="store_true")
    args = parser.parse_args()
    import uvicorn
    output = ROOT / "outputs/v04"
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="isolated-", dir=output))
    app, archive = create_fixture(root)
    if args.sync_references:
        report = asyncio.run(app.state.service.refs.sync())
        print("REFERENCE_FIXTURE", report["items"], report["recipes"], flush=True)
    (output / "qa-server.json").write_text(json.dumps({"data": str(root), "zip": str(archive), "port": args.port}, indent=2))
    print("ISOLATED_DESKTOP_QA", root, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
