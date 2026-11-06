from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from backend.config import Settings
from backend.service import gold_to_copper
from backend.web import create_app
from conftest import savedvariables


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(mode="mock", data_dir=tmp_path)), base_url="http://127.0.0.1:18761") as client:
        yield client


def test_mock_api_complete_workflow(client):
    assert client.get("/api/health").json()["mode"] == "mock"
    snapshot = client.get("/api/snapshots/latest").json()["snapshot"]
    assert snapshot["character"]["class_token"] == "MAGE"
    comparison = client.post("/api/equipment/compare", json={"slot": 1, "candidate_kind": "bag", "bag_index": 0})
    assert comparison.status_code == 200
    assert comparison.json()["deltas"][0]["delta"] == 4
    assert client.post("/api/prices", json={"item_id": 1900000101, "copper": 100}).status_code == 200
    quote = client.post("/api/economy/quote", json={"recipe_id": 1900000201, "sale_unit_copper": 1000, "fee_percent": "5"})
    assert quote.json()["profit_copper"] == 600
    advice = client.post("/api/ai/plan").json()
    assert advice["engine"] == "mock-rules"
    assert len(advice["advice"]["actions"]) == 3
    assert client.post("/api/ai/ask", json={"question": "我现在应该刷什么装备？"}).status_code == 200
    task = client.post("/api/tasks", json={"title": "检查消耗品", "note": "用户手工核实"}).json()["id"]
    assert client.patch(f"/api/tasks/{task}", json={"done": True}).json()["done"] is True
    assert next(t for t in client.get("/api/tasks").json()["tasks"] if t["id"] == task)["done"] == 1
    assert client.delete(f"/api/tasks/{task}").status_code == 200
    assert client.delete(f"/api/tasks/{task}").status_code == 404
    assert client.post("/api/snapshots/import", json={"source_id": "not-a-source"}).status_code == 400


def test_local_origin_and_streaming_limits(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/ai/plan", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/ai/plan", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/ai/ask", content=b"x" * 65537, headers={"Content-Length": "0"}).status_code == 413
    assert client.get("/api/health").headers["X-Content-Type-Options"] == "nosniff"


def test_bad_inputs_do_not_change_data(client):
    before = client.get("/api/prices").json()
    assert client.post("/api/prices", json={"item_id": 1, "copper": -1}).status_code == 422
    assert client.post("/api/prices", json={"item_id": 1, "copper": True}).status_code == 422
    assert client.post("/api/ai/ask", json={"question": "x" * 2001}).status_code == 422
    assert client.post("/api/ai/ask", json={"question": "   "}).status_code == 400
    assert client.post("/api/economy/quote", json={"recipe_id": 1900000201, "fee_percent": "nan"}).status_code == 400
    assert client.get("/api/prices").json() == before
    assert client.post("/api/references/mcp", json={"tool": "stage", "arguments": {}}).status_code == 400


def test_live_import_from_windows_shaped_tree(tmp_path, live_raw):
    # The directory contract is shared by macOS and Windows; this is not Windows OS UAT.
    char = live_raw["character"]
    root = tmp_path / "World of Warcraft"
    flavor = root / "_cn_beta_"
    folder = flavor / "WTF" / "Account" / "account-never-exposed" / char["realm"] / char["name"] / "SavedVariables"
    folder.mkdir(parents=True)
    (flavor / "Interface").mkdir()
    (folder / "ForeverAI.lua").write_text(savedvariables(live_raw))
    app = create_app(Settings(mode="live", data_dir=tmp_path / "service", game_path=str(root), auto_sync=False))
    with TestClient(app, base_url="http://127.0.0.1:18761") as client:
        assert client.get("/api/snapshots/latest").status_code == 400
        sources = client.get("/api/sources")
        assert "account-never-exposed" not in sources.text
        ident = sources.json()["sources"][0]["id"]
        imported = client.post("/api/snapshots/import", json={"source_id": ident})
        assert imported.status_code == 200
        assert client.post("/api/snapshots/import", json={"source_id": ident}).json()["id"] == imported.json()["id"]
        assert client.get("/api/snapshots/latest").json()["snapshot"]["data_mode"] == "live"
        assert client.post("/api/ai/plan").json()["engine"] == "rules-no-api-key"
        assert client.post("/api/settings/path", json={"game_path": str(tmp_path / "does-not-exist")}).status_code == 400


def test_gold_precision():
    assert gold_to_copper("0.0001") == 1
    assert gold_to_copper("1.2345") == 12345
    assert gold_to_copper("", optional=True) is None
    for value in ("0.00001", "-1", "NaN", "Infinity", "abc"):
        with pytest.raises(ValueError):
            gold_to_copper(value)


def test_installer_preserves_existing(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("installer", Path(__file__).resolve().parents[1] / "scripts/install_addons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    flavor = tmp_path / "_cn_beta_"
    (flavor / "WTF").mkdir(parents=True)
    old = flavor / "Interface/AddOns/ForeverAI"
    old.mkdir(parents=True)
    (old / "user-file.txt").write_text("preserve")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        module.install(tmp_path, apply=True)
    assert (old / "user-file.txt").read_text() == "preserve"


def test_installer_preflights_both_addons(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("installer", Path(__file__).resolve().parents[1] / "scripts/install_addons.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    flavor = tmp_path / "_cn_beta_"
    (flavor / "WTF").mkdir(parents=True)
    existing = flavor / "Interface/AddOns/ForeverUI"
    existing.mkdir(parents=True)
    (existing / "user-file.txt").write_text("preserve")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        module.install(tmp_path, apply=True)
    assert not (existing.parent / "ForeverAI").exists()
    assert (existing / "user-file.txt").read_text() == "preserve"
