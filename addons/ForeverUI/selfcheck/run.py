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
MainActionBar:SetSize(620,48); MainActionBar:SetScale(.85)
MainActionBar:ClearAllPoints(); MainActionBar:SetPoint('BOTTOM',UIParent,'BOTTOM',17,91)
ActionButton1:SetSize(42,42)
ActionButton1.container:SetSize(48,48)
ActionButton1.normal:SetAlpha(.6)
local originalFont,originalSize,originalFlags=ActionButton1.HotKey:GetFont()
MOCK.LockBarWrites()
assert(ForeverUI.ApplyProfile())
assert(ForeverUI.modules.actionbars.active, ForeverUI.modules.actionbars.error)
assert(MainActionBar:GetWidth()==620 and MainActionBar:GetScale()==.85 and ActionButton1:GetWidth()==42)
local point,parent,relative,x,y=MainActionBar:GetPoint(1)
assert(point=='BOTTOM' and parent==UIParent and x==17 and y==91)
assert(ActionButton12:GetPoint(1)=='CENTER')
assert(ActionButton12:GetParent()==ActionButton12.container)
assert(ActionButton1.container:GetWidth()==48)
assert(ActionButton1.icon.coords[1]==.07 and ActionButton1.normal:GetAlpha()==0, 'skin actually applies')
local _,size=ActionButton1.HotKey:GetFont(); assert(size==10)
for _,info in pairs(ForeverUI.movers) do assert(info.owner~='actionbars', 'native bars have no FUI mover') end
for _,rec in ipairs(ForeverUI.native.actionbars) do
 assert(rec.frame:GetObjectType()=='Texture' or rec.frame:GetObjectType()=='FontString')
 assert(not rec.points and not rec.hasParent and not rec.size and not rec.scale)
