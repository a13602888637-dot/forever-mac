local F = ForeverUI
local M = { decorations = {} }
local unpack = unpack
local function first(...)
    for i = 1, select("#", ...) do local f = _G[select(i, ...)]; if f then return f end end
end
function M:SkinButton(button)
    if not button then return end
    local name = button:GetName()
    local icon = button.icon or button.Icon or (name and _G[name .. "Icon"])
    if not icon then return end
    F.Crop(self.id, icon)
    local border = self.decorations[button]
    if not border then
        border = CreateFrame("Frame", nil, button)
        border:SetPoint("TOPLEFT", -2, 2); border:SetPoint("BOTTOMRIGHT", 2, -2)
        border:SetFrameLevel(math.max(0, F.Number(button:GetFrameLevel(), 2) - 1))
        border:EnableMouse(false)
        F.Surface(border, F.colors.background, F.colors.edge)
        self.decorations[button] = border
    end
    border:Show()
    -- Only decorative regions are changed. Native action attributes, key bindings,
    -- paging, cooldowns, charge counts, range/usability indicators, tooltips and flyouts stay intact.
    local normal = button.GetNormalTexture and button:GetNormalTexture()
    F.Tint(self.id, normal, 0.38, 0.28, 0.47, 0.8)
    local hotkey = button.HotKey or (name and _G[name .. "HotKey"])
    if hotkey and hotkey.GetTextColor then
        local rec = F.Remember(self.id, hotkey)
        if not rec.textColor then rec.textColor = { n = 4, hotkey:GetTextColor() } end
        hotkey:SetTextColor(0.80, 0.72, 0.89, 1)
    end
end
function M:Enable()
    local main = first("MainActionBar", "MainMenuBar")
    assert(main, "未找到原生动作条，保留原样")
    local count = 0
    for i = 1, 12 do if _G["ActionButton" .. i] then count = count + 1 end end
    assert(count == 12, "原生主动作按钮不完整，保留原样")
    local roots = {
        { "mainbar", main, "主动作条", { point = "BOTTOM", x = 0, y = 28 } },
        { "barleft", first("MultiBarBottomLeft"), "动作条 · 下排", { point = "BOTTOM", x = 0, y = 76 } },
        { "barright", first("MultiBarBottomRight"), "动作条 · 上排", { point = "BOTTOM", x = 0, y = 124 } },
        { "barrightedge", first("MultiBarRight"), "右侧动作条", { point = "RIGHT", x = -18, y = -50 } },
        { "barleftedge", first("MultiBarLeft"), "右侧第二动作条", { point = "RIGHT", x = -60, y = -50 } },
        { "petbar", first("PetActionBar", "PetActionBarFrame"), "宠物动作条", { point = "BOTTOM", x = 0, y = 172 } },
        { "stancebar", first("StanceBar", "StanceBarFrame"), "姿态动作条", { point = "BOTTOM", x = -340, y = 28 } },
    }
    for _, spec in ipairs(roots) do
        if spec[2] then
            F.RememberPoints(self.id, spec[2])
            F.RegisterMover(self.id, spec[1], spec[2], spec[3], spec[4])
        end
    end
    for _, prefix in ipairs({ "ActionButton", "MultiBarBottomLeftButton", "MultiBarBottomRightButton", "MultiBarRightButton", "MultiBarLeftButton", "MultiBar5Button", "MultiBar6Button", "MultiBar7Button", "PetActionButton", "StanceButton" }) do
        for i = 1, 12 do self:SkinButton(_G[prefix .. i]) end
    end
    for _, name in ipairs({ "MainMenuBarLeftEndCap", "MainMenuBarRightEndCap", "MainMenuBarTexture0", "MainMenuBarTexture1", "MainMenuBarTexture2", "MainMenuBarTexture3" }) do F.Alpha(self.id, _G[name], 0) end
    local art = _G.MainMenuBarArtFrame
    if art then F.Alpha(self.id, art.LeftEndCap, 0); F.Alpha(self.id, art.RightEndCap, 0) end
    if main.EndCaps then F.Alpha(self.id, main.EndCaps.LeftEndCap, 0); F.Alpha(self.id, main.EndCaps.RightEndCap, 0) end
    -- No Show/Hide of native bars and no protected attribute changes are performed.
end
function M:Disable()
    for _, decoration in pairs(self.decorations) do decoration:Hide() end
end
F.RegisterModule("actionbars", "动作条", "为原生安全按钮换肤；按键、分页、提示与冷却保持原生。", M)
