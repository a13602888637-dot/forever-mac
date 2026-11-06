local FAI = _G.ForeverAI
local NULL = FAI.NULL

local function field(t, key, path)
    if t == NULL or type(t) ~= "table" then return FAI.Missing(path, "parent_unavailable") end
    return FAI.Clean(t[key], path)
end

local function publicNumber(v) return FAI.Public(v) and type(v) == "number" end
local function publicString(v) return FAI.Public(v) and type(v) == "string" end

local function itemData(id, link, path)
    local item = { item_id = id, name = NULL, item_level = NULL, quality = NULL, stats = NULL, equip_location = NULL, count = 1 }
    if publicString(link) then
        local values, reason = FAI.Call("C_Item.GetItemInfo", link)
        if values then
            item.name = FAI.Clean(values[1], path .. ".name")
            item.quality = FAI.Clean(values[3], path .. ".quality")
            item.item_level = FAI.Clean(values[4], path .. ".item_level")
            item.equip_location = FAI.Clean(values[9], path .. ".equip_location")
        else
            FAI.Missing(path .. ".name", reason)
            FAI.Missing(path .. ".quality", reason)
            FAI.Missing(path .. ".item_level", reason)
            FAI.Missing(path .. ".equip_location", reason)
        end
        item.stats = FAI.Read(path .. ".stats", "C_Item.GetItemStats", link)
    else
        FAI.Missing(path, "item_link_not_cached")
    end
    return item
end

