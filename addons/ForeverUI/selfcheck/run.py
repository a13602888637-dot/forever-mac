"""Local logic/parse checks only; no client access and no claim of in-game compatibility."""
from pathlib import Path
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
FILES = [s.strip().replace('\\', '/') for s in (ROOT / 'ForeverUI.toc').read_text().splitlines() if s.strip().endswith('.lua')]


def load():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute((ROOT / 'selfcheck/mock.lua').read_text())
    for name in FILES:
        lua.execute((ROOT / name).read_text(), name=name)
    lua.execute("MOCK.Fire('ADDON_LOADED','ForeverUI'); MOCK.Fire('PLAYER_LOGIN')")
    return lua


lua = load()
lua.execute("""
assert(ForeverUI.db.enabled == false, 'first install must not apply itself')
assert(PlayerFrame:GetParent() == UIParent, 'native untouched on first load')
assert(ForeverUI.ApplyProfile())
for _,id in ipairs(ForeverUI.order) do assert(ForeverUI.modules[id].active, id..': '..tostring(ForeverUI.modules[id].error)) end
assert(#ForeverUI.modules.units.buttons == 48)
assert(PlayerFrame:GetParent() == ForeverUI.hider)
assert(PlayerCastingBarFrame:GetParent() == UIParent)
assert(#ForeverUI.modules.bags.items == 2)
ForeverUI.modules.bags.query='丝绸'; ForeverUI.modules.bags:Filter()
assert(#ForeverUI.modules.bags.filtered == 1 and ForeverUI.modules.bags.filtered[1].id == 1001)
ForeverUI.modules.bags.query=''; ForeverUI.modules.bags.category='gear'; ForeverUI.modules.bags:Filter()
assert(#ForeverUI.modules.bags.filtered == 1 and ForeverUI.modules.bags.filtered[1].id == 1002)
MOCK.secretHealth=true; MOCK.Fire('UNIT_HEALTH','target'); MOCK.Fire('UNIT_POWER_UPDATE','player')
assert(MOCK.secretDisplay > 0, 'secret values should reach permitted display setters')
assert(ForeverUI.Number(MOCK.secret) == nil and ForeverUI.Text(MOCK.secret) == nil)
ForeverUI.SetEdit(true); assert(ForeverUI.editing)
MOCK.combat=true; MOCK.Fire('PLAYER_REGEN_DISABLED'); assert(not ForeverUI.editing)
local before=MOCK.mutations
ForeverUI.ApplyProfile(); ForeverUI.RestoreAll(); ForeverUI.ResetLayout(); ForeverUI.ToggleModule('units',false); ForeverUI.SetEdit(true)
assert(MOCK.mutations==before, 'combat configuration must not mutate layout/attributes')
assert(ForeverUI.db.enabled and ForeverUI.modules.units.active)
MOCK.combat=false; ForeverUI.RestoreAll()
for _,id in ipairs(ForeverUI.order) do assert(not ForeverUI.modules[id].active) end
assert(PlayerFrame:GetParent()==UIParent and PlayerCastingBarFrame:GetParent()==PlayerFrame)
assert(not ForeverUI.modules.bags.launcher:IsShown())
assert(ForeverUI.ApplyProfile())
for _,id in ipairs(ForeverUI.order) do assert(ForeverUI.modules[id].active,id) end
ForeverUI.ToggleModule('units',false); assert(PlayerFrame:GetParent()==UIParent)
assert(ForeverUI.modules.actionbars.active, 'independent module toggle')
ForeverUI.ShowConfig(); assert(ForeverUI.config:IsShown())
""")
layout = load()
layout.execute("""
assert(ForeverUI.ApplyProfile())
assert(MainActionBar:GetWidth()==452 and ActionButton1:GetWidth()==34)
assert(ActionButton12:GetPoint(1)=='TOPLEFT')
local _,parent,_,x,y=ActionButton12:GetPoint(1)
assert(parent==MainActionBar and x==418 and y==0)
assert(MultiBarBottomLeft:GetWidth()==MainActionBar:GetWidth())
assert(EssentialCooldownViewer:GetParent()==ForeverUI.hider and UtilityCooldownViewer:GetParent()==ForeverUI.hider)
assert(ExtraActionButton1:GetParent()==UIParent and ZoneAbilityFrame:GetParent()==UIParent)
ForeverUI.SetCooldownIcons(true)
assert(EssentialCooldownViewer:GetParent()==UIParent and UtilityCooldownViewer:GetParent()==UIParent)
ForeverUI.SetCooldownIcons(false)
MOCK.combat=true
local before=MOCK.mutations
ForeverUI.SetCooldownIcons(true); ForeverUI.ApplyCompactLayout()
MOCK.Fire('ACTIONBAR_PAGE_CHANGED'); MOCK.Fire('UI_SCALE_CHANGED')
assert(MOCK.mutations==before, 'layout and icon options cannot mutate protected frames in combat')
MOCK.combat=false
MOCK.Fire('PLAYER_REGEN_ENABLED')
ForeverUI.db.layout.mainbar={point='BOTTOM',x=120,y=80}
ForeverUI.ApplyCompactLayout()
assert(ForeverUI.db.layout.mainbar==nil)
ForeverUI.UndoCompactLayout()
assert(ForeverUI.db.layout.mainbar.x==120)
ForeverUI.RestoreAll()
assert(MainActionBar:GetWidth()==180 and ActionButton1:GetWidth()==180)
assert(EssentialCooldownViewer:GetParent()==UIParent and UtilityCooldownViewer:GetParent()==UIParent)
assert(MicroMenuContainer:GetScale()==1 and MinimapCluster:GetScale()==1)
""")
for failure in ('failSecure', 'failDriver'):
    failed = load()
    failed.execute(f"MOCK.{failure}=true; ForeverUI.ApplyProfile()")
    failed.execute("""
    assert(not ForeverUI.modules.units.active)
    assert(PlayerFrame:GetParent()==UIParent and TargetFrame:GetParent()==UIParent)
    assert(ForeverUI.modules.actionbars.active and ForeverUI.modules.bags.active)
    for _,root in ipairs(ForeverUI.modules.units.roots) do assert(not root:IsShown()) end
    ForeverUI.RestoreAll()
    """)
