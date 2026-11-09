"""Stream ZIPs into quarantine; validate paths, sizes, active TOCs and references."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import stat
import zipfile

from .addon_metadata import read_toc
from .platform_io import MAX_EXPANDED, MAX_FILE, MAX_FILES, MAX_UPLOAD, folded, inside, manifest, relative


def unpack(archive: Path, destination: Path) -> dict[str, Path]:
    if archive.stat().st_size > MAX_UPLOAD:
        raise ValueError("ZIP 超过 128 MiB")
    try:
        with zipfile.ZipFile(archive) as z:
            items = z.infolist()
            if not items or len(items) > MAX_FILES:
                raise ValueError("ZIP 文件数异常")
            total, names, file_names, prefixes = 0, set(), set(), {}
            for entry in items:
                relative(entry.orig_filename.rstrip("/"))
                name = entry.filename.rstrip("/")
                relative(name)
                for index in range(1, len(name.split("/")) + 1):
                    prefix = "/".join(name.split("/")[:index])
                    if folded(prefix) in prefixes and prefixes[folded(prefix)] != prefix:
                        raise ValueError("ZIP 路径大小写冲突或 Unicode 冲突")
                    prefixes[folded(prefix)] = prefix
                if folded(name) in names:
                    raise ValueError("ZIP 包含重复路径或大小写冲突")
                names.add(folded(name))
                if not entry.is_dir():
                    file_names.add(folded(name))
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                    raise ValueError("ZIP 含符号链接、特殊文件或加密文件")
                total += entry.file_size
                if entry.file_size > MAX_FILE or total > MAX_EXPANDED or entry.file_size > max(entry.compress_size, 1) * 1000:
                    raise ValueError("ZIP 解压体积或压缩率异常")
            for name in names:
                if any('/'.join(name.split('/')[:i]) in file_names for i in range(1, len(name.split('/')))):
                    raise ValueError("ZIP 文件与目录路径冲突")
            destination.mkdir(parents=True)
            actual = 0
            for entry in items:
                target = inside(destination, entry.filename.rstrip("/"))
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with z.open(entry) as source, target.open("xb") as output:
                    while chunk := source.read(128 * 1024):
                        written += len(chunk)
                        actual += len(chunk)
                        if written > MAX_FILE or actual > MAX_EXPANDED:
                            raise ValueError("ZIP 实际解压体积异常")
                        output.write(chunk)
                if written != entry.file_size:
                    raise ValueError("ZIP 文件长度不一致")
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise ValueError("ZIP 无效或无法完整解压") from exc
    # Accept direct addon directories or a single conventional wrapper.
    roots = []
    for toc in destination.rglob("*.toc"):
        if len(toc.relative_to(destination).parts) > 6:
            continue
        folder = toc.parent
        if toc.name in (folder.name + ".toc", folder.name + "_Camelot.toc"):
            roots.append(folder)
    roots = sorted(set(roots))
    roots = [p for p in roots if not any(p != other and p.is_relative_to(other) for other in roots)]
    if not roots or len({p.parent for p in roots}) != 1:
        raise ValueError("ZIP 没有同层、可识别的插件目录")
    result = {}
    for folder in roots:
        if folded(folder.name) in {folded(x) for x in result}:
            raise ValueError("插件目录大小写冲突")
        result[folder.name] = folder
    return result


def check_references(folder: Path, package_root: Path) -> list[str]:
    data = read_toc(folder)
    issues, visited = [], set()

    def check(parent: Path, value: str):
        # WoW's TOC loader expands these filename tokens. This product targets
        # the Chinese Forever client; validate its actual zhCN resources.
        value = re.split(r"\s+\[", value)[0].replace("[TextLocale]", "zhCN").replace("[AudioLocale]", "zhCN").replace("[Game]", "Camelot").replace("\\", "/").strip()
        if not value:
            return
        target = (parent / value).resolve()
        if not target.is_relative_to(package_root.resolve()) or target.is_symlink():
            issues.append(f"TOC/XML 路径越界：{value}")
            return
        if target in visited:
            return
        visited.add(target)
        if not target.is_file():
            issues.append(f"TOC/XML 引用缺失：{value}")
        elif target.suffix.lower() == ".xml":
            if target.stat().st_size > MAX_FILE:
                issues.append("XML 体积异常")
                return
            content = target.read_text(errors="replace")
            if "<!ENTITY" in content or "<!DOCTYPE" in content:
                issues.append("XML 不允许外部实体或 DTD")
                return
            # No XML evaluation or entity expansion, only declared local files.
            content = re.sub(r"<!--.*?-->", "", content, flags=re.S)
            for child in re.findall(r'<(?:Script|Include)\b[^>]*\bfile\s*=\s*[\'"]([^\'"]+)', content, re.I):
                check(target.parent, child)
    for file in data["files"]:
        check(folder, file)
    return issues


def copy_tree(source: Path, target: Path):
    manifest(source)  # Includes symlink/special-file and bounded-size validation.
    shutil.copytree(source, target)