local function equipment()
    if not FAI.Resolve("GetInventoryItemID") then return FAI.Missing("equipment", "unsupported:GetInventoryItemID") end
    local items = FAI.Array()
    for slot = 1, 19 do
        local path = "equipment." .. (slot - 1)
        local values, reason = FAI.Call("GetInventoryItemID", "player", slot)
        local item
        if not values then
            item = itemData(NULL, nil, path)
            item.status = "unknown"
            FAI.Missing(path, reason)
        elseif values[1] == nil then
            item = { item_id = NULL, name = NULL, stats = NULL, quality = NULL, item_level = NULL, equip_location = NULL,
                     count = 0, status = "empty" }
            FAI.Missing(path, "empty_slot")
        else
            local id = FAI.Clean(values[1], path .. ".item_id")
            local links = FAI.Call("GetInventoryItemLink", "player", slot)
            item = itemData(id, links and links[1], path)
            item.status = "available"
        end
        item.slot = slot
        items[#items + 1] = item
    end
    return items
end

local function bags()
    local count = _G.NUM_BAG_SLOTS
    if not publicNumber(count) or count < 0 or count > 20 then
        return FAI.Missing("bags", "unsupported:NUM_BAG_SLOTS")
    end
    if not FAI.Resolve("C_Container.GetContainerNumSlots") or not FAI.Resolve("C_Container.GetContainerItemInfo") then
        FAI.Read("bags", "C_Container.GetContainerNumSlots", 0)
        return FAI.Missing("bags", "unsupported:container_api")
    end
    local items = FAI.Array()
    for bag = 0, count do
        local slots = FAI.Read("bags.scan." .. bag, "C_Container.GetContainerNumSlots", bag)
        if publicNumber(slots) then
            for slot = 1, math.min(slots, 200) do
                local values, reason = FAI.Call("C_Container.GetContainerItemInfo", bag, slot)
                if not values then return FAI.Missing("bags", reason) end
                local info = values[1]
                if type(info) == "table" then
                    local path = "bags." .. #items
                    info = FAI.Clean(info, path)
                    if info ~= NULL then
                        local id = field(info, "itemID", path .. ".item_id")
                        local item = itemData(id, info.hyperlink, path)
                        item.bag, item.bag_slot = bag, slot
                        if publicNumber(info.stackCount) then item.count = info.stackCount
                        else return FAI.Missing("bags", "item_count_unavailable") end
                        items[#items + 1] = item
                    end
                end
            end
        else return FAI.Missing("bags", "container_scan_incomplete") end
    end
    return items
end

local function professionsAndRecipes()
    local all = FAI.Read("professions", "C_TradeSkillUI.GetAllProfessionTradeSkillLines")
    local count = FAI.Read("professions", "C_SkillInfo.GetNumSkillLines")
    if type(all) ~= "table" or all == NULL or not publicNumber(count) then
        return FAI.Missing("professions", "profession_apis_unavailable"), FAI.Missing("recipes", "profession_apis_unavailable")
    end
    local ids, professions, recipes, seen = {}, FAI.Array(), FAI.Array(), {}
    for _, id in pairs(all) do if publicNumber(id) then ids[id] = true end end
    local incomplete = false
    for i = 1, math.min(count, 1000) do
        local skill = FAI.Read("professions.scan." .. i, "C_SkillInfo.GetSkillLineInfo", i)
        if type(skill) == "table" and skill ~= NULL and skill.isHeader == true and skill.isCollapsed == true then
            return FAI.Missing("professions", "skill_header_collapsed_open_and_retry"), FAI.Missing("recipes", "skill_header_collapsed_open_and_retry")
        end
        if type(skill) == "table" and skill ~= NULL and publicNumber(skill.skillID) and ids[skill.skillID] then
            local path = "professions." .. #professions
            professions[#professions + 1] = {
                skill_line_id = skill.skillID, name = field(skill, "name", path .. ".name"),
                rank = field(skill, "rank", path .. ".rank"), max_rank = field(skill, "maxRank", path .. ".max_rank")
            }
            local info = FAI.Read("recipes.scan.profession." .. i, "C_TradeSkillUI.GetProfessionInfoBySkillLineID", skill.skillID)
            local professionID = type(info) == "table" and info ~= NULL and info.professionID
            if not publicNumber(professionID) then incomplete = true
            else
                local known = FAI.Read("recipes.scan.spells." .. i, "C_TradeSkillUI.GetProfessionSpells", professionID, skill.skillID)
                if type(known) ~= "table" or known == NULL then incomplete = true
                else
                    for _, spellID in pairs(known) do
                        if publicNumber(spellID) and not seen[spellID] then
                            seen[spellID] = true
                            local recipeInfo = FAI.Read("recipes.scan.info." .. spellID, "C_TradeSkillUI.GetRecipeInfo", spellID)
                            local schematic = FAI.Read("recipes.scan.schematic." .. spellID, "C_TradeSkillUI.GetRecipeSchematic", spellID, false)
                            local rpath = "recipes." .. #recipes
                            local recipe = { recipe_id = spellID, name = NULL, output_item_id = NULL, output_quantity = NULL, reagents = NULL }
                            FAI.Missing(rpath, "recipe_details_unavailable_or_profession_window_closed")
                            if type(recipeInfo) == "table" and recipeInfo ~= NULL and publicString(recipeInfo.name) then recipe.name = recipeInfo.name end
                            if type(schematic) == "table" and schematic ~= NULL then
                                if publicNumber(schematic.outputItemID) then recipe.output_item_id = schematic.outputItemID end
                                if publicNumber(schematic.quantityMin) and publicNumber(schematic.quantityMax) and
                                   schematic.quantityMin == schematic.quantityMax and schematic.quantityMin > 0 then
                                    recipe.output_quantity = schematic.quantityMin
                                end
                                if type(schematic.reagentSlotSchematics) == "table" and schematic.reagentSlotSchematics ~= NULL then
                                    local reagents, valid = FAI.Array(), true
                                    for _, rslot in pairs(schematic.reagentSlotSchematics) do
                                        if type(rslot) ~= "table" or rslot == NULL then valid = false; break end
                                        if rslot.required ~= false then
                                            if type(rslot.reagents) ~= "table" or #rslot.reagents ~= 1 or
                                               not publicNumber(rslot.quantityRequired) then valid = false; break end
                                            local reagent = rslot.reagents[1]
                                            if type(reagent) ~= "table" or not publicNumber(reagent.itemID) then valid = false; break end
                                            reagents[#reagents + 1] = { item_id = reagent.itemID, quantity = rslot.quantityRequired }
                                        end
                                    end
                                    if valid and #reagents > 0 then recipe.reagents = reagents end
                                end
                            end
                            recipes[#recipes + 1] = recipe
                            if #recipes >= 10000 then incomplete = true; break end
                        end
                    end
                end
            end
        elseif skill == NULL then incomplete = true end
    end
    if incomplete then
        -- Do not present a partial enumeration as the full learned recipe collection.
        return professions, FAI.Missing("recipes", "recipe_enumeration_incomplete_open_profession_and_retry")
    end
    return professions, recipes
end

local function talents()
    local config = FAI.Read("talents", "C_ClassTalents.GetActiveConfigID")
    if not publicNumber(config) or config <= 0 then return FAI.Missing("talents", "active_config_unavailable") end
    local info = FAI.Read("talents", "C_Traits.GetConfigInfo", config)
    if type(info) ~= "table" or info == NULL then return FAI.Missing("talents", "config_unavailable") end
    local result = { config_id = config, name = field(info, "name", "talents.name"), nodes = FAI.Array() }
    if type(info.treeIDs) ~= "table" then result.nodes = FAI.Missing("talents.nodes", "tree_ids_unavailable"); return result end
    for _, tree in ipairs(info.treeIDs) do
        local nodes = FAI.Read("talents.nodes", "C_Traits.GetTreeNodes", tree)
        if type(nodes) ~= "table" or nodes == NULL then result.nodes = FAI.Missing("talents.nodes", "nodes_unavailable"); return result end
        for _, nodeID in ipairs(nodes) do
            local node = FAI.Read("talents.nodes.scan." .. nodeID, "C_Traits.GetNodeInfo", config, nodeID)
            local path = "talents.nodes." .. #result.nodes .. ".rank"
            local rank = type(node) == "table" and node ~= NULL and node.activeRank
            if not publicNumber(rank) then rank = FAI.Missing(path, "active_rank_unavailable") end
            result.nodes[#result.nodes + 1] = { node_id = nodeID, rank = rank }
        end
    end
    return result
end

local function quests()
    local count = FAI.Read("quests", "C_QuestLog.GetNumQuestLogEntries")
    if not publicNumber(count) then return FAI.Missing("quests", "quest_log_unavailable") end
    local result = FAI.Array()
    for i = 1, math.min(count, 1000) do
        local info = FAI.Read("quests.scan." .. i, "C_QuestLog.GetInfo", i)
        if type(info) ~= "table" or info == NULL then return FAI.Missing("quests", "quest_scan_incomplete") end
        if info.isHeader == false and publicNumber(info.questID) and info.questID > 0 then
            local path = "quests." .. #result
            local objectives = FAI.Read(path .. ".objectives", "C_QuestLog.GetQuestObjectives", info.questID)
            local texts = FAI.Array()
            if type(objectives) == "table" and objectives ~= NULL then
                for _, objective in ipairs(objectives) do
                    if type(objective) == "table" and publicString(objective.text) then texts[#texts + 1] = objective.text
                    else texts = FAI.Missing(path .. ".objectives", "objective_text_unavailable"); break end
                end
            else texts = NULL end
            result[#result + 1] = {
                quest_id = info.questID, title = field(info, "title", path .. ".title"),
                level = field(info, "level", path .. ".level"),
                is_complete = FAI.Read(path .. ".is_complete", "C_QuestLog.IsComplete", info.questID), objectives = texts
            }
        end
    end
    return result
end

function FAI.Collect()
    FAI.capabilities, FAI.unavailable = {}, {}
    local build, buildReason = FAI.Call("GetBuildInfo")
    local name = FAI.Read("character.name", "UnitName", "player")
    local realm = FAI.Read("character.realm", "GetRealmName")
    if not publicString(name) or name == "" or not publicString(realm) or realm == "" then
        error("角色身份不可读，未覆盖已有快照")
    end
    local classes, classReason = FAI.Call("UnitClass", "player")
    local races, raceReason = FAI.Call("UnitRace", "player")
    local spec = FAI.Read("character.specialization", "C_SpecializationInfo.GetSpecialization")
    local specName = NULL
    if publicNumber(spec) and spec > 0 then
        local details, reason = FAI.Call("C_SpecializationInfo.GetSpecializationInfo", spec)
        specName = details and FAI.Clean(details[2], "character.specialization") or FAI.Missing("character.specialization", reason)
    else FAI.Missing("character.specialization", "specialization_not_available_in_this_ruleset") end
    local professionList, recipeList = professionsAndRecipes()
    local snapshot = {
        schema_version = 1, addon_version = FAI.version, data_mode = "live",
        captured_at = time(),
        client = {
            version = build and FAI.Clean(build[1], "client.version") or FAI.Missing("client.version", buildReason),
            build = build and FAI.Clean(build[2], "client.build") or FAI.Missing("client.build", buildReason),
            interface = build and FAI.Clean(build[4], "client.interface") or FAI.Missing("client.interface", buildReason)
        },
        character = {
            name = name, realm = realm, level = FAI.Read("character.level", "UnitLevel", "player"),
            class_token = classes and FAI.Clean(classes[2], "character.class_token") or FAI.Missing("character.class_token", classReason),
            race_token = races and FAI.Clean(races[2], "character.race_token") or FAI.Missing("character.race_token", raceReason),
            specialization = specName, faction = FAI.Read("character.faction", "UnitFactionGroup", "player")
        },
        equipment = equipment(), bags = bags(), professions = professionList, recipes = recipeList,
        talents = talents(), quests = quests(),
        auction_quotes = FAI.GetObservedQuotes and FAI.GetObservedQuotes() or FAI.Missing("auction_quotes", "observer_not_loaded")
    }
    snapshot.capabilities, snapshot.unavailable = FAI.capabilities, FAI.unavailable
    return snapshot
end
