local F = ForeverUI
local M = { items = {}, filtered = {}, cells = {}, page = 1, category = "all", query = "" }
local categories = { {"all", "全部"}, {"gear", "装备"}, {"reagent", "材料"}, {"consumable", "消耗品"}, {"other", "其他"} }
local pageSize, columns = 60, 10
local function api(modern, legacy) return F.Resolve(modern) or F.Resolve(legacy) end
local function info(bag, slot)
    local modern = F.Resolve("C_Container.GetContainerItemInfo")
    if modern then
        local ok, result = pcall(modern, bag, slot)
        if not ok or not F.Public(result) then return nil, true end
        if type(result) == "table" then return result, false end
        return nil, result ~= nil
    end
    local legacy = F.Resolve("GetContainerItemInfo")
    if not legacy then return nil end
    local ok, texture, count, locked, quality, readable, lootable, link = pcall(legacy, bag, slot)
    if not ok then return nil, true end
    return { iconFileID = texture, stackCount = count, quality = quality, hyperlink = link }
end
function M:ReadItems()
    local slotsAPI = api("C_Container.GetContainerNumSlots", "GetContainerNumSlots")
    if not slotsAPI then self.items = {}; self.restricted = 1; self.totalSlots = 0; self.partialScan = true; return end
    local items, restricted, totalSlots, partial = {}, 0, 0, false
    local maxBag = F.Number(NUM_BAG_SLOTS)
    if not maxBag or maxBag < 0 or maxBag > 10 or maxBag ~= math.floor(maxBag) then
        maxBag, partial = 0, true -- known backpack only; never guess the equipped bag count
    elseif Enum and F.Public(Enum) and Enum.BagIndex and F.Public(Enum.BagIndex) then
        local reagent = F.Number(Enum.BagIndex.ReagentBag)
        if reagent and reagent >= 0 and reagent <= 10 and reagent == math.floor(reagent) then maxBag = math.max(maxBag, reagent) end
    end
    for bag = 0, maxBag do
        local ok, slots = pcall(slotsAPI, bag)
        slots = ok and F.Number(slots) or nil
        if slots and slots >= 0 and slots == math.floor(slots) then
            if slots > 200 then partial = true end
            local readableSlots = math.min(slots, 200)
            totalSlots = totalSlots + readableSlots
            for slot = 1, readableSlots do
                local data, inaccessible = info(bag, slot)
                if inaccessible then restricted = restricted + 1 end
                if data then
                    local id = F.Number(data.itemID)
                    if not id then id = F.Number(F.Read("C_Container.GetContainerItemID", bag, slot) or F.Read("GetContainerItemID", bag, slot)) end
                    local link = F.Text(data.hyperlink)
                    local texture = F.Public(data.iconFileID) and data.iconFileID or nil
                    if id or link then
                        local name, itemLink, quality, level, minLevel, itemType, subtype, stack, equipLoc, icon, sell, classID, subclass, bind, expansion, set, reagent
                        if F.Resolve("C_Item.GetItemInfo") then name, itemLink, quality, level, minLevel, itemType, subtype, stack, equipLoc, icon, sell, classID, subclass, bind, expansion, set, reagent = F.Read("C_Item.GetItemInfo", id or link)
                        else name, itemLink, quality, level, minLevel, itemType, subtype, stack, equipLoc, icon, sell, classID, subclass, bind, expansion, set, reagent = F.Read("GetItemInfo", id or link) end
                        if not classID then
                            local _, _, _, instantEquip, instantIcon, instantClass
                            if F.Resolve("C_Item.GetItemInfoInstant") then _, _, _, instantEquip, instantIcon, instantClass = F.Read("C_Item.GetItemInfoInstant", id or link)
                            else _, _, _, instantEquip, instantIcon, instantClass = F.Read("GetItemInfoInstant", id or link) end
                            classID, equipLoc, icon = instantClass, instantEquip, instantIcon
                        end
                        local category = "other"
                        if classID == 2 or classID == 4 then category = "gear"
                        elseif classID == 7 or reagent == true then category = "reagent"
                        elseif classID == 0 then category = "consumable" end
                        local itemName = F.Text(name, id and ("物品 " .. id) or "读取中")
                        items[#items + 1] = { bag = bag, slot = slot, id = id, name = itemName, link = link,
                            count = F.Number(data.stackCount), quality = F.Number(quality, F.Number(data.quality, 1)),
                            icon = texture or icon or "Interface\\Icons\\INV_Misc_QuestionMark", category = category,
                            search = (itemName .. " " .. F.Text(id, "") .. " " .. F.Text(itemType, "")):lower() }
                    elseif not F.Public(data.itemID) or not F.Public(data.hyperlink) then restricted = restricted + 1 end
                end
            end
        else restricted = restricted + 1 end
    end
    table.sort(items, function(a, b)
        if a.category ~= b.category then return a.category < b.category end
        if a.name ~= b.name then return a.name < b.name end
        if a.bag ~= b.bag then return a.bag < b.bag end
        return a.slot < b.slot
    end)
    self.items, self.restricted, self.totalSlots = items, restricted, totalSlots
    self.partialScan = partial or restricted > 0
