"""Bounded file IO and a process-wide lock shared by HTTP and stdio MCP."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import time
import unicodedata

MAX_UPLOAD = 128 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_FILES = 30000
MAX_FILE = 64 * 1024 * 1024


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value) or ".." in value:
        raise ValueError("标识格式无效")
    return value


def relative(value: str) -> Path:
    if not value or len(value) > 500 or "\\" in value or ":" in value or any(ord(c) < 32 for c in value):
        raise ValueError("路径格式无效")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise ValueError("路径越过工作区")
    return Path(*p.parts)


def inside(root: Path, value: str) -> Path:
    p = root / relative(value)
    if root.is_symlink() or not p.resolve().is_relative_to(root.resolve()):
        raise ValueError("路径越过工作区或包含符号链接")
    cursor = p
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError("拒绝符号链接")
        cursor = cursor.parent
    return p


def folded(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def atomic_bytes(path: Path, value: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".forever-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        # Persist the rename as well as its contents for interruption recovery.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode())


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    if path.is_symlink() or path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("本地记录格式无效")
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        raise ValueError("本地记录不可读；保留原文件，请检查后重试") from exc


def digest_file(path: Path) -> str:
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("拒绝符号链接或特殊文件")
    if path.stat().st_size > MAX_FILE:
        raise ValueError("单个文件体积异常")
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def manifest(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    if root.is_symlink() or not root.is_dir():
        raise ValueError("插件目录包含符号链接或不是目录，暂停覆盖")
    result, total, names = {}, 0, set()
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(base) / name
            if path.is_symlink():
                raise ValueError("目录含符号链接，暂停覆盖")
            key = path.relative_to(root).as_posix()
            relative(key)
            if folded(key) in names:
                raise ValueError("文件路径大小写冲突")
            names.add(folded(key))
        for name in sorted(files):
            path = Path(base) / name
            total += path.stat().st_size
            if len(result) >= MAX_FILES or total > MAX_EXPANDED:
                raise ValueError("目录体积或文件数异常")
            result[path.relative_to(root).as_posix()] = digest_file(path)
    return result


@contextmanager
def operation_lock(root: Path):
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    path = root / "operations.lock"
    if path.is_symlink():
        raise ValueError("操作锁不能为符号链接")
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("另一个插件操作正在进行，请稍候") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def game_running() -> bool:
    """Fail closed if the OS process inventory cannot be obtained."""
    try:
        result = subprocess.run(["/bin/ps", "-axo", "comm="], capture_output=True, text=True, timeout=5, check=True)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("无法确认游戏是否退出，暂停写入") from None
    names = {"world of warcraft", "world of warcraft classic", "wow", "wowclassic", "wowf", "wow.exe"}
    return any(Path(line.strip()).name.casefold() in names for line in result.stdout.splitlines())


def require_game_closed(platform_root: Path | None = None):
    if platform_root is not None:
        launch = read_json(platform_root / "game-launch.json", {})
        if launch.get("status") == "starting" and time.time() - launch.get("created_at", 0) < 30:
            raise ValueError("游戏正在启动，请等待启动完成并退出游戏后再应用")
    if game_running():
        raise ValueError("游戏仍在运行；可检查和准备，退出游戏后再应用")
