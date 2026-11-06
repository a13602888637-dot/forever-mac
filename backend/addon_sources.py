"""Author release assets only. CurseForge API remains an opt-in adapter."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .addon_metadata import INTERFACE, SOURCES
from .platform_io import MAX_UPLOAD

NETWORK_HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
CURSEFORGE_FOREVER = "https://www.curseforge.com/wow/search?class=addons&search=Forever"
CURSEFORGE_APPLY = "https://support.curseforge.com/support/solutions/articles/9000208346-about-the-curseforge-api-and-how-to-apply-for-a-key"
CATALOG = [
    {"id": key, "name": s["name"], "category": s["category"], "url": "https://github.com/" + s["repo"] + "/releases",
     "note": "检查作者 Forever 发布；安装前展示依赖和目录变更"} for key, s in SOURCES.items() if s.get("repo")
] + [
    {"id": "foreverui", "name": "ForeverUI · 亡灵奥术", "category": "界面", "url": None, "note": "本项目内置；与 EllesmereUI 的动作条、头像、背包、聊天、地图、任务追踪重叠"},
    {"id": "suite", "name": "WoW Forever Suite", "category": "界面", "url": "https://www.curseforge.com/wow/addons/wow-forever-suite", "note": "可选；背包、地图、聊天及升级功能与当前界面重叠，需官网检查 Forever 文件后导入 ZIP"},
    {"id": "bags", "name": "背包插件", "category": "背包", "url": "https://www.curseforge.com/wow/addons/search?search=bags", "note": "在官网选择 Forever；注意与 EllesmereUIBags / ForeverUI 重叠"},
    {"id": "combat", "name": "Details!", "category": "战斗", "url": "https://www.curseforge.com/wow/addons/details", "note": "需官网检查 Forever 文件；与 EllesmereUIDamageMeters 重叠"},
    {"id": "maps", "name": "地图与任务", "category": "地图", "url": "https://www.curseforge.com/wow/addons/search?search=forever%20map", "note": "在官网选择 Forever；与现有小地图和任务追踪功能核对"},
]


def fetch(url: str, limit: int, destination: Path | None = None) -> bytes:
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
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("下载体积超过限制")
                        if stream:
                            stream.write(chunk)
                        else:
                            chunks.append(chunk)
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
                "declaration": "author_release", "manifest": release}
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
