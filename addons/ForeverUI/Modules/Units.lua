local F = ForeverUI
local M = { buttons = {}, roots = {}, watchers = {}, drivers = {} }
local unpack = unpack
local function raw(name, unit)
    local fn = F.Resolve(name)
    if not fn then return nil, false end
    local ok, value = pcall(fn, unit)
    return value, ok
end
-- The 1.60.1.70450 API reference marks these display setters AllowedWhenTainted:
-- StatusBar:SetValue, StatusBar:SetMinMaxValues, FontString:SetText / SetFormattedText.
-- Restricted values go directly to those setters and nowhere else.
local function displayBar(bar, text, currentAPI, maxAPI, unit)
    local value, ok = raw(currentAPI, unit)
    local maximum, maxOK = raw(maxAPI, unit)
    if not ok or not maxOK then bar:SetMinMaxValues(0, 1); bar:SetValue(0); text:SetText("未知"); return end
    local private = not F.Public(value) or not F.Public(maximum)
    if private then
        local a = pcall(bar.SetMinMaxValues, bar, 0, maximum)
        local b = pcall(bar.SetValue, bar, value)
        local c = pcall(text.SetFormattedText, text, "%s / %s", value, maximum)
        if not a or not b or not c then
            bar:SetMinMaxValues(0, 1); bar:SetValue(0); text:SetText("数值受限")
        end
        return
    end
    value, maximum = F.Number(value), F.Number(maximum)
    if not value or not maximum then bar:SetMinMaxValues(0, 1); bar:SetValue(0); text:SetText("未知"); return end
    bar:SetMinMaxValues(0, math.max(1, maximum)); bar:SetValue(value)
    text:SetText(tostring(value) .. " / " .. tostring(maximum))
end
local function makeBar(parent, height, color)
    local bar = CreateFrame("StatusBar", nil, parent)
    bar:SetHeight(height); bar:SetStatusBarTexture("Interface\\Buttons\\WHITE8X8")
    bar:SetStatusBarColor(unpack(color)); bar:SetMinMaxValues(0, 1); bar:SetValue(0)
    local bg = bar:CreateTexture(nil, "BACKGROUND"); bg:SetAllPoints(); bg:SetColorTexture(0.10, 0.08, 0.13, 1)
    return bar
end
function M:Update(button)
    local unit = button.unit
    local name, nameOK = raw("UnitName", unit)
    if nameOK and not F.Public(name) then pcall(button.name.SetText, button.name, name)
    else button.name:SetText(F.Text(name, button.fallback)) end
    local level = F.Number(F.Read("UnitLevel", unit))
    button.level:SetText(level and (level > 0 and tostring(level) or "??") or "")
    displayBar(button.health, button.healthText, "UnitHealth", "UnitHealthMax", unit)
    displayBar(button.power, button.powerText, "UnitPower", "UnitPowerMax", unit)
    local dead = F.Read("UnitIsDeadOrGhost", unit)
    local connected = F.Read("UnitIsConnected", unit)
    if dead == true then button.state:SetText("已死亡")
    elseif connected == false then button.state:SetText("离线") else button.state:SetText("") end
end
function M:UpdateAuras(button)
    if not button.auras then return end
    local fn = F.Resolve("C_UnitAuras.GetAuraDataByIndex")
    for i, icon in ipairs(button.auras) do
        local aura
        if fn then
            local ok, data = pcall(fn, button.unit, i, "HARMFUL")
            if ok and F.Public(data) and type(data) == "table" then aura = data end
        end
        if aura then
            local texture = F.Public(aura.icon) and aura.icon or nil
            local count = F.Number(aura.applications, 0)
            icon.texture:SetTexture(texture or "Interface\\Icons\\INV_Misc_QuestionMark")
            icon.count:SetText(count > 1 and tostring(count) or "")
            icon:Show()
        else icon:Hide() end
    end