end
function M:Filter()
    self.filtered = {}
    local query = self.query:lower()
    for _, item in ipairs(self.items) do
        if (self.category == "all" or item.category == self.category) and (query == "" or item.search:find(query, 1, true)) then self.filtered[#self.filtered + 1] = item end
    end
    local pages = math.max(1, math.ceil(#self.filtered / pageSize))
    self.page = math.min(math.max(1, self.page), pages)
    self.pageText:SetText(self.page .. " / " .. pages .. " 页")
    self.summary:SetText(#self.items .. " 个已读物品栏位  ·  " .. (self.partialScan and "已读 " or "") .. self.totalSlots .. " 格" .. (self.partialScan and "  ·  部分读取" or "行囊"))
    self.empty:SetText(#self.filtered == 0 and "没有匹配的物品。试试名称、类型或物品 ID。" or "")
    for i, cell in ipairs(self.cells) do
        local item = self.filtered[(self.page - 1) * pageSize + i]
        cell.item = item
        if item then
            cell.icon:SetTexture(item.icon)
            cell.count:SetText(item.count and (item.count > 1 and tostring(item.count) or "") or "?")
            local r, g, b = F.Read("GetItemQualityColor", item.quality)
            for _, line in ipairs(cell.surface.lines) do line:SetColorTexture(F.Number(r, .31), F.Number(g, .22), F.Number(b, .40), 1) end
            cell:Show()
        else cell:Hide() end
    end
    for _, button in ipairs(self.categoryButtons) do button.text:SetTextColor(unpack(button.category == self.category and F.colors.purple or F.colors.muted)) end
end
function M:Refresh()
    self:ReadItems(); self:Filter()
end
function M:Toggle()
    if not self.active then return end
    if self.window:IsShown() then self.window:Hide()
    else self:Refresh(); self.window:Show() end
end
function M:Build()
    assert(api("C_Container.GetContainerNumSlots", "GetContainerNumSlots") and api("C_Container.GetContainerItemInfo", "GetContainerItemInfo"), "背包只读接口不可用")
    local window = CreateFrame("Frame", "ForeverUIBagWindow", UIParent)
    self.window = window; window:SetSize(594, 498); window:SetFrameStrata("HIGH"); window:EnableMouse(true); window:Hide()
    F.Surface(window, F.colors.background)
    local title = F.Font(window, 18, F.colors.bone); title:SetPoint("TOPLEFT", 20, -18); title:SetText("行囊")
    local sub = F.Font(window, 10, F.colors.muted); sub:SetPoint("TOPLEFT", 70, -24); sub:SetText("FOREVER · 只读整理")
    F.Button(window, "×", 28, function() window:Hide() end):SetPoint("TOPRIGHT", -12, -12)
    self.summary = F.Font(window, 10, F.colors.muted); self.summary:SetPoint("TOPLEFT", 20, -46)
    local search = CreateFrame("EditBox", nil, window, "InputBoxTemplate")
    search:SetSize(215, 24); search:SetPoint("TOPRIGHT", -25, -47); search:SetAutoFocus(false); search:SetMaxLetters(100)
    search:SetScript("OnTextChanged", function(self) M.query = F.Text(self:GetText(), ""); M.page = 1; M:Filter() end)
    search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    local searchLabel = F.Font(window, 9, F.colors.muted, "RIGHT"); searchLabel:SetPoint("RIGHT", search, "LEFT", -12, 0); searchLabel:SetText("搜索名称 / ID")
    self.categoryButtons = {}
    for i, category in ipairs(categories) do
        local b = F.Button(window, category[2], 65, function() M.category = category[1]; M.page = 1; M:Filter() end)
        b:SetPoint("TOPLEFT", 20 + (i - 1) * 72, -82); b:SetHeight(24); b.category = category[1]; self.categoryButtons[i] = b
    end
    for i = 1, pageSize do
        local cell = CreateFrame("Button", nil, window); cell:SetSize(47, 47)
        cell:SetPoint("TOPLEFT", 20 + ((i - 1) % columns) * 55, -120 - math.floor((i - 1) / columns) * 53)
        cell.surface = F.Surface(cell); cell.icon = cell:CreateTexture(nil, "ARTWORK"); cell.icon:SetPoint("TOPLEFT", 2, -2); cell.icon:SetPoint("BOTTOMRIGHT", -2, 2); cell.icon:SetTexCoord(.07,.93,.07,.93)
        cell.count = F.Font(cell, 11, F.colors.bone, "RIGHT"); cell.count:SetPoint("BOTTOMRIGHT", -3, 3)
        cell:SetScript("OnEnter", function(self)
            if self.item and GameTooltip then
                GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
                local ok = pcall(GameTooltip.SetBagItem, GameTooltip, self.item.bag, self.item.slot)
                if not ok then GameTooltip:SetText(self.item.name) end
                GameTooltip:AddLine("背包 " .. self.item.bag .. " · 位置 " .. self.item.slot, .57, .49, .64)
                GameTooltip:AddLine("只读浏览；物品操作请使用原生背包。", .67, .52, .92)
                GameTooltip:Show()
            end
        end)
        cell:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
        -- No OnClick / drag / item-use handlers: this view cannot move, use, sell or destroy items.
        self.cells[i] = cell
    end
    self.empty = F.Font(window, 12, F.colors.muted, "CENTER"); self.empty:SetPoint("CENTER"); self.empty:SetWidth(500)
    self.pageText = F.Font(window, 11, F.colors.muted, "CENTER"); self.pageText:SetPoint("BOTTOM", 0, 30)
    F.Button(window, "‹", 28, function() M.page = M.page - 1; M:Filter() end):SetPoint("RIGHT", self.pageText, "LEFT", -18, 0)
    F.Button(window, "›", 28, function() M.page = M.page + 1; M:Filter() end):SetPoint("LEFT", self.pageText, "RIGHT", 18, 0)
    F.Button(window, "打开原生背包", 120, function()
        if not F.Guard() then return end
        local fn = F.Resolve("ToggleAllBags") or F.Resolve("OpenAllBags")
        if fn then pcall(fn) else F.Message("请使用游戏原生背包按键。"); end
    end):SetPoint("BOTTOMRIGHT", -20, 17)
    local hint = F.Font(window, 9, F.colors.muted); hint:SetPoint("BOTTOMLEFT", 20, 25); hint:SetText("B 键仍保留原生操作")
    F.RegisterMover(self.id, "bags", window, "行囊窗口", { point = "CENTER", x = 0, y = 0 }, 594, 498)
    self.launcher = F.Button(UIParent, "◇ 行囊", 80, function() M:Toggle() end)
    F.RegisterMover(self.id, "bagbutton", self.launcher, "行囊入口", { point = "BOTTOMRIGHT", x = -30, y = 27 }, 80, 30)
    if UISpecialFrames then table.insert(UISpecialFrames, "ForeverUIBagWindow") end
    self.events = CreateFrame("Frame")
    self.events:SetScript("OnEvent", function() if M.active and M.window:IsShown() then M:Refresh() end end)
    self.built = true
end
function M:Enable()
    if self.failedBuild then error("本次初始化未完成，请重载后再试。") end
    if not self.built then
        local ok, err = pcall(self.Build, self)
        if not ok then self.failedBuild = true; error(err) end
    end
    self.launcher:Show()
    F.Place("bags"); F.Place("bagbutton")
    for _, event in ipairs({ "BAG_UPDATE_DELAYED", "GET_ITEM_INFO_RECEIVED", "PLAYER_ENTERING_WORLD" }) do F.TryEvent(self.events, event) end
    self:Refresh()
end
function M:Disable()
    if self.window then self.window:Hide() end
    if self.launcher then self.launcher:Hide() end
    if self.events then self.events:UnregisterAllEvents() end
end
F.RegisterModule("bags", "行囊", "聚合行囊、自动分类与搜索；只读浏览，保留原生物品操作。", M)
