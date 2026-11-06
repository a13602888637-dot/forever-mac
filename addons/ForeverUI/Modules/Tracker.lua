local F = ForeverUI
local M = {}
function M:Enable()
    local frame = _G.ObjectiveTrackerFrame or _G.QuestWatchFrame
    assert(frame, "未找到原生任务追踪，保留原样")
    if not self.skin then
        self.skin = CreateFrame("Frame", nil, frame)
        self.skin:SetPoint("TOPLEFT", -9, 10); self.skin:SetPoint("BOTTOMRIGHT", 9, -9)
        self.skin:SetFrameLevel(math.max(0, F.Number(frame:GetFrameLevel(), 2) - 1)); self.skin:EnableMouse(false)
        F.Surface(self.skin, { .055, .04, .075, .80 }, { .25, .18, .32, .8 })
    end
    F.RememberPoints(self.id, frame)
    F.RegisterMover(self.id, "tracker", frame, "任务追踪", { point = "TOPRIGHT", x = -35, y = -270 }, 260, 70)
    local header = frame.Header and (frame.Header.Text or frame.Header.Label)
    if header and header.SetTextColor then
        local rec = F.Remember(self.id, header)
        rec.textColor = rec.textColor or { n = 4, header:GetTextColor() }
        header:SetTextColor(.81, .68, .94, 1)
    end
    self.skin:Show()
    -- Native quest clicks, item buttons, objectives and timers are untouched.
end
function M:Disable() if self.skin then self.skin:Hide() end end
F.RegisterModule("tracker", "任务追踪", "为原生任务追踪换肤与定位，保留任务物品按钮和追踪交互。", M)
