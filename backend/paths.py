from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .savedvariables import ImportError, read_snapshot

FLAVORS = ("_forever_", "_cn_beta_", "_classic_beta_", "_beta_")


@dataclass(frozen=True)
class Source:
    id: str
    path: Path
    character: str
    realm: str


def default_roots() -> list[Path]:
    if sys.platform == "win32":
        bases = [Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
                 Path(os.environ.get("ProgramFiles", "C:/Program Files")), Path("C:/Games"), Path("D:/Games")]
        roots = [base / "World of Warcraft" for base in bases]
        # Read known installation entries; never enumerate user files or entire drives.
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for key in (r"SOFTWARE\Blizzard Entertainment\World of Warcraft",
                            r"SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft",
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\World of Warcraft"):
                    try:
                        with winreg.OpenKey(hive, key) as handle:
                            for field in ("InstallPath", "InstallLocation"):
                                try:
                                    value, _ = winreg.QueryValueEx(handle, field)
                                    if isinstance(value, str) and value:
                                        roots.append(Path(value))
                                except OSError:
                                    pass
                    except OSError:
                        pass
        except ImportError:
            pass
        return list(dict.fromkeys(roots))
    return [Path("/Applications/World of Warcraft"), Path.home() / "Applications/World of Warcraft"]


def game_flavors(root: Path) -> list[Path]:
    root = root.expanduser().resolve()
    # An explicitly selected old beta also migrates discovery to the released
    # sibling. Nothing is moved or deleted from the old installation.
    if root.name in FLAVORS[1:] and (root.parent / "_forever_/WTF").is_dir():
        root = root.parent / "_forever_"
    if (root / "WTF").is_dir() and (root / "Interface").is_dir():
        return [root]
    if (root / "_forever_/WTF").is_dir() and (root / "_forever_/Interface").is_dir():
        return [root / "_forever_"]
    return [root / name for name in FLAVORS if (root / name / "WTF").is_dir()]


def discover(root: str | Path | None) -> list[Source]:
    roots = [Path(root)] if root else default_roots()
    sources = []
    for install in roots:
        for flavor in game_flavors(install):
            allowed = (flavor / "WTF" / "Account").resolve()
            # The depth and filename are fixed; no recursive drive scan.
            for path in sorted(allowed.glob("*/*/*/SavedVariables/ForeverAI.lua")):
                if len(sources) >= 100:
                    return sources
                resolved = path.resolve()
                if path.is_symlink() or not resolved.is_relative_to(allowed) or not resolved.is_file():
                    continue
                realm, character = path.parts[-4], path.parts[-3]
                source_id = hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
                sources.append(Source(source_id, resolved, character, realm))
    return sources


def import_source(source_id: str, root: str | Path | None):
    source = next((s for s in discover(root) if s.id == source_id), None)
    if source is None:
        raise ImportError("来源不存在或已不在配置的游戏目录中，请重新发现")
    return read_snapshot(source.path, source.character, source.realm)
