"""One service for desktop and MCP: inventory, staging, plans and transactions."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import plistlib
import subprocess
import time
from urllib.parse import urlsplit
import uuid
import zipfile

from .addon_archive import check_references, unpack
from .addon_metadata import INTERFACE, SOURCES, packages, read_toc, scan_addons
from .addon_sources import CATALOG, CurseForgeAdapter, author_release, fetch, same_version
from .paths import default_roots, game_flavors
from .platform_io import (MAX_UPLOAD, digest_file, folded, game_running, identifier, inside, manifest,
                          operation_lock, read_json, require_game_closed, write_json)
from .platform_transactions import Transactions, fingerprint
from .platform_tasks import tracked, task_receipts

BATTLE_NET_APPS = (Path("/Applications/Battle.net.app"), Path.home() / "Applications/Battle.net.app")


class AddonPlatform:
    def __init__(self, settings, path_provider=None):
        self.settings, self.path_provider = settings, path_provider
        self.root = settings.data_dir / "platform" / settings.mode
        for name in ("plans", "staging", "uploads", "workspaces", "profile-snapshots"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.tx = Transactions(self.root)
        self.curseforge = CurseForgeAdapter()
        if settings.mode == "mock" and not settings.game_path:
            sandbox = self.root / "game/_forever_"
            (sandbox / "Interface/AddOns").mkdir(parents=True, exist_ok=True)
            (sandbox / "WTF").mkdir(exist_ok=True)

    def lock(self):
        return operation_lock(self.root)

    def game(self) -> Path:
        if self.settings.mode == "mock" and not self.settings.game_path:
            return self.root / "game/_forever_"
        selected = self.path_provider() if self.path_provider else self.settings.game_path
        roots = [Path(selected)] if selected else default_roots()
        choices = list(dict.fromkeys(p.resolve() for root in roots for p in game_flavors(root)))
        if len(choices) != 1:
            raise ValueError("没有唯一的无限客户端，请在连接设置中选择 _forever_ 目录")
        game = choices[0]
        if game.name in ("_retail_", "_classic_", "_classic_era_"):
            raise ValueError("仅支持国服无限客户端")
        inside(game, "Interface/AddOns")
        inside(game, "WTF")
        return game

    def client(self):
        game = self.game()
        build = None
        info = game.parent / ".build.info"
        if info.is_file() and info.stat().st_size < 1024 * 1024:
            lines = info.read_text(errors="replace").splitlines()
            if lines:
                fields = [x.split("!")[0] for x in lines[0].split("|")]
                for row in lines[1:]:
                    record = dict(zip(fields, row.split("|")))
                    if record.get("Active") == "1" and record.get("Product") == "wowf":
                        build = record.get("Version")
                        break
        return {"path": str(game), "flavor": game.name, "build": build, "interface": INTERFACE,
                "runtime_verified": False, "mode": self.settings.mode}

    def inventory(self):
        state = self.tx.state()
        try:
            client = self.client()
            modules = scan_addons(self.game() / "Interface/AddOns")
            groups = packages(modules, state["installs"])
            errors = []
        except ValueError as exc:
            client, modules, groups, errors = None, [], [], [str(exc)]
        for group in groups:
            record = state["installs"].get(group["id"])
            group["modified"] = False
            if record:
                try:
                    group["modified"] = any(manifest(self.game() / "Interface/AddOns" / name) != hashes for name, hashes in record["files"].items())
                except (ValueError, OSError):
                    group["modified"] = True
            cached = state.get("updates", {}).get(group["id"])
            if cached and group["source"] not in ("workshop", "bundled") and cached.get("installed_version") == group["version"]:
                group["update"] = cached
                group["update_status"] = cached["status"]
            group["issues"] = list(dict.fromkeys(i for m in group["modules"] for i in m["issues"]))
        names = {m["directory"] for m in modules}
        diagnostics = [{"level": "error", "message": f"{m['directory']} 缺少依赖 {d}",
                        "repair": "bigwigs" if d == "BigWigs" else None} for m in modules if m["compatibility"] != "inactive_flavor" for d in m["missing_dependencies"]]
        diagnostics += [{"level": "error", "message": f"{m['directory']} 未声明 Interface 16001", "repair": None}
                        for m in modules if m["compatibility"] == "incompatible"]
        if "EllesmereUI" in names and "ForeverUI" in names:
            diagnostics.append({"level": "warning", "message": "EllesmereUI 与 ForeverUI 有界面功能重叠；请按角色选择一套组合", "repair": "profiles"})
        if "DBM-Core" in names and "BigWigs" in names:
            diagnostics.append({"level": "warning", "message": "DBM 与 BigWigs 均已安装，请在游戏内确认副本提示方案；不会自动停用或替换", "repair": None})
        return {"client": client, "module_count": len(modules), "packages": groups, "diagnostics": diagnostics,
                "errors": errors, "game_running": game_running(), "pending": self.tx.pending(),
                "curseforge": self.curseforge.status, "catalog": CATALOG, "launch": self.launch_status()}

    def game_application(self):
        if self.settings.mode != "live":
            raise ValueError("演示模式不启动真实游戏，请打开真实客户端模式")
        game = self.game()
        if game.name != "_forever_":
            raise ValueError("启动入口只支持当前 _forever_ 无限客户端")
        application = inside(game, "World of Warcraft.app")
        info = inside(game, "World of Warcraft.app/Contents/Info.plist")
        executable = inside(game, "World of Warcraft.app/Contents/MacOS/World of Warcraft")
        if not info.is_file() or info.stat().st_size > 128 * 1024 or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("未找到完整的无限 Mac 客户端，请在战网完成安装或修复")
        try:
            data = plistlib.loads(info.read_bytes())
        except (ValueError, plistlib.InvalidFileException):
            raise ValueError("游戏应用元数据不可读，请在战网检查安装") from None
        if not isinstance(data, dict) or data.get("CFBundleIdentifier") != "com.blizzard.worldofwarcraft" or not str(data.get("CFBundleShortVersionString", "")).startswith("1.60."):
            raise ValueError("游戏应用不是已识别的国服无限客户端")
        return application

    def battle_net_application(self):
        self.game_application()
        for application in BATTLE_NET_APPS:
            info = inside(application, "Contents/Info.plist")
            executable = inside(application, "Contents/MacOS/Battle.net")
            if not info.is_file() or info.stat().st_size > 128 * 1024 or not executable.is_file() or not os.access(executable, os.X_OK):
                continue
            try:
                data = plistlib.loads(info.read_bytes())
            except (ValueError, plistlib.InvalidFileException):
                continue
            if isinstance(data, dict) and data.get("CFBundleIdentifier") == "net.battle.app":
                return application
        raise ValueError("未找到战网 Mac 应用，请先安装或修复战网；游戏入口需要通过战网登录")

    def launch_status(self):
        try:
            self.battle_net_application()
            running = game_running()
            launch = read_json(self.root / "game-launch.json", {})
            starting = not running and launch.get("status") == "starting" and time.time() - launch.get("created_at", 0) < 30
            return {"available": True, "running": running, "starting": starting,
                    "via": "battlenet", "product": "wowf",
                    "note": "游戏运行中" if running else "游戏启动中" if starting else "通过战网进入《无限》，使用战网已有登录态"}
        except (ValueError, OSError) as exc:
            return {"available": False, "running": False, "starting": False, "note": str(exc)}

    @tracked("打开战网 · 无限")
    def launch_game(self):
        with self.lock():
            application = self.battle_net_application()
            if self.tx.pending():
                raise ValueError("有插件操作等待恢复，请先恢复中断后再启动游戏")
            status = self.launch_status()
            if status["running"] or status["starting"]:
                return {"status": "already_running" if status["running"] else "starting", "note": status["note"]}
            try:
                subprocess.run(["/usr/bin/open", str(application)], check=True, capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError) as exc:
                record = {"status": "failed", "created_at": time.time(), "via": "battlenet"}
                write_json(self.root / "game-launch.json", record)
                raise ValueError("macOS 未能打开战网，请检查战网安装后重试") from exc
            # Opening the launcher does not start WoW. Keep addon preparation and
            # application available until a real game process is detected.
            record = {"status": "battlenet_opened", "created_at": time.time(), "game": str(self.game()), "via": "battlenet"}
            write_json(self.root / "game-launch.json", record)
            return {"status": "battlenet_opened", "via": "battlenet", "note": "已打开战网，请选择《无限》并点击「进入游戏」，沿用战网登录状态。"}

    def adopt(self, key: str):
        identifier(key)
        with self.lock():
            if self.tx.pending():
                raise ValueError("请先恢复中断操作")
            group = next((g for g in self.inventory()["packages"] if g["id"] == key), None)
            if not group:
                raise ValueError("插件包不存在")
            # Explicit baseline adoption acknowledges current files. It does not
            # grant unattended updates or write anything to the game directory.
            state = self.tx.state()
            old = state["installs"].get(key, {})
            state["installs"][key] = {"version": group["version"], "source": group["source"],
                "files": {m["directory"]: manifest(self.game() / "Interface/AddOns" / m["directory"]) for m in group["modules"]},
                "owned": old.get("owned", []), "adopted_at": time.time()}
            self.tx.save_state(state)
            return {"package_id": key, "status": "adopted", "note": "已记录当前文件基线；后续变化将暂停覆盖"}

    @tracked("检查作者更新")
    def check_updates(self, key: str | None = None):
        groups = self.inventory()["packages"]
        if key:
            groups = [g for g in groups if g["id"] == identifier(key)]
            if not groups:
                raise ValueError("插件包不存在")
        updates = {}
        # Network IO is read-only and stays outside the mutation lock.
        for group in groups:
            item = {"installed_version": group["version"], "checked_at": time.time()}
            if not group.get("repo") or group["source"] in ("workshop", "bundled"):
                item.update(status=group["update_status"], note="需官网检查" if group["source"] == "curseforge" else "本地版本" if group["source"] in ("workshop", "bundled") else "来源待绑定")
            else:
                try:
                    release = author_release(group["id"])
                    status = "current" if same_version(group["version"], release["version"]) else "release_differs" if group["version"] else "version_unknown"
                    item.update(status=status, release=release, note="已核对作者 Forever 发布；游戏内加载待验证")
                except ValueError as exc:
                    item.update(status="unknown", note=str(exc))
            updates[group["id"]] = item
        with self.lock():
            state = self.tx.state()
            state.setdefault("updates", {}).update(updates)
            self.tx.save_state(state)
        return updates

    @tracked("准备作者发布包")
    def download(self, key: str):
        identifier(key)
        release = author_release(key)
        archive = self.root / "uploads" / (uuid.uuid4().hex + ".zip")
        try:
            fetch(release["url"], MAX_UPLOAD, archive)
            if archive.stat().st_size != release["size"]:
                raise ValueError("下载长度与作者发布资产不一致")
            if release.get("sha256") and digest_file(archive) != release["sha256"]:
                raise ValueError("作者发布资产 SHA256 校验失败")
            return self.stage(archive, package_id=key, provenance=release)
        finally:
            archive.unlink(missing_ok=True)

    def bundled(self, name: str):
        if name not in ("ForeverAI", "ForeverUI"):
            raise ValueError("未知内置插件")
        source = Path(__file__).resolve().parents[1] / "addons" / name
        archive = self.root / "uploads" / (uuid.uuid4().hex + ".zip")
        files = manifest(source)
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for filename in files:
                z.write(source / filename, name + "/" + filename)
        try:
            return self.stage(archive, package_id="local-" + name,
                              provenance={"declaration": "bundled", "version": read_toc(source)["version"], "source_url": None})
        finally:
            archive.unlink(missing_ok=True)

    def stage(self, archive: Path, package_id: str | None = None, provenance: dict | None = None,
              source_url: str = "", forever_confirmed: bool = False, original_filename: str | None = None):
        with self.lock():
            game = self.game()
            op = uuid.uuid4().hex
            stage = self.root / "staging" / op
            directories = unpack(archive, stage)
            provenance = deepcopy(provenance or {})
            if not provenance:
                # A downloaded ZIP may carry an author release manifest itself.
                metadata = stage / "release.json"
                if metadata.is_file():
                    data = read_json(metadata, {})
                    candidates = [r for r in data.get("releases", []) if r.get("filename") == (original_filename or archive.name) and
                                  any(m.get("flavor") == "forever" and m.get("interface") == INTERFACE for m in r.get("metadata", []))]
                    if len(candidates) == 1:
                        provenance = {"declaration": "zip_manifest", "version": candidates[0].get("version"), "manifest": candidates[0]}
                if forever_confirmed:
                    parsed = urlsplit(source_url)
                    if parsed.scheme != "https" or parsed.hostname not in ("www.curseforge.com", "curseforge.com") or not parsed.path.startswith("/wow/addons/") or parsed.username:
                        raise ValueError("请提供 CurseForge 插件的 Forever 文件页面链接")
                    provenance = {"declaration": "user_confirmed_curseforge", "source_url": source_url,
                                  "note": "用户在官网确认了 Forever 文件；平台未调用官方 API 核验"}
            if package_id is None:
                owners = {g["id"] for g in self.inventory()["packages"] if any(m["directory"] in directories for m in g["modules"])}
                package_id = next(iter(owners)) if len(owners) == 1 else "local-" + next(iter(directories)) if len(directories) == 1 else "import-" + op[:12]
            identifier(package_id)
            state = self.tx.state()
            record = state["installs"].get(package_id, {})
            retired = sorted(set(record.get("owned", [])) - set(directories))
            toc = [read_toc(path) for path in directories.values()]
            files = {name: manifest(folder) for name, folder in directories.items()}
            changes = []
            for name in sorted(set(directories) | set(retired)):
                current = game / "Interface/AddOns" / name
                try:
                    before = fingerprint(current)
                except ValueError as exc:
                    before = {"unsafe": str(exc)}
                after = {"kind": "directory", "files": files[name]} if name in files else None
                old_files = before.get("files", {}) if before else {}
                new_files = files.get(name, {})
                changes.append({"directory": name, "before": before, "after": after,
                    "action": "remove" if after is None else "update" if before else "install",
                    "added": sorted(set(new_files) - set(old_files)), "removed": sorted(set(old_files) - set(new_files)),
                    "modified": sorted(f for f in new_files.keys() & old_files.keys() if new_files[f] != old_files[f])})
            blockers = []
            if not any(item["compatibility"] == "toc_supported" for item in toc):
                blockers.append("发布包没有支持当前无限 Interface 16001 的活动模块")
            if not provenance.get("declaration"):
                blockers.append("缺少发布包 Forever 支持声明；仅改 Interface 号不能证明兼容。请使用作者发布源或确认官网 Forever 文件后重新导入")
            for item in toc:
                if item["compatibility"] not in ("toc_supported", "inactive_flavor"):
                    blockers.append(f"{item['directory']} 的活动 TOC 未声明 Interface 16001")
                blockers.extend(f"{item['directory']}：{i}" for i in check_references(directories[item['directory']], next(iter(directories.values())).parent))
            if package_id in SOURCES and SOURCES[package_id].get("repo"):
                expected = SOURCES[package_id]
                core = next((x for x in toc if x["directory"] == expected["core"]), None)
                if not core or core["compatibility"] != "toc_supported" or core["metadata"].get("x-curse-project-id") != expected["curse_id"]:
                    blockers.append("发布包核心身份与所选作者源不一致")
            plan = {"id": op, "kind": "addons", "status": "prepared", "created_at": time.time(), "game": str(game),
                    "package_id": package_id, "provenance": provenance, "toc": toc, "files": files,
                    "directories": {name: str(folder.relative_to(self.root)) for name, folder in directories.items()},
                    "changes": changes, "static_blockers": list(dict.fromkeys(blockers)),
                    "record_before": record or None, "version": provenance.get("version") or (toc[0]["version"] if len(toc) == 1 else None)}
            write_json(self.root / "plans" / (op + ".json"), plan)
            return self.review(op)

    def load_plan(self, op):
        identifier(op)
        plan = read_json(self.root / "plans" / (op + ".json"))
        if not plan:
            raise ValueError("安装计划不存在")
        return plan

    def review(self, op):
        plan = self.load_plan(op)
        blockers = list(plan["static_blockers"])
        game, state = self.game(), self.tx.state()
        if str(game) != plan["game"]:
            blockers.append("客户端选择已变化，请重新生成计划")
        current_modules = scan_addons(game / "Interface/AddOns")
        retiring = {c["directory"] for c in plan["changes"] if c["action"] == "remove"}
        available = ({m["directory"] for m in current_modules if m["compatibility"] == "toc_supported"} |
                     {m["directory"] for m in plan["toc"] if m["compatibility"] == "toc_supported"}) - retiring
        missing = sorted({dep for m in plan["toc"] if m["compatibility"] != "inactive_flavor" for dep in m["dependencies"] if dep not in available and not dep.startswith("Blizzard_")})
        if missing:
            blockers.append("缺少依赖：" + ", ".join(missing))
        # An update may remove a module another installed addon still requires.
        if any(dep in retiring for m in current_modules if m["directory"] not in retiring for dep in m["dependencies"]):
            blockers.append("将移除其他插件仍依赖的模块")
        record = state["installs"].get(plan["package_id"], {})
        for change in plan["changes"]:
            name = change["directory"]
            current = game / "Interface/AddOns" / name
            try:
                current_fp = fingerprint(current)
                if current_fp != change["before"]:
                    blockers.append(f"{name} 自计划生成后发生变化，请重新生成计划")
                if current_fp is not None:
                    baseline = record.get("files", {}).get(name)
                    if baseline is None:
                        blockers.append(f"{name} 已存在但尚未接管文件基线；请先接管，再重新生成计划")
                    elif current_fp.get("files") != baseline:
                        blockers.append(f"{name} 有本地修改，暂停覆盖；请复制到开发工作区并保留修改")
                for owner, item in state["installs"].items():
                    if owner != plan["package_id"] and name in item["files"]:
                        blockers.append(f"目录 {name} 属于其他已管理插件包 {owner}")
                if name in plan["directories"] and manifest(inside(self.root, plan["directories"][name])) != plan["files"][name]:
                    blockers.append(f"{name} 暂存内容发生变化，请重新生成计划")
            except (ValueError, OSError) as exc:
                blockers.append(f"{name}：{exc}")
        if (record or None) != plan.get("record_before"):
            blockers.append("接管基线已变化，请重新生成计划")
        # Protect case-insensitive macOS destinations and untracked directories.
        existing = {folded(m["directory"]): m["directory"] for m in current_modules}
        for name in plan["directories"]:
            if folded(name) in existing and existing[folded(name)] != name:
                blockers.append(f"目录大小写冲突：{name}")
        if self.tx.pending():
            blockers.append("有中断操作等待恢复")
        running = game_running()
        if running:
            blockers.append("游戏仍在运行，退出后再应用")
        elif self.launch_status()["starting"]:
            blockers.append("游戏正在启动，请等待启动完成并退出游戏后再应用")
        return {**plan, "blockers": list(dict.fromkeys(blockers)), "missing_dependencies": missing,
                "can_apply": not blockers and plan["status"] == "prepared", "game_running": running}

    def apply(self, op):
        with self.lock():
            plan = self.review(op)
            if not plan["can_apply"]:
                raise ValueError("；".join(plan["blockers"]) or "计划已应用")
            require_game_closed(self.root)
            state = self.tx.state()
            state["installs"][plan["package_id"]] = {"version": plan["version"], "source": plan["provenance"],
                "files": plan["files"], "owned": list(plan["directories"]), "installed_at": time.time()}
            changes = [("Interface/AddOns/" + c["directory"], inside(self.root, plan["directories"][c["directory"]]) if c["action"] != "remove" else None) for c in plan["changes"]]
            journal = self.tx.execute(self.game(), "addons:" + plan["package_id"], changes, state)
            saved = self.load_plan(op)
            saved.update(status="applied", operation_id=journal["id"])
            write_json(self.root / "plans" / (op + ".json"), saved)
            return {"id": journal["id"], "status": journal["status"], "plan_id": op}

    def history(self):
        # Hide file hashes and account path details from the overview.
        return [{k: j.get(k) for k in ("id", "kind", "status", "created_at", "error", "rollback_id")}
                for j in self.tx.history()]

    def rollback(self, op):
        with self.lock():
            if self.tx.get(op)["game"] != str(self.game()):
                raise ValueError("此操作属于其他客户端，请先切回相应客户端")
            return self.tx.rollback(op)

    def recover(self, op):
        with self.lock():
            if self.tx.get(op)["game"] != str(self.game()):
                raise ValueError("此操作属于其他客户端，请先切回相应客户端")
            return self.tx.recover(op)

    def plans(self):
        return sorted([{"id": p["id"], "kind": p["kind"], "package_id": p["package_id"], "status": p["status"], "created_at": p["created_at"]}
                       for path in (self.root / "plans").glob("*.json") if (p := read_json(path))], key=lambda x: x["created_at"], reverse=True)

    def tasks(self):
        return task_receipts(self.root)

    def check_due(self):
        state = self.tx.state()
        for group in self.inventory()["packages"]:
            if group.get("repo") and group["source"] not in ("workshop", "bundled") and time.time() - state.get("updates", {}).get(group["id"], {}).get("checked_at", 0) > 21600:
                self.check_updates(group["id"])
