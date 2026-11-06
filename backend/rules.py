from decimal import Decimal, ROUND_HALF_UP

from .models import Action, Advice, Claim, Item, Recipe, Snapshot

STAT_NAMES = {
    "ITEM_MOD_INTELLECT_SHORT": "智力", "ITEM_MOD_STAMINA_SHORT": "耐力",
    "ITEM_MOD_SPIRIT_SHORT": "精神", "ITEM_MOD_AGILITY_SHORT": "敏捷",
    "ITEM_MOD_STRENGTH_SHORT": "力量", "ITEM_MOD_SPELL_POWER_SHORT": "法术强度",
    "ITEM_MOD_CRIT_RATING_SHORT": "暴击等级", "ITEM_MOD_HIT_RATING_SHORT": "命中等级",
    "ITEM_MOD_MANA_SHORT": "法力", "RESISTANCE0_NAME": "护甲",
}


def rule_plan(snapshot: Snapshot, snapshot_id: str, question: str | None = None) -> Advice:
    source = "assumption" if snapshot.data_mode == "mock" else "verified"
    def claim(text, section, provenance=None):
        return Claim(text=text, provenance=provenance or source,
                     evidence_ids=[f"snapshot:{snapshot_id}:{section}"])
    quests = [q for q in snapshot.quests or [] if q.is_complete and q.title]
    if quests:
        first = Action(title="先处理已完成的任务", reason=claim(f"快照中“{quests[0].title}”已完成；请在游戏中核对交付位置与奖励。", "quests"))
    elif snapshot.quests:
        quest = next((q for q in snapshot.quests if q.title), None)
        first = Action(title="规划下一段任务路线", reason=claim(
            f"任务日志记录了“{quest.title}”；结合游戏地图核实目标和路径，再决定顺序。" if quest else "任务日志中标题不可读，请先在游戏中核实目标。", "quests"))
    else:
        first = Action(title="补全当前任务信息", reason=Claim(text="尚无可用任务日志。打开任务界面，重新导出后再安排具体路线。", provenance="assumption", evidence_ids=[]))
    if snapshot.equipment is not None and snapshot.bags is not None:
        second = Action(title="检查自动装备比较", reason=claim("系统会按槽位匹配背包中的候选装备，列出已知属性变化；在游戏中核实后自行决定换装。", "equipment"))
    else:
        second = Action(title="补全装备与背包快照", reason=Claim(text="装备或背包不可读，当前无法给出可靠换装结论。请脱战后重新导出。", provenance="assumption", evidence_ids=[]))
    tailoring = any(p.skill_line_id == 197 for p in snapshot.professions or [])
    third = Action(title="查看裁缝成本与报价覆盖" if tailoring else "核实专业与团本准备事项",
                   reason=claim("专业快照记录了裁缝。系统会自动匹配配方与可用报价，缺少的价格或费率保留未知。", "professions") if tailoring else
                   Claim(text="先核实你的专业和目标副本；将确定的装备、消耗品与任务要求加入个人待办。", provenance="assumption", evidence_ids=[]))
    unknowns = []
    for key, label in (("talents", "天赋"), ("professions", "专业"), ("recipes", "已学配方"), ("quests", "任务")):
        if getattr(snapshot, key) is None:
            unknowns.append(f"{label}未知：{snapshot.unavailable.get(key, '字段不可读')}")
    if snapshot.stale:
        unknowns.append("快照已超过 24 小时，建议重新同步。")
    if snapshot.data_mode == "mock":
        unknowns.insert(0, "当前为合成演示数据，不能用作真实游戏建议。")
    if question:
        unknowns.append("离线规则无法判断问题中未提供的掉落、路线、市场价格或服务器规则。")
    summary = "根据当前快照整理下一步；具体路线和数值以游戏内核实为准。"
    if question:
        summary = "当前使用离线规则回答。可先查看以下与当前快照相关的行动；具体问答需要配置 OpenAI API Key 并使用真实模式。"
    return Advice(summary=summary, claims=[first.reason, second.reason, third.reason], actions=[first, second, third], unknowns=unknowns)


