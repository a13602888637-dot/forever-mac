"""Offline, versioned copies. Third-party Lua is compiled only, never executed."""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import time
import uuid
import zipfile

from .addon_archive import check_references
from .addon_metadata import INTERFACE, read_toc
from .platform_io import (atomic_bytes, digest_file, identifier, inside, manifest,
                          read_json, write_json)
from .platform_tasks import tracked

EDITABLE = {".lua", ".toc", ".xml", ".json", ".txt", ".md"}
MAX_TEXT = 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Workshop:
    def __init__(self, platform):
        self.platform, self.root = platform, platform.root / "workspaces"
        for name in ("workspace-baselines", "workspace-history", "exports"):
            (platform.root / name).mkdir(exist_ok=True)

    def project(self, project_id):
        path = inside(self.root, identifier(project_id))
        metadata = read_json(path / "project.json")
        if not metadata:
            raise ValueError("工作区不存在")
        return path, metadata

    def projects(self):
        return sorted([read_json(p) for p in self.root.glob("*/project.json")], key=lambda p: p["created_at"], reverse=True)

    def create(self, name: str, description: str = ""):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,60}", name):
            raise ValueError("插件名需以英文字母开头，只含英文字母、数字和下划线，最长 61 字符")
        if len(description) > 1000:
            raise ValueError("描述过长")
        with self.platform.lock():
            op = uuid.uuid4().hex
            path = self.root / op
            addon = path / "addons" / name
            addon.mkdir(parents=True)
            # No injected description appears in executable code or TOC fields.
            (addon / (name + "_Camelot.toc")).write_text(f"## Interface: {INTERFACE}\n## Title: {name}\n## Version: 0.1.0\n## Notes: Offline workshop addon for WoW Forever\nCore.lua\n")
            (addon / "Core.lua").write_text('local addonName, addon = ...\nlocal frame = CreateFrame("Frame")\nframe:RegisterEvent("PLAYER_LOGIN")\nframe:SetScript("OnEvent", function()\n    print(addonName .. " loaded")\nend)\n')
            metadata = {"id": op, "name": name, "description": description, "created_at": time.time(),
                        "source": "created", "baseline": {}, "client": self.platform.client(), "package_id": "local-" + name}
            write_json(path / "project.json", metadata)
            return metadata

    def clone(self, package_id: str):
        with self.platform.lock():
            group = next((g for g in self.platform.inventory()["packages"] if g["id"] == package_id), None)
            if not group:
                raise ValueError("已装插件包不存在")
            op = uuid.uuid4().hex
            path, baseline = self.root / op / "addons", self.platform.root / "workspace-baselines" / op
            path.mkdir(parents=True)
            baseline.mkdir(parents=True)
            for module in group["modules"]:
                name = identifier(module["directory"])
                source = inside(self.platform.game(), "Interface/AddOns/" + name)
                manifest(source)
                shutil.copytree(source, path / name)
                shutil.copytree(source, baseline / name)
            files = manifest(path)
            metadata = {"id": op, "name": group["name"], "description": "已装插件的离线副本", "created_at": time.time(),
                        "source": "cloned", "baseline": files, "client": self.platform.client(), "package_id": package_id}
            write_json(path.parent / "project.json", metadata)
            return metadata

    def files(self, project_id):
        path, _ = self.project(project_id)
        files = manifest(path / "addons")
        return [{"path": "addons/" + name, "sha256": digest, "bytes": (path / "addons" / name).stat().st_size,
                 "editable": Path(name).suffix.lower() in EDITABLE and (path / "addons" / name).stat().st_size <= MAX_TEXT}
                for name, digest in sorted(files.items())]

    def text_path(self, project_id, name):
        path, _ = self.project(project_id)
        file = inside(path, name)
        if not file.is_relative_to(path / "addons") or file.suffix.lower() not in EDITABLE:
            raise ValueError("只允许访问工作区 addons 中的源码文本文件")
        if file.exists() and (not file.is_file() or file.stat().st_size > MAX_TEXT):
            raise ValueError("文件不适合文本编辑或超过 1 MiB")
        return file

    def read(self, project_id, name):
        file = self.text_path(project_id, name)
        if not file.exists():
            raise ValueError("文件不存在")
        try:
            with file.open("rb") as stream:
                raw = stream.read(MAX_TEXT + 1)
            if len(raw) > MAX_TEXT:
                raise ValueError("源码超过 1 MiB")
            return {"path": name, "content": raw.decode("utf-8-sig"), "sha256": hashlib.sha256(raw).hexdigest()}
        except UnicodeDecodeError:
            raise ValueError("文件不是 UTF-8 文本") from None

    def write(self, project_id, name, content, expected_sha256: str | None = None):
        if len(content.encode()) > MAX_TEXT or "\x00" in content:
            raise ValueError("文本超过 1 MiB 或包含空字节")
        with self.platform.lock():
            file = self.text_path(project_id, name)
            current = digest_file(file) if file.exists() else None
            if current != expected_sha256:
                raise ValueError("文件已变化，请重新读取文件及 sha256 后保存")
            revision = uuid.uuid4().hex
            history = self.platform.root / "workspace-history" / project_id / revision
            history.mkdir(parents=True)
            before = file.read_bytes() if file.exists() else None
            if before is not None:
                atomic_bytes(history / "before", before)
            atomic_bytes(file, content.encode())
            record = {"id": revision, "project_id": project_id, "path": name, "created_at": time.time(),
                      "before": current, "after": digest_file(file), "status": "saved"}
            write_json(history / "revision.json", record)
            return record

    def history(self, project_id):
        self.project(project_id)
        return sorted([read_json(p) for p in (self.platform.root / "workspace-history" / project_id).glob("*/revision.json")], key=lambda p: p["created_at"], reverse=True)

    def revert(self, project_id, revision):
        with self.platform.lock():
            identifier(revision)
            root = self.platform.root / "workspace-history" / project_id / revision
            self.project(project_id)
            record = read_json(root / "revision.json")
            if not record or record["status"] != "saved":
                raise ValueError("修改记录不存在或已撤销")
            file = self.text_path(project_id, record["path"])
            if not file.is_file() or digest_file(file) != record["after"]:
                raise ValueError("文件已再次修改，不能直接撤销此版本")
            before = root / "before"
            if record["before"]:
                if digest_file(before) != record["before"]:
                    raise ValueError("历史备份校验失败")
                atomic_bytes(file, before.read_bytes())
            else:
                file.unlink()
            record["status"] = "reverted"
            write_json(root / "revision.json", record)
            return record

    def diff(self, project_id):
        path, meta = self.project(project_id)
        current, before = manifest(path / "addons"), meta["baseline"]
        entries, text = [], []
        remaining = 200000
        for name in sorted(current.keys() | before.keys()):
            if current.get(name) == before.get(name):
                continue
            entries.append({"path": "addons/" + name, "action": "added" if name not in before else "removed" if name not in current else "modified"})
            old = self.platform.root / "workspace-baselines" / project_id / name
            new = path / "addons" / name
            if Path(name).suffix.lower() in EDITABLE and remaining > 0:
                try:
                    a = old.read_text().splitlines(True) if old.exists() and old.stat().st_size <= MAX_TEXT else []
                    b = new.read_text().splitlines(True) if new.exists() and new.stat().st_size <= MAX_TEXT else []
                    delta = "".join(difflib.unified_diff(a, b, "before/" + name, "workspace/" + name))
                    text.append(delta[:remaining])
                    remaining -= len(delta)
                except UnicodeDecodeError:
                    pass
        return {"entries": entries, "diff": "\n".join(text), "truncated": remaining <= 0}

    def api(self, query: str):
        if not query.strip() or len(query) > 100:
            raise ValueError("请提供 1–100 字符的 API 名称")
        evidence = json.loads((PROJECT_ROOT / "docs/api-evidence.json").read_text())
        matches = [{"name": name, **value} for name, value in evidence["functions"].items() if query.casefold() in name.casefold()][:50]
        client = self.platform.client()
        return {"query": query, "client_build": client["build"], "reference_build": evidence["reference_build"],
                "source": evidence["source"], "retrieved_at": evidence["retrieved_at"], "matches": matches,
                "version_matches": client["build"] == evidence["reference_build"],
                "note": "公开 API 资料缓存；不是完整 API 清单。未命中不代表 API 缺失，运行与战斗保护需在游戏内验证。"}

    def validate(self, project_id):
        path, metadata = self.project(project_id)
        files = manifest(path / "addons")
        errors, warnings, checked, api_candidates = [], [], 0, set()
        from lupa.lua51 import LuaRuntime
        lua = LuaRuntime(unpack_returned_tuples=True, max_memory=64 * 1024 * 1024)
        compile_only = lua.eval('function(code, name) local chunk, err = loadstring(code, name); return chunk ~= nil, err end')
        for name in files:
            file = path / "addons" / name
            if file.suffix.lower() != ".lua":
                continue
            if file.stat().st_size > 8 * 1024 * 1024:
                errors.append({"path": name, "message": "Lua 超过 8 MiB 编译限制"})
                continue
            raw = file.read_bytes()
            if raw.startswith(b"\x1b"):
                errors.append({"path": name, "message": "不接受 Lua 字节码"})
                continue
            try:
                content = raw.decode("utf-8-sig")
                ok, message = compile_only(content, "@" + name)
                checked += 1
                if not ok:
                    errors.append({"path": name, "message": message})
                api_candidates.update(re.findall(r"\bC_[A-Za-z0-9_]+\.[A-Za-z0-9_]+\b", content))
            except (ValueError, UnicodeDecodeError, MemoryError) as exc:
                errors.append({"path": name, "message": str(exc)})
        addons = [p for p in (path / "addons").iterdir() if p.is_dir()]
        if not addons:
            errors.append({"path": "addons", "message": "没有插件目录"})
        for addon in addons:
            toc = read_toc(addon)
            if toc["compatibility"] not in ("toc_supported", "inactive_flavor"):
                errors.append({"path": addon.name, "message": "活动 TOC 未声明 Interface 16001"})
            errors.extend({"path": addon.name, "message": issue} for issue in check_references(addon, path / "addons"))
        evidence = json.loads((PROJECT_ROOT / "docs/api-evidence.json").read_text())
        unverified = sorted(api_candidates - evidence["functions"].keys())
        warnings.append("Lua 5.1 仅编译，未执行插件源码；布局、动作条与战斗保护需游戏内验收")
        if evidence["reference_build"] != self.platform.client()["build"]:
            warnings.append(f"API 缓存版本 {evidence['reference_build']}，与当前客户端版本未确认一致")
        return {"passed": not errors, "syntax_errors": errors, "missing_apis": [], "unverified_apis": unverified,
                "warnings": warnings, "lua_files_compiled": checked, "lua_version": "5.1", "executed": False,
                "reference_build": evidence["reference_build"], "client": self.platform.client(),
                "client_at_creation": metadata["client"]}

    @tracked("检查并打包工作区")
    def pack(self, project_id):
        with self.platform.lock():
            report = self.validate(project_id)
            if not report["passed"]:
                raise ValueError("检查未通过，请先修复语法和 TOC 引用")
            path, metadata = self.project(project_id)
            files = manifest(path / "addons")
            export_id = uuid.uuid4().hex
            target = self.platform.root / "exports" / (export_id + ".zip")
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
                for name in sorted(files):
                    z.write(path / "addons" / name, name)
                z.writestr("release.json", json.dumps({"releases": [{"name": metadata["name"], "version": "workshop-" + export_id[:8],
                    "filename": target.name, "metadata": [{"flavor": "forever", "interface": INTERFACE}]}]}))
            if manifest(path / "addons") != files:
                target.unlink(missing_ok=True)
                raise ValueError("打包期间源码发生变化，请重新检查并打包")
            record = {"id": export_id, "project_id": project_id, "sha256": digest_file(target), "files": files,
                      "created_at": time.time(), "package_id": metadata["package_id"]}
            write_json(target.with_suffix(".json"), record)
            return {**record, "url": "/api/workshop/exports/" + export_id}

    def export_path(self, export_id):
        identifier(export_id)
        target = inside(self.platform.root / "exports", export_id + ".zip")
        record = read_json(target.with_suffix(".json"))
        if not record or digest_file(target) != record["sha256"]:
            raise ValueError("打包文件不存在或校验失败")
        return target, record

    def install_plan(self, export_id):
        target, record = self.export_path(export_id)
        return self.platform.stage(target, package_id=record["package_id"], provenance={"declaration": "workshop",
            "version": "workshop-" + export_id[:8], "export_id": export_id, "source_url": None,
            "note": "离线工作区产物；仅通过编译与静态检查，游戏内行为待验证"})

    def read_installed(self, package_id, directory, name):
        group = next((g for g in self.platform.inventory()["packages"] if g["id"] == package_id), None)
        if not group or directory not in {m["directory"] for m in group["modules"]}:
            raise ValueError("插件目录不属于此包")
        root = inside(self.platform.game(), "Interface/AddOns/" + identifier(directory))
        file = inside(root, name)
        if file.suffix.lower() not in EDITABLE or not file.is_file() or file.stat().st_size > MAX_TEXT:
            raise ValueError("只允许读取插件内不超过 1 MiB 的源码文本")
        return {"directory": directory, "path": name, "content": file.read_text(encoding="utf-8-sig"), "sha256": digest_file(file)}
