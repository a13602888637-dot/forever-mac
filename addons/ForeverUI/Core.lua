-- ForeverUI · Undead Arcane. All code is local; no remote execution or gameplay automation.
local ADDON = ...
local F = { version = "0.1.0", modules = {}, order = {}, movers = {}, native = {}, editing = false }
_G.ForeverUI = F
F.colors = {
    background = { 0.055, 0.043, 0.075, 0.95 }, panel = { 0.085, 0.063, 0.115, 0.96 },
    edge = { 0.31, 0.22, 0.40, 1 }, purple = { 0.67, 0.52, 0.92, 1 },
    bone = { 0.91, 0.87, 0.80, 1 }, muted = { 0.57, 0.49, 0.64, 1 },
    health = { 0.40, 0.29, 0.56, 1 }, power = { 0.40, 0.53, 0.75, 1 },
    mint = { 0.62, 0.74, 0.69, 1 }, amber = { 0.82, 0.71, 0.48, 1 },
}
local unpack = unpack
local function pack(...) return { n = select("#", ...), ... } end

-- Never branch, calculate, stringify, index, or persist an inaccessible value.
function F.Public(value)
    if type(issecretvalue) == "function" and issecretvalue(value) then return false end
    if type(canaccessvalue) == "function" and not canaccessvalue(value) then return false end
    if type(value) == "table" then
        if type(issecrettable) == "function" and issecrettable(value) then return false end
        if type(canaccesstable) == "function" and not canaccesstable(value) then return false end
    end
    return true
end
function F.Number(value, fallback)
    if F.Public(value) and type(value) == "number" and value == value and value > -math.huge and value < math.huge then return value end
    return fallback
end
function F.Text(value, fallback)
    if not F.Public(value) then return fallback end
    if type(value) == "string" then return value end
    if type(value) == "number" and F.Number(value) then return tostring(value) end
    return fallback
end
function F.Resolve(path)
    local obj = _G
    for part in path:gmatch("[^.]+") do
        if not F.Public(obj) or type(obj) ~= "table" then return nil end
        obj = obj[part]
    end
    if F.Public(obj) and type(obj) == "function" then return obj end
end
function F.Read(path, ...)
    local fn = F.Resolve(path)
    if not fn then return nil end
    local values = pack(pcall(fn, ...))
    if not values[1] then return nil end
    for i = 2, values.n do if not F.Public(values[i]) then return nil end end
    return unpack(values, 2, values.n)
end
function F.InCombat()
    local fn = F.Resolve("InCombatLockdown") or F.Resolve("C_RestrictedActions.InCombatLockdown")
    if not fn then return true end -- unknown protection state fails closed
    local ok, value = pcall(fn)
    if not ok or not F.Public(value) then return true end
    return value and true or false
end
function F.Message(message)
    if DEFAULT_CHAT_FRAME and F.Public(message) then DEFAULT_CHAT_FRAME:AddMessage("|cffab84ebForeverUI|r · " .. message) end
end
function F.Guard()
    if F.InCombat() then F.Message("战斗中不能调整布局或模块设置，请脱战后再操作。"); return false end
    return true
end
function F.TryEvent(frame, event)
    return pcall(frame.RegisterEvent, frame, event)
end
function F.Font(parent, size, color, align)
    local fs = parent:CreateFontString(nil, "OVERLAY")
    fs:SetFont(STANDARD_TEXT_FONT or "Fonts\\ARKai_T.ttf", size or 12, "")
    fs:SetTextColor(unpack(color or F.colors.bone))
    fs:SetJustifyH(align or "LEFT")
    fs:SetShadowColor(0, 0, 0, 0.85)
    fs:SetShadowOffset(1, -1)
    return fs
