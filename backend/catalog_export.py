"""Compile cached public records into data-only Lua; never evaluate downloaded content."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from .db import Database


def lua_string(value: str) -> str:
    parts = ['"']
    for char in value:
        if char in ('"', "\\"):
            parts.append("\\" + char)
        elif ord(char) < 32 or ord(char) == 127:
            parts.append(f"\\{ord(char):03d}")
        else:
            parts.append(char)
    return "".join(parts) + '"'


def lua_literal(value, depth=0):
    if depth > 24:
        raise ValueError("资料结构过深，未更新插件资料库")
    if value is None:
        return "N"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        if not math.isfinite(value) or abs(value) > 2**53:
            raise ValueError("资料数值超出 Lua 可精确表示范围")
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, list):
        return "{" + ",".join(lua_literal(v, depth + 1) for v in value) + "}"
    if isinstance(value, dict):
        fields = []
        for key in sorted(value, key=str):
            if type(key) not in (str, int):
                raise ValueError("资料包含不支持的表键")
            fields.append("[" + lua_literal(key, depth + 1) + "]=" + lua_literal(value[key], depth + 1))
        return "{" + ",".join(fields) + "}"
    raise ValueError("资料包含不支持的类型")


def export_catalog(db: Database, destination: Path):
    with db.connect() as connection:
        rows = {row["name"]: dict(row) for row in connection.execute(
            "SELECT name,build,built_at,payload FROM reference_cache WHERE name IN ('manifest','items','recipes')")}
    if set(rows) != {"manifest", "items", "recipes"}:
        raise ValueError("物品、配方或版本资料尚未同步完整")
    if len({(r["build"], r["built_at"]) for r in rows.values()}) != 1:
        raise ValueError("资料版本不一致，保留旧插件资料库")
    manifest, items, recipes = (json.loads(rows[key]["payload"]) for key in ("manifest", "items", "recipes"))
    if manifest.get("product") not in {"wowf", "wow_cn_beta"} or not isinstance(items, dict) or not isinstance(recipes, list):
        raise ValueError("不是已识别的《无限》国服资料结构")
    declared = manifest.get("counts", {})
    if not isinstance(declared, dict):
        raise ValueError("资料数量声明无效，保留旧插件资料库")
    for key, values in (("items", items), ("recipes", recipes)):
        if key in declared and (type(declared[key]) is not int or declared[key] != len(values)):
            raise ValueError("资料数量与来源声明不符，保留旧插件资料库")
    item_table, recipe_table = {}, {}
    for key, item in items.items():
        if not isinstance(item, dict) or type(item.get("id")) is not int or str(item["id"]) != key or not isinstance(item.get("name"), str):
            raise ValueError("物品记录校验失败")
        item_table[item["id"]] = item
    for recipe in recipes:
        if not isinstance(recipe, dict) or type(recipe.get("id")) is not int or not isinstance(recipe.get("name"), str) or recipe["id"] in recipe_table:
            raise ValueError("配方记录校验失败或编号重复")
        recipe_table[recipe["id"]] = recipe
    canonical = json.dumps([manifest["build"], manifest["built_at"], items, recipes], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    metadata = {"schema_version": 1, "build": manifest["build"], "built_at": manifest["built_at"],
                "source": "https://wuxianwow.com/about", "item_count": len(item_table),
                "recipe_count": len(recipe_table), "sha256": digest}
    payload = {**metadata, "items": item_table, "recipes": recipe_table}
    text = "-- Generated data only. Source: https://wuxianwow.com/about\n-- Not character state; never include this table in SavedVariables.\nlocal F = ForeverAI\nF.CatalogNull = {}\nlocal N = F.CatalogNull\nF.CatalogData = " + lua_literal(payload) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > 24 * 1024 * 1024:
        raise ValueError("插件资料库超过 24 MiB，未覆盖旧文件")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".catalog-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    (destination.parent / "CatalogManifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return {**metadata, "file": destination.name, "bytes": len(encoded)}