# Focused restoration and bag-capacity edge regressions.
for failure in ('count', 'point', 'throw'):
    edge = load()
    edge.execute("""
    probe=CreateFrame('Frame','RestoreProbe',UIParent)
    probe:SetPoint('TOPLEFT',UIParent,'TOPLEFT',10,-10)
    probe:SetPoint('BOTTOMRIGHT',UIParent,'BOTTOMRIGHT',-10,10)
    """)
    if failure == 'count':
        edge.execute("probe.GetNumPoints=function() return MOCK.secret end")
    elif failure == 'point':
        edge.execute("local old=probe.GetPoint; probe.GetPoint=function(self,i) if i==2 then return MOCK.secret end; return old(self,i) end")
    else:
        edge.execute("probe.GetPoint=function() error('unreadable points') end")
    edge.execute("""
    local before=MOCK.mutations
    local ok=pcall(ForeverUI.RememberPoints,'probe',probe)
    assert(not ok, 'unreadable native points must fail closed')
    assert(MOCK.mutations==before and #probe.points==2)
    assert(ForeverUI.native.probe[1].points==nil, 'partial point capture must not be committed')
    """)
restore = load()
restore.execute("""
assert(ForeverUI.ApplyProfile())
local original=MainActionBar.SetPoint
MainActionBar.SetPoint=function() error('blocked restore') end
ForeverUI.RestoreAll()
assert(#ForeverUI.native.actionbars==1, 'failed restore record must be retained')
assert(ForeverUI.native.actionbars[1].points[1][1]=='CENTER')
assert(ForeverUI.modules.actionbars.restorePending, 'partial restoration must be visible')
assert(MOCK.messages[#MOCK.messages]:find('恢复未完成',1,true))
ForeverUI.ShowConfig(); assert(ForeverUI.config.status:GetText():find('恢复未完成',1,true))
MainActionBar.SetPoint=original
ForeverUI.RestoreAll()
assert(#ForeverUI.native.actionbars==0 and not ForeverUI.modules.actionbars.restorePending)
assert(MainActionBar.points[1][1]=='CENTER')
""")
bags = load()
bags.execute("""
NUM_BAG_SLOTS=nil
assert(ForeverUI.ApplyProfile())
local module=ForeverUI.modules.bags
local old=C_Container.GetContainerNumSlots
local seen={}
C_Container.GetContainerNumSlots=function(bag) seen[#seen+1]=bag; return old(bag) end
module:Refresh()
assert(#seen==1 and seen[1]==0, 'unknown equipped count may only scan known backpack')
assert(module.partialScan and module.totalSlots==16)
assert(module.summary:GetText():find('部分读取',1,true), 'partial scan must be labelled')
""")
print(f'PASS · Lua 5.1 parsed {len(FILES)} files; compact action grids, cooldown icon toggle and native restoration, special abilities preserved, layout undo, first-install opt-in, 48 secure unit buttons, combat guards, secret display, bag search/categories; unreadable anchors fail closed, restore retry, unknown bag count partial scan.')
print('NOT VERIFIED · real client templates, secure execution, layout, taint, combat and visual UAT.')
