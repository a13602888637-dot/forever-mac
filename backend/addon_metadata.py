"""TOC facts and conservative package ownership; never execute addon code."""
from __future__ import annotations

from pathlib import Path
import re

from .platform_io import identifier

INTERFACE = 16001
SOURCES = {
    "dbm": {"name": "Deadly Boss Mods", "core": "DBM-Core", "curse_id": "3358", "repo": "DeadlyBossMods/DeadlyBossMods", "category": "副本"},
    "ellesmere": {"name": "EllesmereUI", "core": "EllesmereUI", "curse_id": "1477613", "repo": "EllesmereGaming/EllesmereUI", "category": "界面"},
    "littlewigs": {"name": "LittleWigs", "core": "LittleWigs", "curse_id": "4383", "repo": "BigWigsMods/LittleWigs", "category": "副本"},
    "bigwigs": {"name": "BigWigs", "core": "BigWigs", "curse_id": "2382", "repo": "BigWigsMods/BigWigs", "category": "副本"},
    "details": {"name": "Details!", "core": "Details", "curse_id": "61284", "category": "战斗", "url": "https://www.curseforge.com/wow/addons/details"},
    "atlas": {"name": "Atlas", "core": "Atlas", "curse_id": "301", "repo": "arithmandar/Atlas", "category": "地图"},
    "atlas-classic": {"name": "Atlas Kalimdor & Eastern Kingdoms", "core": "Atlas_ClassicWoW", "curse_id": "33667", "repo": "arithmandar/Atlas-Kalimdor-and-Eastern-Kingdoms", "category": "地图"},
    "dbm-dungeons": {"name": "DBM · 地下城首领模块", "core": "DBM-Party-Forever", "curse_id": "314994", "repo": "DeadlyBossMods/DBM-Dungeons", "category": "副本"},
    "questie": {"name": "Questie", "core": "Questie", "curse_id": "334372", "category": "任务", "url": "https://www.curseforge.com/wow/addons/questie"},
}


def plain(value):
    return re.sub(r"\|[cC][0-9a-fA-F]{8}|\|[rR]|\|[Tt].*?\|[tT]", "", value).strip()


def read_toc(folder: Path, directory_name: str | None = None) -> dict:
    name = identifier(directory_name) if directory_name is not None else folder.name
    choices = [folder / f"{name}_Camelot.toc", folder / f"{name}.toc"]
    toc = next((p for p in choices if p.is_file() and not p.is_symlink()), None)
    data = {"directory": name, "title": name, "version": None, "interface": [],
            "dependencies": [], "optional_dependencies": [], "saved_variables": [], "files": [], "toc": None,
            "metadata": {}, "compatibility": "unknown", "issues": []}
    if folder.is_symlink():
        data["issues"].append("符号链接：暂停覆盖")
        return data
    if toc is None:
        data["issues"].append("缺少 Camelot 或通用 TOC")
        return data
    if toc.stat().st_size > 1024 * 1024:
        raise ValueError("TOC 体积异常")
    meta, files = {}, []
    for line in toc.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = re.match(r"^##\s*([^:]+):\s*(.*)$", line)
        if match:
            meta[match[1].strip().lower()] = match[2].strip()
        elif line.strip() and not line.lstrip().startswith("#"):
            files.append(line.strip())
    def parts(*keys):
        return list(dict.fromkeys(x.strip() for key in keys for x in meta.get(key, "").split(",") if x.strip()))
    interface = [int(n) for n in re.findall(r"\b\d+\b", meta.get("interface", ""))]
    allowed_flavors = parts("allowloadgametype")
    excluded_flavors = parts("excludeloadgametype")
    inactive = (bool(allowed_flavors) and not {"camelot", "forever"}.intersection(allowed_flavors)) or bool({"camelot", "forever"}.intersection(excluded_flavors))
    version = meta.get("version")
    if version and ("@" in version or "$" in version):
        version = None
    data.update(title=plain(meta.get("title-zhcn", meta.get("title", name))), version=version,
                interface=interface, dependencies=parts("dependencies", "requireddeps"),
                optional_dependencies=parts("optionaldeps", "optionaldependencies"),
                saved_variables=parts("savedvariables", "savedvariablespercharacter"),
                files=files, toc=toc.name, metadata=meta,
                compatibility="inactive_flavor" if inactive else "toc_supported" if INTERFACE in interface else "incompatible" if interface else "unknown")
    return data


