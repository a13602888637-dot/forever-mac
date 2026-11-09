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
from .platform_transactions import dependency_blockers, fingerprint, precondition_token

COMBOS = ("EllesmereUI", "ForeverUI")
OVERLAP = {"EllesmereUIActionBars", "EllesmereUIBags", "EllesmereUIChat", "EllesmereUIMinimap",
           "EllesmereUIQuestTracker", "EllesmereUIUnitFrames", "EllesmereUIRaidFrames", "EllesmereUIResourceBars",
           "EllesmereUICooldownManager"}


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
                           "snapshot_identity": f"{int(path.parent.parent.name) if path.parent.parent.name.isdecimal() else path.parent.parent.name}:{path.parent.name}",
                           "display_name": path.parent.name.replace("-", " "),
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

    def prepare_switch(self, character_id, combo, keep_ellesmere_dps=False):
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
            details_members = []
            if keep_ellesmere_dps:
                if "EllesmereUIDamageMeters" not in installed:
                    raise ValueError("尚未安装 EllesmereUI 伤害统计，不能停用替代统计")
                updates["EllesmereUIDamageMeters"] = True
                details = next((g for g in packages(mods, {}) if g["id"] == "details"), None)
                if "Details" in installed and not details:
                    raise ValueError("Details 包身份未确认，暂不改动")
                details_members = sorted(m["directory"] for m in details["modules"]) if details else []
                updates.update({name: False for name in details_members})
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
            blockers = dependency_blockers(mods, {**states, **updates})
            if blockers:
                raise ValueError("；".join(blockers) + "；不会自动停用其他插件")
            op = uuid.uuid4().hex
            output = self.root / "profile-plans" / (op + ".txt")
            atomic_bytes(output, render_addon_state(raw, updates))
            plan = {"id": op, "character_id": character_id, "combo": combo, "created_at": time.time(), "status": "prepared",
                    "game": str(self.platform.game()), "target": character.relative_to(self.platform.game()).as_posix(),
                    "before": fingerprint(character), "after": fingerprint(output), "updates": updates,
                    "members": members, "keep_ellesmere_dps": keep_ellesmere_dps, "details_members": details_members,
                    "note": "只修改选定角色相关插件启用状态；首次 ForeverUI 请在游戏内 /fui 应用主题。配置备份和恢复是独立操作。" +
                            (" 伤害统计保留 EllesmereUI，Details 及附属模块停用，配置文件保留。" if keep_ellesmere_dps else "")}
            write_json(self.root / "profile-plans" / (op + ".json"), plan)
            return plan

    def prepare_restore_switch(self, old_op):
        """Prepare a fresh diff from a verified, previously applied state file."""
        identifier(old_op)
        with self.platform.lock():
            source_path = self.root / "profile-plans" / (old_op + ".json")
            source = read_json(source_path)
            if not source or source.get("status") != "applied":
                raise ValueError("只能从已成功应用的历史角色方案准备恢复")
            game = self.platform.game()
            if source.get("game") != str(game):
                raise ValueError("历史方案属于其他客户端，请先切回相应客户端")
            target = self.character_path(source["character_id"])
            if target.relative_to(game).as_posix() != source.get("target"):
                raise ValueError("历史方案与当前存档角色不一致")
            old_output = source_path.with_suffix(".txt")
            if not isinstance(source.get("after"), dict) or source["after"].get("kind") != "file" or fingerprint(old_output) != source["after"]:
                raise ValueError("历史方案状态文件校验失败，不能恢复")
            old_raw = old_output.read_bytes()
            if hashlib.sha256(old_raw).hexdigest() != source["after"].get("sha256"):
                raise ValueError("历史方案状态文件在读取期间变化，不能恢复")
            _, _, desired, _ = parse_addon_state(old_raw)
            journal = self.platform.tx.get(source.get("operation_id", ""))
            if journal["game"] != str(game) or journal["kind"] != "profile:" + source["combo"] or not any(
                    entry["target"] == source["target"] and entry["after"] == source["after"] for entry in journal["entries"]):
                raise ValueError("历史方案与成功事务证据不一致，不能推导缺省状态")
            known_installed = {name for record in journal["state_after"].get("installs", {}).values()
                               for name in record.get("files", {})}
            historic_defaults = sorted(known_installed - set(desired))
            desired.update({name: True for name in historic_defaults})
            raw = target.read_bytes()
            current_before = {"kind": "file", "sha256": hashlib.sha256(raw).hexdigest()}
            _, _, current, _ = parse_addon_state(raw)
            modules = scan_addons(game / "Interface/AddOns")
            members = self.members(source["combo"])
            if not members:
                raise ValueError("历史界面组合尚未安装，不能恢复启用状态")
            installed = {module["directory"]: module for module in modules}
            updates, blockers, unchanged, dependencies = {}, [], [], {}
            for module in modules:
                name = module["directory"]
                # No proof of a historic setting means no permission to infer it.
                # Inactive client-flavor modules also retain their current state.
                if name not in desired:
                    unchanged.append({"directory": name, "enabled": current.get(name, True), "reason": "历史未记录，保持当前状态"})
                    continue
                if module["compatibility"] == "inactive_flavor":
                    continue
                if desired[name] and module["compatibility"] != "toc_supported":
                    blockers.append(f"{name} 当前兼容声明未知或不支持，不能恢复启用")
                if current.get(name, True) != desired[name]:
                    updates[name] = desired[name]
            visited, visiting = set(), set()

            def require_dependencies(name):
                if name in visiting:
                    blockers.append(f"{name} 存在循环依赖，不能恢复启用")
                    return
                if name in visited:
                    return
                module = installed.get(name)
                if not module or module["compatibility"] != "toc_supported":
                    blockers.append(f"{name} 缺失或当前兼容声明未知，不能恢复启用")
                    return
                visiting.add(name)
                for dep in module["dependencies"]:
                    if dep.startswith("Blizzard_"):
                        continue
                    if dep not in installed or installed[dep]["compatibility"] != "toc_supported":
                        blockers.append(f"{name} 的依赖 {dep} 缺失或当前兼容声明未知")
                        continue
                    if desired.get(dep) is False:
                        blockers.append(f"历史方案要求停用 {dep}，但 {name} 当前依赖它，请先处理冲突")
                        continue
                    if not current.get(dep, True) and desired.get(dep) is not True:
                        dependency = dependencies.setdefault(dep, {"directory": dep, "required_by": [], "before": False,
                                                                   "after": True, "reason": "恢复已选模块所需的额外依赖"})
                        if name not in dependency["required_by"]:
                            dependency["required_by"].append(name)
                        updates[dep] = True
                    require_dependencies(dep)
                visiting.remove(name)
                visited.add(name)

            for name, enabled in desired.items():
                if enabled and name in installed and installed[name]["compatibility"] != "inactive_flavor":
                    require_dependencies(name)
            unchanged = [item for item in unchanged if item["directory"] not in dependencies]
            blockers.extend(dependency_blockers(modules, {**current, **updates}))
            details = next((g for g in packages(modules, {}) if g["id"] == "details"), None)
            character = next(c for c in self.characters() if c["id"] == source["character_id"])
            enabled_count = sum(value is True for value in updates.values())
            disabled_count = sum(value is False for value in updates.values())
            op = uuid.uuid4().hex
            output = self.root / "profile-plans" / (op + ".txt")
            atomic_bytes(output, render_addon_state(raw, updates))
            plan = {"id": op, "kind": "profile", "status": "prepared", "restore_from": old_op,
                    "character_id": source["character_id"], "character": character, "combo": source["combo"],
                    "created_at": time.time(), "game": str(game), "target": target.relative_to(game).as_posix(),
                    "before": current_before, "after": fingerprint(output), "updates": updates,
                    "members": members, "keep_ellesmere_dps": source.get("keep_ellesmere_dps", False),
                    "details_members": sorted(m["directory"] for m in details["modules"]) if details else [],
                    "modules_before": {name: fingerprint(inside(game, "Interface/AddOns/" + name)) for name in updates},
                    "enabled_count": enabled_count, "disabled_count": disabled_count,
                    "dependencies": list(dependencies.values()), "unchanged_modules": unchanged,
                    "historical_default_enabled": historic_defaults, "blockers": list(dict.fromkeys(blockers)),
                    "can_apply": bool(updates) and not blockers,
                    "note": f"恢复上次已确认方案：启用 {enabled_count} 个模块，停用 {disabled_count} 个模块。"
                            f"其中 {len(dependencies)} 个为恢复所需的额外依赖，已单列说明；"
                            f"{len(unchanged)} 个没有历史状态证据的模块保持当前状态。"
                            "保留当前注释和全部 SavedVariables，确认后自动备份。"}
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
            if plan.get("restore_from") and not plan["updates"]:
                raise ValueError("历史状态已经恢复，无需重复应用")
            if plan.get("restore_from") and plan.get("blockers"):
                raise ValueError("；".join(plan["blockers"]) + "；请重新准备恢复预览")
            if time.time() - plan["created_at"] > 86400:
                raise ValueError("切换计划已过期，请重新查看变更")
            if plan["game"] != str(self.platform.game()):
                raise ValueError("客户端选择已变化，请重新生成计划")
            target = self.character_path(plan["character_id"])
            if fingerprint(target) != plan["before"] or fingerprint(path.with_suffix(".txt")) != plan["after"]:
                raise ValueError("状态文件已变化，请重新生成计划")
            for name, before in plan.get("modules_before", {}).items():
                if fingerprint(inside(self.platform.game(), "Interface/AddOns/" + name)) != before:
                    raise ValueError("插件文件在恢复预览后发生变化，请重新生成计划")
            if self.members(plan["combo"]) != plan["members"]:
                raise ValueError("组合模块已变化，请重新生成计划")
            _, _, states, _ = parse_addon_state(target.read_bytes())
            installed = {m["directory"]: m for m in scan_addons(self.platform.game() / "Interface/AddOns")}
            if plan.get("keep_ellesmere_dps"):
                details = next((g for g in packages(list(installed.values()), {}) if g["id"] == "details"), None)
                current_details = sorted(m["directory"] for m in details["modules"]) if details else []
                if current_details != plan["details_members"]:
                    raise ValueError("伤害统计模块已变化，请重新生成计划")
            for name, enabled in plan["updates"].items():
                if not enabled:
                    continue
                module = installed.get(name)
                if not module or module["compatibility"] != "toc_supported":
                    raise ValueError("组合兼容声明已变化，请重新生成计划")
                for dep in module["dependencies"]:
                    if not dep.startswith("Blizzard_") and (dep not in installed or not plan["updates"].get(dep, states.get(dep, True))):
                        raise ValueError("组合依赖已变化，请重新生成计划")
            blockers = dependency_blockers(list(installed.values()), {**states, **plan["updates"]})
            if blockers:
                raise ValueError("；".join(blockers) + "；组合依赖已变化，请重新生成计划")
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

    def restore_preview(self, op, character_id):
        identifier(op)
        root = self.root / "profile-snapshots" / op
        snapshot = read_json(root / "snapshot.json")
        if not snapshot or snapshot["character_id"] != character_id or snapshot["game"] != str(self.platform.game()):
            raise ValueError("配置备份与当前客户端或选定角色不一致")
        target_character = self.character_path(character_id)
        character = next(c for c in self.characters() if c["id"] == character_id)
        allowed = {p.relative_to(self.platform.game()).as_posix() for p in self.config_paths(character_id, snapshot["combo"])}
        files, blockers = [], []
        if self.platform.tx.pending():
            blockers.append("有中断操作等待恢复")
        try:
            require_game_closed(self.root)
        except ValueError as exc:
            blockers.append(str(exc))
        for file in snapshot["files"]:
            try:
                if file["target"] not in allowed:
                    raise ValueError("配置备份超出当前组合范围")
                stored = inside(root, file["stored"])
                desired = fingerprint(stored)
                if desired != file["fingerprint"]:
                    raise ValueError("配置备份校验失败")
                target = inside(self.platform.game(), file["target"])
                before = fingerprint(target)
                if before is not None and before["kind"] != "file":
                    raise ValueError("当前配置目标不是普通文件")
                scope = "character" if target.is_relative_to(target_character.parent) else "account"
                files.append({"target": file["target"], "filename": target.name, "scope": scope,
                              "before": before, "after": desired,
                              "action": "unchanged" if before == desired else "remove" if desired is None else "restore" if before is None else "replace"})
            except (ValueError, OSError) as exc:
                blockers.append(str(exc))
        state = self.platform.tx.state()
        targets = {file["target"] for file in files}
        operations = [(j["id"], j["status"]) for j in self.platform.tx.history()
                      if j["game"] == snapshot["game"] and any(e["target"] in targets for e in j["entries"])]
        token = precondition_token({"snapshot": snapshot, "files": files, "allowed": sorted(allowed),
                                    "installs": state.get("installs", {}), "profiles": state.get("profiles", {}),
                                    "character_state": fingerprint(target_character), "operations": operations})
        return {"id": op, "kind": "config_restore", "character_id": character_id, "character": character,
                "combo": snapshot["combo"], "created_at": snapshot["created_at"], "files": files,
                "backup": "应用前自动备份当前账号级及角色级配置，可从操作历史恢复", "blockers": list(dict.fromkeys(blockers)),
                "can_apply": not blockers, "precondition_token": token}

    def restore_config(self, op, character_id, expected_token=None):
        identifier(op)
        with self.platform.lock():
            preview = self.restore_preview(op, character_id)
            if not preview["can_apply"]:
                raise ValueError("；".join(preview["blockers"]))
            if expected_token is not None and preview["precondition_token"] != expected_token:
                raise ValueError("恢复预览后文件或管理状态发生变化，请重新查看变更")
            root = self.root / "profile-snapshots" / op
            snapshot = read_json(root / "snapshot.json")
            changes = []
            for file in snapshot["files"]:
                stored = inside(root, file["stored"])
                changes.append((file["target"], stored if file["fingerprint"] else None))
            journal = self.platform.tx.execute(self.platform.game(), "config-restore:" + snapshot["combo"], changes, deepcopy(self.platform.tx.state()))
            return {"id": journal["id"], "status": "applied"}
