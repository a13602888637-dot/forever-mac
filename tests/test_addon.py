import json
import time

from lupa.lua51 import LuaRuntime

from backend.models import Snapshot
from backend.savedvariables import parse_savedvariables
from conftest import ROOT


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        _G = _G or _ENV
        SlashCmdList = {}
        UIParent = {}
        FRAMES, TIMERS = {}, {}
        function CreateFrame()
            local frame = {RegisterEvent=function()end, SetScript=function(self,key,fn)self[key]=fn end}
            table.insert(FRAMES,frame)
            return frame
        end
        C_Timer={After=function(_,callback)table.insert(TIMERS,callback)end}
        function time() return NOW end
        function GetBuildInfo() return "1.60.1", "70450", "", 16001 end
        function UnitName() return "亡灵法师" end
        function GetRealmName() return "测试服务器" end
        function UnitClass() return "法师", "MAGE", 8 end
        function UnitRace() return "亡灵", "Scourge", 5 end
        function UnitLevel() return 32 end
        function GetInventoryItemID() return nil end
        function InCombatLockdown() return false end
        SECRET = {}
        function issecretvalue(v) return v == SECRET end
    ''')
    lua.globals().NOW = int(time.time())
    for file in ("Core.lua", "Auction.lua", "Collector.lua", "UI.lua", "Export.lua", "Auto.lua"):
        lua.execute((ROOT / "addons/ForeverAI" / file).read_text(), name=file)
    return lua


def test_real_lua51_export_round_trip():
    lua = runtime()
    assert lua.globals().ForeverAI.Export() is True
    data = lua.globals().ForeverAICharDB.snapshot_json
    snapshot = Snapshot.model_validate_json(data)
    assert snapshot.character.class_token == "MAGE"
    assert len(snapshot.equipment) == 19
    assert all(item.status == "empty" for item in snapshot.equipment)
    assert snapshot.professions is None
    assert "unsupported" in snapshot.unavailable["professions"] or "unavailable" in snapshot.unavailable["professions"]
    text = "ForeverAICharDB={schema_version=1,snapshot_json=" + json.dumps(data, ensure_ascii=False) + "}"
    assert parse_savedvariables(text).character.name == "亡灵法师"


def test_secret_identity_does_not_overwrite_existing_snapshot():
    lua = runtime()
    lua.execute('ForeverAICharDB={schema_version=1,snapshot_json="previous"}; function UnitName() return SECRET end')
    assert lua.globals().ForeverAI.Export() is False
    assert lua.globals().ForeverAICharDB.snapshot_json == "previous"


def test_combat_and_future_schema_do_not_overwrite():
    lua = runtime()
    lua.execute('ForeverAICharDB={schema_version=1,snapshot_json="previous"}; function InCombatLockdown() return true end')
    assert lua.globals().ForeverAI.Export() is False
    lua.execute('function InCombatLockdown() return false end; ForeverAICharDB.schema_version=2')
    assert lua.globals().ForeverAI.Export() is False
    assert lua.globals().ForeverAICharDB.snapshot_json == "previous"


def test_item_stats_and_nested_secret_are_handled():
    lua = runtime()
    lua.execute('''
      function GetInventoryItemID(_, slot) if slot == 1 then return 12345 end end
      function GetInventoryItemLink() return "item:12345" end
      C_Item={
        GetItemInfo=function()return "测试帽子", "item:12345", 2, 20 end,
        GetItemStats=function()return {ITEM_MOD_INTELLECT_SHORT=7, HIDDEN=SECRET} end
      }
    ''')
    assert lua.globals().ForeverAI.Export() is True
    snapshot = Snapshot.model_validate_json(lua.globals().ForeverAICharDB.snapshot_json)
    assert snapshot.equipment[0].stats["HIDDEN"] is None
    assert snapshot.equipment[0].stats["ITEM_MOD_INTELLECT_SHORT"] == 7
    assert snapshot.unavailable["equipment.0.stats.HIDDEN"] == "secret_or_inaccessible"


def test_bags_and_quests_use_actual_shapes():
    lua = runtime()
    lua.execute('''
      NUM_BAG_SLOTS=0
      C_Container={GetContainerNumSlots=function()return 1 end,
        GetContainerItemInfo=function()return {itemID=12345,stackCount=3,hyperlink="item:12345"}end}
      C_Item={GetItemInfo=function()return "帽子", "item:12345", 2, 20 end,
        GetItemStats=function()return {ITEM_MOD_INTELLECT_SHORT=3}end}
      C_QuestLog={GetNumQuestLogEntries=function()return 1,1 end,
        GetInfo=function()return {questID=100,title="测试任务",level=30,isHeader=false}end,
        GetQuestObjectives=function()return {{text="测试目标"}}end,
        IsComplete=function()return false end}
    ''')
    assert lua.globals().ForeverAI.Export() is True
    snapshot = Snapshot.model_validate_json(lua.globals().ForeverAICharDB.snapshot_json)
    assert snapshot.bags[0].count == 3
    assert snapshot.quests[0].objectives == ["测试目标"]
    assert snapshot.quests[0].is_complete is False


def test_automatic_events_debounce_and_defer_in_combat():
    lua = runtime()
    lua.execute('''
      auto=FRAMES[#FRAMES]
      auto.OnEvent(auto,"BAG_UPDATE_DELAYED")
      auto.OnEvent(auto,"PLAYER_EQUIPMENT_CHANGED")
      assert(#TIMERS==1)
      function InCombatLockdown()return true end
      TIMERS[1]()
      assert(ForeverAICharDB==nil)
      function InCombatLockdown()return false end
      auto.OnEvent(auto,"PLAYER_REGEN_ENABLED")
      assert(#TIMERS==2)
      TIMERS[2]()
    ''')
    snapshot = Snapshot.model_validate_json(lua.globals().ForeverAICharDB.snapshot_json)
    assert snapshot.character.level == 32
    assert snapshot.auction_quotes is None


def test_passive_auction_getters_only_and_no_owner_data():
    lua = runtime()
    lua.execute('''
      C_AuctionHouse={
        SendSearchQuery=function()error("Must never query")end,
        GetNumCommoditySearchResults=function()return 2 end,
        GetCommoditySearchResultInfo=function(_,i)return {unitPrice=i==1 and SECRET or 90,quantity=5,owners={"PRIVATE_SELLER"}}end,
        GetNumItemSearchResults=function()return 1 end,
        GetItemSearchResultInfo=function()return {buyoutAmount=100,quantity=3,owners={"PRIVATE_SELLER"}}end
      }
      ForeverAI.ObserveCommodity(100)
      ForeverAI.ObserveItems({itemID=200})
      ForeverAI.Export(true)
    ''')
    raw = lua.globals().ForeverAICharDB.snapshot_json
    assert "PRIVATE_SELLER" not in raw
    snapshot = Snapshot.model_validate_json(raw)
    quotes = {q.item_id: q for q in snapshot.auction_quotes}
    assert quotes[100].copper == 90
    assert quotes[200].copper == 34
    assert quotes[200].basis == "rounded_listing_unit_price"
