"""HTTP surface uses the same platform services as the official stdio server."""
from __future__ import annotations

from pathlib import Path
import sys
import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field

from .models import Model
from .platform_io import MAX_UPLOAD


class PackageInput(Model):
    package_id: str = Field(min_length=1, max_length=100)


class UpdateInput(Model):
    package_id: str | None = Field(default=None, max_length=100)


class BundleInput(Model):
    name: str = Field(pattern="^(ForeverAI|ForeverUI)$")


class ProfileInput(Model):
    character_id: str = Field(min_length=1, max_length=100)
    combo: str = Field(pattern="^(EllesmereUI|ForeverUI)$")


class RestoreInput(Model):
    character_id: str = Field(min_length=1, max_length=100)


class ProjectInput(Model):
    name: str = Field(min_length=1, max_length=61)
    description: str = Field(default="", max_length=1000)


class FileInput(Model):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1024 * 1024)
    expected_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")


def mcp_configuration(platform):
    project = Path(__file__).resolve().parents[1]
    args = [str(project / "scripts/mcp_serve.py"), "--mode", platform.settings.mode, "--data-dir", str(platform.settings.data_dir)]
    try:
        args += ["--game-path", str(platform.game())]
    except ValueError:
        pass
    return {"mcpServers": {"forever": {"command": sys.executable,
        "args": args,
        "env": {"FAI_DATA_DIR": str(platform.settings.data_dir)}}}}


def router(platform, profiles, workshop):
    api = APIRouter()

    @api.get("/api/addons")
    def inventory():
        return platform.inventory()

    @api.get("/api/addons/game-status")
    def game_status():
        return platform.launch_status()

    @api.post("/api/addons/launch-game")
    def launch_game():
        return platform.launch_game()

    @api.post("/api/addons/adopt")
    def adopt(body: PackageInput):
        return platform.adopt(body.package_id)

    @api.post("/api/addons/check-updates")
    def check(body: UpdateInput):
        return platform.check_updates(body.package_id)

    @api.post("/api/addons/download")
    def download(body: PackageInput):
        return platform.download(body.package_id)

    @api.post("/api/addons/bundled")
    def bundled(body: BundleInput):
        return platform.bundled(body.name)

    @api.post("/api/addons/import")
    async def import_zip(file: UploadFile = File(...), source_url: str = Form(""), forever_confirmed: bool = Form(False)):
        if not (file.filename or "").lower().endswith(".zip"):
            raise ValueError("请选择 ZIP 发布包")
        target = platform.root / "uploads" / (uuid.uuid4().hex + ".zip")
        try:
            total = 0
            with target.open("xb") as stream:
                while chunk := await file.read(128 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise ValueError("ZIP 超过 128 MiB")
                    stream.write(chunk)
            # The synchronous validator runs off the event loop.
            import asyncio
            return await asyncio.to_thread(platform.stage, target, source_url=source_url, forever_confirmed=forever_confirmed, original_filename=file.filename)
        finally:
            target.unlink(missing_ok=True)
            await file.close()

    @api.get("/api/addons/plans")
    def plans():
        return platform.plans()

    @api.get("/api/addons/plans/{op}")
    def plan(op: str):
        return platform.review(op)

    @api.post("/api/addons/plans/{op}/apply")
    def apply(op: str):
        return platform.apply(op)

    @api.get("/api/addons/history")
    def history():
        return platform.history()

    @api.get("/api/addons/tasks")
    def tasks():
        return platform.tasks()

    @api.post("/api/addons/operations/{op}/rollback")
    def rollback(op: str):
        result = platform.rollback(op)
        return {"id": result["id"], "status": result["status"]}

    @api.post("/api/addons/operations/{op}/recover")
    def recover(op: str):
        result = platform.recover(op)
        return {"id": result["id"], "status": result["status"]}

    @api.get("/api/profiles")
    def profile_overview():
        return profiles.overview()

    @api.post("/api/profiles/plans")
    def switch_plan(body: ProfileInput):
        return profiles.prepare_switch(body.character_id, body.combo)

    @api.get("/api/profiles/plans/{op}")
    def get_switch(op: str):
        from .platform_io import identifier, read_json
        result = read_json(profiles.root / "profile-plans" / (identifier(op) + ".json"))
        if not result:
            raise ValueError("组合计划不存在")
        return result

    @api.post("/api/profiles/plans/{op}/apply")
    def apply_switch(op: str):
        return profiles.apply_switch(op)

    @api.post("/api/profiles/snapshots")
    def backup(body: ProfileInput):
        return profiles.backup_config(body.character_id, body.combo)

    @api.post("/api/profiles/snapshots/{op}/restore")
    def restore(op: str, body: RestoreInput):
        return profiles.restore_config(op, body.character_id)

    @api.get("/api/workshop/mcp-config")
    def mcp_config():
        return mcp_configuration(platform)

    @api.get("/api/workshop/projects")
    def projects():
        return workshop.projects()

    @api.post("/api/workshop/projects")
    def create(body: ProjectInput):
        return workshop.create(body.name, body.description)

    @api.post("/api/workshop/clone")
    def clone(body: PackageInput):
        return workshop.clone(body.package_id)

    @api.get("/api/workshop/projects/{project_id}/files")
    def files(project_id: str):
        return workshop.files(project_id)

    @api.get("/api/workshop/projects/{project_id}/file")
    def read(project_id: str, path: str):
        return workshop.read(project_id, path)

    @api.put("/api/workshop/projects/{project_id}/file")
    def write(project_id: str, body: FileInput):
        return workshop.write(project_id, body.path, body.content, body.expected_sha256)

    @api.get("/api/workshop/projects/{project_id}/diff")
    def diff(project_id: str):
        return workshop.diff(project_id)

    @api.get("/api/workshop/projects/{project_id}/history")
    def project_history(project_id: str):
        return workshop.history(project_id)

    @api.post("/api/workshop/projects/{project_id}/revisions/{revision}/revert")
    def revert(project_id: str, revision: str):
        return workshop.revert(project_id, revision)

    @api.post("/api/workshop/projects/{project_id}/validate")
    def validate(project_id: str):
        return workshop.validate(project_id)

    @api.post("/api/workshop/projects/{project_id}/pack")
    def pack(project_id: str):
        return workshop.pack(project_id)

    @api.get("/api/workshop/exports/{export_id}")
    def export(export_id: str):
        target, _ = workshop.export_path(export_id)
        return FileResponse(target, media_type="application/zip", filename="Forever-" + target.name)

    @api.post("/api/workshop/exports/{export_id}/plan")
    def export_plan(export_id: str):
        return workshop.install_plan(export_id)

    @api.get("/api/workshop/api")
    def api_lookup(q: str):
        return workshop.api(q)

    return api
