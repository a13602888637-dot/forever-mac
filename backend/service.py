from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path

from pydantic import Field, StrictInt

from .ai import Advisor
from .config import Settings
from .db import Database
from .models import Item, Model, PositiveID, Recipe, Snapshot
from .market import Market
from .paths import discover, game_flavors, import_source
from .references import References
from .rules import compare_items, economy_quote, rule_plan

ROOT = Path(__file__).resolve().parent.parent


class ComparisonInput(Model):
    slot: StrictInt = Field(ge=1, le=19)
    candidate_kind: str = Field(pattern="^(bag|reference|manual)$")
    bag_index: StrictInt | None = Field(default=None, ge=0, le=2000)
    reference_item_id: PositiveID | None = None
    manual_item: Item | None = None
    weights: dict[str, float] | None = None


class EconomyInput(Model):
    recipe_origin: str = Field(default="snapshot", pattern="^(snapshot|reference|manual)$")
    recipe_id: PositiveID | None = None
    manual_recipe: Recipe | None = None
    sale_unit_copper: StrictInt | None = Field(default=None, ge=0, le=10**14)
    fee_percent: str | int | float | None = None
    batches: StrictInt = Field(default=1, ge=1, le=10000)
    extra_cost_copper: StrictInt = Field(default=0, ge=0, le=10**14)


def gold_to_copper(value, optional=False):
    if value is None or value == "":
        if optional:
            return None
        raise ValueError("请填写金币金额")
    try:
        amount = Decimal(str(value)) * 10000
        if not amount.is_finite() or amount < 0 or amount > 10**14 or amount != amount.to_integral_value():
            raise ValueError("金额必须非负，最小单位为 0.0001 金（1 铜）")
        return int(amount)
    except InvalidOperation:
        raise ValueError("金币金额格式无效") from None