def compare_items(current: Item, candidate: Item, *, weights: dict[str, float] | None = None):
    deltas = []
    unknowns = []
    if current.stats is None or candidate.stats is None:
        unknowns.append("至少一件装备的属性未知，无法计算属性差。")
    else:
        for key in sorted(set(current.stats) | set(candidate.stats)):
            before, after = current.stats.get(key, 0), candidate.stats.get(key, 0)
            delta = after - before if before is not None and after is not None else None
            deltas.append({"stat": key, "label": STAT_NAMES.get(key, key), "current": before, "candidate": after,
                           "delta": delta, "provenance": "calculated"})
            if delta is None:
                unknowns.append(f"{STAT_NAMES.get(key, key)}存在不可读数值。")
    score = None
    if weights:
        if current.stats is not None and candidate.stats is not None:
            total = Decimal(0)
            for key, weight in weights.items():
                before, after = current.stats.get(key, 0), candidate.stats.get(key, 0)
                if before is None or after is None:
                    break
                total += (Decimal(str(after)) - Decimal(str(before))) * Decimal(str(weight))
            else:
                score = str(total)
    return {"current": current.model_dump(), "candidate": candidate.model_dump(), "deltas": deltas,
            "weighted_delta": score, "weight_basis": "用户自定权重（assumption），不是 DPS 模拟" if weights else None,
            "unknowns": unknowns, "provenance": "calculated",
            "conclusion": "仅比较已知属性；套装、特效、命中阈值和实战收益未建模。"}


def economy_quote(recipe: Recipe, prices: dict[int, int], sale_unit_copper: int | None,
                  fee_percent: Decimal | None, batches=1, extra_cost_copper=0):
    if type(batches) is not int or not 1 <= batches <= 10000:
        raise ValueError("制作批次应在 1–10000 之间")
    if sale_unit_copper is not None and (type(sale_unit_copper) is not int or not 0 <= sale_unit_copper <= 10**14):
        raise ValueError("成品价格无效")
    if type(extra_cost_copper) is not int or not 0 <= extra_cost_copper <= 10**14:
        raise ValueError("额外费用无效")
    if fee_percent is not None and (not fee_percent.is_finite() or not 0 <= fee_percent <= 100):
        raise ValueError("手续费率应为 0–100")
    if any(type(v) is not int or not 0 <= v <= 10**14 for v in prices.values()):
        raise ValueError("材料价格必须为非负整数铜币")
    unknowns, lines = [], []
    cost = 0
    if recipe.reagents is None:
        unknowns.append("材料清单未知或存在未选定的替代材料。")
    for reagent in recipe.reagents or []:
        price = prices.get(reagent.item_id)
        line_cost = price * reagent.quantity * batches if price is not None else None
        lines.append({"item_id": reagent.item_id, "quantity": reagent.quantity * batches,
                      "unit_copper": price, "cost_copper": line_cost})
        if line_cost is None:
            unknowns.append(f"材料 {reagent.item_id} 缺少手工价格。")
        else:
            cost += line_cost
    material_cost = None if unknowns else cost
    quantity = recipe.output_quantity * batches if recipe.output_quantity is not None else None
    if quantity is None:
        unknowns.append("固定产量未知，无法确定销售收入。")
    if sale_unit_copper is None:
        unknowns.append("成品售价未知。")
    if fee_percent is None:
        unknowns.append("手续费率未知，请手工输入。")
    gross = sale_unit_copper * quantity if sale_unit_copper is not None and quantity is not None else None
    fee = int((Decimal(gross) * fee_percent / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)) if gross is not None and fee_percent is not None else None
    profit = gross - fee - material_cost - extra_cost_copper if not unknowns else None
    total_cost = material_cost + extra_cost_copper if material_cost is not None else None
    gross_margin = gross - total_cost if gross is not None and total_cost is not None else None
    break_even = str((Decimal(gross_margin) / gross * 100).quantize(Decimal("0.01"))) if gross_margin is not None and gross else None
    roi = str((Decimal(profit) / total_cost * 100).quantize(Decimal("0.01"))) if profit is not None and total_cost else None
    return {"recipe_id": recipe.recipe_id, "lines": lines, "batches": batches, "output_quantity": quantity,
            "material_cost_copper": material_cost, "gross_copper": gross, "fee_copper": fee,
            "extra_cost_copper": extra_cost_copper, "profit_copper": profit, "roi_percent": roi,
            "gross_margin_copper": gross_margin, "break_even_fee_percent": break_even,
            "unknowns": unknowns, "provenance": "calculated",
            "assumptions": ["手工价格和手续费率是用户输入；销售成交情况未知。", "费用估算四舍五入至铜，客户端实际收费取整仍需验证。", "额外费用仅填写实际不退回的成本；不重复扣除成功出售后退回的押金。"]}
