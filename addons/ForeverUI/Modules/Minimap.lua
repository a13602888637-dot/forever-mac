local F = ForeverUI
local M = {}
function M:Refresh()
    if not self.active then return end
    self.zone:SetText(F.Text(F.Read("GetMinimapZoneText"), "未知区域"))
    local hour, minute = F.Read("GetGameTime")
    hour, minute = F.Number(hour), F.Number(minute)
    self.time:SetText(hour and minute and string.format("%02d:%02d", hour, minute) or "")
end
function M:Enable()
    local map, cluster = _G.Minimap, _G.MinimapCluster
    assert(map and cluster, "未找到原生小地图，保留原样")
    if not self.skin then
        self.skin = CreateFrame("Frame", nil, cluster); self.skin:SetPoint("TOPLEFT", map, "TOPLEFT", -5, 5); self.skin:SetPoint("BOTTOMRIGHT", map, "BOTTOMRIGHT", 5, -5)
        self.skin:EnableMouse(false); self.skin:SetFrameLevel(math.max(0, F.Number(map:GetFrameLevel(), 2) - 1)); F.Surface(self.skin, { .06, .04, .09, .85 }, F.colors.edge)
        self.zone = F.Font(self.skin, 11, F.colors.bone, "CENTER"); self.zone:SetPoint("BOTTOM", self.skin, "TOP", 0, 7); self.zone:SetWidth(200)
        self.time = F.Font(self.skin, 11, F.colors.muted, "CENTER"); self.time:SetPoint("TOP", self.skin, "BOTTOM", 0, -8)
        self.launcher = F.Button(cluster, "✧", 25, function(_, button)
            if button == "RightButton" and F.modules.bags.active then F.modules.bags:Toggle() else F.ShowConfig() end
        end)
        self.launcher:RegisterForClicks("LeftButtonUp", "RightButtonUp"); self.launcher:SetSize(25, 25); self.launcher:SetPoint("TOPLEFT", map, "BOTTOMRIGHT", -20, 14)
        self.launcher:SetScript("OnEnter", function(self)
            if GameTooltip then GameTooltip:SetOwner(self, "ANCHOR_LEFT"); GameTooltip:SetText("ForeverUI · 亡灵奥术"); GameTooltip:AddLine("左键：主题设置\n右键：只读行囊", .67, .52, .92); GameTooltip:Show() end
        end)
        self.launcher:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
        self.events = CreateFrame("Frame"); self.events:SetScript("OnEvent", function() M:Refresh() end)
        self.timer = 0
        self.skin:SetScript("OnUpdate", function(_, elapsed)
            M.timer = M.timer + elapsed
            if M.timer >= 15 then M.timer = 0; M:Refresh() end
        end)
    end
    F.RememberPoints(self.id, cluster)
    F.Scale(self.id, cluster, .9)
    F.RegisterMover(self.id, "minimap", cluster, "小地图", { point = "TOPRIGHT", x = -22, y = -25 }, 180, 180)
    for _, name in ipairs({ "MinimapBorder", "MinimapBorderTop", "MinimapBackdrop", "MiniMapTrackingBackground" }) do F.Alpha(self.id, _G[name], 0) end
    F.Alpha(self.id, _G.MinimapZoneTextButton, 0)
    self.skin:Show(); self.launcher:Show()
    for _, event in ipairs({ "ZONE_CHANGED", "ZONE_CHANGED_INDOORS", "ZONE_CHANGED_NEW_AREA", "PLAYER_ENTERING_WORLD" }) do F.TryEvent(self.events, event) end
    local wasActive = self.active; self.active = true; self:Refresh(); self.active = wasActive
end
function M:Disable()
    if self.skin then self.skin:Hide() end
    if self.launcher then self.launcher:Hide() end
    if self.events then self.events:UnregisterAllEvents() end
end
F.RegisterModule("minimap", "小地图", "奥术边框、区域与时间；保留原生缩放、追踪和地图交互。", M)
