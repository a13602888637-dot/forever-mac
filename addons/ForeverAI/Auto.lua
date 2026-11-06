local FAI = _G.ForeverAI
local frame = CreateFrame("Frame")
local pending, combatPending = false, false

local function queue()
    if pending then return end
    if type(C_Timer) ~= "table" or type(C_Timer.After) ~= "function" then return end
    pending = true
    C_Timer.After(5, function()
        pending = false
        if type(InCombatLockdown) == "function" and InCombatLockdown() then combatPending = true; return end
        FAI.Export(true)
    end)
end

for _, event in ipairs({ "PLAYER_LOGIN", "PLAYER_LOGOUT", "PLAYER_LEVEL_UP", "PLAYER_EQUIPMENT_CHANGED",
    "BAG_UPDATE_DELAYED", "SKILL_LINES_CHANGED", "TRADE_SKILL_LIST_UPDATE", "QUEST_LOG_UPDATE",
    "PLAYER_TALENT_UPDATE", "PLAYER_REGEN_ENABLED", "COMMODITY_SEARCH_RESULTS_UPDATED", "ITEM_SEARCH_RESULTS_UPDATED" }) do
    pcall(frame.RegisterEvent, frame, event)
end

frame:SetScript("OnEvent", function(_, event, argument)
    if event == "PLAYER_LOGOUT" then FAI.Export(true); return end
    if event == "PLAYER_REGEN_ENABLED" then
        if combatPending then combatPending = false; queue() end
        return
    end
    if event == "COMMODITY_SEARCH_RESULTS_UPDATED" then FAI.ObserveCommodity(argument)
    elseif event == "ITEM_SEARCH_RESULTS_UPDATED" then FAI.ObserveItems(argument) end
    queue()
end)
