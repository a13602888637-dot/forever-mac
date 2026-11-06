-- No gameplay actions, network bridge, dynamic code loading, or protected calls.
local FAI = { version = "0.1.1", NULL = {}, capabilities = {}, unavailable = {} }
_G.ForeverAI = FAI
local unpack = unpack

function FAI.Array(t)
    return setmetatable(t or {}, { __json_array = true })
end

function FAI.Message(text)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffb9a0ffForever AI|r · " .. text) end
end

function FAI.Public(value)
    if type(issecretvalue) == "function" and issecretvalue(value) then return false end
    if type(canaccessvalue) == "function" and not canaccessvalue(value) then return false end
    if type(value) == "table" then
        if type(issecrettable) == "function" and issecrettable(value) then return false end
        if type(canaccesstable) == "function" and not canaccesstable(value) then return false end
    end
    return true
end

function FAI.Resolve(name)
    local value = _G
    for part in name:gmatch("[^.]+") do
        if type(value) ~= "table" then return nil end
        value = value[part]
    end
    if type(value) == "function" then return value end
end

local function pack(...) return { n = select("#", ...), ... } end
function FAI.Call(name, ...)
    local fn = FAI.Resolve(name)
    if not fn then
        FAI.capabilities[name] = { status = "unsupported", reason = "missing_api" }
        return nil, "unsupported:" .. name
    end
    local values = pack(pcall(fn, ...))
    if not values[1] then
        FAI.capabilities[name] = { status = "unavailable", reason = "api_call_failed" }
        return nil, "api_call_failed:" .. name
    end
    local out = { n = values.n - 1 }
    for i = 2, values.n do
        if not FAI.Public(values[i]) then
            FAI.capabilities[name] = { status = "restricted", reason = "secret_or_inaccessible" }
            return nil, "secret_or_inaccessible:" .. name
        end
        out[i - 1] = values[i]
    end
    FAI.capabilities[name] = { status = "runtime_verified", reason = FAI.NULL }
    return out
end

function FAI.Missing(path, reason)
    FAI.unavailable[path] = reason or "unavailable"
    return FAI.NULL
end

function FAI.Clean(value, path, depth)
    depth = depth or 0
    if not FAI.Public(value) then return FAI.Missing(path, "secret_or_inaccessible") end
    if value == nil then return FAI.Missing(path, "api_returned_nil") end
    if value == FAI.NULL then return value end
    local kind = type(value)
    if kind == "string" or kind == "boolean" then return value end
    if kind == "number" then
        if value ~= value or value == math.huge or value == -math.huge then
            return FAI.Missing(path, "non_finite_number")
        end
        return value
    end
    if kind == "table" and depth < 20 then
        local copy = {}
        for key, val in pairs(value) do
            if not FAI.Public(key) then return FAI.Missing(path, "secret_table_key") end
            if type(key) ~= "string" and type(key) ~= "number" then
                return FAI.Missing(path, "unsupported_table_key")
            end
            copy[key] = FAI.Clean(val, path .. "." .. tostring(key), depth + 1)
        end
        return copy
    end
    return FAI.Missing(path, "unsupported_value_type")
end

function FAI.Read(path, name, ...)
    local values, reason = FAI.Call(name, ...)
    if not values then return FAI.Missing(path, reason) end
    return FAI.Clean(values[1], path)
end

local function quote(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        return string.format("\\u%04x", string.byte(c))
    end) .. '"'
end

function FAI.Encode(value, depth)
    depth = depth or 0
    if depth > 32 then error("Snapshot too deep") end
    if not FAI.Public(value) then error("Secret value cannot be exported") end
    if value == FAI.NULL or value == nil then return "null" end
    local kind = type(value)
    if kind == "string" then return quote(value) end
    if kind == "boolean" then return value and "true" or "false" end
    if kind == "number" then
        if value ~= value or value == math.huge or value == -math.huge then error("Non-finite number") end
        return tostring(value)
    end
    if kind ~= "table" then error("Unsupported export type") end
    local parts, meta = {}, getmetatable(value)
    if meta and meta.__json_array then
        for i = 1, #value do parts[i] = FAI.Encode(value[i], depth + 1) end
        return "[" .. table.concat(parts, ",") .. "]"
    end
    local keys = {}
    for key in pairs(value) do
        if type(key) ~= "string" then error("JSON objects require string keys") end
        keys[#keys + 1] = key
    end
    table.sort(keys)
    for _, key in ipairs(keys) do
        parts[#parts + 1] = quote(key) .. ":" .. FAI.Encode(value[key], depth + 1)
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:SetScript("OnEvent", function(_, _, name)
    if name ~= "ForeverAI" then return end
    if type(ForeverAICharDB) ~= "table" then ForeverAICharDB = {} end
    -- Do not overwrite an unknown future schema or an existing snapshot at login.
    FAI.Message("自动记录已开启 · 手动 /reload 或退出游戏后，网页自动同步。/fai 打开助手。")
end)

SLASH_FOREVERAI1 = "/fai"
SlashCmdList.FOREVERAI = function(message)
    message = (message or ""):match("^%s*(.-)%s*$"):lower()
    if message == "export" then FAI.Export()
    elseif message == "catalog" or message == "db" then FAI.ShowCatalog()
    elseif message == "diagnose" then
        FAI.ShowPanel()
        FAI.Message("接口检测随导出执行；完整结果会保存到快照 capabilities。")
    else FAI.ShowPanel() end
end
