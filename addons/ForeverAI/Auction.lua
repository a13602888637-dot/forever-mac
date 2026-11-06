-- Passive observations only. No queries, scans, bids, purchases, or seller identities.
local FAI = _G.ForeverAI
FAI.marketQuotes = {}

local function number(value)
    return FAI.Public(value) and type(value) == "number" and value == value and value >= 0 and value < 1e14
end

local function remember(id, copper, source, basis)
    if not number(id) or id < 1 or not number(copper) or copper % 1 ~= 0 then return end
    local previous = FAI.marketQuotes[id]
    local now = time()
    if previous and previous.observed_at == now and previous.copper <= copper then return end
    FAI.marketQuotes[id] = { item_id = id, copper = copper, observed_at = now, source = source, basis = basis }
end

function FAI.ObserveCommodity(itemID)
    if not number(itemID) then return end
    local values = FAI.Call("C_AuctionHouse.GetNumCommoditySearchResults", itemID)
    if not values or not number(values[1]) then return end
    local lowest
    for i = 1, math.min(values[1], 500) do
        local result = FAI.Call("C_AuctionHouse.GetCommoditySearchResultInfo", itemID, i)
        local info = result and result[1]
        if type(info) == "table" and FAI.Public(info) and number(info.unitPrice) and
           number(info.quantity) and info.quantity > 0 then
            if not lowest or info.unitPrice < lowest then lowest = info.unitPrice end
        end
    end
    if lowest then remember(itemID, lowest, "game_commodity_search", "unit_price") end
end

function FAI.ObserveItems(itemKey)
    if type(itemKey) ~= "table" or not FAI.Public(itemKey) or not number(itemKey.itemID) then return end
    local values = FAI.Call("C_AuctionHouse.GetNumItemSearchResults", itemKey)
    if not values or not number(values[1]) then return end
    local lowest
    for i = 1, math.min(values[1], 500) do
        local result = FAI.Call("C_AuctionHouse.GetItemSearchResultInfo", itemKey, i)
        local info = result and result[1]
        if type(info) == "table" and FAI.Public(info) and number(info.buyoutAmount) and info.buyoutAmount > 0 and
           number(info.quantity) and info.quantity > 0 then
            local unit = math.ceil(info.buyoutAmount / info.quantity)
            if not lowest or unit < lowest then lowest = unit end
        end
    end
    if lowest then remember(itemKey.itemID, lowest, "game_item_search", "rounded_listing_unit_price") end
end

function FAI.GetObservedQuotes()
    local result = FAI.Array()
    for _, quote in pairs(FAI.marketQuotes) do
        result[#result + 1] = quote
        if #result >= 2000 then break end
    end
    table.sort(result, function(a, b) return a.item_id < b.item_id end)
    if #result == 0 then return FAI.Missing("auction_quotes", "no_passive_auction_observations") end
    return result
end