class Companion:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.data_dir / "companion.sqlite3")
        self.refs = References(self.db, settings.references_enabled,
                               addon_catalog_path=ROOT / "addons/ForeverAI/CatalogData.lua")
        self.advisor = Advisor(settings)
        self.market = Market(self)
        self.game_path = settings.game_path or self.db.get("game_path")
        if settings.mode == "mock":
            snapshot = Snapshot.model_validate_json((ROOT / "fixtures/mock_snapshot.json").read_text())
            self.db.save_snapshot(snapshot)
            prices = {p["item_id"] for p in self.db.prices("mock", snapshot.character.realm)}
            for item_id, copper in ((1900000101, 100), (1900000102, 50), (1900000202, 1000)):
                if item_id not in prices:
                    self.db.add_price("mock", snapshot.character.realm, item_id, copper)
        self._derived_version = None
        self.ensure_derived()

    def latest(self):
        selected = self.db.get("character:" + self.settings.mode)
        found = self.db.latest(self.settings.mode, selected)
        return found or self.db.latest(self.settings.mode)

    def require_snapshot(self):
        result = self.latest()
        if result is None:
            raise ValueError("尚无角色快照。插件会自动记录；手动 /reload 或退出游戏后，本地服务会自动发现并导入。")
        return result

    def sources(self):
        return [{"id": s.id, "realm": s.realm, "character": s.character} for s in discover(self.game_path)]

    def configure_path(self, value):
        value = value.strip()
        if len(value) > 1000 or "\x00" in value:
            raise ValueError("游戏路径无效")
        if value:
            root = Path(value).expanduser()
            if not root.is_dir() or not game_flavors(root):
                raise ValueError("没有找到包含 WTF 的无限客户端版本目录，请选择游戏安装根目录或 _forever_ 目录。")
            value = str(root.resolve())
        self.game_path = value or None
        self.db.set("game_path", value)

    def import_snapshot(self, source_id):
        if self.settings.mode != "live":
            raise ValueError("Mock 模式不导入真实角色。请用 serve --mode live 启动后同步。")
        snapshot = import_source(source_id, self.game_path)
        ident = self.db.save_snapshot(snapshot)
        self.market.ingest_snapshot(snapshot)
        self.db.set("character:live", snapshot.character.identity)
        self.ensure_derived()
        return ident, snapshot

    def select_character(self, identity):
        if not any(c["character_id"] == identity for c in self.db.characters(self.settings.mode)):
            raise ValueError("当前模式中没有这个角色")
        self.db.set("character:" + self.settings.mode, identity)

    def compare(self, request: ComparisonInput):
        snapshot_id, snapshot = self.require_snapshot()
        current = next((item for item in snapshot.equipment or [] if item.slot == request.slot and item.item_id and item.status == "available"), None)
        if current is None:
            raise ValueError("选定槽位没有可比较的已知装备")
        source = {"provenance": "assumption" if snapshot.data_mode == "mock" else "verified",
                  "evidence_id": f"snapshot:{snapshot_id}:bags", "origin": "当前角色背包快照"}
        if request.candidate_kind == "bag":
            if request.bag_index is None or snapshot.bags is None or request.bag_index >= len(snapshot.bags):
                raise ValueError("请选择有效的背包候选装备")
            candidate = snapshot.bags[request.bag_index]
        elif request.candidate_kind == "reference":
            if request.reference_item_id is None:
                raise ValueError("请填写资料库物品 ID")
            candidate, source = self.refs.get_item(request.reference_item_id, snapshot)
        else:
            if request.manual_item is None:
                raise ValueError("请填写手工候选装备属性")
            candidate = request.manual_item
            source = {"provenance": "assumption", "origin": "用户手工输入，属性需要确认"}
        if request.weights and (len(request.weights) > 100 or any(len(k) > 100 for k in request.weights)):
            raise ValueError("权重字段过多或过长")
        result = compare_items(current, candidate, weights=request.weights)
        result.update(source=source, snapshot_id=snapshot_id)
        result["unknowns"].append("候选装备的穿戴槽位、职业限制、特效与套装效果仍需在游戏中核实。")
        return result

    def quote(self, request: EconomyInput):
        snapshot_id, snapshot = self.require_snapshot()
        source = {"provenance": "assumption" if snapshot.data_mode == "mock" else "verified",
                  "evidence_id": f"snapshot:{snapshot_id}:recipes", "origin": "当前角色已学配方快照"}
        if request.recipe_origin == "reference":
            if request.recipe_id is None:
                raise ValueError("请填写资料库配方 ID")
            recipe, source = self.refs.get_recipe(request.recipe_id, snapshot)
            source["learning_status"] = "资料库配方不代表角色已学会"
        elif request.recipe_origin == "manual":
            if request.manual_recipe is None:
                raise ValueError("请填写完整手工配方")
            recipe = request.manual_recipe
            source = {"provenance": "assumption", "origin": "用户手工输入，配方需要确认"}
        else:
            recipe = next((r for r in snapshot.recipes or [] if r.recipe_id == request.recipe_id), None)
            if recipe is None:
                raise ValueError("当前快照没有该配方；也可选择资料库或手工配方")
        prices = {p["item_id"]: p["copper"] for p in self.db.prices(self.settings.mode, snapshot.character.realm)}
        try:
            rate = Decimal(str(request.fee_percent)) if request.fee_percent not in (None, "") else None
        except InvalidOperation:
            raise ValueError("手续费率格式无效") from None
        result = economy_quote(recipe, prices, request.sale_unit_copper, rate, request.batches, request.extra_cost_copper)
        result.update(source=source, snapshot_id=snapshot_id, recipe_name=recipe.name)
        return result

    async def advice(self, question=None):
        latest = self.latest()
        if not latest and not question:
            self.require_snapshot()
        snapshot_id, snapshot = latest if latest else ("general", None)
        refs = []
        # Only cached, explicitly versioned matches may enter the model context.
        if question and snapshot and self.db.reference_status():
            refs = self.refs.context_matches(question, snapshot)
        result, engine = await self.advisor.generate(snapshot, snapshot_id, question, refs)
        if snapshot:
            self.db.save_advice(snapshot_id, "ask" if question else "plan", engine, result.model_dump(), question)
        return result.model_dump(), engine

    def add_price(self, item_id, copper):
        _, snapshot = self.require_snapshot()
        return self.db.add_price(self.settings.mode, snapshot.character.realm, item_id, copper)

    def price_context(self):
        _, snapshot = self.require_snapshot()
        names = {i.item_id: i.name for i in (snapshot.equipment or []) + (snapshot.bags or []) if i.item_id}
        return {"prices": self.db.prices(self.settings.mode, snapshot.character.realm),
                "history": self.db.price_history(self.settings.mode, snapshot.character.realm), "item_names": names}

    def task_context(self):
        _, snapshot = self.require_snapshot()
        return {"tasks": self.db.tasks(self.settings.mode, snapshot.character.identity)}

    def ensure_derived(self):
        latest = self.latest()
        if not latest:
            return
        ident, snapshot = latest
        saved = self.db.last_advice(ident)
        if saved is None:
            advice = rule_plan(snapshot, ident).model_dump()
            engine = "mock-rules" if snapshot.data_mode == "mock" else "rules-awaiting-ai" if self.advisor.status()["ready"] else "rules-no-api-key"
            advice_id = self.db.save_advice(ident, "plan", engine, advice)
        else:
            advice = saved["payload"]
            advice_id = saved["id"]
        if self._derived_version == (ident, advice_id):
            return
        entries = []
        for action in advice["actions"]:
            key = "action:" + hashlib.sha256(action["title"].encode()).hexdigest()[:20]
            entries.append((key, action["title"], action["reason"]["text"][:2000], None,
                            action["reason"]["provenance"], action["reason"]["evidence_ids"]))
        for quest in snapshot.quests or []:
            if quest.title:
                entries.append((f"quest:{quest.quest_id}", quest.title[:200],
                                "由任务日志自动跟踪。目标完成不等于已经交付任务。", quest.is_complete,
                                "verified" if snapshot.data_mode == "live" else "assumption", [f"snapshot:{ident}:quests"]))
        self.db.sync_auto_tasks(snapshot.data_mode, snapshot.character.identity, entries)
        self._derived_version = (ident, advice_id)

    def auto_comparisons(self):
        latest = self.latest()
        if not latest:
            return []
        ident, snapshot = latest
        slots = {"INVTYPE_HEAD": (1,), "INVTYPE_NECK": (2,), "INVTYPE_SHOULDER": (3,), "INVTYPE_BODY": (4,),
                 "INVTYPE_CHEST": (5,), "INVTYPE_ROBE": (5,), "INVTYPE_WAIST": (6,), "INVTYPE_LEGS": (7,),
                 "INVTYPE_FEET": (8,), "INVTYPE_WRIST": (9,), "INVTYPE_HAND": (10,), "INVTYPE_FINGER": (11, 12),
                 "INVTYPE_TRINKET": (13, 14), "INVTYPE_CLOAK": (15,), "INVTYPE_WEAPON": (16, 17),
                 "INVTYPE_2HWEAPON": (16,), "INVTYPE_WEAPONMAINHAND": (16,), "INVTYPE_WEAPONOFFHAND": (17,),
                 "INVTYPE_SHIELD": (17,), "INVTYPE_HOLDABLE": (17,), "INVTYPE_RANGED": (18,),
                 "INVTYPE_RANGEDRIGHT": (18,), "INVTYPE_THROWN": (18,), "INVTYPE_TABARD": (19,)}
        equipped = {item.slot: item for item in snapshot.equipment or [] if item.item_id and item.status == "available"}
        results = []
        for candidate in snapshot.bags or []:
            for slot in slots.get(candidate.equip_location, ()):
                current = equipped.get(slot)
                if not current:
                    continue
                result = compare_items(current, candidate)
                result.update(snapshot_id=ident, source={"provenance": "assumption" if snapshot.data_mode == "mock" else "verified",
                              "origin": "自动匹配背包中的同槽位候选", "evidence_id": f"snapshot:{ident}:bags"})
                result["unknowns"].append("属性变化不等于实战收益；穿戴限制、套装和特效仍需在游戏中确认。")
                results.append(result)
        def intellect_delta(result):
            row = next((r for r in result["deltas"] if r["stat"] == "ITEM_MOD_INTELLECT_SHORT"), None)
            return row["delta"] if row and row["delta"] is not None else float("-inf")
        return sorted(results, key=intellect_delta, reverse=True)[:12]

    def _auto_recipe_options(self, snapshot, ident):
        options = []
        reference = self.refs.dataset("recipes")
        rows = reference["payload"] if reference else []
        by_spell = {r.get("spell"): r for r in rows if isinstance(r, dict) and type(r.get("spell")) is int}
        if snapshot.recipes:
            for recipe in snapshot.recipes[:1000]:
                source = {"provenance": "assumption" if snapshot.data_mode == "mock" else "verified",
                          "origin": "当前角色已学配方快照", "evidence_id": f"snapshot:{ident}:recipes"}
                record = by_spell.get(recipe.recipe_id)
                if record and record.get("skill") != 197:
                    continue
                if record and (recipe.reagents is None or recipe.output_quantity is None or recipe.output_item_id is None):
                    supplemental, supplemental_source = self.refs.get_recipe(record["id"], snapshot)
                    if supplemental_source["version_matches"]:
                        recipe = recipe.model_copy(update={
                            "reagents": recipe.reagents if recipe.reagents is not None else supplemental.reagents,
                            "output_quantity": recipe.output_quantity if recipe.output_quantity is not None else supplemental.output_quantity,
                            "output_item_id": recipe.output_item_id if recipe.output_item_id is not None else supplemental.output_item_id,
                        })
                        source = {**supplemental_source, "origin": "已学配方；缺失材料或产量由同版本资料补充"}
                options.append((recipe, source, "mock" if snapshot.data_mode == "mock" else "learned"))
        elif snapshot.recipes is None:
            tailoring = next((p for p in snapshot.professions or [] if p.skill_line_id == 197), None)
            if tailoring and tailoring.rank is not None:
                candidates = [r for r in rows if isinstance(r, dict) and r.get("skill") == 197 and
                              type(r.get("rank")) is int and r["rank"] <= tailoring.rank]
                for record in sorted(candidates, key=lambda r: r["rank"], reverse=True)[:30]:
                    recipe, source = self.refs.get_recipe(record["id"], snapshot)
                    source = {**source, "provenance": "assumption", "origin": "按已知裁缝等级匹配的资料库配方，尚未确认学会"}
                    options.append((recipe, source, "unconfirmed"))
        return options

    def auto_economy(self):
        latest = self.latest()
        if not latest:
            return {"auto_quotes": [], "market_status": {"status": "waiting", "source": "等待角色快照", "observed_at": None,
                    "realm": None, "note": "角色快照落盘后自动匹配配方和报价。", "errors": {}}, "prices": [], "history": [], "item_names": {}}
        ident, snapshot = latest
        price_rows, status, scopes = self.market.available(snapshot)
        prices = {key: row["copper"] for key, row in price_rows.items()}
        quotes = []
        relevant = set()
        for recipe, source, learning in self._auto_recipe_options(snapshot, ident):
            related = {r.item_id for r in recipe.reagents or []}
            if recipe.output_item_id:
                related.add(recipe.output_item_id)
            relevant.update(related)
            fee = Decimal(5) if snapshot.data_mode == "mock" else None
            result = economy_quote(recipe, prices, prices.get(recipe.output_item_id), fee)
            used = [price_rows[item_id] for item_id in related if item_id in price_rows]
            result.update(source=source, snapshot_id=ident, recipe_name=recipe.name, price_sources=used)
            result["assumptions"] = ["按一批固定产量计算；挂牌报价不等于实际成交价。", "额外上架损失未知，当前仅列材料与挂牌收入的毛差。"]
            if snapshot.data_mode == "mock":
                result["assumptions"].append("演示数据采用模拟 5% 手续费；不可用于真实交易判断。")
            else:
                result["assumptions"].append("实际手续费率尚未核实，净利润保持未知；毛差尚未扣手续费。")
                if any(not p["scope_matches"] for p in used):
                    result["assumptions"].append("部分报价来自其他服务器或阵营，仅为参考市场情景。")
            quotes.append({"recipe": recipe.model_dump(), "result": result, "learning_status": learning})
        # Prefer complete price coverage, never turn an unknown fee into a guaranteed net-profit ranking.
        quotes.sort(key=lambda q: (q["result"]["gross_margin_copper"] is not None,
                                   q["result"]["gross_margin_copper"] or 0), reverse=True)
        names = {i.item_id: i.name for i in (snapshot.bags or []) + (snapshot.equipment or []) if i.item_id}
        metadata = self.market.metadata()
        names.update({int(k): v for k, v in (metadata or {}).get("names", {}).items() if str(k).isdigit()})
        if snapshot.data_mode == "mock":
            history = [{**r, "source": "mock-fixture", "observed_at": r["recorded_at"], "provenance": "assumption"}
                       for r in self.db.price_history("mock", snapshot.character.realm)]
        else:
            history = self.db.market_history("live", scopes)
        display_prices = [row for key, row in price_rows.items() if key in relevant]
        return {"auto_quotes": quotes[:12], "market_status": status, "prices": display_prices[:60],
                "history": history, "item_names": names}
