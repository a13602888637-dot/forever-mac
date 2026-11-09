import asyncio
import json

import pytest
import httpx
from lupa.lua51 import LuaRuntime

from backend.catalog_export import export_catalog
from backend.db import Database
from backend.references import References
from conftest import ROOT
from test_addon import runtime
from test_services import reference_transport


def seed(db, item_name='测试"物品\n下一行'):
    db.cache_references({
        "manifest": {"build": "1.60.1.70450", "built_at": "2026-10-26", "product": "wow_cn_beta"},
        "items": {"100": {"id": 100, "name": item_name, "stats": [[5, 8]], "desc": None}},
        "recipes": [{"id": 200, "name": "测试配方", "spell": 300, "reagents": [[100, 2]]}],
    }, "1.60.1.70450", "2026-10-26")


def test_catalog_lua_is_data_only_and_preserves_null(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    malicious = '"; _G.BAD=true; --\n中文\\123'
    seed(db, malicious)
    path = tmp_path / "CatalogData.lua"
    report = export_catalog(db, path)
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("ForeverAI={}")
    lua.execute(path.read_text())
    assert lua.globals().BAD is None
    assert lua.eval("ForeverAI.CatalogData.items[100].name") == malicious
    assert lua.eval("ForeverAI.CatalogData.items[100].desc == ForeverAI.CatalogNull") is True
    assert report["item_count"] == report["recipe_count"] == 1


def test_catalog_mixed_versions_preserve_existing_file(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    seed(db)
    path = tmp_path / "CatalogData.lua"
    export_catalog(db, path)
    old = path.read_bytes()
    db.cache_references({"recipes": [{"id": 200, "name": "其他版本"}]}, "1.60.2.99999", "later")
    with pytest.raises(ValueError, match="版本不一致"):
        export_catalog(db, path)
    assert path.read_bytes() == old


def test_full_bundled_catalog_counts_lookup_and_snapshot_separation():
    lua = runtime()
    lua.execute((ROOT / "addons/ForeverAI/CatalogData.lua").read_text())
    lua.execute((ROOT / "addons/ForeverAI/Catalog.lua").read_text())
    manifest = json.loads((ROOT / "addons/ForeverAI/CatalogManifest.json").read_text())
    count = lua.eval("function(t) local n=0; for _ in pairs(t) do n=n+1 end; return n end")
    data = lua.globals().ForeverAI.CatalogData
    assert count(data["items"]) == manifest["item_count"]
    assert count(data["recipes"]) == manifest["recipe_count"]
    assert count(data["items"]) >= 15496 and count(data["recipes"]) >= 2594
    assert lua.globals().ForeverAI.FindCatalog("items", "10001", 10)[1].name == "黑色魔纹长袍"
    # The bundled public dataset can advance independently of the older runtime fixture.
    version, build = manifest["build"].rsplit(".", 1)
    lua.execute("GetBuildInfo = function() return " + json.dumps(version) + ", " + json.dumps(build) + ", \"catalog fixture\", 16001 end")
    assert lua.globals().ForeverAI.CatalogStatus().matches is True
    lua.execute('GetBuildInfo = function() return "1.0.0", "1", "older", 16001 end')
    assert lua.globals().ForeverAI.CatalogStatus().matches is False
    assert lua.globals().ForeverAI.Export() is True
    raw = lua.globals().ForeverAICharDB.snapshot_json
    assert len(raw) < 50000
    assert "黑色魔纹长袍" not in raw


def test_reference_sync_also_updates_addon_catalog(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    path = tmp_path / "addon/CatalogData.lua"
    refs = References(db, transport=reference_transport(), addon_catalog_path=path)
    report = asyncio.run(refs.sync())
    assert path.exists()
    assert report["addon_catalog"]["item_count"] == 1
    assert report["addon_catalog"]["recipe_count"] == 1


def test_partial_remote_catalog_preserves_cache_and_addon(tmp_path):
    db = Database(tmp_path / "db.sqlite3")
    seed(db)
    path = tmp_path / "CatalogData.lua"
    export_catalog(db, path)
    previous = path.read_bytes()
    data = {
        "manifest": {"build": "1.60.1.70450", "built_at": "2026-10-26", "product": "wow_cn_beta", "counts": {"items": 2, "recipes": 1}},
        "items": {"100": {"id": 100, "name": "部分数据"}},
        "recipes": [{"id": 200, "name": "配方"}],
        "professions": [{"id": 197}], "stat_names": {"5": "智力"},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=data[request.url.path.rsplit("/", 1)[-1].removesuffix(".json")]))
    refs = References(db, transport=transport, addon_catalog_path=path)
    with pytest.raises(ValueError, match="数量"):
        asyncio.run(refs.sync())
    assert path.read_bytes() == previous
    assert db.reference("items")["payload"]["100"]["name"] != "部分数据"
