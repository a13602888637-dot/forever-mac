local F = ForeverUI
local function showStatus()
    if not F.config or not F.db then return end
    local active, pending = 0, false
    for _, id in ipairs(F.order) do
        if F.modules[id].active then active = active + 1 end
        if F.modules[id].restorePending then pending = true end
    end
    if F.config.cooldownCheck then F.config.cooldownCheck:SetChecked(F.db.showCooldownIcons) end
    if pending then F.config.status:SetText("部分界面恢复未完成 · 可重试恢复，或 /reload")
    elseif F.db.enabled and active > 0 then F.config.status:SetText("已应用 " .. active .. " 个模块 · 点击模块可独立开关")
    elseif F.db.enabled then F.config.status:SetText("模块暂未就绪 · 原生界面保留")
    else F.config.status:SetText("原生界面 · 点击下方按钮应用主题") end
    for _, id in ipairs(F.order) do
        local module, row = F.modules[id], F.config.rows[id]
        row.check:SetChecked(F.db.modules[id])
        if module.restorePending then row.state:SetText("恢复待重试"); row.state:SetTextColor(unpack(F.colors.amber))
        elseif module.error then row.state:SetText("未就绪 · 已降级"); row.state:SetTextColor(unpack(F.colors.amber))
        elseif module.active then row.state:SetText("已应用"); row.state:SetTextColor(unpack(F.colors.mint))
        else row.state:SetText(F.db.modules[id] and "待应用" or "未启用"); row.state:SetTextColor(unpack(F.colors.muted)) end
    end
end
F.RefreshConfig = showStatus
function F.ShowConfig()
    if not F.db then return end
    if not F.config then
        local panel = CreateFrame("Frame", "ForeverUIConfig", UIParent)
        F.config = panel; panel:SetSize(640, 608); panel:SetPoint("CENTER"); panel:SetFrameStrata("DIALOG"); panel:EnableMouse(true); panel:SetMovable(true); panel:RegisterForDrag("LeftButton")
        F.Surface(panel, F.colors.background, F.colors.edge)
        panel:SetScript("OnDragStart", function(self) if F.Guard() then self:StartMoving() end end)
        panel:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
        local eyebrow = F.Font(panel, 10, F.colors.muted); eyebrow:SetPoint("TOPLEFT", 28, -24); eyebrow:SetText("FOREVER · UNDEAD ARCANE")
        local title = F.Font(panel, 24, F.colors.bone); title:SetPoint("TOPLEFT", 27, -47); title:SetText("亡灵奥术")
        local mark = F.Font(panel, 45, F.colors.purple, "CENTER"); mark:SetPoint("TOPRIGHT", -28, -30); mark:SetText("◇")
        panel.status = F.Font(panel, 11, F.colors.muted); panel.status:SetPoint("TOPLEFT", 28, -87)
        F.Button(panel, "×", 25, function() panel:Hide() end):SetPoint("TOPRIGHT", -9, -8)
        panel.rows = {}
        for i, id in ipairs(F.order) do
            local module = F.modules[id]
            local row = CreateFrame("Frame", nil, panel); row:SetSize(582, 47); row:SetPoint("TOPLEFT", 28, -119 - (i - 1) * 51)
            local line = row:CreateTexture(nil, "BACKGROUND"); line:SetColorTexture(.19,.14,.24,1); line:SetHeight(1); line:SetPoint("BOTTOMLEFT"); line:SetPoint("BOTTOMRIGHT")
            row.check = CreateFrame("CheckButton", nil, row, "UICheckButtonTemplate"); row.check:SetSize(25, 25); row.check:SetPoint("LEFT", 0, 2)
            row.check:SetScript("OnClick", function(self) F.ToggleModule(id, self:GetChecked()) end)
            row.title = F.Font(row, 12, F.colors.bone); row.title:SetPoint("TOPLEFT", 37, -3); row.title:SetText(module.title)
            row.description = F.Font(row, 10, F.colors.muted); row.description:SetPoint("TOPLEFT", 37, -23); row.description:SetWidth(460); row.description:SetText(module.description)
            row.state = F.Font(row, 10, F.colors.muted, "RIGHT"); row.state:SetPoint("TOPRIGHT", -2, -4)
            row:EnableMouse(true)
            row:SetScript("OnEnter", function(self)
                if (module.error or module.restorePending) and GameTooltip then
                    GameTooltip:SetOwner(self, "ANCHOR_RIGHT"); GameTooltip:SetText(module.title .. (module.restorePending and " · 恢复未完成" or " · 原生界面可用"))
                    GameTooltip:AddLine("当前客户端未能完成适配。可重载后再试；错误如下：", .82,.71,.48,true)
                    GameTooltip:AddLine(module.restorePending and "原状态已保留；请 /fui off 重试，或 /reload 恢复原生界面。" or module.error, .57,.49,.64,true); GameTooltip:Show()
                end
            end)
            row:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
            panel.rows[id] = row
        end
        local footnote = F.Font(panel, 10, F.colors.muted); footnote:SetPoint("TOPLEFT", 28, -437); footnote:SetWidth(580)
        footnote:SetText("动作条位置由游戏原生编辑模式管理；其他模块可拖动标签。战斗中暂停布局与模块设置。")
        panel.cooldownCheck = CreateFrame("CheckButton", nil, panel, "UICheckButtonTemplate")
        panel.cooldownCheck:SetSize(24, 24); panel.cooldownCheck:SetPoint("TOPLEFT", 27, -465)
        panel.cooldownCheck:SetScript("OnClick", function(self) F.SetCooldownIcons(self:GetChecked()) end)
        local cooldownLabel = F.Font(panel, 11, F.colors.bone)
        cooldownLabel:SetPoint("LEFT", panel.cooldownCheck, "RIGHT", 7, 0)
        cooldownLabel:SetText("显示动作条外的悬浮技能冷却图标")
        local apply = F.Button(panel, "应用亡灵奥术", 148, function() F.ApplyProfile(); showStatus() end); apply:SetPoint("BOTTOMLEFT", 28, 61)
        apply.surface.background:SetColorTexture(.29,.18,.41,1)
        F.Button(panel, "编辑布局", 116, function() panel:Hide(); F.SetEdit(true) end):SetPoint("LEFT", apply, "RIGHT", 10, 0)
        F.Button(panel, "紧凑布局", 116, function() F.ApplyCompactLayout() end):SetPoint("LEFT", apply, "RIGHT", 136, 0)
        F.Button(panel, "恢复原生", 116, function() F.RestoreAll() end):SetPoint("LEFT", apply, "RIGHT", 262, 0)
        local build = F.Font(panel, 9, F.colors.muted); build:SetPoint("BOTTOMLEFT", 28, 25)
        local version, number, date, interface = F.Read("GetBuildInfo")
        build:SetText("ForeverUI " .. F.version .. "  ·  客户端 " .. F.Text(version, "未知") .. " / " .. F.Text(number, "未知") .. "  ·  Interface " .. F.Text(interface, "未知"))
        F.Button(panel, "查看行囊", 95, function()
            if F.modules.bags.active then panel:Hide(); F.modules.bags:Toggle() else F.Message("请先应用主题并启用行囊模块。") end
        end):SetPoint("BOTTOMRIGHT", -28, 15)
        if UISpecialFrames then table.insert(UISpecialFrames, "ForeverUIConfig") end
    end
    showStatus(); F.config:Show()
end
