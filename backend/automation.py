"""Automation runs only while the explicitly started local service is running."""
from __future__ import annotations

import asyncio
import json
import time

from .paths import discover
from .savedvariables import read_snapshot

OFFICIAL_PROVIDER = {
    "name": "Blizzard 官方 Web API", "status": "unverified_for_forever_cn",
    "source": "https://community.developer.battle.net/documentation/world-of-warcraft/guides/namespaces",
    "note": "尚未核实《无限》国服对应的公开命名空间与访问条件，当前不导入正式服或怀旧服数据。",
}


class Automation:
    def __init__(self, service):
        self.service = service
        self.lock = asyncio.Lock()
        self.seen = {}
        self.reference_attempt = 0
        self.market_attempt = 0
        self.ai_attempt = 0
        saved = service.db.get("automation:" + service.settings.mode)
        try:
            saved = json.loads(saved) if saved else {}
        except json.JSONDecodeError:
            saved = {}
        self.state = {"enabled": service.settings.auto_sync, "status": "paused" if not service.settings.auto_sync else "mock" if service.settings.mode == "mock" else "waiting",
                      "last_scan": None, "last_import": saved.get("last_import"),
                      "last_reference_sync": saved.get("last_reference_sync"), "last_market_sync": saved.get("last_market_sync"),
                      "sources_count": 0, "errors": {}, "providers": [OFFICIAL_PROVIDER]}

    def status(self):
        return {**self.state, "errors": dict(self.state["errors"]),
                "events": self.service.db.automation_events(self.service.settings.mode)}

    def error(self, key, message):
        if self.state["errors"].get(key) != message:
            self.service.db.automation_event(self.service.settings.mode, key, "error", message)
        self.state["errors"][key] = message

    def scan(self):
        sources = discover(self.service.game_path)
        self.state["sources_count"] = len(sources)
        changed = []
        valid_ids = {source.id for source in sources}
        for key in list(self.state["errors"]):
            if key.startswith("source:") and key[7:] not in valid_ids:
                self.state["errors"].pop(key, None)
        for source in sources:
            key = "source:" + source.id
            try:
                stat = source.path.stat()
                signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                if self.seen.get(source.id) == signature:
                    continue
                snapshot = read_snapshot(source.path, source.character, source.realm)
                ident = self.service.db.save_snapshot(snapshot)
                self.service.market.ingest_snapshot(snapshot)
                self.seen[source.id] = signature
                self.state["errors"].pop(key, None)
                changed.append((ident, snapshot))
            except (ValueError, OSError):
                self.error(key, "角色存档暂时不可读或校验未通过；保留上一份数据，下次自动重试。")
        if changed:
            _, latest = max(changed, key=lambda entry: entry[1].captured_at)
            # Do not let an older edited file displace a newer valid snapshot.
            global_latest = self.service.db.latest("live")
            if global_latest and global_latest[1].captured_at >= latest.captured_at:
                latest = global_latest[1]
            self.service.db.set("character:live", latest.character.identity)
            self.state["last_import"] = int(time.time())
            self.service.db.automation_event("live", "snapshots", "ok", f"自动读取 {len(changed)} 份角色快照；按角色和时间保存。")
        self.state["last_scan"] = int(time.time())
        return changed

    async def run_once(self, force=False):
        if self.lock.locked():
            return self.status()
        async with self.lock:
            mode = self.service.settings.mode
            self.state["status"] = "mock" if mode == "mock" else "running"
            if mode == "live":
                await asyncio.to_thread(self.scan)
            else:
                self.state["last_scan"] = int(time.time())
            await asyncio.to_thread(self.service.ensure_derived)
            now = int(time.time())
            if mode == "live" and self.service.settings.references_enabled:
                cache = self.service.db.reference("manifest")
                reference_due = cache is None or now - cache["fetched_at"] > 21600 or "references" in self.state["errors"]
                if force or (reference_due and now - self.reference_attempt >= 300):
                    self.reference_attempt = now
                    try:
                        report = await self.service.refs.sync()
                        self.state["last_reference_sync"] = int(time.time())
                        self.state["errors"].pop("references", None)
                        self.service.db.automation_event(mode, "references", "ok", f"自动同步版本 {report['build']} 的资料。")
                    except (ValueError, OSError):
                        self.error("references", "公开资料暂时无法同步；保留缓存，稍后自动重试。")
                last_market = int(self.service.db.get("market:last_sync", "0"))
                if force or (now - last_market > 1800 and now - self.market_attempt >= 300):
                    self.market_attempt = now
                    try:
                        market = await self.service.market.sync()
                        self.state["last_market_sync"] = int(time.time())
                        self.state["errors"].pop("market", None)
                        self.service.db.automation_event(mode, "market", "ok", f"自动归档 {market['count']} 条公开参考报价；市场范围保留在记录中。")
                    except (ValueError, OSError):
                        self.error("market", "公开报价暂时无法同步；保留历史，不生成替代价格。")
                if cache and not self.state["last_reference_sync"]:
                    self.state["last_reference_sync"] = cache["fetched_at"]
            if mode == "live" and self.service.settings.api_key and now - self.ai_attempt >= 300:
                latest = self.service.latest()
                if latest:
                    saved = self.service.db.last_advice(latest[0])
                    if not saved or saved["engine"].startswith("rules"):
                        self.ai_attempt = now
                        try:
                            await self.service.advice()
                            await asyncio.to_thread(self.service.ensure_derived)
                            self.state["errors"].pop("ai", None)
                        except ValueError:
                            self.error("ai", "AI 暂时不可用；已保留自动规则建议，稍后重试。")
            self.state["status"] = "mock" if mode == "mock" else "error" if self.state["errors"] else "ready"
            self.service.db.set("automation:" + mode, json.dumps(self.state, ensure_ascii=False))
            return self.status()

    async def loop(self):
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.error("worker", "自动同步遇到异常；已有记录保留，下一轮重试。")
            await asyncio.sleep(5)
