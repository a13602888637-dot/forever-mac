"""Registered, same-origin artwork. Network failures never affect addon operations."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct
from urllib.parse import urlsplit

import httpx

from .platform_io import atomic_bytes, identifier, inside, read_json, write_json

ASSETS = Path(__file__).resolve().parents[1] / "frontend/static/media"
MAX_IMAGE_BYTES = 6 * 1024 * 1024
CLASS_ART = {
    "WARRIOR": (626008, "战士"), "PALADIN": (626003, "圣骑士"), "HUNTER": (626000, "猎人"),
    "ROGUE": (626005, "潜行者"), "PRIEST": (626004, "牧师"), "SHAMAN": (626006, "萨满祭司"),
    "MAGE": (626001, "法师"), "WARLOCK": (626007, "术士"), "DRUID": (625999, "德鲁伊"),
}
RACE_ART = {
    "HUMAN": (1, "人类"), "ORC": (2, "兽人"), "DWARF": (3, "矮人"), "NIGHTELF": (4, "暗夜精灵"),
    "SCOURGE": (5, "亡灵"), "UNDEAD": (5, "亡灵"), "TAUREN": (6, "牛头人"), "GNOME": (7, "侏儒"),
    "TROLL": (8, "巨魔"),
}


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment):
        raise ValueError("图片来源未登记")
    allowed = (
        parsed.hostname == "wuxianwow.com"
        and (re.fullmatch(r"/share/(?:[1-9][0-9]{0,9}|race-(?:[1-9][0-9]?)(?:-f)?)\.jpg", parsed.path)
             or re.fullmatch(r"/data/(?:maps/[1-9][0-9]{0,9}|loading/[1-9][0-9]{0,9}|bosses/c?[1-9][0-9]{0,9}(?:_model)?)\.webp", parsed.path))
    ) or (
        parsed.hostname in ("media.forgecdn.net", "mediafilez.forgecdn.net")
        and re.fullmatch(r"/(?:attachments|avatars)/[0-9]+/[0-9]+/[A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|webp)", parsed.path)
    )
    if not allowed:
        raise ValueError("图片来源未登记")
    return url


def image_type(content: bytes) -> str:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片体积超出限制")
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        width, height = struct.unpack(">II", content[16:24])
        if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > 32_000_000:
            raise ValueError("图片尺寸超出限制")
        return "image/png"
    if content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("图片格式不受支持")


class MediaCache:
    def __init__(self, root: Path, transport=None):
        self.root = Path(root)
        self.transport = transport
        self.assets = read_json(ASSETS / "manifest.json", {})
        (self.root / "registry").mkdir(parents=True, exist_ok=True)
        (self.root / "files").mkdir(parents=True, exist_ok=True)

    def register(self, resource_id: str, url: str, source_url: str = "https://wuxianwow.com/about") -> str:
        """Called only with trusted catalog/reference records; no public URL registration endpoint."""
        identifier(resource_id)
        validate_url(url)
        record = {"url": url, "source_url": source_url}
        path = inside(self.root, "registry/" + resource_id + ".json")
        existing = read_json(path)
        if existing and existing != record:
            raise ValueError("图片资源标识已绑定其他来源")
        if existing is None:
            write_json(path, record)
        return self.url(resource_id)

    def url(self, resource_id: str, size="thumb") -> str:
        identifier(resource_id)
        if size not in ("thumb", "full"):
            raise ValueError("图片尺寸参数无效")
        return f"/api/media/{resource_id}?size={size}"

    def item_icon(self, record: dict | None) -> str | None:
        if not isinstance(record, dict):
            return None
        value = record.get("icon_id", record.get("icon"))
        if type(value) is not int or not 0 < value <= 2_147_483_647:
            return None
        key = f"wow-icon-{value}"
        if key not in self.assets:
            self.register(key, f"https://wuxianwow.com/share/{value}.jpg")
        return self.url(key)

    def character_art(self, class_token=None, race_token=None):
        # A token that names more than one race (Skyborne) is deliberately not guessed.
        class_info = CLASS_ART.get(str(class_token or "").upper())
        race_info = RACE_ART.get(str(race_token or "").replace("_", "").upper())
        return {
            "class": {"name": class_info[1], "url": self.item_icon({"icon": class_info[0]})} if class_info
                else {"name": class_token or "职业未知", "url": None},
            "race": {"name": race_info[1], "url": self.url(f"race-{race_info[0]}")} if race_info
                else {"name": race_token or "种族未知", "url": None},
        }

    def reference_image(self, path):
        if not isinstance(path, str) or not re.fullmatch(
                r"(?:maps/[1-9][0-9]{0,9}|loading/[1-9][0-9]{0,9}|bosses/c?[1-9][0-9]{0,9}(?:_model)?)\.webp", path):
            return None
        key = "world-" + path.removesuffix(".webp").replace("/", "-")
        return self.register(key, "https://wuxianwow.com/data/" + path)

    def metadata(self, resource_id: str):
        identifier(resource_id)
        if resource_id in self.assets:
            return self.assets[resource_id]
        result = read_json(inside(self.root, "registry/" + resource_id + ".json"))
        if not result:
            raise ValueError("图片资源未登记")
        validate_url(result["url"])
        return result

    def get(self, resource_id: str, size="thumb") -> tuple[Path, str]:
        if size not in ("thumb", "full"):
            raise ValueError("图片尺寸参数无效")
        record = self.metadata(resource_id)
        if "file" in record:
            path = inside(ASSETS, record.get("thumbnail", record["file"]) if size == "thumb" else record["file"])
            if not path.is_file() or path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("内置图片不可用")
            if path.suffix == ".svg":
                return path, "image/svg+xml"  # Only authored, bundled SVGs can enter this branch.
            return path, image_type(path.read_bytes())
        # Dynamic resources are already icon-sized. Their original pixels are the thumbnail.
        # The key includes the bound URL to avoid reusing content from a different source.
        key = hashlib.sha256(record["url"].encode()).hexdigest()
        path = inside(self.root, "files/" + key + ".img")
        if path.is_file() and path.stat().st_size <= MAX_IMAGE_BYTES:
            return path, image_type(path.read_bytes())
        url = validate_url(record["url"])
        try:
            with httpx.Client(timeout=httpx.Timeout(15, connect=6), follow_redirects=False, transport=self.transport,
                              headers={"User-Agent": "Forever/0.4 media-cache", "Accept": "image/*"}) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").split(";")[0].strip().startswith("image/"):
                        raise ValueError("图片服务返回了其他内容")
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_IMAGE_BYTES:
                            raise ValueError("图片体积超出限制")
            mime = image_type(content)
            atomic_bytes(path, content)
            return path, mime
        except httpx.HTTPError:
            raise ValueError("图片暂不可用；已缓存图片仍可离线查看") from None
