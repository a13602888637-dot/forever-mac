"""Paged local catalog and explicitly selected, read-only public markets."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import Field

from .models import Model


class MarketSelection(Model):
    house: str | None = Field(default=None, max_length=80)


def attach_media(payload, media):
    if media is None:
        return payload
    rows = payload.get("results", []) if "results" in payload else [payload]
    for row in rows:
        row["icon_url"] = media.item_icon(row.get("record", row))
        row["art_url"] = media.reference_image(row["art_path"]) if row.get("art_path") else None
        for atlas in row.get("maps", []):
            atlas["image_url"] = media.reference_image(atlas.get("art_path"))
        for group in row.get("loot_groups", []):
            for item in group["items"]:
                item["icon_url"] = media.item_icon(item)
        for relation in ("materials", "products", "used_by", "created_by"):
            for item in row.get(relation, []):
                item["icon_url"] = media.item_icon(item)
    return payload


def router(service, media=None):
    api = APIRouter()

    def snapshot():
        latest = service.latest()
        return latest[1] if latest else None

    @api.get("/api/references/browse")
    def browse(kind: str = "items", q: str = Query(default="", max_length=100), category: str = "",
               page: int = Query(default=1, ge=1, le=10000), page_size: int = Query(default=24, ge=1, le=100)):
        return attach_media(service.refs.browse(q, kind, snapshot(), category, page, page_size), media)

    @api.get("/api/references/details/{kind}/{entity_id}")
    def detail(kind: str, entity_id: int):
        return attach_media(service.refs.detail(kind, entity_id, snapshot()), media)

    @api.get("/api/market/markets")
    async def markets(refresh: bool = False):
        current = service.market.markets()
        if service.refs.enabled and (refresh or not current["markets"]):
            current = await service.market.discover_markets()
        return {**current, "observation": service.market.metadata(), "legacy_observation": service.market.legacy_metadata()}

    @api.post("/api/market/selection")
    def selection(body: MarketSelection):
        return service.market.select(body.house)

    @api.post("/api/market/refresh")
    async def refresh():
        return await service.market.sync()

    return api
