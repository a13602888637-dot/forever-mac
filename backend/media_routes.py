"""Read-only catalog and media HTTP endpoints."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse


def router(catalog, media):
    api = APIRouter()

    @api.get("/api/catalog")
    def catalog_browse(q: str = Query(default="", max_length=150), category: str = Query(default="全部", max_length=30)):
        return catalog.browse(q, category)

    @api.get("/api/catalog/{package_id}")
    def catalog_detail(package_id: str):
        return catalog.detail(package_id)

    @api.get("/api/media/{resource_id}")
    def image(resource_id: str, size: str = "thumb"):
        try:
            path, mime = media.get(resource_id, size)
        except (ValueError, OSError):
            raise HTTPException(404, "图片暂不可用") from None
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, max-age=86400",
                                                          "X-Content-Type-Options": "nosniff"})

    return api
