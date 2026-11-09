from __future__ import annotations

import math
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

PositiveID = Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]
Text = Annotated[StrictStr, Field(max_length=300)]
Provenance = Literal["verified", "calculated", "assumption"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ClientInfo(Model):
    version: Text | None
    build: Text | None
    interface: PositiveID | None


class Character(Model):
    name: Annotated[StrictStr, Field(min_length=1, max_length=64)]
    realm: Annotated[StrictStr, Field(min_length=1, max_length=100)]
    level: Annotated[StrictInt, Field(ge=1, le=1000)] | None
    class_token: Text | None
    race_token: Text | None
    specialization: Text | None
    faction: Text | None = None
    # Desktop-derived storage metadata. It never replaces game-reported names
    # and is excluded from model prompts.
    storage_name: Annotated[StrictStr, Field(min_length=1, max_length=200)] | None = None
    storage_realm_id: PositiveID | None = None

    @field_validator("name", "realm", "storage_name")
    @classmethod
    def identity_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value != value.strip() or any(ord(c) < 32 or c in "/\\" for c in value):
            raise ValueError("角色名和服务器不得包含路径、控制字符或首尾空格")
        return value

    @property
    def identity(self) -> str:
        if self.storage_name is not None and self.storage_realm_id is not None:
            return f"{self.storage_realm_id}:{self.storage_name}"
        return f"{self.realm}:{self.name}"

    @property
    def display_name(self) -> str:
        return self.storage_name.replace("-", " ") if self.storage_name else self.name


class Item(Model):
    item_id: PositiveID | None
    name: Text | None
    slot: Annotated[StrictInt, Field(ge=1, le=19)] | None = None
    bag: Annotated[StrictInt, Field(ge=0, le=20)] | None = None
    bag_slot: Annotated[StrictInt, Field(ge=1, le=200)] | None = None
    count: Annotated[StrictInt, Field(ge=0, le=1_000_000)] = 1
    item_level: Annotated[float, Field(ge=0, le=10000)] | None
    quality: Annotated[StrictInt, Field(ge=0, le=10)] | None
    stats: dict[Annotated[StrictStr, Field(max_length=100)], float | None] | None
    equip_location: Text | None = None
    status: Literal["available", "empty", "unknown"] = "available"

    @field_validator("stats")
    @classmethod
    def numeric_stats(cls, value):
        if value is not None and (len(value) > 100 or any(v is not None and not math.isfinite(v) for v in value.values())):
            raise ValueError("装备属性过多或含非有限数值")
        return value


class Profession(Model):
    skill_line_id: PositiveID
    name: Text | None
    rank: Annotated[StrictInt, Field(ge=0, le=10000)] | None
    max_rank: Annotated[StrictInt, Field(ge=0, le=10000)] | None


class Reagent(Model):
    item_id: PositiveID
    quantity: Annotated[StrictInt, Field(gt=0, le=100000)]


class Recipe(Model):
    recipe_id: PositiveID
    name: Text | None
    output_item_id: PositiveID | None
    output_quantity: Annotated[StrictInt, Field(gt=0, le=10000)] | None
    reagents: Annotated[list[Reagent], Field(max_length=100)] | None


class Quest(Model):
    quest_id: PositiveID
    title: Text | None
    level: Annotated[StrictInt, Field(ge=-1, le=1000)] | None
    is_complete: StrictBool | None
    objectives: Annotated[list[Text], Field(max_length=100)] | None


class TalentNode(Model):
    node_id: PositiveID
    rank: Annotated[StrictInt, Field(ge=0, le=100)] | None


class Talents(Model):
    config_id: PositiveID
    name: Text | None
    nodes: Annotated[list[TalentNode], Field(max_length=3000)] | None


class Capability(Model):
    status: Literal["runtime_verified", "unsupported", "unavailable", "restricted"]
    reason: Text | None


class MarketQuote(Model):
    item_id: PositiveID
    copper: Annotated[StrictInt, Field(ge=0, le=10**14)]
    observed_at: Annotated[StrictInt, Field(gt=1_577_836_800)]
    source: Literal["game_commodity_search", "game_item_search"]
    basis: Literal["unit_price", "rounded_listing_unit_price"]


class Snapshot(Model):
    schema_version: Literal[1]
    addon_version: Text
    captured_at: Annotated[StrictInt, Field(gt=1_577_836_800)]
    data_mode: Literal["live", "mock"]
    client: ClientInfo
    character: Character
    equipment: Annotated[list[Item], Field(max_length=19)] | None
    bags: Annotated[list[Item], Field(max_length=2000)] | None
    professions: Annotated[list[Profession], Field(max_length=1000)] | None
    recipes: Annotated[list[Recipe], Field(max_length=10000)] | None
    quests: Annotated[list[Quest], Field(max_length=1000)] | None
    talents: Talents | None
    auction_quotes: Annotated[list[MarketQuote], Field(max_length=2000)] | None = None
    unavailable: dict[Annotated[StrictStr, Field(max_length=250)], Text]
    capabilities: dict[Annotated[StrictStr, Field(max_length=150)], Capability]

    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and type(value.get("schema_version")) is not int:
            raise ValueError("schema_version 必须为整数 1")
        if isinstance(value, dict):
            value = {**value, "unavailable": dict(value.get("unavailable", {}))}
            if isinstance(value.get("character"), dict) and "faction" not in value["character"]:
                value["character"] = {**value["character"], "faction": None}
                value["unavailable"]["character.faction"] = "not_in_older_snapshot"
            if "auction_quotes" not in value:
                value["auction_quotes"] = None
                value["unavailable"]["auction_quotes"] = "not_in_older_snapshot"
            for section in ("equipment", "bags"):
                if isinstance(value.get(section), list):
                    value[section] = [dict(item) if isinstance(item, dict) else item for item in value[section]]
                    for i, item in enumerate(value[section]):
                        if isinstance(item, dict) and "equip_location" not in item:
                            item["equip_location"] = None
                            value["unavailable"][f"{section}.{i}.equip_location"] = "not_in_older_snapshot"
        return value

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.captured_at > int(time.time()) + 300:
            raise ValueError("快照时间超过本机时间五分钟")
        if any(q.observed_at > self.captured_at + 300 for q in self.auction_quotes or []):
            raise ValueError("报价时间不能晚于快照时间")
        if len(self.unavailable) > 20000 or len(self.capabilities) > 500:
            raise ValueError("诊断数据过多")
        # Every unknown value must have an explicit reason at that path or a parent path.
        def visit(value, path=""):
            if value is None:
                parts = path.split(".")
                if not any(".".join(parts[:i]) in self.unavailable for i in range(1, len(parts) + 1)):
                    raise ValueError(f"{path} 为 null，但缺少 reason")
            elif isinstance(value, dict):
                for key, child in value.items():
                    visit(child, f"{path}.{key}" if path else key)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    visit(child, f"{path}.{i}")
        value = self.model_dump(exclude={"unavailable", "capabilities"})
        # These fields describe a local save location, not missing game data.
        for key in ("storage_name", "storage_realm_id"):
            value["character"].pop(key, None)
        # Location-only optional fields are not unknown game data.
        for section in ("equipment", "bags"):
            for item in value.get(section) or []:
                for key in ("slot", "bag", "bag_slot"):
                    item.pop(key)
        visit(value)
        slots = [i.slot for i in self.equipment or [] if i.slot is not None]
        if len(set(slots)) != len(slots):
            raise ValueError("装备槽位重复")
        return self

    @property
    def stale(self) -> bool:
        return self.captured_at < time.time() - 86400


class Claim(Model):
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    provenance: Provenance
    evidence_ids: list[str]


class Action(Model):
    title: Annotated[str, Field(min_length=1, max_length=120)]
    reason: Claim


class Advice(Model):
    summary: Annotated[str, Field(min_length=1, max_length=3000)]
    claims: Annotated[list[Claim], Field(max_length=30)]
    actions: Annotated[list[Action], Field(min_length=3, max_length=3)]
    unknowns: Annotated[list[str], Field(max_length=30)]
