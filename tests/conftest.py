from pathlib import Path
import json

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def raw_snapshot():
    return json.loads((ROOT / "fixtures/mock_snapshot.json").read_text())


@pytest.fixture
def live_raw(raw_snapshot):
    raw_snapshot["data_mode"] = "live"
    return raw_snapshot


def savedvariables(snapshot):
    # JSON quoting is also a valid Lua quoted string for this fixture's literal data.
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    return 'ForeverAICharDB = { ["schema_version"] = 1, ["snapshot_json"] = ' + json.dumps(encoded, ensure_ascii=False) + ', }\n'