end
function F.Surface(frame, color, border)
    local bg = frame:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(frame)
    bg:SetColorTexture(unpack(color or F.colors.panel))
    local lines = {}
    for i = 1, 4 do
        local t = frame:CreateTexture(nil, "BORDER")
        t:SetColorTexture(unpack(border or F.colors.edge))
        if i == 1 then t:SetPoint("TOPLEFT"); t:SetPoint("TOPRIGHT"); t:SetHeight(1)
        elseif i == 2 then t:SetPoint("BOTTOMLEFT"); t:SetPoint("BOTTOMRIGHT"); t:SetHeight(1)
        elseif i == 3 then t:SetPoint("TOPLEFT"); t:SetPoint("BOTTOMLEFT"); t:SetWidth(1)
        else t:SetPoint("TOPRIGHT"); t:SetPoint("BOTTOMRIGHT"); t:SetWidth(1) end
        lines[i] = t
    end
    return { background = bg, lines = lines }
end
function F.Button(parent, text, width, callback)
    local b = CreateFrame("Button", nil, parent)
    b:SetSize(width or 120, 30)
    b.surface = F.Surface(b)
    b.text = F.Font(b, 11, F.colors.bone, "CENTER")
    b.text:SetPoint("CENTER"); b.text:SetText(text)
    b:SetScript("OnEnter", function() b.surface.background:SetColorTexture(0.18, 0.12, 0.25, 1) end)
    b:SetScript("OnLeave", function() b.surface.background:SetColorTexture(unpack(F.colors.panel)) end)
    b:SetScript("OnClick", callback)
    return b
end

