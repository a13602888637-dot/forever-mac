local F = ForeverUI
local M = { skin_only = true }
local prefixes = { "ActionButton", "MultiBarBottomLeftButton", "MultiBarBottomRightButton", "MultiBarRightButton", "MultiBarLeftButton", "MultiBar5Button", "MultiBar6Button", "MultiBar7Button", "PetActionButton", "StanceButton" }
local function first(...)
    for i = 1, select("#", ...) do local frame = _G[select(i, ...)]; if frame then return frame end end
end
local function buttons(prefix, maximum)
    local result = {}
    for i = 1, maximum or 12 do if _G[prefix .. i] then result[#result + 1] = _G[prefix .. i] end end
    return result
end
local function isRegion(region, kind)
    if not F.Public(region) or not region or type(region.GetObjectType) ~= "function" then return false end
    local ok, objectType = pcall(region.GetObjectType, region)
    return ok and F.Public(objectType) and objectType == kind
end
local function hideArt(region)
    -- Names such as Background/SlotArt may also resolve to a Frame on another
    -- client. Never alpha a frame: that would also fade its actionable children.
    if isRegion(region, "Texture") then F.Alpha(M.id, region, 0) end
end
local function styleText(text, size, color)
    if isRegion(text, "FontString") then F.StyleText(M.id, text, size, color) end
end
function M:SkinButton(button)
    if not button then return end
    local name = button:GetName()
    local icon = button.icon or button.Icon or (name and _G[name .. "Icon"])
    if isRegion(icon, "Texture") then F.Crop(self.id, icon) end
    local normal = button.GetNormalTexture and button:GetNormalTexture()
    hideArt(normal)
    for _, suffix in ipairs({ "NormalTexture", "FloatingBG", "SlotBackground", "BorderArt", "SlotArt" }) do
        hideArt(button[suffix] or (name and _G[name .. suffix]))
    end
    styleText(button.HotKey or (name and _G[name .. "HotKey"]), 10, F.colors.bone)
    styleText(button.Count or (name and _G[name .. "Count"]), 10, F.colors.bone)
    styleText(button.Name or (name and _G[name .. "Name"]), 9, F.colors.muted)
    -- Every native frame property is Blizzard-owned, including geometry,
    -- visibility, alpha, paging, bindings, cooldowns, and button containers.
end
function M:RefreshSkin()
    if F.InCombat() then self.skinPending = true; return end
    self.skinPending = false
    for _, prefix in ipairs(prefixes) do
        for _, button in ipairs(buttons(prefix)) do self:SkinButton(button) end
    end
    for _, name in ipairs({ "MainMenuBarLeftEndCap", "MainMenuBarRightEndCap", "MainMenuBarTexture0", "MainMenuBarTexture1", "MainMenuBarTexture2", "MainMenuBarTexture3", "MainMenuBarArtFrameBackground" }) do
        hideArt(_G[name])
    end
    local main = first("MainActionBar", "MainMenuBar")
    for _, frame in ipairs({ _G.MainMenuBarArtFrame or false, main or false }) do
        if frame then
            for _, field in ipairs({ "LeftEndCap", "RightEndCap", "Background", "Bg", "BarArt", "BorderArt" }) do hideArt(frame[field]) end
            if frame.EndCaps then hideArt(frame.EndCaps.LeftEndCap); hideArt(frame.EndCaps.RightEndCap) end
        end
    end
end
local function readFrame(frame, method, ...)
    if not frame or type(frame[method]) ~= "function" then return nil end
    local ok, value = pcall(frame[method], frame, ...)
    if ok and F.Public(value) and (type(value) == "boolean" or type(value) == "string" or F.Number(value)) then return value end
end
local function frameState(name, frame)
    if not frame then return { name = name, missing = true } end
    local state = { name = name, shown = readFrame(frame, "IsShownBase") }
    if state.shown == nil then state.shown = readFrame(frame, "IsShown") end
    state.visible = readFrame(frame, "IsVisible")
    state.alpha = readFrame(frame, "GetAlpha"); state.effectiveAlpha = readFrame(frame, "GetEffectiveAlpha")
    state.visibility = F.Text(frame.visibility, "未设置")
    state.secureVisibility = readFrame(frame, "GetAttribute", "state-visibility")
    state.left = readFrame(frame, "GetLeft"); state.bottom = readFrame(frame, "GetBottom")
    state.width = readFrame(frame, "GetWidth"); state.height = readFrame(frame, "GetHeight")
    state.parents = {}
    local parent = frame
    for _ = 1, 5 do
        local ok, value = pcall(parent.GetParent, parent)
        if not ok or not F.Public(value) or not value then break end
        parent = value
        state.parents[#state.parents + 1] = { name = readFrame(parent, "GetName") or "匿名框体",
            shown = readFrame(parent, "IsShown"), alpha = readFrame(parent, "GetAlpha") }
    end
    return state
end
function M:Status()
    local result = { combat = F.InCombat(), enabled = F.db and F.db.enabled == true,
        active = self.active == true, editing = F.editing == true, version = F.version, skin_only = self.skin_only, frames = {} }
    for _, name in ipairs({ "MainActionBar", "MainMenuBar", "ActionButton1", "MultiBarBottomLeft", "MultiBarBottomRight" }) do
        result.frames[#result.frames + 1] = frameState(name, _G[name])
    end
    return result
end
function M:PrintStatus()
    local status = self:Status()
    local function display(value)
        if value == true then return "是" elseif value == false then return "否" end
        return F.Text(value, "未知")
    end
    F.Message("动作条诊断 · v" .. display(status.version) .. " · 仅换肤/原生布局=" .. display(status.skin_only) .. " · 战斗=" .. display(status.combat) .. " · 主题=" .. display(status.enabled) .. " · 模块=" .. display(status.active) .. " · 编辑=" .. display(status.editing))
    for _, state in ipairs(status.frames) do
        if not state.missing then
            F.Message(state.name .. " · 显示=" .. display(state.shown) .. " · 实际可见=" .. display(state.visible) ..
                " · 有效透明度=" .. display(state.effectiveAlpha) .. " · 原生规则=" .. display(state.visibility) ..
                " · 安全显隐=" .. display(state.secureVisibility) .. " · 左/下=" .. display(state.left) .. "/" .. display(state.bottom))
            local parents = {}
            for _, parent in ipairs(state.parents) do
                parents[#parents + 1] = parent.name .. "(显示=" .. display(parent.shown) .. ",透明度=" .. display(parent.alpha) .. ")"
            end
            if #parents > 0 then F.Message("父层：" .. table.concat(parents, " → ")) end
        end
    end
    -- Diagnostic data stays in this UI session; no game settings or saved data change.
    self.lastStatus = status
    return status
end
function M:RefreshCooldownIcons()
    if F.InCombat() then self.cooldownsPending = true; return end
    self.cooldownsPending = false
    if F.db.showCooldownIcons then
        assert(F.RestoreNative("cooldownicons"), "悬浮冷却图标恢复未完成，请 /reload 后重试")
    else
        -- These are display-only cooldown viewers. Never hide quest-specific
        -- ExtraActionButton1, zone abilities, or any castable action button.
        for _, name in ipairs({ "EssentialCooldownViewer", "UtilityCooldownViewer" }) do
            F.HideNative("cooldownicons", _G[name])
        end
    end
end
local function refresh(callback)
    local ok, err = pcall(callback, M)
    if not ok then
        M.error = F.Text(err, "样式刷新未完成")
        F.Message("动作条样式刷新未完成，请查看 /fui；原生布局仍由游戏管理。")
    end
end
function M:Enable()
    assert(not F.InCombat(), "战斗中不能切换动作条样式")
    assert(first("MainActionBar", "MainMenuBar"), "未找到原生动作条，保留原样")
    assert(#buttons("ActionButton") == 12, "原生主动作按钮不完整，保留原样")
    self:RefreshSkin()
    self:RefreshCooldownIcons()
    if not self.events then
        self.events = CreateFrame("Frame")
        self.events:SetScript("OnEvent", function(_, event)
            if not M.active then return end
            if event == "PLAYER_REGEN_DISABLED" then M.lastCombatStatus = M:Status(); return end
            if event == "PLAYER_REGEN_ENABLED" then
                -- Only finish deferred texture/font work. Never re-enable or
                -- restore a bar layout when the native combat lifecycle runs.
                if M.skinPending then refresh(M.RefreshSkin) end
                if M.cooldownsPending then refresh(M.RefreshCooldownIcons) end
                return
            end
            if F.InCombat() then
                M.skinPending = true
                if event ~= "ACTIONBAR_PAGE_CHANGED" then M.cooldownsPending = true end
                return
            end
            refresh(M.RefreshSkin)
            if event ~= "ACTIONBAR_PAGE_CHANGED" then refresh(M.RefreshCooldownIcons) end
        end)
    end
    self.events:RegisterEvent("PLAYER_REGEN_DISABLED"); self.events:RegisterEvent("PLAYER_REGEN_ENABLED")
    self.events:RegisterEvent("ADDON_LOADED"); self.events:RegisterEvent("PLAYER_ENTERING_WORLD")
    self.events:RegisterEvent("ACTIONBAR_PAGE_CHANGED")
end
function M:Disable()
    if self.events then self.events:UnregisterAllEvents() end
    self.skinPending, self.cooldownsPending = false, false
    -- Core restores only recorded textures/fonts for this owner. No native
    -- points/parents/sizes were recorded, so no Edit Mode wrappers are called.
    assert(F.RestoreNative("cooldownicons"), "悬浮冷却图标恢复未完成")
end
F.RegisterModule("actionbars", "动作条", "只调整图标、装饰和文字；位置与显隐由原生编辑模式管理。可单独关闭悬浮技能冷却图标。", M)
