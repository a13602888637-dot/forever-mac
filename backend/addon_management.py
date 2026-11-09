"""Reviewed package operations, bound to concrete files and character storage IDs."""
from __future__ import annotations

from copy import deepcopy
import os
import time
import uuid

from .addon_metadata import scan_addons
from .addon_profiles import Profiles, parse_addon_state, render_addon_state
from .platform_io import atomic_bytes, folded, identifier, inside, read_json, require_game_closed, write_json
from .platform_tasks import tracked, task_progress
from .platform_transactions import fingerprint

PLAN_LIFETIME = 86400
ACTIONS = {"update", "enable", "disable", "uninstall"}


class AddonManagement:
    def __init__(self, platform, profiles=None):
        self.platform = platform
        self.profiles = profiles or Profiles(platform)
        self.root = platform.root
        self.directory = self.root / "management-plans"
        self.directory.mkdir(exist_ok=True)

    def _path(self, op):
        return self.directory / (identifier(op) + ".json")

    def load(self, op):
        plan = read_json(self._path(op))
        if not plan:
            raise ValueError("管理计划不存在")
        return plan

    def _save(self, plan):
        write_json(self._path(plan["id"]), plan)

    def plans(self):
        fields = ("id", "kind", "action", "status", "created_at", "package_ids", "character", "items")
        result = []
        for path in self.directory.glob("*.json"):
            if plan := read_json(path):
                plan = self._reconcile(plan)
                result.append({k: plan.get(k) for k in fields})
        return sorted(result, key=lambda p: p["created_at"], reverse=True)

    def _character(self, character_id):
        if not character_id:
            raise ValueError("请先选择要修改的存档角色")
        path = self.profiles.character_path(character_id)
        character = next(c for c in self.profiles.characters() if c["id"] == character_id)
        if character["format_error"]:
            raise ValueError(character["format_error"])
        return path, character

    def enablement(self, character_id=None):
        groups = self.platform.inventory()["packages"]
        if not character_id:
            return {"character": None, "needs_character": True,
                    "packages": [{"id": g["id"], "status": "unknown", "enabled": None, "modules": []} for g in groups]}
        path, character = self._character(character_id)
        _, _, states, _ = parse_addon_state(path.read_bytes())
        result = []
        for group in groups:
            modules = [{"directory": m["directory"], "enabled": states.get(m["directory"], True),
                        "explicit": m["directory"] in states}
                       for m in group["modules"] if m["compatibility"] != "inactive_flavor"]
            values = {m["enabled"] for m in modules}
            status = "mixed" if len(values) > 1 else "enabled" if values == {True} else "disabled" if values == {False} else "unknown"
            result.append({"id": group["id"], "status": status,
                           "enabled": next(iter(values)) if len(values) == 1 else None, "modules": modules})
        return {"character": character, "needs_character": False, "packages": result}

    @staticmethod
    def _graph(modules):
        return {m["directory"]: {"dependencies": sorted(m["dependencies"]), "compatibility": m["compatibility"]}
                for m in modules}

    @staticmethod
    def _order(groups, reverse=False):
        """Stable dependency order for selected packages; no implicit installs."""
        owners = {folded(m["directory"]): g["id"] for g in groups for m in g["modules"]}
        by_id = {g["id"]: g for g in groups}
        result, visiting, done = [], set(), set()

        def visit(key):
            if key in done:
                return
            if key in visiting:
                raise ValueError("所选插件存在循环依赖，请分别检查后重试")
            visiting.add(key)
            for module in by_id[key]["modules"]:
                for dependency in module["dependencies"]:
                    owner = owners.get(folded(dependency))
                    if owner and owner != key:
                        visit(owner)
            visiting.remove(key)
            done.add(key)
            result.append(by_id[key])

        for group in groups:
            visit(group["id"])
        return list(reversed(result)) if reverse else result

    @tracked("准备管理变更")
    def prepare(self, action, package_ids, character_id=None):
        if action not in ACTIONS:
            raise ValueError("不支持的插件操作")
        if not isinstance(package_ids, list) or not 1 <= len(package_ids) <= 100 or len(set(package_ids)) != len(package_ids):
            raise ValueError("请选择 1 到 100 个不同的插件包")
        keys = [identifier(key) for key in package_ids]
        available = {g["id"]: g for g in self.platform.inventory()["packages"]}
        if any(key not in available for key in keys):
            raise ValueError("所选插件已变化，请刷新列表后重试")
        groups = self._order([available[key] for key in keys], reverse=action == "uninstall")
        now = time.time()
        plan = {"id": uuid.uuid4().hex, "kind": "management", "action": action,
                "package_ids": [g["id"] for g in groups], "created_at": now, "expires_at": now + PLAN_LIFETIME,
                "game": str(self.platform.game()), "status": "preparing", "character": None,
                "items": [], "static_blockers": [], "note": "每项操作先备份；卸载保留 SavedVariables。"}
        self._save(plan)
        task_progress("preparing", plan_id=plan["id"], plan_kind="management", items_total=len(groups))
        if action == "update":
            for index, group in enumerate(groups):
                item = self._item(group)
                task_progress("preparing", package_id=group["id"], items_completed=index)
                try:
                    if not group.get("repo") or group["source"] in ("workshop", "bundled"):
                        raise ValueError("此插件需从官网获取 ZIP 后导入，不能自动准备作者更新")
                    child = self.platform.download(group["id"])
                    item.update(plan_id=child["id"], to_version=child["version"], changes=child["changes"],
                                dependencies=sorted({d for m in child["toc"] for d in m["dependencies"]}),
                                missing_dependencies=child["missing_dependencies"])
                except (ValueError, OSError) as exc:
                    item.update(status="blocked", error=str(exc))
                    plan["static_blockers"].append(f"{group['name']}：{exc}")
                plan["items"].append(item)
                self._save(plan)
        else:
            with self.platform.lock():
                modules = scan_addons(self.platform.game() / "Interface/AddOns")
                plan["graph_before"] = self._graph(modules)
                if action == "uninstall":
                    self._prepare_uninstall(plan, groups, modules)
                else:
                    self._prepare_enablement(plan, groups, modules, character_id)
        plan["status"] = "prepared"
        self._save(plan)
        task_progress("awaiting_confirmation", items_completed=len(groups))
        return self.review(plan["id"])

    @staticmethod
    def _item(group):
        return {"package_id": group["id"], "name": group["name"], "from_version": group["version"],
                "to_version": None, "status": "pending", "changes": [], "dependencies": []}

    def _prepare_uninstall(self, plan, groups, modules):
        state = self.platform.tx.state()
        all_selected = {folded(m["directory"]) for g in groups for m in g["modules"]}
        for group in groups:
            item = self._item(group)
            names = {m["directory"] for m in group["modules"]}
            record = state["installs"].get(group["id"])
            item["record_before"] = deepcopy(record)
            if not record or set(record.get("owned", [])) != names or set(record.get("files", {})) != names:
                plan["static_blockers"].append(f"{group['name']}：目录归属未确认，请先接管当前文件基线后重新预览")
            for name in sorted(names):
                target = inside(self.platform.game(), "Interface/AddOns/" + name)
                before = fingerprint(target)
                item["changes"].append({"directory": name, "action": "remove", "before": before, "after": None})
                for owner, other in state["installs"].items():
                    if owner != group["id"] and name in other.get("files", {}):
                        plan["static_blockers"].append(f"{name} 与 {owner} 共享目录，不能卸载")
                if record and (before or {}).get("files") != record.get("files", {}).get(name):
                    plan["static_blockers"].append(f"{name} 有本地修改，请先保留修改后重新预览")
            dependents = [m["directory"] for m in modules if folded(m["directory"]) not in all_selected
                          and m["compatibility"] != "inactive_flavor"
                          and {folded(n) for n in names}.intersection(folded(d) for d in m["dependencies"])]
            if dependents:
                plan["static_blockers"].append(f"{group['name']} 仍被 {', '.join(dependents)} 依赖；请先处理依赖插件")
            item["dependencies"] = sorted({d for m in group["modules"] for d in m["dependencies"]})
            plan["items"].append(item)

    def _prepare_enablement(self, plan, groups, modules, character_id):
        path, character = self._character(character_id)
        raw = path.read_bytes()
        _, _, states, _ = parse_addon_state(raw)
        installed = {m["directory"]: m for m in modules}
        names = {m["directory"] for g in groups for m in g["modules"] if m["compatibility"] != "inactive_flavor"}
        updates = {name: plan["action"] == "enable" for name in names}
        if not names:
            plan["static_blockers"].append("所选插件没有当前客户端的活动模块")
        if plan["action"] == "enable":
            visited, visiting = set(), set()

            def dependency(name):
                if name in visiting:
                    plan["static_blockers"].append(f"{name} 存在循环依赖，请检查插件依赖")
                    return
                if name in visited:
                    return
                visiting.add(name)
                module = installed.get(name)
                if not module or module["compatibility"] != "toc_supported":
                    plan["static_blockers"].append(f"{name} 未安装或未声明当前客户端支持")
                    visiting.remove(name)
                    return
                for dep in module["dependencies"]:
                    if dep.startswith("Blizzard_"):
                        continue
                    if dep not in installed:
                        if any(folded(dep) == folded(key) for key in installed):
                            plan["static_blockers"].append(f"{name} 依赖 {dep} 的目录大小写不一致，请检查作者发布包")
                        else:
                            plan["static_blockers"].append(f"{name} 缺少依赖 {dep}，请先安装依赖")
                        continue
                    updates[dep] = True
                    dependency(dep)
                visiting.remove(name)
                visited.add(name)

            for name in sorted(names):
                dependency(name)
        else:
            for module in modules:
                if module["directory"] in names or module["compatibility"] == "inactive_flavor" or not states.get(module["directory"], True):
                    continue
                needed = {d for d in module["dependencies"] if folded(d) in {folded(n) for n in names}}
                if needed:
                    plan["static_blockers"].append(f"{module['directory']} 正在使用 {', '.join(sorted(needed))}；不会自动停用它，请先单独处理")
        for group in groups:
            item = self._item(group)
            item["changes"] = [{"directory": m["directory"], "action": plan["action"],
                                "before": states.get(m["directory"], True), "after": updates[m["directory"]]}
                               for m in group["modules"] if m["directory"] in updates]
            item["to_version"] = item["from_version"]
            item["dependencies"] = sorted({d for m in group["modules"] for d in m["dependencies"] if not d.startswith("Blizzard_")})
            plan["items"].append(item)
        plan.update(character=character, character_id=character_id,
                    target=path.relative_to(self.platform.game()).as_posix(), before=fingerprint(path), updates=updates,
                    dependencies=[{"directory": name, "before": states.get(name, True), "after": value}
                                  for name, value in sorted(updates.items()) if name not in names],
                    modules_before={name: fingerprint(self.platform.game() / "Interface/AddOns" / name) for name in updates})
        output = self.directory / (plan["id"] + ".txt")
        atomic_bytes(output, render_addon_state(raw, updates))
        plan["after"] = fingerprint(output)

    def _reconcile(self, plan):
        # A stopped process cannot resume a partially consumed confirmation.
        # Derive item receipts from the journal, including an explicit recovery.
        interrupted = plan["status"] == "interrupted"
        if plan["status"] == "applying" and plan.get("pid"):
            try:
                os.kill(plan["pid"], 0)
            except ProcessLookupError:
                interrupted = True
        if interrupted:
            plan["status"] = "interrupted"
            journals = self.platform.tx.history()
            for item in plan["items"]:
                if item["status"] == "pending":
                    item.update(status="skipped", note="操作已中断，尚未执行；请重新准备")
                if item["status"] == "applying" or plan["action"] in ("enable", "disable"):
                    journal = next((j for j in journals
                                    if (j.get("context", {}).get("management_plan_id") == plan["id"]
                                        and j.get("context", {}).get("package_id") in (None, item["package_id"]))
                                    or (item.get("plan_id") and j.get("context", {}).get("plan_id") == item["plan_id"])), None)
                    if journal:
                        item.update(status=journal["status"], operation_id=journal["id"])
        return plan

    def review(self, op):
        plan = self._reconcile(self.load(op))
        blockers = list(plan["static_blockers"])
        if plan["game"] != str(self.platform.game()):
            blockers.append("客户端选择已变化，请重新生成计划")
        if time.time() >= plan["expires_at"]:
            blockers.append("计划已过期，请重新查看变更")
        if self.platform.tx.pending():
            blockers.append("有中断操作等待恢复")
        try:
            require_game_closed(self.root)
        except ValueError as exc:
            blockers.append(str(exc))
        if plan["status"] == "prepared":
            if plan["action"] == "update":
                for item in plan["items"]:
                    if item.get("plan_id"):
                        child = self.platform.review(item["plan_id"])
                        blockers.extend(f"{item['name']}：{message}" for message in child["blockers"])
                        if child["status"] != "prepared":
                            blockers.append(f"{item['name']} 的安装计划已被单独使用，请重新准备批量更新")
            else:
                modules = scan_addons(self.platform.game() / "Interface/AddOns")
                if self._graph(modules) != plan["graph_before"]:
                    blockers.append("插件模块或依赖已变化，请重新查看变更")
                if plan["action"] == "uninstall":
                    state = self.platform.tx.state()
                    for item in plan["items"]:
                        if state["installs"].get(item["package_id"]) != item["record_before"]:
                            blockers.append(f"{item['name']} 的管理记录已变化，请重新预览")
                        for change in item["changes"]:
                            try:
                                target = inside(self.platform.game(), "Interface/AddOns/" + change["directory"])
                                if fingerprint(target) != change["before"]:
                                    blockers.append(f"{change['directory']} 自预览后发生变化")
                                if any(owner != item["package_id"] and change["directory"] in record.get("files", {})
                                       for owner, record in state["installs"].items()):
                                    blockers.append(f"{change['directory']} 出现共享目录归属，不能卸载")
                            except (ValueError, OSError) as exc:
                                blockers.append(str(exc))
                else:
                    try:
                        target = self.profiles.character_path(plan["character_id"])
                        if target.relative_to(self.platform.game()).as_posix() != plan["target"] or fingerprint(target) != plan["before"]:
                            blockers.append("角色启用状态已变化，请重新预览")
                        if fingerprint(self.directory / (op + ".txt")) != plan["after"]:
                            blockers.append("暂存启用状态发生变化，请重新预览")
                        for name, before in plan["modules_before"].items():
                            if fingerprint(inside(self.platform.game(), "Interface/AddOns/" + name)) != before:
                                blockers.append(f"{name} 文件发生变化，请重新预览")
                    except (ValueError, OSError) as exc:
                        blockers.append(str(exc))
        return {**plan, "blockers": list(dict.fromkeys(blockers)),
                "can_apply": not blockers and plan["status"] == "prepared"}

    @tracked("应用管理变更")
    def apply(self, op):
        with self.platform.lock():
            reviewed = self.review(op)
            if not reviewed["can_apply"]:
                raise ValueError("；".join(reviewed["blockers"]) or "计划已使用，请查看逐项结果")
            plan = self.load(op)
            plan["status"] = "applying"
            plan["pid"] = os.getpid()
            self._save(plan)
            task_progress("applying", plan_id=op, plan_kind="management", items_total=len(plan["items"]))
            if plan["action"] in ("enable", "disable"):
                try:
                    state = self.platform.tx.state()
                    # A package toggle may invalidate a remembered UI combination.
                    state.setdefault("profiles", {}).pop(plan["character_id"], None)
                    journal = self.platform.tx.execute(self.platform.game(), plan["action"] + ":" + ",".join(plan["package_ids"]),
                                                       [(plan["target"], self.directory / (op + ".txt"))], state,
                                                       context={"management_plan_id": op})
                    for item in plan["items"]:
                        item.update(status="applied", operation_id=journal["id"])
                except Exception as exc:
                    for item in plan["items"]:
                        item.update(status="failed", error=str(exc))
                except BaseException:
                    plan["status"] = "interrupted"
                    self._save(plan)
                    raise
            else:
                for index, item in enumerate(plan["items"]):
                    task_progress("applying", items_completed=index, package_id=item["package_id"])
                    item["status"] = "applying"
                    self._save(plan)
                    try:
                        require_game_closed(self.root)
                        if plan["action"] == "update":
                            result = self.platform.apply_locked(item["plan_id"])
                        else:
                            state = self.platform.tx.state()
                            state["installs"].pop(item["package_id"], None)
                            changes = [("Interface/AddOns/" + c["directory"], None) for c in item["changes"]]
                            # Preflight again immediately before each transaction.
                            for change in item["changes"]:
                                if fingerprint(inside(self.platform.game(), "Interface/AddOns/" + change["directory"])) != change["before"]:
                                    raise ValueError("文件在应用期间发生变化，已停止剩余项目")
                            result = self.platform.tx.execute(self.platform.game(), "uninstall:" + item["package_id"], changes, state,
                                                              context={"management_plan_id": op, "package_id": item["package_id"]})
                        item.update(status="applied", operation_id=result["id"])
                        self._save(plan)
                    except Exception as exc:
                        item.update(status="failed", error=str(exc))
                        for remaining in plan["items"][index + 1:]:
                            remaining.update(status="skipped", note="前一项目失败，尚未执行")
                        break
                    except BaseException:
                        plan["status"] = "interrupted"
                        self._save(plan)
                        raise
            plan["status"] = "applied" if all(i["status"] == "applied" for i in plan["items"]) else "failed"
            plan["finished_at"] = time.time()
            self._save(plan)
            task_progress("completed" if plan["status"] == "applied" else "stopped",
                          items_completed=sum(i["status"] == "applied" for i in plan["items"]))
            return self.review(op)
