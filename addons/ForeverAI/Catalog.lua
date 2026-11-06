local FAI = ForeverAI

local function plain(value)
    if value == nil or value == FAI.CatalogNull then return "未知" end
    if type(value) ~= "string" and type(value) ~= "number" then return "未知" end
    return tostring(value):gsub("|", "||")
end

function FAI.CatalogStatus()
    local data = FAI.CatalogData
    if type(data) ~= "table" then return nil end
    local values = FAI.Call("GetBuildInfo")
    local matches
    if values and type(values[1]) == "string" and (type(values[2]) == "string" or type(values[2]) == "number") then
        matches = values[1] .. "." .. tostring(values[2]) == data.build
    end
    return { build = data.build, item_count = data.item_count, recipe_count = data.recipe_count, matches = matches }
end

function FAI.FindCatalog(kind, query, limit)
    local data = FAI.CatalogData
    local records = data and (kind == "recipes" and data.recipes or data.items)
    if type(records) ~= "table" then return {} end
    query = type(query) == "string" and query:lower() or ""
    limit = math.max(1, math.min(math.floor(tonumber(limit) or 12), 50))
    local id = tonumber(query)
    if id and records[id] then return { records[id] } end
    local results = {}
    for _, record in pairs(records) do
        if query == "" or (type(record.name) == "string" and record.name:lower():find(query, 1, true)) then
            results[#results + 1] = record
        end
    end
    table.sort(results, function(a, b) return a.id < b.id end)
    while #results > limit do table.remove(results) end
    return results
end

function FAI.CatalogLines(kind, query)
    local lines, data = {}, FAI.CatalogData
    for _, record in ipairs(FAI.FindCatalog(kind, query, 10)) do
        lines[#lines + 1] = plain(record.name) .. "  ·  #" .. plain(record.id)
        if kind == "recipes" then
            local parts = {}
            for _, reagent in ipairs(type(record.reagents) == "table" and record.reagents or {}) do
                if type(reagent) == "table" then
                    local item = data.items[reagent[1]]
                    parts[#parts + 1] = plain(item and item.name or reagent[1]) .. " × " .. plain(reagent[2])
                end
            end
            lines[#lines + 1] = "材料：" .. (#parts > 0 and table.concat(parts, "、") or "未知")
        else
            lines[#lines + 1] = "装等 " .. plain(record.ilvl) .. " · 需求等级 " .. plain(record.req) .. " · " .. plain(record.slot)
        end
        if record.tp or record.hidden then lines[#lines + 1] = "来源或可用性需进一步核实" end
        lines[#lines + 1] = ""
    end
    return #lines > 0 and table.concat(lines, "\n") or "没有匹配的记录。"
end

function FAI.ShowCatalog()
    local status = FAI.CatalogStatus()
    if not status then FAI.Message("插件资料库尚未装载，请完整重启客户端。"); return end
    if not FAI.catalogPanel then
        local frame = CreateFrame("Frame", "ForeverAICatalogPanel", UIParent, "BackdropTemplate")
        frame:SetSize(680, 560); frame:SetPoint("CENTER"); frame:SetFrameStrata("DIALOG")
        frame:SetMovable(true); frame:EnableMouse(true); frame:RegisterForDrag("LeftButton")
        frame:SetScript("OnDragStart", frame.StartMoving); frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
        if frame.SetBackdrop then
            frame:SetBackdrop({ bgFile="Interface\\Buttons\\WHITE8X8",edgeFile="Interface\\Buttons\\WHITE8X8",edgeSize=1 })
            frame:SetBackdropColor(.055,.045,.10,.98); frame:SetBackdropBorderColor(.49,.34,.75,1)
        end
        local title = frame:CreateFontString(nil,"OVERLAY","GameFontNormalLarge")
        title:SetPoint("TOPLEFT",24,-22);title:SetText("无限图鉴 · 插件离线资料库")
        frame.meta = frame:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
        frame.meta:SetPoint("TOPLEFT",24,-52);frame.meta:SetWidth(630);frame.meta:SetJustifyH("LEFT")
        local input = CreateFrame("EditBox",nil,frame,"InputBoxTemplate")
        input:SetSize(330,28);input:SetPoint("TOPLEFT",30,-88);input:SetAutoFocus(false);input:SetMaxLetters(100)
        local scroll = CreateFrame("ScrollFrame",nil,frame,"UIPanelScrollFrameTemplate")
        scroll:SetPoint("TOPLEFT",24,-140);scroll:SetPoint("BOTTOMRIGHT",-44,55)
        local child = CreateFrame("Frame",nil,scroll);child:SetSize(590,600);scroll:SetScrollChild(child)
        local body = child:CreateFontString(nil,"OVERLAY","GameFontHighlight")
        body:SetPoint("TOPLEFT");body:SetWidth(590);body:SetJustifyH("LEFT");body:SetSpacing(4)
        frame.kind = "items"
        local function refresh(kind)
            frame.kind = kind or frame.kind
            body:SetText(FAI.CatalogLines(frame.kind,input:GetText()))
            child:SetHeight(math.max(400,body:GetStringHeight()+20));scroll:SetVerticalScroll(0)
        end
        for i, spec in ipairs({{"items","查物品"},{"recipes","查配方"}}) do
            local button = CreateFrame("Button",nil,frame,"UIPanelButtonTemplate")
            button:SetSize(112,28);button:SetPoint("TOPLEFT",370+(i-1)*120,-88);button:SetText(spec[2])
            button:SetScript("OnClick",function()refresh(spec[1])end)
        end
        input:SetScript("OnEnterPressed",function(self)self:ClearFocus();refresh()end)
        input:SetScript("OnEscapePressed",function(self)self:ClearFocus()end)
        local close = CreateFrame("Button",nil,frame,"UIPanelButtonTemplate")
        close:SetSize(80,28);close:SetPoint("BOTTOMRIGHT",-24,18);close:SetText("关闭")
        close:SetScript("OnClick",function()frame:Hide()end)
        local note = frame:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
        note:SetPoint("BOTTOMLEFT",24,25);note:SetText("来源：wuxianwow.com · 资料查询不代表拥有物品或学会配方")
        if UISpecialFrames then table.insert(UISpecialFrames,"ForeverAICatalogPanel") end
        frame.Refresh = refresh
        FAI.catalogPanel = frame
    end
    local version = status.matches == true and "版本一致" or status.matches == false and "客户端版本不同，需核实" or "客户端版本未检测"
    FAI.catalogPanel.meta:SetText(status.item_count .. " 件物品 · " .. status.recipe_count .. " 条配方 · " .. plain(status.build) .. " · " .. version)
    FAI.catalogPanel.Refresh(); FAI.catalogPanel:Show()
end
