import json
import time

import pytest
from pydantic import ValidationError

from backend.models import Snapshot
from backend.paths import discover, import_source
from backend.savedvariables import ImportError, MAX_FILE_BYTES, parse_savedvariables, read_snapshot
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


def forever_save(tmp_path, live_raw, folder_name="测试名-甲", realm="97"):
    live_raw["character"].update(name="测试名", realm="CN Test Realm PvE")
    live_raw["client"].update(version="1.60.1", interface=16001)
    folder = tmp_path / "_forever_/WTF/Account/local-account" / realm / folder_name / "SavedVariables"
    folder.mkdir(parents=True)
    path = folder / "ForeverAI.lua"
    path.write_text(savedvariables(live_raw))
    return path


def test_forever_numeric_realm_and_surname_layout(tmp_path, live_raw):
    path = forever_save(tmp_path, live_raw)
    snapshot = read_snapshot(path, "测试名-甲", "97")
    assert snapshot.character.name == "测试名"
    assert snapshot.character.realm == "CN Test Realm PvE"
    assert snapshot.character.display_name == "测试名 甲"
    assert snapshot.character.identity == "97:测试名-甲"
    # Derived location metadata survives database serialization without becoming
    # a required game API field in older snapshots.
    assert Snapshot.model_validate_json(snapshot.model_dump_json()).character.identity == snapshot.character.identity
    from backend.ai import evidence_context
    context = json.dumps(evidence_context(snapshot, "id"), ensure_ascii=False)
    assert "测试名" not in context and "CN Test Realm PvE" not in context
    assert "storage_name" not in context and "storage_realm_id" not in context


@pytest.mark.parametrize("other", ["97/测试名-乙", "98/测试名-乙", "98/测试名-甲"])
def test_forever_short_first_name_is_rejected_when_ambiguous(tmp_path, live_raw, other):
    path = forever_save(tmp_path, live_raw)
    (path.parents[3] / other / "SavedVariables").mkdir(parents=True)
    with pytest.raises(ImportError, match="同名不同姓"):
        read_snapshot(path, "测试名-甲", "97")


def test_forever_full_name_keeps_surnames_separate(tmp_path, live_raw):
    path = forever_save(tmp_path, live_raw)
    (path.parents[2] / "测试名-乙/SavedVariables").mkdir(parents=True)
    live_raw["character"]["name"] = "测试名 甲"
    path.write_text(savedvariables(live_raw))
    assert read_snapshot(path, "测试名-甲", "97").character.identity == "97:测试名-甲"
    live_raw["character"]["name"] = "测试名 乙"
    path.write_text(savedvariables(live_raw))
    with pytest.raises(ImportError, match="身份"):
        read_snapshot(path, "测试名-甲", "97")


def test_numeric_layout_does_not_relax_other_clients_or_numeric_realm_mismatches(tmp_path, live_raw):
    path = forever_save(tmp_path, live_raw)
    live_raw["client"].update(version="12.0.0", interface=120000)
    path.write_text(savedvariables(live_raw))
    with pytest.raises(ImportError, match="身份"):
        read_snapshot(path, "测试名-甲", "97")
    live_raw["client"].update(version="1.60.1", interface=16001)
    live_raw["character"]["realm"] = "98"
    path.write_text(savedvariables(live_raw))
    with pytest.raises(ImportError, match="服务器编号"):
        read_snapshot(path, "测试名-甲", "97")


@pytest.mark.parametrize("name,realm", [("测试名 甲", "CN Test Realm PvE"), ("测试名-甲", "97")])
def test_forever_full_name_and_realm_formats_keep_storage_identity(tmp_path, live_raw, name, realm):
    path = forever_save(tmp_path, live_raw)
    original = read_snapshot(path, "测试名-甲", "97")
    live_raw["character"].update(name=name, realm=realm, storage_name="伪造-姓名", storage_realm_id=999)
    path.write_text(savedvariables(live_raw))
    updated = read_snapshot(path, "测试名-甲", "97")
    assert updated.character.identity == original.character.identity
    assert updated.character.display_name == original.character.display_name
    assert updated.character.storage_name == "测试名-甲"
    assert updated.character.storage_realm_id == 97


def test_traditional_identity_ignores_exported_storage_metadata(tmp_path, live_raw):
    character = live_raw["character"]
    character.update(storage_name="伪造-姓名", storage_realm_id=999)
    path = tmp_path / "ForeverAI.lua"
    path.write_text(savedvariables(live_raw))
    snapshot = read_snapshot(path, character["name"], character["realm"])
    assert snapshot.character.identity == f'{character["realm"]}:{character["name"]}'
    assert snapshot.character.storage_name is None
    assert snapshot.character.storage_realm_id is None