end
function M:MakeButton(parent, unit, label, width, height, compact)
    local button = CreateFrame("Button", "ForeverUIUnit_" .. unit, parent, "SecureUnitButtonTemplate")
    self.buttons[#self.buttons + 1] = button -- registered before any operation that may fail
    button.unit, button.fallback = unit, label
    button:SetSize(width, height); button:RegisterForClicks("AnyUp")
    button:SetAttribute("unit", unit); button:SetAttribute("type1", "target"); button:SetAttribute("type2", "togglemenu")
    F.Surface(button, F.colors.background)
    button.name = F.Font(button, compact and 10 or 12, F.colors.bone); button.name:SetPoint("TOPLEFT", 7, -5); button.name:SetWidth(width - 39); button.name:SetHeight(15)
    button.level = F.Font(button, 9, F.colors.muted, "RIGHT"); button.level:SetPoint("TOPRIGHT", -6, -6)
    button.health = makeBar(button, compact and 15 or 21, F.colors.health)
    button.health:SetPoint("TOPLEFT", 4, compact and -21 or -25); button.health:SetPoint("TOPRIGHT", -4, compact and -21 or -25)
    button.healthText = F.Font(button.health, compact and 8 or 10, F.colors.bone, "RIGHT"); button.healthText:SetPoint("RIGHT", -4, 0)
    button.power = makeBar(button, compact and 3 or 7, F.colors.power); button.power:SetPoint("TOPLEFT", button.health, "BOTTOMLEFT", 0, -2); button.power:SetPoint("TOPRIGHT", button.health, "BOTTOMRIGHT", 0, -2)
    button.powerText = F.Font(button.power, 8, F.colors.bone, "RIGHT"); button.powerText:SetPoint("RIGHT", -3, 0)
    if compact then button.powerText:Hide() end
    button.state = F.Font(button.health, 9, F.colors.amber); button.state:SetPoint("LEFT", 4, 0)
    button:SetScript("OnEnter", function(self)
        if GameTooltip then GameTooltip:SetOwner(self, "ANCHOR_RIGHT"); pcall(GameTooltip.SetUnit, GameTooltip, self.unit); GameTooltip:Show() end
    end)
    button:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    if not compact and (unit == "player" or unit == "target") then
        button.auras = {}
        for i = 1, 8 do
            local aura = CreateFrame("Frame", nil, button); aura:SetSize(20, 20); aura:SetPoint("TOPLEFT", button, "BOTTOMLEFT", (i - 1) * 23, -5)
            F.Surface(aura); aura.texture = aura:CreateTexture(nil, "ARTWORK"); aura.texture:SetPoint("TOPLEFT", 1, -1); aura.texture:SetPoint("BOTTOMRIGHT", -1, 1); aura.texture:SetTexCoord(.07,.93,.07,.93)
            aura.count = F.Font(aura, 9, F.colors.bone, "RIGHT"); aura.count:SetPoint("BOTTOMRIGHT", -1, 1)
            aura:Hide(); button.auras[i] = aura
        end
    end
    RegisterUnitWatch(button); self.watchers[#self.watchers + 1] = button
    self:Update(button); self:UpdateAuras(button)
    return button
end
function M:MakeRoot(key, width, height, label, default)
    local root = CreateFrame("Frame", "ForeverUIGroup_" .. key, UIParent)
    root:SetSize(width, height); root:Hide(); self.roots[#self.roots + 1] = root
    F.RegisterMover(self.id, key, root, label, default, width, height)
    return root
end
function M:Build()
    assert(type(RegisterUnitWatch) == "function" and type(UnregisterUnitWatch) == "function" and type(RegisterStateDriver) == "function" and type(UnregisterStateDriver) == "function", "安全单位框接口不可用")
    assert(F.Resolve("UnitHealth") and F.Resolve("UnitHealthMax") and F.Resolve("UnitPower") and F.Resolve("UnitPowerMax"), "单位数值接口不可用")
    local specs = {
        { "player", "玩家", 238, 58, { point = "BOTTOM", x = -270, y = 232 } },
        { "target", "目标", 238, 58, { point = "BOTTOM", x = 270, y = 232 } },
        { "targettarget", "目标的目标", 146, 42, { point = "BOTTOM", x = 470, y = 184 } },
        { "pet", "宠物", 146, 42, { point = "BOTTOM", x = -320, y = 184 } },
    }
    for _, spec in ipairs(specs) do
        local root = self:MakeRoot(spec[1], spec[3], spec[4], spec[2], spec[5])
        local button = self:MakeButton(root, spec[1], spec[2], spec[3], spec[4], spec[1] == "pet" or spec[1] == "targettarget")
        button:SetPoint("TOPLEFT")
    end
    local party = self:MakeRoot("party", 164, 204, "队伍", { point = "LEFT", x = 25, y = 20 })
    for i = 1, 4 do self:MakeButton(party, "party" .. i, "队友 " .. i, 164, 46, true):SetPoint("TOPLEFT", 0, -(i - 1) * 52) end
    RegisterStateDriver(party, "visibility", "[group:party] show; hide"); self.drivers[#self.drivers + 1] = party
    local raid = self:MakeRoot("raid", 536, 236, "团队（40 人）", { point = "TOPLEFT", x = 25, y = -160 })
    for i = 1, 40 do
        local col, row = math.floor((i - 1) / 8), (i - 1) % 8
        self:MakeButton(raid, "raid" .. i, "团员 " .. i, 104, 27, true):SetPoint("TOPLEFT", col * 108, -row * 30)
        local b = self.buttons[#self.buttons]
        b.name:SetPoint("TOPLEFT", 5, -2); b.name:SetFont(STANDARD_TEXT_FONT or "Fonts\\ARKai_T.ttf", 9, "")
        b.name:SetHeight(12); b.level:Hide(); b.health:ClearAllPoints(); b.health:SetPoint("TOPLEFT", 3, -15); b.health:SetPoint("TOPRIGHT", -3, -15); b.health:SetHeight(7)
        b.healthText:Hide(); b.power:Hide(); b.state:SetFont(STANDARD_TEXT_FONT or "Fonts\\ARKai_T.ttf", 7, "")
    end
    RegisterStateDriver(raid, "visibility", "[group:raid] show; hide"); self.drivers[#self.drivers + 1] = raid
    self.built = true
end
function M:Enable()
    if self.failedBuild then error("本次初始化未完成，请重载后再试。") end
    if not self.built then
        local ok, err = pcall(self.Build, self)
        if not ok then self.failedBuild = true; error(err) end
    else
        for _, button in ipairs(self.buttons) do RegisterUnitWatch(button) end
        RegisterStateDriver(self.roots[5], "visibility", "[group:party] show; hide")
        RegisterStateDriver(self.roots[6], "visibility", "[group:raid] show; hide")
    end
    for i = 1, 4 do self.roots[i]:Show() end
    for key, info in pairs(F.movers) do if info.owner == self.id then F.Place(key) end end
    -- Rescue native cast bars if this client parents them to a replaced frame.
    -- Native cast duration/secret handling stays entirely Blizzard-owned.
    for _, name in ipairs({ "PlayerCastingBarFrame", "CastingBarFrame", "TargetFrameSpellBar" }) do
        local cast = _G[name]
        if cast and cast.GetParent and (cast:GetParent() == PlayerFrame or cast:GetParent() == TargetFrame) then
            F.RememberPoints(self.id, cast)
            local targetCast = cast:GetParent() == TargetFrame
            F.Reparent(self.id, cast, UIParent)
            cast:ClearAllPoints(); cast:SetPoint("BOTTOM", self.roots[targetCast and 2 or 1], "TOP", 0, 8)
        end
    end
    -- Only after every replacement and secure visibility driver was constructed successfully.
    for _, name in ipairs({ "PlayerFrame", "TargetFrame", "TargetFrameToT", "PetFrame", "PartyFrame", "PartyMemberFrame1", "PartyMemberFrame2", "PartyMemberFrame3", "PartyMemberFrame4", "CompactPartyFrame", "CompactRaidFrameContainer" }) do F.HideNative(self.id, _G[name]) end
    if not self.events then
        self.events = CreateFrame("Frame")
        self.events:SetScript("OnEvent", function(_, event, unit)
            if not M.active then return end
            -- Event payloads can be restricted; compare only after Public().
            local publicUnit = F.Public(unit) and type(unit) == "string" and unit or nil
            for _, button in ipairs(M.buttons) do
                if not publicUnit or event == "GROUP_ROSTER_UPDATE" or event == "PLAYER_TARGET_CHANGED" or event == "PLAYER_ENTERING_WORLD" or event == "UNIT_TARGET" or button.unit == publicUnit then
                    M:Update(button)
                    if event == "UNIT_AURA" or event == "PLAYER_TARGET_CHANGED" or event == "PLAYER_ENTERING_WORLD" then M:UpdateAuras(button) end
                end
            end
        end)
    end
    for _, event in ipairs({ "UNIT_HEALTH", "UNIT_MAXHEALTH", "UNIT_POWER_UPDATE", "UNIT_MAXPOWER", "UNIT_NAME_UPDATE", "UNIT_LEVEL", "UNIT_CONNECTION", "UNIT_FLAGS", "UNIT_AURA", "PLAYER_TARGET_CHANGED", "UNIT_TARGET", "GROUP_ROSTER_UPDATE", "PLAYER_ENTERING_WORLD" }) do F.TryEvent(self.events, event) end
    for _, button in ipairs(self.buttons) do self:Update(button); self:UpdateAuras(button) end
end
function M:Disable()
    if self.events then self.events:UnregisterAllEvents() end
    for _, button in ipairs(self.watchers) do if type(UnregisterUnitWatch) == "function" then pcall(UnregisterUnitWatch, button) end; button:Hide() end
    for _, root in ipairs(self.drivers) do if type(UnregisterStateDriver) == "function" then pcall(UnregisterStateDriver, root, "visibility") end end
    for _, root in ipairs(self.roots) do root:Hide() end
end
F.RegisterModule("units", "单位框", "玩家、目标、宠物、队伍与团队；点击行为使用安全单位模板。", M)
