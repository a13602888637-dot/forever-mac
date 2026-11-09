import json
from pathlib import Path
import plistlib
import subprocess

import pytest

from scripts import build_macos_app as builder


def make_app(path, version, content, bundle_id=builder.BUNDLE_ID):
    executable = path / "Contents/MacOS/ForeverAI"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(content)
    (path / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": bundle_id, "CFBundleShortVersionString": version,
    }))


@pytest.fixture
def build_root(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder.sys, "platform", "darwin")
    monkeypatch.setattr(builder.subprocess, "check_output", lambda *args, **kwargs: "")
    monkeypatch.setattr(builder, "compile_app", lambda output, work, version: make_app(output, version, b"new"))
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.4.0"\n')
    return tmp_path


def test_rebuild_archives_old_app_after_build_and_keeps_batches(build_root):
    output = build_root / "Forever AI Companion.app"
    make_app(output, "0.2.0", b"original")
    builder.build(output)
    builder.build(output)
    receipts = sorted((build_root / "delete").glob("*-build/manifest.json"))
    assert len(receipts) == 2
    archived = []
    for receipt in receipts:
        info = json.loads(receipt.read_text())
        assert info["status"] == "installed" and info["new_version"] == "0.4.0"
        path = build_root / info["destination"]
        assert path.suffix == ".disabled" and path.is_relative_to(build_root / "delete")
        archived.append((path / "Contents/MacOS/ForeverAI").read_bytes())
    assert archived == [b"original", b"new"]
    assert (output / "Contents/MacOS/ForeverAI").read_bytes() == b"new"


def test_compile_failure_leaves_original_and_cleans_staging(build_root, monkeypatch):
    output = build_root / "Forever AI Companion.app"
    make_app(output, "0.2.0", b"original")

    def fail(staged, work, version):
        make_app(staged, version, b"partial")
        raise subprocess.CalledProcessError(1, ["codesign"])

    monkeypatch.setattr(builder, "compile_app", fail)
    with pytest.raises(subprocess.CalledProcessError):
        builder.build(output)
    assert (output / "Contents/MacOS/ForeverAI").read_bytes() == b"original"
    assert not list((build_root / "delete").glob("*-build"))
    assert not list(build_root.glob(".forever-build-*"))


def test_install_failure_restores_original(build_root, monkeypatch):
    output = build_root / "Forever AI Companion.app"
    make_app(output, "0.2.0", b"original")
    rename = Path.rename

    def fail_install(path, target):
        if path.parent.name.startswith(".forever-build-") and target == output:
            raise OSError("simulated install failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_install)
    with pytest.raises(OSError, match="simulated"):
        builder.build(output)
    assert (output / "Contents/MacOS/ForeverAI").read_bytes() == b"original"
    receipt = next((build_root / "delete").glob("*-build/manifest.json"))
    info = json.loads(receipt.read_text())
    assert info["status"] == "restored_after_install_failure"
    assert not (build_root / info["destination"]).exists()


@pytest.mark.parametrize("reason", ["running", "foreign", "symlink"])
def test_unrelated_or_running_app_is_not_moved(build_root, monkeypatch, reason):
    output = build_root / "Forever AI Companion.app"
    original = build_root / "original.app" if reason == "symlink" else output
    make_app(original, "0.2.0", b"original", "other.app" if reason == "foreign" else builder.BUNDLE_ID)
    if reason == "symlink":
        output.symlink_to(original, target_is_directory=True)
    if reason == "running":
        monkeypatch.setattr(builder.subprocess, "check_output", lambda *a, **kw: str(output / "Contents/MacOS/ForeverAI"))
    with pytest.raises(ValueError):
        builder.build(output)
    assert (original / "Contents/MacOS/ForeverAI").read_bytes() == b"original"
    assert not list((build_root / "delete").glob("*-build"))


def test_first_build_has_no_archived_version(build_root):
    output = build_root / "Forever AI Companion.app"
    builder.build(output)
    info = plistlib.loads((output / "Contents/Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == "0.4.0"
    assert not list((build_root / "delete").glob("*-build"))
