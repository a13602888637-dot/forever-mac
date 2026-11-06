local F = ForeverUI
local M = { skins = {} }
local function rememberText(owner, text, color)
    if not text or not text.GetTextColor then return end
    local rec = F.Remember(owner, text)
    rec.textColor = rec.textColor or { n = 4, text:GetTextColor() }
    text:SetTextColor(unpack(color))
end
function M:Skin(frame, index)
    local name = frame:GetName()
    local skin = self.skins[frame]
    if not skin then
        skin = CreateFrame("Frame", nil, frame)
        skin:SetPoint("TOPLEFT", -9, 7); skin:SetPoint("BOTTOMRIGHT", 9, -7)
        skin:SetFrameLevel(math.max(0, F.Number(frame:GetFrameLevel(), 2) - 1)); skin:EnableMouse(false)
        F.Surface(skin, { .055, .04, .075, .78 }, { .25, .18, .32, .8 }); self.skins[frame] = skin
    end
    skin:Show()
    if frame.GetFont and frame.SetFont then
        local path, size, flags = frame:GetFont()
        if F.Public(path) and F.Number(size) and F.Public(flags) then
            local rec = F.Remember(self.id, frame); rec.font = rec.font or { n = 3, path, size, flags }
            frame:SetFont(path, math.max(12, size), flags)
        end
    end
    for _, suffix in ipairs({ "Background", "LeftTexture", "RightTexture", "TopTexture", "BottomTexture", "TopLeftTexture", "TopRightTexture", "BottomLeftTexture", "BottomRightTexture" }) do F.Alpha(self.id, name and _G[name .. suffix], 0) end
    rememberText(self.id, name and _G[name .. "TabText"], F.colors.muted)
    local edit = name and _G[name .. "EditBox"]
    if edit then
        for _, suffix in ipairs({ "Left", "Mid", "Right", "FocusLeft", "FocusMid", "FocusRight" }) do F.Tint(self.id, _G[name .. "EditBox" .. suffix], .60, .42, .75, 1) end
    end
end
function M:Enable()
    assert(_G.ChatFrame1, "未找到原生聊天窗口，保留原样")
    for i = 1, math.min(F.Number(NUM_CHAT_WINDOWS, 10), 20) do if _G["ChatFrame" .. i] then self:Skin(_G["ChatFrame" .. i], i) end end
    F.RememberPoints(self.id, ChatFrame1)
    F.RegisterMover(self.id, "chat", ChatFrame1, "聊天", { point = "BOTTOMLEFT", x = 28, y = 38 })
    -- No chat filters, message sending, key interception, or history writes.
end
function M:Disable() for _, skin in pairs(self.skins) do skin:Hide() end end
F.RegisterModule("chat", "聊天", "安静的深色聊天底板与清晰文字；频道、输入和原生消息行为不变。", M)
