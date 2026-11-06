-- Minimal Lua 5.1 execution harness. It verifies our logic, not the game client's secure engine.
unpack = unpack or table.unpack
local frames = {}
MOCK = { combat = false, mutations = 0, secretDisplay = 0, secretHealth = false, failSecure = false, failDriver = false, messages = {} }
MOCK.secret = setmetatable({}, {
    __tostring = function() error("secret tostring") end,
    __add = function() error("secret arithmetic") end,
    __sub = function() error("secret arithmetic") end,
    __mul = function() error("secret arithmetic") end,
    __div = function() error("secret arithmetic") end,
    __lt = function() error("secret comparison") end,
    __le = function() error("secret comparison") end,
    __concat = function() error("secret concat") end,
})
function issecretvalue(value) return rawequal(value, MOCK.secret) end
function canaccessvalue(value) return not issecretvalue(value) end
function issecrettable(value) return issecretvalue(value) end
function canaccesstable(value) return not issecretvalue(value) end
function InCombatLockdown() return MOCK.combat end
local methods = {}
local function mutation(self)
    if self.protected and MOCK.combat then error("protected mutation in combat") end
    MOCK.mutations = MOCK.mutations + 1
end
function methods:SetSize(w,h) self.width,self.height=w,h end
function methods:SetWidth(w) self.width=w end
function methods:SetHeight(h) self.height=h end
function methods:GetWidth() return self.width or 180 end
function methods:GetHeight() return self.height or 40 end
function methods:SetPoint(...) mutation(self); self.points[#self.points+1]={n=select('#',...),...} end
function methods:ClearAllPoints() mutation(self); self.points={} end
function methods:GetPoint(i) local p=self.points[i]; if p then return unpack(p,1,p.n) end end
function methods:GetNumPoints() return #self.points end
function methods:SetAllPoints(p) self.allpoints=p end
function methods:GetCenter() return 400,300 end
function methods:GetParent() return self.parent end
function methods:SetParent(p) mutation(self); self.parent=p end
function methods:GetName() return self.name end
function methods:SetFrameStrata(s) self.strata=s end
function methods:GetFrameStrata() return self.strata or 'MEDIUM' end
function methods:GetFrameLevel() return self.level or 3 end
function methods:SetFrameLevel(n) self.level=n end
function methods:EnableMouse(v) self.mouse=v end
function methods:SetMovable(v) self.movable=v end
function methods:SetUserPlaced(v) self.userPlaced=v end
function methods:IsUserPlaced() return self.userPlaced or false end
function methods:RegisterForDrag(...) end
function methods:RegisterForClicks(...) end
function methods:StartMoving() self.moving=true end
function methods:StopMovingOrSizing() self.moving=false end
function methods:SetScript(e,f) self.scripts[e]=f end
function methods:GetScript(e) return self.scripts[e] end
function methods:RegisterEvent(e) self.events[e]=true end
function methods:UnregisterAllEvents() self.events={} end
function methods:SetAttribute(k,v) mutation(self); self.attrs[k]=v end
function methods:GetAttribute(k) return self.attrs[k] end
function methods:Show() self.shown=true end
function methods:Hide() self.shown=false end
function methods:IsShown() return self.shown~=false end
function methods:SetAlpha(a) self.alpha=a end
function methods:GetAlpha() return self.alpha or 1 end
function methods:SetColorTexture(...) self.color={...} end
function methods:SetVertexColor(...) self.color={...} end
function methods:GetVertexColor() return unpack(self.color or {1,1,1,1}) end
function methods:SetTexture(texture) assert(not issecretvalue(texture)); self.texture=texture end
function methods:SetTexCoord(...) self.coords={...} end
function methods:GetTexCoord() return unpack(self.coords or {0,0,0,1,1,0,1,1}) end
function methods:SetStatusBarTexture(texture) self.texture=texture end
function methods:SetStatusBarColor(...) self.color={...} end
function methods:SetMinMaxValues(a,b) if issecretvalue(a) or issecretvalue(b) then MOCK.secretDisplay=MOCK.secretDisplay+1 else self.minimum,self.maximum=a,b end end
function methods:SetValue(v) if issecretvalue(v) then MOCK.secretDisplay=MOCK.secretDisplay+1 else self.value=v end end
function methods:SetText(v) if issecretvalue(v) then MOCK.secretDisplay=MOCK.secretDisplay+1; self.text='restricted' else self.text=v end end
function methods:GetText() return self.text or '' end
function methods:SetFormattedText(format,...)
    for i=1,select('#',...) do if issecretvalue(select(i,...)) then MOCK.secretDisplay=MOCK.secretDisplay+1; self.text='restricted'; return end end
    self.text=string.format(format,...)
end
function methods:SetTextColor(...) self.textColor={...} end
function methods:GetTextColor() return unpack(self.textColor or {1,1,1,1}) end
function methods:SetJustifyH(s) end
function methods:SetFont(path,size,flags) self.font={path,size,flags} end
function methods:GetFont() return unpack(self.font or {'Fonts\\ARKai_T.ttf',12,''}) end
function methods:SetShadowColor(...) end
function methods:SetShadowOffset(...) end
function methods:SetAutoFocus(v) end
function methods:SetMaxLetters(v) end
function methods:ClearFocus() end
function methods:SetChecked(v) self.checked=v end
function methods:GetChecked() return self.checked end
function methods:GetNormalTexture() return self.normal end
function methods:SetOwner(owner,anchor) end
function methods:SetUnit(unit) self.unit=unit end
function methods:SetBagItem(bag,slot) self.item=bag..':'..slot end
function methods:AddLine(text,...) assert(not issecretvalue(text)) end
function methods:AddMessage(text) MOCK.messages[#MOCK.messages+1]=text end
local function make(kind,name,parent,template)
    if template=='SecureUnitButtonTemplate' and MOCK.failSecure then error('unsupported secure template') end
    if name and _G[name] then error('duplicate frame name '..name) end
    local f=setmetatable({kind=kind,name=name,parent=parent,points={},scripts={},events={},attrs={},shown=true,protected=template=='SecureUnitButtonTemplate'}, {__index=function(_,k) local m=methods[k]; if not m then return nil end; return m end})
    frames[#frames+1]=f
    if name then _G[name]=f end
    return f
end
function methods:CreateTexture(name,layer) return make('Texture',name,self) end
function methods:CreateFontString(name,layer) return make('FontString',name,self) end
CreateFrame=make
UIParent=make('Frame','UIParent',nil); UIParent:SetSize(1920,1080)
GameTooltip=make('Tooltip','GameTooltip',UIParent)
DEFAULT_CHAT_FRAME=make('Chat','DEFAULT_CHAT_FRAME',UIParent)
STANDARD_TEXT_FONT='Fonts\\ARKai_T.ttf'
NUM_BAG_SLOTS=4; NUM_CHAT_WINDOWS=2; UISpecialFrames={}; SlashCmdList={}
function RegisterUnitWatch(frame) frame.watch=true end
function UnregisterUnitWatch(frame) frame.watch=false end
function RegisterStateDriver(frame,state,condition) if MOCK.failDriver then error('state driver failure') end; frame.driver=condition end
function UnregisterStateDriver(frame,state) frame.driver=nil end
function GetBuildInfo() return '1.60.1','70450','Oct 15 2026',16001 end
function GetMinimapZoneText() return '幽暗城' end
function GetGameTime() return 21,15 end
function UnitName(unit) if MOCK.secretHealth and unit=='target' then return MOCK.secret end; return unit end
function UnitLevel(unit) return 32 end
function UnitHealth(unit) return MOCK.secretHealth and MOCK.secret or 100 end
function UnitHealthMax(unit) return MOCK.secretHealth and MOCK.secret or 500 end
function UnitPower(unit) return MOCK.secretHealth and MOCK.secret or 150 end
function UnitPowerMax(unit) return MOCK.secretHealth and MOCK.secret or 300 end
function UnitIsDeadOrGhost(unit) return false end
function UnitIsConnected(unit) return true end
C_UnitAuras={GetAuraDataByIndex=function() return nil end}
C_Container={
 GetContainerNumSlots=function(bag) return bag==0 and 16 or 0 end,
 GetContainerItemInfo=function(bag,slot)
   if bag==0 and slot==1 then return {itemID=1001,iconFileID=123,stackCount=3,quality=2,hyperlink='item:1001'} end
   if bag==0 and slot==2 then return {itemID=1002,iconFileID=124,stackCount=1,quality=2,hyperlink='item:1002'} end
 end,
 GetContainerItemID=function(bag,slot) return 1000+slot end
}
C_Item={
 GetItemInfo=function(id) return id==1001 and '丝绸' or '奥术兜帽','item:'..id,2,20,20,id==1001 and '材料' or '护甲','',20,id==1001 and '' or 'INVTYPE_HEAD',123,0,id==1001 and 7 or 4,0,0,0,nil,id==1001 end,
 GetItemInfoInstant=function(id) return id,'护甲','','INVTYPE_HEAD',123,4,0 end,
}
function GetItemQualityColor(q) return .3,.7,.3 end
function ToggleAllBags() MOCK.nativeBagsOpened=true end
local function native(name,kind)
 local f=make(kind or 'Frame',name,UIParent); f:SetPoint('CENTER',UIParent,'CENTER',0,0); return f
end
for _,name in ipairs({'PlayerFrame','TargetFrame','TargetFrameToT','PetFrame','PartyFrame','CompactPartyFrame','CompactRaidFrameContainer','MainActionBar','MultiBarBottomLeft','MultiBarBottomRight','MultiBarLeft','MultiBarRight','PetActionBar','StanceBar','Minimap','MinimapCluster','ObjectiveTrackerFrame','ChatFrame1','ChatFrame2'}) do native(name) end
PlayerCastingBarFrame=native('PlayerCastingBarFrame'); PlayerCastingBarFrame:SetParent(PlayerFrame)
for i=1,12 do
 local b=native('ActionButton'..i,'Button'); b.icon=b:CreateTexture(nil,'ARTWORK'); b.normal=b:CreateTexture(nil,'ARTWORK'); b.HotKey=b:CreateFontString(nil,'OVERLAY')
end
function MOCK.Fire(event,...)
 for _,frame in ipairs(frames) do if frame.events[event] and frame.scripts.OnEvent then frame.scripts.OnEvent(frame,event,...) end end
end
