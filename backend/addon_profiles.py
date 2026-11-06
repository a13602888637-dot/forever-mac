"""Character-scoped enablement, with separate explicit configuration snapshots."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import shutil
import time
import uuid

from .addon_metadata import packages, scan_addons
from .platform_io import (atomic_bytes, identifier, inside, read_json,
                          require_game_closed, write_json)
from .platform_transactions import fingerprint

COMBOS = ("EllesmereUI", "ForeverUI")
OVERLAP = {"EllesmereUIActionBars", "EllesmereUIBags", "EllesmereUIChat", "EllesmereUIMinimap",
           "EllesmereUIQuestTracker", "EllesmereUIUnitFrames", "EllesmereUIRaidFrames", "EllesmereUIResourceBars"}


def parse_addon_state(raw: bytes):
    if len(raw) > 1024 * 1024:
        raise ValueError("客户端启用状态文件体积异常")
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("未知客户端状态编码，停止写入") from None
    lines, states = text.splitlines(keepends=True), {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+):[ \t]*(enabled|disabled)[ \t]*(?:\r?\n)?", line)
        if not match or match[1] in states:
            raise ValueError("未知或重复的客户端启用状态格式，停止写入")
        states[match[1]] = match[2] == "enabled"
    if not states:
        raise ValueError("未识别客户端启用状态格式；请先在游戏内保存插件设置")
    return bom, lines, states, "\r\n" if "\r\n" in text else "\n"


def render_addon_state(raw: bytes, updates: dict[str, bool]) -> bytes:
    bom, lines, _, newline = parse_addon_state(raw)
    pending = dict(updates)
    result = []
    for line in lines:
        match = re.match(r"^([A-Za-z0-9_.-]+):", line)
        if match and match[1] in pending:
            name = match[1]
            value = "enabled" if pending.pop(name) else "disabled"
            # Preserve line endings and all unrelated lines verbatim.
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            result.append(f"{name}: {value}{ending}")
        else:
            result.append(line)
    if pending and result and not result[-1].endswith("\n"):
        result[-1] += newline
    result.extend(f"{name}: {'enabled' if enabled else 'disabled'}{newline}" for name, enabled in sorted(pending.items()))
    return (b"\xef\xbb\xbf" if bom else b"") + "".join(result).encode()


class Profiles:
    def __init__(self, platform):
        self.platform = platform
        self.root = platform.root
        (self.root / "profile-plans").mkdir(exist_ok=True)

    def characters(self):
        game = self.platform.game()
        result = []
        account = game / "WTF/Account"
        for path in sorted(account.glob("*/*/*/AddOns.txt"))[:200]:
            try:
                relative = path.relative_to(game).as_posix()
                inside(game, relative)
                if not path.is_file():
                    continue
                parse_addon_state(path.read_bytes())
                error = None
            except (ValueError, OSError) as exc:
                error = str(exc)
            result.append({"id": hashlib.sha256(str(path).encode()).hexdigest()[:24],
                           "realm": path.parent.parent.name, "character": path.parent.name,
                           "format_error": error})
        return result

    def character_path(self, ident):
        identifier(ident)
        game = self.platform.game()
        for path in (game / "WTF/Account").glob("*/*/*/AddOns.txt"):
            if hashlib.sha256(str(path).encode()).hexdigest()[:24] == ident:
                return inside(game, path.relative_to(game).as_posix())
        raise ValueError("角色不存在，请先在游戏中保存插件启用设置")

    def members(self, combo):
        if combo not in COMBOS:
            raise ValueError("未知界面组合")
        mods = scan_addons(self.platform.game() / "Interface/AddOns")
        groups = packages(mods, {})
        if combo == "EllesmereUI":
            group = next((g for g in groups if g["id"] == "ellesmere"), None)
            return [m["directory"] for m in group["modules"]] if group else []
        return ["ForeverUI"] if any(m["directory"] == "ForeverUI" for m in mods) else []

    def overview(self):
        try:
            return {"characters": self.characters(), "combinations": [{"name": c, "members": self.members(c)} for c in COMBOS],
                    "snapshots": self.snapshots(), "active": self.platform.tx.state().get("profiles", {}),
                    "error": None}
        except ValueError as exc:
            return {"characters": [], "combinations": [], "snapshots": [], "active": {}, "error": str(exc)}

    def prepare_switch(self, character_id, combo):
        with self.platform.lock():
            character = self.character_path(character_id)
            raw = character.read_bytes()
            _, _, states, _ = parse_addon_state(raw)
            members = self.members(combo)
            if not members:
                raise ValueError(f"{combo} 尚未安装，请先生成并应用安装计划")
            mods = scan_addons(self.platform.game() / "Interface/AddOns")
            installed = {m["directory"]: m for m in mods}
            updates = {name: True for name in members}
            if combo == "EllesmereUI" and "ForeverUI" in installed:
                updates["ForeverUI"] = False
            elif combo == "ForeverUI":
                updates.update({name: False for name in self.members("EllesmereUI") if name in OVERLAP})
            for name, enabled in updates.items():
                if not enabled:
                    continue
                if installed[name]["compatibility"] != "toc_supported":
                    raise ValueError(f"{name} 未声明当前接口支持")
                for dep in installed[name]["dependencies"]:
                    if dep.startswith("Blizzard_"):
                        continue
                    if dep not in installed or not updates.get(dep, states.get(dep, True)):
                        raise ValueError(f"{name} 需要启用依赖 {dep}")
            op = uuid.uuid4().hex
            output = self.root / "profile-plans" / (op + ".txt")
            atomic_bytes(output, render_addon_state(raw, updates))
            plan = {"id": op, "character_id": character_id, "combo": combo, "created_at": time.time(), "status": "prepared",
                    "game": str(self.platform.game()), "target": character.relative_to(self.platform.game()).as_posix(),
                    "before": fingerprint(character), "after": fingerprint(output), "updates": updates,
                    "members": members, "note": "只修改选定角色相关插件启用状态；首次 ForeverUI 请在游戏内 /fui 应用主题。配置备份和恢复是独立操作。"}
            write_json(self.root / "profile-plans" / (op + ".json"), plan)
            return plan

    def apply_switch(self, op):
        identifier(op)
        with self.platform.lock():
            require_game_closed(self.root)
            path = self.root / "profile-plans" / (op + ".json")
            plan = read_json(path)
            if not plan or plan["status"] != "prepared":
                raise ValueError("切换计划不存在或已使用")
            if plan["game"] != str(self.platform.game()):
                raise ValueError("客户端选择已变化，请重新生成计划")
            target = self.character_path(plan["character_id"])
            if fingerprint(target) != plan["before"] or fingerprint(path.with_suffix(".txt")) != plan["after"]:
                raise ValueError("状态文件已变化，请重新生成计划")
            if self.members(plan["combo"]) != plan["members"]:
                raise ValueError("组合模块已变化，请重新生成计划")
            _, _, states, _ = parse_addon_state(target.read_bytes())
            installed = {m["directory"]: m for m in scan_addons(self.platform.game() / "Interface/AddOns")}
            for name, enabled in plan["updates"].items():
                if not enabled:
                    continue
                module = installed.get(name)
                if not module or module["compatibility"] != "toc_supported":
                    raise ValueError("组合兼容声明已变化，请重新生成计划")
                for dep in module["dependencies"]:
                    if not dep.startswith("Blizzard_") and (dep not in installed or not plan["updates"].get(dep, states.get(dep, True))):
                        raise ValueError("组合依赖已变化，请重新生成计划")
            state = self.platform.tx.state()
            state["profiles"][plan["character_id"]] = plan["combo"]
            journal = self.platform.tx.execute(self.platform.game(), "profile:" + plan["combo"], [(plan["target"], path.with_suffix(".txt"))], state)
            plan.update(status="applied", operation_id=journal["id"])
            write_json(path, plan)
            return {"id": journal["id"], "status": "applied"}

    def config_paths(self, character_id, combo):
        character = self.character_path(character_id)
        members = self.members(combo)
        if not members:
            raise ValueError("组合尚未安装")
        # Account and selected-character SavedVariables only; unrelated addon
        # configurations and other characters are never copied or restored.
        roots = [character.parent / "SavedVariables", character.parent.parent.parent / "SavedVariables"]
        return [root / (name + suffix) for root in roots for name in members for suffix in (".lua", ".lua.bak")]

    def backup_config(self, character_id, combo):
        with self.platform.lock():
            paths = self.config_paths(character_id, combo)
            op = uuid.uuid4().hex
            root = self.root / "profile-snapshots" / op
            root.mkdir()
            files = []
            game = self.platform.game()
            for index, path in enumerate(paths):
                target = inside(game, path.relative_to(game).as_posix())
                before = fingerprint(target)
                if before:
                    if before["kind"] != "file":
                        raise ValueError("配置目标不是普通文件")
                    shutil.copy2(target, root / str(index))
                    if fingerprint(root / str(index)) != before:
                        raise ValueError("配置备份校验失败")
                files.append({"target": path.relative_to(game).as_posix(), "fingerprint": before, "stored": str(index)})
            snapshot = {"id": op, "character_id": character_id, "combo": combo, "created_at": time.time(),
                        "game": str(game), "files": files, "note": "含此组合的账号级共享配置与选定角色配置；来源为磁盘存档"}
            write_json(root / "snapshot.json", snapshot)
            return {k: snapshot[k] for k in ("id", "character_id", "combo", "created_at", "note")}

    def snapshots(self):
        return sorted([{k: s[k] for k in ("id", "character_id", "combo", "created_at", "note")}
                       for p in (self.root / "profile-snapshots").glob("*/snapshot.json") if (s := read_json(p))],
                      key=lambda s: s["created_at"], reverse=True)

    def restore_config(self, op, character_id):
        identifier(op)
        with self.platform.lock():
            require_game_closed(self.root)
            root = self.root / "profile-snapshots" / op
            snapshot = read_json(root / "snapshot.json")
            if not snapshot or snapshot["character_id"] != character_id or snapshot["game"] != str(self.platform.game()):
                raise ValueError("配置备份与当前客户端或选定角色不一致")
            allowed = {p.relative_to(self.platform.game()).as_posix() for p in self.config_paths(character_id, snapshot["combo"])}
            changes = []
            for file in snapshot["files"]:
                if file["target"] not in allowed:
                    raise ValueError("配置备份超出当前组合范围")
                stored = inside(root, file["stored"])
                if fingerprint(stored) != file["fingerprint"]:
                    raise ValueError("配置备份校验失败")
                changes.append((file["target"], stored if file["fingerprint"] else None))
            journal = self.platform.tx.execute(self.platform.game(), "config-restore:" + snapshot["combo"], changes, deepcopy(self.platform.tx.state()))
            return {"id": journal["id"], "status": "applied"}
