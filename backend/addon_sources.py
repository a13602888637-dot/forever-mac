"""Author release assets only. CurseForge API remains an opt-in adapter."""
from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from .addon_metadata import INTERFACE, SOURCES
from .addon_catalog import PROJECTS
from .platform_io import MAX_UPLOAD

NETWORK_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
CURSEFORGE_FOREVER = "https://www.curseforge.com/wow/search?class=addons&search=Forever"
CURSEFORGE_APPLY = "https://support.curseforge.com/support/solutions/articles/9000208346-about-the-curseforge-api-and-how-to-apply-for-a-key"
# Kept for older inventory/MCP clients; every entry is a concrete project.

CATALOG = [{"id": key, "name": value["name"], "category": value["category"],
            "url": value.get("source_url"), "note": value["description"]} for key, value in PROJECTS.items()]



def fetch(url: str, limit: int, destination: Path | None = None,
          progress: Callable[[int], None] | None = None) -> bytes:
    """Bound both redirects and decompressed response bytes; never forward credentials."""
    total, chunks = 0, []
    stream = destination.open("wb") if destination else None
    try:
        with httpx.Client(timeout=httpx.Timeout(45, connect=15), headers={"User-Agent": "ForeverPlatform/0.2"}) as client:
            for _ in range(5):
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname not in NETWORK_HOSTS or parsed.username or parsed.port not in (None, 443):
                    raise ValueError("下载地址不在作者发布白名单")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    if progress:
                        progress(0)
                    for chunk in response.iter_bytes(chunk_size=128 * 1024):
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("下载体积超过限制")
                        if stream:
                            stream.write(chunk)
                        else:
                            chunks.append(chunk)
                        if progress:
                            progress(total)
                    return b"".join(chunks)
            raise ValueError("下载重定向过多")
    except (httpx.HTTPError, KeyError) as exc:
        raise ValueError("作者发布源暂时不可用，请稍后检查；当前版本状态未知") from exc
    finally:
        if stream:
            stream.close()


def author_release(key: str) -> dict:
    source = SOURCES.get(key, {})
    repo = source.get("repo")
    if not repo:
        raise ValueError("此来源需官网检查并导入 ZIP")
    try:
        data = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest", 2 * 1024 * 1024))
        if data.get("draft") or data.get("prerelease"):
            raise ValueError("当前发布不是稳定版本")
        assets = {a["name"]: a for a in data["assets"]}
        metadata = assets.get("release.json")
        if not metadata:
            raise ValueError("发布缺少 release.json；Forever 支持尚未核实")
        prefix = f"https://github.com/{repo}/releases/download/"
        if not metadata["browser_download_url"].startswith(prefix):
            raise ValueError("发布清单来源不匹配")
        manifest = json.loads(fetch(metadata["browser_download_url"], 1024 * 1024))
        candidates = [r for r in manifest["releases"] if not r.get("nolib") and
                      any(m.get("flavor") == "forever" and m.get("interface") == INTERFACE for m in r.get("metadata", []))]
        if len(candidates) != 1:
            raise ValueError("没有唯一声明 Forever / 16001 支持的发布包")
        release = candidates[0]
        asset = assets.get(release["filename"])
        if not asset or not release["filename"].lower().endswith(".zip") or not asset["browser_download_url"].startswith(prefix):
            raise ValueError("Forever ZIP 与清单不一致")
        if asset["size"] > MAX_UPLOAD:
            raise ValueError("发布包体积超过限制")
        return {"package_id": key, "version": release["version"], "tag": data["tag_name"],
                "filename": release["filename"], "url": asset["browser_download_url"],
                "size": asset["size"], "source_url": f"https://github.com/{repo}/releases/tag/{data['tag_name']}",
                "sha256": asset.get("digest", "").removeprefix("sha256:") if (asset.get("digest") or "").startswith("sha256:") else None,
                "declaration": "author_release", "manifest": release,
                "published_at": data.get("published_at"), "changelog": data.get("body")}
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("作者发布清单格式未知，不能判断最新版") from exc


def same_version(installed, published):
    # Only exact equality with the author's conventional leading v removed.
    return bool(installed and published and installed.removeprefix("v") == published.removeprefix("v"))


class CurseForgeAdapter:
    """Optional approved-key API boundary. No key is stored or exposed to the UI."""
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key

    @property
    def status(self):
        return {"status": "available" if self._api_key else "website_required", "label": "需官网检查" if not self._api_key else "官方 API",
                "url": CURSEFORGE_FOREVER, "application_url": CURSEFORGE_APPLY}

    def search(self, query: str):
        if not self._api_key:
            raise ValueError("CurseForge 官方 API 尚未配置授权；请在官网选择 Forever 文件并导入 ZIP")
        # Flavor ids must come from the approved API, never guessed from retail.
        with httpx.Client(base_url="https://api.curseforge.com/v1", timeout=20, headers={"x-api-key": self._api_key}) as client:
            types = client.get("/games/1/version-types")
            types.raise_for_status()
            flavors = [x["id"] for x in types.json()["data"] if "forever" in x["name"].casefold()]
            if len(flavors) != 1:
                raise ValueError("CurseForge API 尚未返回唯一 Forever 分类")
            response = client.get("/mods/search", params={"gameId": 1, "classId": 4471, "gameVersionTypeId": flavors[0], "searchFilter": query[:100], "pageSize": 20})
            response.raise_for_status()
            return response.json()["data"]
