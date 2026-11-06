local F = ForeverUI
local M = { decorations = {}, docks = {} }
local prefixes = { "ActionButton", "MultiBarBottomLeftButton", "MultiBarBottomRightButton", "MultiBarRightButton", "MultiBarLeftButton", "MultiBar5Button", "MultiBar6Button", "MultiBar7Button", "PetActionButton", "StanceButton" }
local function first(...)
    for i = 1, select("#", ...) do local frame = _G[select(i, ...)]; if frame then return frame end end
end
local function buttons(prefix, maximum)
    local result = {}
    for i = 1, maximum or 12 do if _G[prefix .. i] then result[#result + 1] = _G[prefix .. i] end end
    return result
end
function M:SkinButton(button)
    if not button then return end
    local name = button:GetName()
    local icon = button.icon or button.Icon or (name and _G[name .. "Icon"])
    if not icon then return end
    F.Crop(self.id, icon)
    local decoration = self.decorations[button]
    if not decoration then
        decoration = CreateFrame("Frame", nil, button)
        decoration:SetPoint("TOPLEFT", -1, 1); decoration:SetPoint("BOTTOMRIGHT", 1, -1)
        decoration:SetFrameLevel(math.max(0, F.Number(button:GetFrameLevel(), 2) - 1))
        decoration:EnableMouse(false)
        F.Surface(decoration, F.colors.background, F.colors.edge)
        self.decorations[button] = decoration
    end
    decoration:Show()
    local normal = button.GetNormalTexture and button:GetNormalTexture()
    F.Alpha(self.id, normal, 0)
    for _, suffix in ipairs({ "NormalTexture", "FloatingBG", "SlotBackground", "BorderArt", "SlotArt" }) do
        F.Alpha(self.id, button[suffix] or (name and _G[name .. suffix]), 0)
    end
    F.StyleText(self.id, button.HotKey or (name and _G[name .. "HotKey"]), 10, F.colors.bone)
    F.StyleText(self.id, button.Count or (name and _G[name .. "Count"]), 10, F.colors.bone)
    F.StyleText(self.id, button.Name or (name and _G[name .. "Name"]), 9, F.colors.muted)
    -- Icons, attributes, bindings, paging, range/usability and cooldown state
    -- remain Blizzard-owned. Only geometry and decorative regions are styled.
end
function M:Arrange(key, root, label, prefix, columns, size, gap, default, maximum)
    if not root then return end
    local list = buttons(prefix, maximum)
    if #list == 0 then return end
    -- Capture every original anchor before changing the first button.
    F.RememberPoints(self.id, root)
    for _, button in ipairs(list) do F.RememberPoints(self.id, button) end
    local rows = math.ceil(#list / columns)
    local width = math.min(columns, #list) * size + (math.min(columns, #list) - 1) * gap
    local height = rows * size + (rows - 1) * gap
    F.Resize(self.id, root, width, height)
    for index, button in ipairs(list) do
        F.Resize(self.id, button, size, size)
        button:ClearAllPoints()
        button:SetPoint("TOPLEFT", root, "TOPLEFT", ((index - 1) % columns) * (size + gap), -math.floor((index - 1) / columns) * (size + gap))
        self:SkinButton(button)
    end
    F.RegisterMover(self.id, key, root, label, default, width, height)
    local dock = self.docks[key]
    if not dock then
        dock = CreateFrame("Frame", nil, root)
        dock:SetPoint("TOPLEFT", -5, 5); dock:SetPoint("BOTTOMRIGHT", 5, -5)
        dock:SetFrameLevel(math.max(0, F.Number(root:GetFrameLevel(), 3) - 1)); dock:EnableMouse(false)
        F.Surface(dock, F.colors.background, F.colors.edge)
        local accent = dock:CreateTexture(nil, "BORDER")
        accent:SetPoint("TOPLEFT", 1, 0); accent:SetPoint("TOPRIGHT", -1, 0); accent:SetHeight(1)
        accent:SetColorTexture(.46, .34, .64, .65)
        self.docks[key] = dock
    end
    dock:Show()
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
function M:Enable()
    local main = first("MainActionBar", "MainMenuBar")
    assert(main, "未找到原生动作条，保留原样")
    assert(#buttons("ActionButton") == 12, "原生主动作按钮不完整，保留原样")
    self:Arrange("mainbar", main, "主动作条", "ActionButton", 12, 34, 4, { point = "BOTTOM", x = 0, y = 34 })
    self:Arrange("barleft", _G.MultiBarBottomLeft, "动作条 · 第二排", "MultiBarBottomLeftButton", 12, 34, 4, { point = "BOTTOM", x = 0, y = 76 })
    self:Arrange("barright", _G.MultiBarBottomRight, "动作条 · 第三排", "MultiBarBottomRightButton", 12, 34, 4, { point = "BOTTOM", x = 0, y = 118 })
    self:Arrange("barrightedge", _G.MultiBarRight, "右侧动作条", "MultiBarRightButton", 1, 30, 4, { point = "RIGHT", x = -20, y = -50 })
    self:Arrange("barleftedge", _G.MultiBarLeft, "右侧第二动作条", "MultiBarLeftButton", 1, 30, 4, { point = "RIGHT", x = -58, y = -50 })
    self:Arrange("petbar", first("PetActionBar", "PetActionBarFrame"), "宠物动作条", "PetActionButton", 10, 26, 4, { point = "BOTTOM", x = 0, y = 164 }, 10)
    self:Arrange("stancebar", first("StanceBar", "StanceBarFrame"), "姿态动作条", "StanceButton", 10, 26, 4, { point = "BOTTOM", x = -300, y = 34 }, 10)
    for _, prefix in ipairs(prefixes) do for _, button in ipairs(buttons(prefix)) do self:SkinButton(button) end end
    for _, name in ipairs({ "MainMenuBarLeftEndCap", "MainMenuBarRightEndCap", "MainMenuBarTexture0", "MainMenuBarTexture1", "MainMenuBarTexture2", "MainMenuBarTexture3", "MainMenuBarArtFrameBackground" }) do F.Alpha(self.id, _G[name], 0) end
    local art = _G.MainMenuBarArtFrame
    for _, frame in ipairs({ art or false, main or false }) do
        if frame then
            for _, field in ipairs({ "LeftEndCap", "RightEndCap", "Background", "Bg", "BarArt", "BorderArt" }) do F.Alpha(self.id, frame[field], 0) end
            if frame.EndCaps then F.Alpha(self.id, frame.EndCaps.LeftEndCap, 0); F.Alpha(self.id, frame.EndCaps.RightEndCap, 0) end
        end
    end
    for _, spec in ipairs({
        { "micromenu", first("MicroMenuContainer", "MicroButtonAndBagsBar"), "系统菜单", { point = "BOTTOMRIGHT", x = -24, y = 16 }, .8 },
        { "bagbar", _G.BagsBar, "背包按钮", { point = "BOTTOMRIGHT", x = -24, y = 52 }, .8 },
    }) do
        if spec[2] then
            F.RememberPoints(self.id, spec[2]); F.Scale(self.id, spec[2], spec[5])
            F.RegisterMover(self.id, spec[1], spec[2], spec[3], spec[4])
        end
    end
    self:RefreshCooldownIcons()
    if not self.events then
        self.events = CreateFrame("Frame")
        self.events:SetScript("OnEvent", function(_, event)
            if not M.active then return end
            if F.InCombat() then M.cooldownsPending = true; return end
            if event == "ADDON_LOADED" then M:RefreshCooldownIcons()
            else
                local ok, err = pcall(M.Enable, M)
                if not ok then M.error = F.Text(err, "布局更新未完成"); F.Message("动作条布局需要重新应用，请查看 /fui。") end
            end
        end)
    end
    self.events:RegisterEvent("PLAYER_REGEN_ENABLED"); self.events:RegisterEvent("ADDON_LOADED")
    self.events:RegisterEvent("PLAYER_ENTERING_WORLD"); self.events:RegisterEvent("UI_SCALE_CHANGED")
    self.events:RegisterEvent("DISPLAY_SIZE_CHANGED"); self.events:RegisterEvent("ACTIONBAR_PAGE_CHANGED")
end
function M:Disable()
    if self.events then self.events:UnregisterAllEvents() end
    for _, decoration in pairs(self.decorations) do decoration:Hide() end
    for _, dock in pairs(self.docks) do dock:Hide() end
    assert(F.RestoreNative("cooldownicons"), "悬浮冷却图标恢复未完成")
end
F.RegisterModule("actionbars", "动作条", "紧凑居中的动作条、细边框和清晰键位；可关闭悬浮技能冷却图标。", M)