-- Native state lives only in memory; SavedVariables contains our configuration, never native frame data.
function F.Remember(owner, frame)
    if not frame then return nil end
    F.native[owner] = F.native[owner] or {}
    local records = F.native[owner]
    for _, rec in ipairs(records) do if rec.frame == frame then return rec end end
    local rec = { frame = frame }
    records[#records + 1] = rec
    return rec
end
function F.RememberPoints(owner, frame)
    local rec = F.Remember(owner, frame)
    if rec.points then return rec end
    assert(frame.GetNumPoints and frame.GetPoint, "原生布局无法读取，未作改动")
    local ok, count = pcall(frame.GetNumPoints, frame)
    count = ok and F.Number(count) or nil
    assert(count and count >= 0 and count <= 64 and count == math.floor(count), "原生布局锚点数不可读，未作改动")
    local points = {}
    for i = 1, count do
        local values = pack(pcall(frame.GetPoint, frame, i))
        assert(values[1], "原生布局锚点读取失败，未作改动")
        local point = { n = values.n - 1 }
        for j = 2, values.n do
            assert(F.Public(values[j]), "原生布局包含受限锚点，未作改动")
            point[j - 1] = values[j]
        end
        assert(type(point[1]) == "string", "原生布局锚点不完整，未作改动")
        points[#points + 1] = point
    end
    local userPlaced
    if frame.IsUserPlaced and frame.SetUserPlaced then
        local readable, value = pcall(frame.IsUserPlaced, frame)
        assert(readable and F.Public(value) and type(value) == "boolean", "原生布局标记不可读，未作改动")
        userPlaced = value
    end
    -- Commit only after EVERY anchor and every property we will change is readable.
    rec.points, rec.userPlaced = points, userPlaced
    return rec
end
function F.Tint(owner, region, r, g, b, a)
    if not region or not region.GetVertexColor or not region.SetVertexColor then return end
    local rec = F.Remember(owner, region)
    if not rec.color then
        local values = pack(region:GetVertexColor())
        for i = 1, values.n do if not F.Public(values[i]) then return end end
        rec.color = values
    end
    region:SetVertexColor(r, g, b, a or 1)
end
function F.Alpha(owner, region, value)
    if not region or not region.SetAlpha or not region.GetAlpha then return end
    local rec = F.Remember(owner, region)
    if rec.alpha == nil then rec.alpha = F.Number(region:GetAlpha()) end
    if rec.alpha ~= nil then region:SetAlpha(value) end
end
function F.Crop(owner, texture)
    if not texture or not texture.GetTexCoord or not texture.SetTexCoord then return end
    local rec = F.Remember(owner, texture)
    if not rec.coords then
        local coords = pack(texture:GetTexCoord())
        for i = 1, coords.n do if not F.Public(coords[i]) then return end end
        rec.coords = coords
    end
    texture:SetTexCoord(0.07, 0.93, 0.07, 0.93)
end
function F.Reparent(owner, frame, parent)
    if not frame then return end
    local rec = F.Remember(owner, frame)
    if not rec.hasParent then
        local ok, original = pcall(frame.GetParent, frame)
        assert(ok and F.Public(original), "原生父框体不可读，未作改动")
        rec.parent, rec.hasParent = original, true
    end
    frame:SetParent(parent)
end
function F.HideNative(owner, frame)
    if not frame then return end
    if not F.hider then F.hider = CreateFrame("Frame", "ForeverUIHiddenParent", UIParent); F.hider:Hide() end
    F.Reparent(owner, frame, F.hider)
end
function F.RestoreNative(owner)
    local remaining = {}
    for _, rec in ipairs(F.native[owner] or {}) do
        local frame, failed = rec.frame, false
        local function restore(method, ...)
            if type(method) ~= "function" then failed = true; return false end
            local ok = pcall(method, frame, ...)
            if not ok then failed = true end
            return ok
        end
        if rec.hasParent then restore(frame.SetParent, rec.parent) end
        if rec.points then
            if restore(frame.ClearAllPoints) then
                for _, point in ipairs(rec.points) do restore(frame.SetPoint, unpack(point, 1, point.n)) end
            end
            if rec.userPlaced ~= nil then restore(frame.SetUserPlaced, rec.userPlaced) end
        end
        if rec.alpha ~= nil then restore(frame.SetAlpha, rec.alpha) end
        if rec.color then restore(frame.SetVertexColor, unpack(rec.color, 1, rec.color.n)) end
        if rec.coords then restore(frame.SetTexCoord, unpack(rec.coords, 1, rec.coords.n)) end
        if rec.font then restore(frame.SetFont, unpack(rec.font, 1, rec.font.n)) end
        if rec.textColor then restore(frame.SetTextColor, unpack(rec.textColor, 1, rec.textColor.n)) end
        if rec.fading ~= nil then restore(frame.SetFading, rec.fading) end
        if rec.timeVisible ~= nil then restore(frame.SetTimeVisible, rec.timeVisible) end
        if failed then remaining[#remaining + 1] = rec end
    end
    -- A failed restore retains its original state for a later retry; it is never reported as restored.
    F.native[owner] = remaining
    return #remaining == 0
end
function F.Place(key)
    local info = F.movers[key]
    if not info or not F.db or F.InCombat() then return end
    local pos = F.db.layout[key] or info.default
    info.frame:ClearAllPoints()
    info.frame:SetPoint(pos.point or "CENTER", UIParent, pos.relative or pos.point or "CENTER", pos.x or 0, pos.y or 0)
    for _, rec in ipairs(F.native[info.owner] or {}) do
        if rec.frame == info.frame and rec.points and rec.userPlaced ~= nil then info.frame:SetUserPlaced(true); break end
    end
end
function F.RegisterMover(owner, key, frame, label, default, width, height)
    local info = F.movers[key]
    if not info then
        info = { owner = owner, frame = frame, label = label, default = default, width = width, height = height }
        F.movers[key] = info
    else info.frame = frame end
    F.Place(key)
    return info
end
function F.ShowMover(info)
    local mover = info.mover
    if not mover then
        mover = CreateFrame("Frame", nil, UIParent)
        mover:SetFrameStrata("DIALOG"); mover:SetMovable(true); mover:EnableMouse(true); mover:RegisterForDrag("LeftButton")
        mover.surface = F.Surface(mover, { 0.26, 0.16, 0.38, 0.88 }, F.colors.purple)
        mover.label = F.Font(mover, 12, F.colors.bone, "CENTER"); mover.label:SetPoint("CENTER"); mover.label:SetText(info.label)
        mover:SetScript("OnDragStart", function(self) if not F.InCombat() then self:StartMoving() end end)
        mover:SetScript("OnDragStop", function(self)
            self:StopMovingOrSizing()
            if F.InCombat() then return end
            local x, y = self:GetCenter()
            local px, py = UIParent:GetCenter()
            x, y, px, py = F.Number(x), F.Number(y), F.Number(px), F.Number(py)
            if not x or not y or not px or not py then return end
            F.db.layout[info.key] = { point = "CENTER", relative = "CENTER", x = math.floor(x - px + 0.5), y = math.floor(y - py + 0.5) }
            F.Place(info.key)
        end)
        info.mover = mover
    end
    local frame = info.frame
    local x, y = frame:GetCenter()
    x, y = F.Number(x), F.Number(y)
    if not x or not y then return end
    if frame.GetEffectiveScale and UIParent.GetEffectiveScale then
        local scale, parentScale = F.Number(frame:GetEffectiveScale()), F.Number(UIParent:GetEffectiveScale())
        if not scale or not parentScale or parentScale <= 0 then return end
        x, y = x * scale / parentScale, y * scale / parentScale
    end
    mover:ClearAllPoints(); mover:SetPoint("CENTER", UIParent, "BOTTOMLEFT", x, y)
    mover:SetSize(info.width or F.Number(frame:GetWidth(), 180), info.height or math.max(F.Number(frame:GetHeight(), 40), 25))
    mover:Show()
end
function F.SetEdit(enabled)
    if enabled and not F.Guard() then return end
    if enabled and not F.db.enabled then F.Message("先在 /fui 中应用主题，再调整布局。"); return end
    F.editing = enabled and true or false
    for key, info in pairs(F.movers) do
        info.key = key
        if F.editing and F.modules[info.owner].active then F.ShowMover(info)
        elseif info.mover then info.mover:StopMovingOrSizing(); info.mover:Hide() end
    end
    if F.editing then F.Message("拖动紫色标签调整位置；再次 /fui edit 结束。进入战斗会取消编辑。"); end
end
function F.ResetLayout()
    if not F.Guard() then return end
    F.SetEdit(false); F.db.layout = {}
    if F.db.enabled then
        for key, info in pairs(F.movers) do if F.modules[info.owner].active then F.Place(key) end end
    end
    F.Message("当前角色布局已重置。")
end
function F.RegisterModule(id, title, description, module)
    module.id, module.title, module.description = id, title, description
    F.modules[id] = module; F.order[#F.order + 1] = id
end
function F.EnableModule(id)
    local m = F.modules[id]
    if m.active then return true end
    if m.restorePending then
        local disabled = pcall(m.Disable, m)
        local restored = F.RestoreNative(id)
        if not disabled or not restored then F.Message(m.title .. "恢复仍未完成，请 /reload 后再试。"); return false end
        m.restorePending = false
    end
    local ok, err = pcall(m.Enable, m)
    if ok then m.active = true; m.error = nil
    else
        local disabled = pcall(m.Disable, m)
        local restored = F.RestoreNative(id)
        m.active = false; m.error = F.Text(err, "接口不可用")
        m.restorePending = not disabled or not restored
        if m.restorePending then F.Message(m.title .. "恢复未完成，原状态已保留；请 /fui off 重试，或 /reload。")
        else F.Message(m.title .. "未能应用，已保留原生界面。") end
    end
    return ok
end
function F.DisableModule(id)
    local m = F.modules[id]
    local disabled = pcall(m.Disable, m)
    local restored = F.RestoreNative(id)
    m.active = false; m.restorePending = not disabled or not restored
    for _, info in pairs(F.movers) do if info.owner == id and info.mover then info.mover:Hide() end end
    return not m.restorePending
end
function F.ApplyProfile()
    if not F.Guard() then return false end
    F.SetEdit(false); F.db.enabled = true
    for _, id in ipairs(F.order) do
        if F.db.modules[id] then F.EnableModule(id) else F.DisableModule(id) end
    end
    if F.RefreshConfig then F.RefreshConfig() end
    local active, waiting = 0, 0
    for _, id in ipairs(F.order) do
        if F.modules[id].active then active = active + 1
        elseif F.db.modules[id] then waiting = waiting + 1 end
    end
    F.Message("亡灵奥术 · 已应用 " .. active .. " 个模块。" .. (waiting > 0 and (waiting .. " 个模块未就绪，详见 /fui。") or ""))
    return true
end
function F.RestoreAll()
    if not F.Guard() then return end
    F.SetEdit(false)
    local complete = true
    for i = #F.order, 1, -1 do if not F.DisableModule(F.order[i]) then complete = false end end
    F.db.enabled = false
    if F.RefreshConfig then F.RefreshConfig() end
    if complete then F.Message("已恢复原生界面，角色布局仍保留。")
    else F.Message("部分界面恢复未完成，原状态已保留。可 /fui off 重试；仍异常请 /reload。"); end
end
function F.ToggleModule(id, enabled)
    if not F.Guard() then if F.RefreshConfig then F.RefreshConfig() end; return end
    F.db.modules[id] = enabled and true or false
    if F.db.enabled then
        F.SetEdit(false)
        if enabled then F.EnableModule(id) else F.DisableModule(id) end
    end
    if F.RefreshConfig then F.RefreshConfig() end
end
function F.Initialize()
    if type(ForeverUICharDB) ~= "table" then ForeverUICharDB = {} end
    F.db = ForeverUICharDB
    if F.db.schema and F.db.schema ~= 1 then
        F.Message("角色配置来自其他版本，未修改。请保留配置并检查版本。")
        F.db = nil; return
    end
    F.db.schema = 1
    if type(F.db.layout) ~= "table" then F.db.layout = {} end
    if type(F.db.modules) ~= "table" then F.db.modules = {} end
    for _, id in ipairs(F.order) do if F.db.modules[id] == nil then F.db.modules[id] = true end end
    if F.db.enabled == nil then F.db.enabled = false end
end
local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED"); events:RegisterEvent("PLAYER_LOGIN"); events:RegisterEvent("PLAYER_REGEN_DISABLED")
events:SetScript("OnEvent", function(_, event, name)
    if event == "ADDON_LOADED" and name == "ForeverUI" then F.Initialize()
    elseif event == "PLAYER_LOGIN" and F.db then
        if F.db.enabled and not F.InCombat() then F.ApplyProfile() end
        F.Message("/fui 打开主题设置 · /fui edit 编辑布局 · /fui off 恢复原生。")
    elseif event == "PLAYER_REGEN_DISABLED" and F.editing then
        -- Only our unprotected ghost handles are hidden here. Protected positions are untouched.
        F.SetEdit(false)
    end
end)
SLASH_FOREVERUI1 = "/fui"
SlashCmdList.FOREVERUI = function(message)
    if not F.db then F.Message("配置尚未就绪。"); return end
    local command = (message or ""):match("^%s*(.-)%s*$"):lower()
    if command == "edit" then F.SetEdit(not F.editing)
    elseif command == "reset" then F.ResetLayout()
    elseif command == "off" or command == "restore" then F.RestoreAll()
    elseif command == "on" then F.ApplyProfile()
    elseif command == "bags" then
        if F.modules.bags.active then F.modules.bags:Toggle() else F.Message("请先在 /fui 中启用行囊模块。") end
    elseif F.ShowConfig then F.ShowConfig() end
end
