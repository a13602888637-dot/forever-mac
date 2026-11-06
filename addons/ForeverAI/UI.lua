local FAI = _G.ForeverAI

function FAI.ShowPanel()
    if not FAI.panel then
        local frame = CreateFrame("Frame", "ForeverAIPanel", UIParent, "BackdropTemplate")
        frame:SetSize(460, 340)
        frame:SetPoint("CENTER")
        frame:SetFrameStrata("DIALOG")
        frame:SetMovable(true)
        frame:EnableMouse(true)
        frame:RegisterForDrag("LeftButton")
        frame:SetScript("OnDragStart", frame.StartMoving)
        frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
        if frame.SetBackdrop then
            frame:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
            frame:SetBackdropColor(0.055, 0.045, 0.10, 0.97)
            frame:SetBackdropBorderColor(0.49, 0.34, 0.75, 1)
        end
        local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
        title:SetPoint("TOPLEFT", 24, -24)
        title:SetText("Forever AI  ·  奥术手记")
        title:SetTextColor(0.77, 0.65, 1)
        local text = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        text:SetPoint("TOPLEFT", 24, -65)
        text:SetWidth(410)
        text:SetJustifyH("LEFT")
        text:SetSpacing(7)
        text:SetText("角色、装备、背包与任务变化会自动记录。\n\n手动 /reload 或退出游戏后写入磁盘，\n本地网页自动发现并导入，不用录入数据。\n\n公开资料和可用报价由本地服务自动同步。\n本地控制台：127.0.0.1:18761\n\n界面设置：/fui  ·  所有游戏行为由你操作")
        local export = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        export:SetSize(150, 30)
        export:SetPoint("BOTTOMLEFT", 24, 22)
        export:SetText("生成角色快照")
        export:SetScript("OnClick", function() FAI.Export() end)
        local catalog = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        catalog:SetSize(130,30);catalog:SetPoint("BOTTOMLEFT",184,22);catalog:SetText("离线资料库")
        catalog:SetScript("OnClick",function() FAI.ShowCatalog() end)
        local close = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
        close:SetSize(80, 30)
        close:SetPoint("BOTTOMRIGHT", -24, 22)
        close:SetText("关闭")
        close:SetScript("OnClick", function() frame:Hide() end)
        if type(UISpecialFrames) == "table" then table.insert(UISpecialFrames, "ForeverAIPanel") end
        FAI.panel = frame
    end
    FAI.panel:Show()
end