def scan_addons(root: Path) -> list[dict]:
    if not root.is_dir():
        return []
    if root.is_symlink():
        raise ValueError("AddOns 根目录不能为符号链接")
    modules = []
    for folder in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if folder.name.startswith(".") or not (folder.is_dir() or folder.is_symlink()):
            continue
        try:
            identifier(folder.name)
            modules.append(read_toc(folder))
        except (ValueError, OSError) as exc:
            modules.append({"directory": folder.name, "title": folder.name, "version": None, "interface": [],
                            "dependencies": [], "optional_dependencies": [], "saved_variables": [], "metadata": {},
                            "compatibility": "unknown", "issues": [str(exc)], "toc": None, "files": []})
    installed = {m["directory"] for m in modules}
    for module in modules:
        module["missing_dependencies"] = [d for d in module["dependencies"] if d not in installed and not d.startswith("Blizzard_")]
        module["issues"] += [f"缺少依赖：{d}" for d in module["missing_dependencies"]]
    return modules


def package_id(module: dict, all_modules: dict) -> str:
    name, meta = module["directory"], module["metadata"]
    # An explicit publisher project id outranks a shared DBM namespace/group.
    # The dungeon pack must never be silently assigned to the core updater.
    for key, source in SOURCES.items():
        core = all_modules.get(source["core"])
        if (core and core["metadata"].get("x-curse-project-id") == source["curse_id"]
                and meta.get("x-curse-project-id") == source["curse_id"]):
            return key
    for key, source in SOURCES.items():
        core = all_modules.get(source["core"])
        # A known core identity is required. Module names alone never bind sources.
        if not core or core["metadata"].get("x-curse-project-id") != source["curse_id"]:
            continue
        if name == source["core"] or meta.get("x-curse-project-id") == source["curse_id"]:
            return key
        if key == "dbm" and meta.get("group") == "DBM-Core":
            return key
        if key == "ellesmere" and meta.get("group") == "EllesmereUI" and "EllesmereUI" in module["dependencies"]:
            return key
        # These author packages ship a fixed namespace of modules, corroborated
        # by a dependency on the verified core (LittleWigs uses BigWigs).
        if key in ("dbm", "bigwigs", "details") and not name.startswith("DBM-VP") and name.startswith(source["core"].split("-Core")[0] + ("-" if key == "dbm" else "_")) and source["core"] in module["dependencies"]:
            return key
        if key == "littlewigs" and name.startswith("LittleWigs_") and "BigWigs" in module["dependencies"] and module["title"].startswith("LittleWigs ["):
            return key
    return "local-" + name


def packages(modules: list[dict], installed_records: dict) -> list[dict]:
    by_name, result = {m["directory"]: m for m in modules}, {}
    for module in modules:
        owners = [key for key, record in installed_records.items() if module["directory"] in record["files"]]
        key = owners[0] if len(owners) == 1 else package_id(module, by_name)
        source = SOURCES.get(key, {})
        record = installed_records.get(key, {})
        group = result.setdefault(key, {"id": key, "name": source.get("name", module["title"]),
                                       "source": "github" if source.get("repo") else "curseforge" if source.get("curse_id") else "unbound",
                                       "repo": source.get("repo"), "category": source.get("category", "其他"),
                                       "source_url": "https://github.com/" + source["repo"] + "/releases" if source.get("repo") else source.get("url"),
                                       "modules": [], "version": None, "managed": bool(record),
                                       "update_status": "unchecked" if source.get("repo") else "website_required" if source.get("curse_id") else "unbound"})
        group["modules"].append(module)
        if module["directory"] == source.get("core") or len(group["modules"]) == 1:
            group["version"] = module["version"]
        if not source and module["metadata"].get("x-curse-project-id", "").isdigit():
            group["source"] = "curseforge"
            group["update_status"] = "website_required"
            group["source_url"] = "https://www.curseforge.com/wow/addons/search?search=" + module["directory"]
        provenance = record.get("source")
        if isinstance(provenance, dict):
            declaration = provenance.get("declaration")
            if declaration in ("workshop", "bundled"):
                group.update(source=declaration, update_status="local_only")
            elif declaration == "user_confirmed_curseforge":
                group.update(source="curseforge", update_status="website_required", source_url=provenance.get("source_url"))
            elif declaration == "zip_manifest":
                group.update(source="import", update_status="unbound")
        elif provenance in ("workshop", "bundled"):
            group.update(source=provenance, update_status="local_only")
    return list(result.values())
