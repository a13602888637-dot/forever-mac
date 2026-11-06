import json
import time

import pytest
from pydantic import ValidationError

from backend.models import Snapshot
from backend.paths import discover, import_source
from backend.savedvariables import ImportError, MAX_FILE_BYTES, parse_savedvariables
from conftest import savedvariables


def test_unicode_round_trip(live_raw):
    live_raw["character"]["name"] = '亡灵"法师'
    text = '-- Saved by game\n' + savedvariables(live_raw)
    assert parse_savedvariables(text).character.name == '亡灵"法师'


@pytest.mark.parametrize("payload", [
    'ForeverAICharDB = (function() return {} end)()',
    'ForeverAICharDB = { schema_version=1 }; os.execute("bad")',
    'ForeverAICharDB = { snapshot_json = loadstring("bad")() }',
    'ForeverAICharDB = { a=1, a=2 }',
    'ForeverAICharDB = { [true]=1 }',
    'ForeverAICharDB = { schema_version=1, snapshot_json="unterminated',
    'OtherDB = {}',
])
def test_code_and_bad_literals_are_rejected(payload):
    with pytest.raises(ImportError):
        parse_savedvariables(payload)


def test_oversize_and_depth():
    with pytest.raises(ImportError):
        parse_savedvariables(' ' * (MAX_FILE_BYTES + 1))
    with pytest.raises(ImportError):
        parse_savedvariables('ForeverAICharDB = ' + '{' * 40 + '}' * 40)


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(schema_version=True),
    lambda s: s.update(schema_version=2),
    lambda s: s.update(captured_at=int(time.time()) + 301),
    lambda s: s["character"].update(level="32"),
    lambda s: s["character"].update(name="../../escape"),
    lambda s: s["equipment"][0]["stats"].update(FAKE="12"),
    lambda s: s.update(unavailable={}),
])
def test_schema_validation(raw_snapshot, mutation):
    mutation(raw_snapshot)
    with pytest.raises(ValidationError):
        Snapshot.model_validate(raw_snapshot)


def test_mock_not_accepted_as_live(raw_snapshot):
    with pytest.raises(ImportError, match="Mock"):
        parse_savedvariables(savedvariables(raw_snapshot))


def test_discovery_and_identity(tmp_path, live_raw):
    char = live_raw["character"]
    flavor = tmp_path / "_cn_beta_"
    folder = flavor / "WTF" / "Account" / "private-account" / char["realm"] / char["name"] / "SavedVariables"
    folder.mkdir(parents=True)
    (flavor / "Interface").mkdir()
    path = folder / "ForeverAI.lua"
    path.write_text(savedvariables(live_raw))
    sources = discover(tmp_path)
    assert len(sources) == 1
    snapshot = import_source(sources[0].id, tmp_path)
    assert snapshot.character.identity == f'{char["realm"]}:{char["name"]}'
    live_raw["character"]["name"] = "另一个角色"
    path.write_text(savedvariables(live_raw))
    with pytest.raises(ImportError, match="身份"):
        import_source(sources[0].id, tmp_path)


def test_symlink_escape_is_not_discovered(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "ForeverAI.lua").write_text("ForeverAICharDB={}")
    folder = tmp_path / "_cn_beta_" / "WTF/Account/a/r/c"
    folder.mkdir(parents=True)
    (folder / "SavedVariables").symlink_to(outside, target_is_directory=True)
    assert discover(tmp_path) == []


def test_duplicate_json_keys_rejected(live_raw):
    text = savedvariables(live_raw)
    # Add a duplicate inside the serialized JSON, not in the outer Lua table.
    inner = json.dumps(live_raw, ensure_ascii=False)
    inner = '{"schema_version":1,' + inner[1:]
    text = 'ForeverAICharDB={schema_version=1,snapshot_json=' + json.dumps(inner, ensure_ascii=False) + '}'
    with pytest.raises(ImportError, match="重复"):
        parse_savedvariables(text)