end
assert(EssentialCooldownViewer:GetParent()==ForeverUI.hider and UtilityCooldownViewer:GetParent()==ForeverUI.hider)
assert(ExtraActionButton1:GetParent()==UIParent and ZoneAbilityFrame:GetParent()==UIParent)
ForeverUI.SetCooldownIcons(true)
assert(EssentialCooldownViewer:GetParent()==UIParent and UtilityCooldownViewer:GetParent()==UIParent)
ForeverUI.SetCooldownIcons(false)
MOCK.combat=true
local before=MOCK.mutations
ForeverUI.SetCooldownIcons(true); ForeverUI.ApplyCompactLayout()
MOCK.Fire('ACTIONBAR_PAGE_CHANGED'); MOCK.Fire('UI_SCALE_CHANGED')
MOCK.Fire('ADDON_LOADED','Blizzard_ActionBar')
local events=ForeverUI.modules.actionbars.events
events.scripts.OnEvent(events,'PLAYER_ENTERING_WORLD')
assert(MOCK.mutations==before, 'layout and icon options cannot mutate protected frames in combat')
MOCK.combat=false
MOCK.Fire('PLAYER_REGEN_ENABLED')
ForeverUI.db.layout.mainbar={point='BOTTOM',x=120,y=80}
ForeverUI.ApplyCompactLayout()
assert(ForeverUI.db.layout.mainbar==nil)
ForeverUI.UndoCompactLayout()
assert(ForeverUI.db.layout.mainbar.x==120)
ForeverUI.RestoreAll()
assert(MainActionBar:GetWidth()==620 and ActionButton1:GetWidth()==42 and ActionButton1.container:GetWidth()==48)
assert(ActionButton1.icon:GetTexCoord()==0 and ActionButton1.normal:GetAlpha()==.6)
local font,size,flags=ActionButton1.HotKey:GetFont()
assert(font==originalFont and size==originalSize and flags==originalFlags, 'original skin restored')
assert(EssentialCooldownViewer:GetParent()==UIParent and UtilityCooldownViewer:GetParent()==UIParent)
assert(MicroMenuContainer:GetScale()==1 and MinimapCluster:GetScale()==1)
assert(MOCK.barWriteAttempts==0, 'enable, events, compact/undo and restore never touch action frame properties')
""")
combat = load()
combat.execute("""
MainActionBar.visibility='Always'
MultiBarBottomLeft.visibility='OutOfCombat'
MultiBarBottomRight.visibility='InCombat'
MultiBarRight.visibility='Hidden'
MainActionBar.driver='[petbattle] hide; show'
MOCK.SetCombat(false)
MOCK.LockBarWrites()
assert(ForeverUI.ApplyProfile())
ForeverUI.SetCooldownIcons(true)
assert(MainActionBar:IsVisible() and ActionButton1:IsVisible())
assert(not MultiBarRight:IsVisible(), 'native hidden choice must stay hidden')
assert(not MultiBarBottomRight:IsVisible(), 'combat-only choice must stay hidden out of combat')
ForeverUI.SetEdit(true)
local before=MOCK.protectedMutations
MOCK.SetCombat(true)
assert(not ForeverUI.editing, 'only edit handles close at combat start')
assert(MainActionBar:IsVisible() and ActionButton1:IsVisible(), 'main bar and its native parent chain remain visible')
assert(not MultiBarBottomLeft:IsVisible() and MultiBarBottomRight:IsVisible())
assert(not MultiBarRight:IsVisible())
assert(ForeverUI.db.showCooldownIcons, 'combat must preserve cooldown viewer selection')
MOCK.Fire('ACTIONBAR_PAGE_CHANGED'); MOCK.Fire('UI_SCALE_CHANGED')
assert(MOCK.protectedMutations==before, 'combat entry/events cannot write secure bar geometry or show/hide')
local point,parent,relative,x,y=ActionButton1:GetPoint(1)
assert(point=='CENTER' and parent==UIParent, 'original anchors preserved, including client container indirection')
assert(ForeverUI.modules.actionbars.lastCombatStatus.frames[1].visible)
MOCK.SetCombat(false)
assert(MainActionBar:IsVisible() and ActionButton1:IsVisible())
assert(MultiBarBottomLeft:IsVisible() and not MultiBarBottomRight:IsVisible())
assert(MainActionBar.driver=='[petbattle] hide; show', 'never replace the native secure visibility driver')
assert(MainActionBar.visibility=='Always' and MultiBarBottomLeft.visibility=='OutOfCombat')
ForeverUI.ToggleModule('actionbars',false)
local disabledBefore=MOCK.protectedMutations
MOCK.SetCombat(true); MOCK.SetCombat(false)
assert(MOCK.protectedMutations==disabledBefore, 'disabled module must not reapply itself after combat')
assert(ActionButton1:GetParent()==ActionButton1.container)
assert(ActionButton1.container:GetWidth()==180, 'native container geometry never changes')
MainActionBar.nativeExternallyHidden=true
MOCK.SetCombat(true); MOCK.SetCombat(false)
assert(not MainActionBar:IsVisible(), 'native external hiding is never overridden')
ForeverUI.RestoreAll()
assert(not ForeverUI.db.enabled)
MOCK.SetCombat(true); MOCK.SetCombat(false)
assert(not ForeverUI.modules.actionbars.active, 'off preference survives combat')
assert(MOCK.barWriteAttempts==0)
""")
art = load()
art.execute("""
-- A same-named Frame must not be mistaken for a decorative Texture.
MainActionBar.Background=CreateFrame('Frame',nil,MainActionBar)
MainActionBar.Background:SetAlpha(.45)
ActionButton1.SlotArt=ActionButton1.container
MainActionBar.LeftEndCap=MainActionBar:CreateTexture(nil,'ARTWORK')
MainActionBar.LeftEndCap:SetAlpha(.7)
MainActionBar.RightEndCap=MainActionBar:CreateTexture(nil,'ARTWORK')
MainActionBar.RightEndCap.GetObjectType=function() return MOCK.secret end
MOCK.LockBarWrites()
assert(ForeverUI.ApplyProfile() and ForeverUI.modules.actionbars.active)
assert(MainActionBar.Background:GetAlpha()==.45 and ActionButton1.container:GetAlpha()==1)
assert(MainActionBar.LeftEndCap:GetAlpha()==0 and MainActionBar.RightEndCap:GetAlpha()==1)
MOCK.combat=true
local before=MOCK.mutations
MOCK.Fire('ACTIONBAR_PAGE_CHANGED'); MOCK.Fire('ADDON_LOADED','LateBar')
assert(MOCK.mutations==before and ForeverUI.modules.actionbars.skinPending)
MOCK.combat=false
ForeverUI.ToggleModule('actionbars',false)
before=MOCK.mutations
MOCK.Fire('PLAYER_REGEN_ENABLED')
local events=ForeverUI.modules.actionbars.events
events.scripts.OnEvent(events,'PLAYER_ENTERING_WORLD')
assert(MOCK.mutations==before and not ForeverUI.modules.actionbars.skinPending)
assert(MainActionBar.LeftEndCap:GetAlpha()==.7 and MOCK.barWriteAttempts==0)
""")
diagnostics = load()
diagnostics.execute("""
assert(ForeverUI.ApplyProfile())
ActionButton1.container:Hide()
MainActionBar:SetAlpha(0)
MOCK.combat=true
local before=MOCK.mutations
SlashCmdList.FOREVERUI('status')
local status=ForeverUI.modules.actionbars.lastStatus
assert(status.combat and status.frames[3].shown and not status.frames[3].visible)
assert(status.frames[3].effectiveAlpha==0, 'diagnostics reveal inherited alpha without resetting it')
assert(status.frames[3].parents[1].shown==false, 'diagnostics identify the hidden native container')
assert(MOCK.mutations==before, 'status is read-only even in combat')
MainActionBar.GetEffectiveAlpha=function() return MOCK.secret end
MainActionBar.GetWidth=function() return MOCK.secret end
SlashCmdList.FOREVERUI('status')
assert(ForeverUI.modules.actionbars.lastStatus.frames[1].effectiveAlpha==nil)
assert(ForeverUI.modules.actionbars.lastStatus.frames[1].width==nil)
assert(MOCK.mutations==before, 'restricted diagnostic values are never coerced or mutated')
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
local original=ActionButton1.icon.SetTexCoord
ActionButton1.icon.SetTexCoord=function() error('blocked texture restore') end
ForeverUI.RestoreAll()
assert(#ForeverUI.native.actionbars==1, 'failed restore record must be retained')
assert(ForeverUI.native.actionbars[1].frame==ActionButton1.icon)
assert(ForeverUI.native.actionbars[1].coords[1]==0)
assert(ForeverUI.modules.actionbars.restorePending, 'partial restoration must be visible')
assert(MOCK.messages[#MOCK.messages]:find('恢复未完成',1,true))
ForeverUI.ShowConfig(); assert(ForeverUI.config.status:GetText():find('恢复未完成',1,true))
ActionButton1.icon.SetTexCoord=original
ForeverUI.RestoreAll()
assert(#ForeverUI.native.actionbars==0 and not ForeverUI.modules.actionbars.restorePending)
assert(ActionButton1.icon:GetTexCoord()==0)
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
print(f'PASS · Lua 5.1 parsed {len(FILES)} files; skin-only textures/fonts applied and restored, zero native action-frame writes, combat entry/exit and native visibility/drivers, read-only diagnostics, deferred refresh cancellation, cooldown toggle, layout undo, first-install opt-in, 48 secure unit buttons, secret display, bag search/categories, restore retry.')
print('NOT VERIFIED · real client templates, secure execution, layout, taint, combat and visual UAT.')
