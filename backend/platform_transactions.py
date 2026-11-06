"""Journaled multi-directory/file transactions with explicit recovery and rollback."""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import time
import uuid

from .platform_io import digest_file, inside, manifest, read_json, require_game_closed, write_json


def fingerprint(path: Path):
    if path.is_symlink():
        raise ValueError("目标是符号链接，暂停覆盖")
    if not path.exists():
        return None
    return {"kind": "directory", "files": manifest(path)} if path.is_dir() else {"kind": "file", "sha256": digest_file(path)}


def remove_owned(path: Path):
    if path.is_symlink():
        raise ValueError("恢复目标变为符号链接，请人工检查")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


class Transactions:
    def __init__(self, root: Path):
        self.root = root
        self.journals = root / "operations"
        self.journals.mkdir(parents=True, exist_ok=True)

    def state(self):
        return read_json(self.root / "state.json", {"installs": {}, "profiles": {}})

    def save_state(self, state):
        write_json(self.root / "state.json", state)

    def history(self):
        return sorted([read_json(p) for p in self.journals.glob("*.json")], key=lambda x: x["created_at"], reverse=True)

    def pending(self):
        return [j for j in self.history() if j["status"] in ("applying", "recovering", "recovery_required")]

    def save(self, journal):
        write_json(self.journals / (journal["id"] + ".json"), journal)

    def restored_state(self, journal):
        # Restore only keys this transaction changed; preserve unrelated adoption
        # and update-check records made after the original operation.
        state = self.state()
        before, after = journal["state_before"], journal["state_after"]
        for section in before.keys() | after.keys():
            old, new = before.get(section, {}), after.get(section, {})
            current = state.setdefault(section, {})
            for key in old.keys() | new.keys():
                if old.get(key) == new.get(key):
                    continue
                if current.get(key) not in (old.get(key), new.get(key)):
                    raise ValueError("此操作的管理记录已变化，暂停恢复")
                if key in old:
                    current[key] = old[key]
                else:
                    current.pop(key, None)
        return state

    def execute(self, game: Path, kind: str, changes: list[tuple[str, Path | None]], state_after: dict):
        """Caller holds the shared lock. All originals stay outside AddOns."""
        if self.pending():
            raise ValueError("有中断操作等待恢复，请先查看操作历史")
        require_game_closed(self.root)
        op = uuid.uuid4().hex
        relative_base = f".forever-backups/{op}"
        inside(game, relative_base)
        entries = []
        # Prepare all new data and hash all originals before the first mutation.
        for index, (name, source) in enumerate(changes):
            target = inside(game, name)
            before = fingerprint(target)
            new = inside(game, f"{relative_base}/new/{index}")
            if source is not None:
                after = fingerprint(source)
                if after is None:
                    raise ValueError("暂存文件已丢失")
                new.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, new)
                else:
                    shutil.copy2(source, new)
                if fingerprint(new) != after:
                    raise ValueError("暂存复制校验失败")
            else:
                after = None
            entries.append({"target": name, "old": f"{relative_base}/old/{index}", "new": f"{relative_base}/new/{index}",
                            "before": before, "after": after, "phase": "pending"})
        journal = {"id": op, "kind": kind, "game": str(game), "created_at": time.time(), "status": "applying",
                   "entries": entries, "state_before": self.state(), "state_after": state_after}
        self.save(journal)
        try:
            require_game_closed(self.root)
            for entry in entries:
                require_game_closed(self.root)
                target, old, new = (inside(game, entry[k]) for k in ("target", "old", "new"))
                if fingerprint(target) != entry["before"]:
                    raise ValueError("目标在准备期间发生变化，已暂停")
                entry["phase"] = "moving_old"
                self.save(journal)
                if entry["before"] is not None:
                    old.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, old)
                entry["phase"] = "installing"
                self.save(journal)
                if entry["after"] is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(new, target)
                entry["phase"] = "done"
                self.save(journal)
            self.save_state(state_after)
            journal["status"] = "applied"
            self.save(journal)
            return journal
        except Exception as exc:
            journal["error"] = str(exc)
            self.save(journal)
            try:
                self.recover(journal["id"])
            except (OSError, ValueError):
                journal["status"] = "recovery_required"
                self.save(journal)
                raise ValueError("操作中断，原文件已保留；请退出游戏后从历史恢复") from exc
            raise ValueError("应用失败，已恢复原文件与记录：" + str(exc)) from exc

    def get(self, op):
        if len(op) != 32 or any(c not in "0123456789abcdef" for c in op):
            raise ValueError("操作编号无效")
        journal = read_json(self.journals / (op + ".json"))
        if not journal:
            raise ValueError("操作不存在")
        return journal

    def recover(self, op):
        require_game_closed(self.root)
        journal = self.get(op)
        if journal["status"] not in ("applying", "recovering", "recovery_required"):
            raise ValueError("此操作无需中断恢复")
        game = Path(journal["game"])
        journal["status"] = "recovering"
        self.save(journal)
        restored_state = self.restored_state(journal)
        # Preflight everything, including retained originals, before restoring.
        for entry in journal["entries"]:
            target, old = inside(game, entry["target"]), inside(game, entry["old"])
            original = fingerprint(old)
            current = fingerprint(target)
            if original is not None and original != entry["before"]:
                raise ValueError("备份校验失败，保留现场")
            if entry["phase"] == "restored":
                if current != entry["before"]:
                    raise ValueError("恢复后的文件发生变化，保留现场")
                continue
            if original is None and entry["before"] is not None and current != entry["before"]:
                raise ValueError("原文件和备份状态未知，保留现场")
            if current not in (entry["before"], entry["after"], None):
                raise ValueError("中断后目标已被修改，保留现场")
        for entry in reversed(journal["entries"]):
            if entry["phase"] == "restored":
                continue
            target, old = inside(game, entry["target"]), inside(game, entry["old"])
            if old.exists():
                remove_owned(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(old, target)
            elif entry["before"] is None and entry["phase"] != "pending":
                remove_owned(target)
            entry["phase"] = "restored"
            self.save(journal)
        self.save_state(restored_state)
        journal["status"] = "recovered"
        self.save(journal)
        return journal

    def rollback(self, op):
        require_game_closed(self.root)
        journal = self.get(op)
        if journal["status"] != "applied":
            raise ValueError("只能回滚已应用的操作")
        # Reverse chronological order avoids undoing ownership/config from later operations.
        applied = [j for j in self.history() if j["status"] == "applied"]
        if applied and applied[0]["id"] != op:
            raise ValueError("请先回滚较新的操作")
        game = Path(journal["game"])
        changes = []
        for entry in journal["entries"]:
            target, old = inside(game, entry["target"]), inside(game, entry["old"])
            if fingerprint(target) != entry["after"]:
                raise ValueError("应用后文件已被修改，暂停回滚；请先备份本地修改")
            if fingerprint(old) != entry["before"]:
                raise ValueError("备份校验失败，暂停回滚")
            changes.append((entry["target"], old if entry["before"] is not None else None))
        reversed_op = self.execute(game, "rollback:" + op, changes, self.restored_state(journal))
        reversed_op["status"] = "rollback_applied"
        self.save(reversed_op)
        journal["status"] = "rolled_back"
        journal["rollback_id"] = reversed_op["id"]
        self.save(journal)
        return reversed_op
