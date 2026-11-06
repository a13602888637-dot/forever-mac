from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime
import json
import hashlib
import time
import tempfile
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import Field, StrictBool, StrictInt, ValidationError

from .config import Settings
from .automation import Automation, OFFICIAL_PROVIDER
from .models import Item, Model, PositiveID, Recipe
from .rules import rule_plan
from .service import Companion, ComparisonInput, EconomyInput, ROOT, gold_to_copper
from .addon_platform import AddonPlatform
from .addon_profiles import Profiles
from .addon_workshop import Workshop
from .platform_routes import router as platform_router, mcp_configuration
from .platform_io import MAX_UPLOAD


class SourceInput(Model):
    source_id: str = Field(min_length=1, max_length=64)


class PriceInput(Model):
    item_id: PositiveID
    copper: StrictInt = Field(ge=0, le=10**14)


class QuestionInput(Model):
    question: str = Field(min_length=1, max_length=2000)


class TaskInput(Model):
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=2000)


class TaskUpdate(Model):
    done: StrictBool


class PathInput(Model):
    game_path: str = Field(max_length=1000)


class CharacterInput(Model):
    character_id: str = Field(min_length=1, max_length=200)


class MCPInput(Model):
    tool: str
    arguments: dict


class LocalOnly:
    """Loopback Host/Origin checks and a real streaming body limit, before parsing forms."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        try:
            host = urlsplit("//" + headers.get("host", ""))
            allowed = host.hostname in ("127.0.0.1", "localhost") and host.username is None
            origin = headers.get("origin")
            origin_url = urlsplit(origin) if origin else None
            if origin_url and (origin_url.scheme != "http" or origin_url.netloc != host.netloc):
                allowed = False
            if scope["method"] != "GET" and headers.get("sec-fetch-site") == "cross-site":
                allowed = False
        except ValueError:
            allowed = False
        if not allowed:
            return await JSONResponse({"detail": "仅接受本机同源请求"}, status_code=403)(scope, receive, send)
        if scope["method"] in ("POST", "PATCH", "PUT", "DELETE"):
            if scope["path"] == "/api/addons/import" and scope["method"] == "POST":
                # ZIP transport has its own bounded stream; ordinary JSON/forms
                # keep the existing 64 KiB cap. Never buffer a ZIP in memory.
                with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as upload:
                    size = 0
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        chunk = message.get("body", b"")
                        size += len(chunk)
                        if size > MAX_UPLOAD + 65536:
                            return await JSONResponse({"detail": "ZIP 上传超过 128 MiB"}, status_code=413)(scope, receive, send)
                        upload.write(chunk)
                        if not message.get("more_body"):
                            break
                    upload.seek(0)
                    finished = False
                    async def replay_upload():
                        nonlocal finished
                        if finished:
                            return await receive()
                        chunk = upload.read(65536)
                        finished = upload.tell() == size
                        return {"type": "http.request", "body": chunk, "more_body": not finished}
                    return await self.app(scope, replay_upload, send)
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                size += len(message.get("body", b""))
                if size > 65536:
                    return await JSONResponse({"detail": "请求体超过 64 KiB"}, status_code=413)(scope, receive, send)
                chunks.append(message.get("body", b""))
                if not message.get("more_body"):
                    break
            pending = True
            async def replay():
                nonlocal pending
                if pending:
                    pending = False
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()
            await self.app(scope, replay, send)
        else:
            await self.app(scope, receive, send)


def money(value):
    if value is None:
        return "未知"
    value = int(value)
    sign = "−" if value < 0 else ""
    value = abs(value)
    return f"{sign}{value // 10000:,} 金 {value % 10000 // 100} 银 {value % 100} 铜"


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    service = Companion(settings)
    automation = Automation(service)
    platform = AddonPlatform(settings, lambda: service.game_path)
    profiles, workshop = Profiles(platform), Workshop(platform)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(automation.loop()) if settings.auto_sync else None
        async def update_checks():
            while True:
                try:
                    await asyncio.to_thread(platform.check_due)
                except (OSError, ValueError):
                    pass  # Per-source errors are retained in task/update receipts.
                await asyncio.sleep(1800)
        updater = asyncio.create_task(update_checks()) if settings.auto_sync and settings.mode == "live" else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if updater:
                updater.cancel()
                with suppress(asyncio.CancelledError):
                    await updater

    app = FastAPI(title="Forever AI Companion", version="0.2.1", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.add_middleware(LocalOnly)
    app.state.service = service
    app.state.automation = automation
    app.state.platform = platform
    app.state.profiles = profiles
    app.state.workshop = workshop
    app.state.reference_lock = asyncio.Lock()
    templates = Jinja2Templates(directory=str(ROOT / "frontend/templates"))
    templates.env.filters["money"] = money
    templates.env.filters["datetime"] = lambda v: datetime.fromtimestamp(v).astimezone().strftime("%Y-%m-%d %H:%M") if v else "未知"
    templates.env.filters["prettyjson"] = lambda v: json.dumps(v, ensure_ascii=False, indent=2, default=str)
    app.mount("/static", StaticFiles(directory=str(ROOT / "frontend/static"), check_dir=False), name="static")
    app.include_router(platform_router(platform, profiles, workshop))

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    def render(request, name, **extra):
        latest = service.latest()
        snapshot_id, snapshot = latest if latest else (None, None)
        context = {"request": request, "current": "", "mode": settings.mode, "snapshot": snapshot,
                   "snapshot_id": snapshot_id, "characters": service.db.characters(settings.mode),
                   "active_character": snapshot.character.identity if snapshot else "",
                   "api_ready": bool(settings.api_key) and settings.mode == "live", "model": settings.model,
                   "now": int(time.time()), "automation": automation.status(), **extra}
        return templates.TemplateResponse(request=request, name=name, context=context)

    def notice(request, message, status="success"):
        return render(request, "partials/notice.html", message=message, status=status)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        message = "输入字段格式无效，请检查填写内容。" if isinstance(exc, ValidationError) else str(exc)
        if request.headers.get("HX-Request") == "true":
            return notice(request, message, "error")
        return JSONResponse({"detail": message}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def request_error(request, exc):
        if request.headers.get("HX-Request") == "true":
            return notice(request, "输入字段格式无效，请检查填写内容。", "error")
        return JSONResponse({"detail": "输入字段格式无效", "fields": [list(e["loc"]) for e in exc.errors()]}, status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": settings.mode, "model": settings.model,
                "api_key_configured": bool(settings.api_key), "bind": "127.0.0.1", "schema_version": 1,
                "application": "forever-ai-companion", "platform_schema": 1,
                "project_id": hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]}

    @app.get("/api/sources")
    def sources():
        return {"sources": service.sources()}

    @app.get("/api/automation/status")
    def automatic_status():
        return automation.status()

    @app.post("/api/automation/run")
    async def automatic_run():
        return await automation.run_once(force=True)

    @app.get("/api/equipment/automatic")
    def automatic_equipment():
        return {"comparisons": service.auto_comparisons()}

    @app.get("/api/economy/automatic")
    def automatic_economy():
        return service.auto_economy()

    @app.get("/api/providers")
    def providers():
        return {"providers": [OFFICIAL_PROVIDER,
                {"name": "无限图鉴", "status": "cached" if service.db.reference_status() else "waiting",
                 "source": "https://wuxianwow.com/about", "datasets": service.db.reference_status()},
                {"name": "公开拍卖快照", "status": "cached" if service.market.metadata() else "waiting",
                 "source": "https://wuxianwow.com/ah", "metadata": service.market.metadata()}]}

    @app.post("/api/settings/path")
    def path_setting(body: PathInput):
        service.configure_path(body.game_path)
        return {"game_path": service.game_path, "sources": service.sources()}

    @app.get("/api/characters")
    def characters():
        return service.db.characters(settings.mode)

    @app.post("/api/characters/select")
    def select(body: CharacterInput):
        service.select_character(body.character_id)
        return {"selected": body.character_id}

    @app.post("/api/snapshots/import")
    def ingest(body: SourceInput):
        ident, snapshot = service.import_snapshot(body.source_id)
        return {"id": ident, "snapshot": snapshot.model_dump(), "stale": snapshot.stale}

    @app.get("/api/snapshots/latest")
    def latest():
        ident, snapshot = service.require_snapshot()
        return {"id": ident, "snapshot": snapshot.model_dump(), "stale": snapshot.stale}

    @app.post("/api/equipment/compare")
    def compare(body: ComparisonInput):
        return service.compare(body)

    @app.post("/api/economy/quote")
    def quote(body: EconomyInput):
        return service.quote(body)

    @app.get("/api/prices")
    def prices():
        return service.price_context()

    @app.post("/api/prices")
    def add_price(body: PriceInput):
        return {"id": service.add_price(body.item_id, body.copper)}

    @app.post("/api/ai/plan")
    async def plan():
        advice, engine = await service.advice()
        return {"advice": advice, "engine": engine}

    @app.post("/api/ai/ask")
    async def ask(body: QuestionInput):
        advice, engine = await service.advice(body.question)
        return {"advice": advice, "engine": engine}

    @app.get("/api/tasks")
    def tasks():
        return service.task_context()

    @app.post("/api/tasks")
    def add_task(body: TaskInput):
        _, snapshot = service.require_snapshot()
        return {"id": service.db.add_task(settings.mode, snapshot.character.identity, body.title, body.note)}

    @app.patch("/api/tasks/{task_id}")
    def patch_task(task_id: int, body: TaskUpdate):
        _, snapshot = service.require_snapshot()
        if not service.db.update_task(task_id, settings.mode, snapshot.character.identity, body.done):
            raise HTTPException(404, "没有找到该待办")
        return {"done": body.done}

    @app.delete("/api/tasks/{task_id}")
    def delete_task(task_id: int):
        _, snapshot = service.require_snapshot()
        if not service.db.delete_task(task_id, settings.mode, snapshot.character.identity):
            raise HTTPException(404, "没有找到该待办")
        return {"deleted": True}

    async def sync_references():
        if app.state.reference_lock.locked():
            raise ValueError("资料正在同步，请稍候")
        async with app.state.reference_lock:
            return await service.refs.sync()

    @app.get("/api/references/status")
    def reference_status():
        return service.db.reference_status()

    @app.post("/api/references/sync")
    async def reference_sync():
        return await sync_references()

    @app.get("/api/references/search")
    def reference_search(q: str, kind: str = "items"):
        snapshot = service.latest()
        return service.refs.search(q, kind, snapshot[1] if snapshot else None)

    @app.post("/api/references/mcp")
    async def mcp(body: MCPInput):
        return await service.refs.mcp(body.tool, body.arguments)

    @app.get("/overview", response_class=HTMLResponse)
    def overview(request: Request):
        return render(request, "overview.html", current="overview")

    @app.get("/", response_class=HTMLResponse)
    def addons_page(request: Request, category: str = "全部"):
        return render(request, "addons.html", current="addons", inventory=platform.inventory(),
                      plans=platform.plans(), history=platform.history(), category=category)

    @app.get("/addons/plans/{op}", response_class=HTMLResponse)
    def addon_plan_page(request: Request, op: str):
        return render(request, "addon_plan.html", current="addons", plan=platform.review(op))

    @app.get("/profiles", response_class=HTMLResponse)
    def profiles_page(request: Request):
        return render(request, "profiles.html", current="profiles", profiles=profiles.overview())

    @app.get("/workshop", response_class=HTMLResponse)
    def workshop_page(request: Request, project: str | None = None):
        selected = workshop.project(project)[1] if project else None
        return render(request, "workshop.html", current="workshop", projects=workshop.projects(), selected=selected,
                      files=workshop.files(project) if project else [],
                      revisions=workshop.history(project) if project else [], mcp_config=mcp_configuration(platform),
                      installed=platform.inventory()["packages"])

    @app.get("/growth", response_class=HTMLResponse)
    def growth(request: Request):
        advice, engine = None, "rules"
        if service.latest():
            ident, snapshot = service.latest()
            saved = service.db.last_advice(ident)
            advice = saved["payload"] if saved else rule_plan(snapshot, ident).model_dump()
            engine = saved["engine"] if saved else "rules"
        return render(request, "growth.html", current="growth", advice=advice, engine=engine)

    @app.get("/equipment", response_class=HTMLResponse)
    def equipment(request: Request, candidate_id: int | None = None):
        latest = service.latest()
        snap = latest[1] if latest else None
        return render(request, "equipment.html", current="equipment",
                      equipped=[i.model_dump() for i in snap.equipment or [] if i.item_id and i.status == "available"] if snap else [],
                      bag_items=[{"index": index, **item.model_dump()} for index, item in enumerate(snap.bags or [])] if snap else [],
                      candidate_prefill=candidate_id, auto_comparisons=service.auto_comparisons(),
                      auto_equipment_note="自动按已知槽位匹配背包候选，按智力增量排序；这是属性比较，不是 DPS 模拟。")

    @app.get("/economy", response_class=HTMLResponse)
    def economy(request: Request, recipe_id: int | None = None, origin: str = "snapshot"):
        snap = service.latest()
        extra = service.auto_economy()
        selected = None
        if origin == "reference" and recipe_id:
            selected = service.refs.get_recipe(recipe_id, snap[1] if snap else None)[0]
        return render(request, "economy.html", current="economy", recipes=snap[1].recipes or [] if snap else [],
                      selected_recipe=selected, recipe_prefill=recipe_id, origin_prefill=origin, **extra)

    @app.get("/ask", response_class=HTMLResponse)
    def ask_page(request: Request):
        return render(request, "ask.html", current="ask")

    @app.get("/tasks", response_class=HTMLResponse)
    def tasks_page(request: Request):
        return render(request, "tasks.html", current="tasks", **(service.task_context() if service.latest() else {"tasks": []}))

    @app.get("/references", response_class=HTMLResponse)
    def refs_page(request: Request):
        return render(request, "references.html", current="references", reference_status=service.db.reference_status(), results=[])

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return render(request, "settings.html", current="settings", game_path=service.game_path or "", sources=service.sources(), reference_status=service.db.reference_status())

    @app.post("/ui/plan")
    async def ui_plan(request: Request):
        advice, engine = await service.advice()
        return render(request, "partials/advice.html", advice=advice, engine=engine, question=None)

    @app.get("/ui/automation/status")
    def ui_automation_status(request: Request):
        return render(request, "partials/automation_status.html")

    @app.post("/ui/automation/run")
    async def ui_automation_run(request: Request):
        await automation.run_once(force=True)
        return render(request, "partials/automation_status.html")

    @app.post("/ui/ask")
    async def ui_ask(request: Request):
        form = await request.form()
        question = QuestionInput(question=str(form.get("question", ""))).question
        advice, engine = await service.advice(question)
        return render(request, "partials/advice.html", advice=advice, engine=engine, question=question)

    @app.post("/ui/equipment")
    async def ui_equipment(request: Request):
        form = dict(await request.form())
        kind = form.get("candidate_kind", "bag")
        manual = None
        if kind == "manual":
            manual = Item(item_id=int(form.get("manual_item_id") or ""), name=form.get("manual_name") or None,
                          item_level=None, quality=None, stats=json.loads(form.get("manual_stats") or "{}"))
        body = ComparisonInput(slot=int(form.get("slot") or ""), candidate_kind=kind,
                               bag_index=int(form["bag_index"]) if kind == "bag" and form.get("bag_index") else None,
                               reference_item_id=int(form["reference_item_id"]) if kind == "reference" and form.get("reference_item_id") else None,
                               manual_item=manual, weights=json.loads(form["weights"]) if form.get("weights") else None)
        return render(request, "partials/comparison.html", result=service.compare(body))

    @app.post("/ui/prices")
    async def ui_prices(request: Request):
        form = await request.form()
        service.add_price(int(form.get("item_id") or ""), gold_to_copper(form.get("price_gold")))
        return render(request, "partials/prices.html", message="手工价格已记录。", **service.price_context())

    @app.post("/ui/economy")
    async def ui_economy(request: Request):
        form = dict(await request.form())
        origin = form.get("recipe_origin", "snapshot")
        recipe_id = form.get("reference_recipe_id") if origin == "reference" else form.get("recipe_id")
        manual = Recipe.model_validate(json.loads(form["manual_recipe"])) if origin == "manual" and form.get("manual_recipe") else None
        body = EconomyInput(recipe_origin=origin, recipe_id=int(recipe_id) if recipe_id else None,
                            manual_recipe=manual, sale_unit_copper=gold_to_copper(form.get("sale_gold"), optional=True),
                            fee_percent=form.get("fee_percent") or None, batches=int(form.get("batches") or 1),
                            extra_cost_copper=gold_to_copper(form.get("extra_gold") or "0"))
        return render(request, "partials/economy_result.html", result=service.quote(body))

    @app.post("/ui/tasks")
    async def ui_tasks(request: Request):
        form = await request.form()
        body = TaskInput(title=str(form.get("title", "")), note=str(form.get("note", "")))
        _, snapshot = service.require_snapshot()
        service.db.add_task(settings.mode, snapshot.character.identity, body.title, body.note)
        return render(request, "partials/tasks.html", **service.task_context())

    @app.post("/ui/tasks/{task_id}/toggle")
    async def ui_task_toggle(request: Request, task_id: int):
        form = await request.form()
        if form.get("done") not in ("0", "1"):
            raise ValueError("待办状态无效")
        _, snapshot = service.require_snapshot()
        if not service.db.update_task(task_id, settings.mode, snapshot.character.identity, form["done"] == "1"):
            raise ValueError("没有找到这个待办")
        return render(request, "partials/tasks.html", **service.task_context())

    @app.post("/ui/tasks/{task_id}/delete")
    async def ui_task_delete(request: Request, task_id: int):
        _, snapshot = service.require_snapshot()
        if not service.db.delete_task(task_id, settings.mode, snapshot.character.identity):
            raise ValueError("没有找到这个待办")
        return render(request, "partials/tasks.html", **service.task_context())

    @app.post("/ui/references/sync")
    async def ui_sync(request: Request):
        report = await sync_references()
        return render(request, "partials/reference_status.html", reference_status=service.db.reference_status(), report=report, message="无限图鉴资料已同步。")

    @app.post("/ui/references/search")
    async def ui_search(request: Request):
        form = await request.form()
        snap = service.latest()
        results = service.refs.search(str(form.get("q", "")), str(form.get("kind", "items")), snap[1] if snap else None)
        return render(request, "partials/reference_results.html", results=results)

    @app.post("/ui/references/mcp")
    async def ui_mcp(request: Request):
        form = await request.form()
        result = await service.refs.mcp(str(form.get("tool", "search")), json.loads(str(form.get("arguments", "{}"))))
        return render(request, "partials/mcp_result.html", result=result)

    @app.post("/ui/settings")
    async def ui_settings(request: Request):
        form = await request.form()
        service.configure_path(str(form.get("game_path", "")))
        return render(request, "partials/sources.html", sources=service.sources(), game_path=service.game_path or "", message="游戏路径已保存。")

    @app.post("/ui/sources")
    def ui_sources(request: Request):
        return render(request, "partials/sources.html", sources=service.sources(), game_path=service.game_path or "", message="角色来源已重新发现。")

    @app.post("/ui/import")
    async def ui_import(request: Request):
        form = await request.form()
        service.import_snapshot(str(form.get("source_id", "")))
        response = notice(request, "角色快照已同步。")
        response.headers["HX-Refresh"] = "true"
        return response

    @app.post("/ui/character")
    async def ui_character(request: Request):
        form = await request.form()
        service.select_character(str(form.get("character_id", "")))
        response = notice(request, "当前角色已切换。")
        response.headers["HX-Refresh"] = "true"
        return response

    return app
