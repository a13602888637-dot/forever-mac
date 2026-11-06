local FAI = _G.ForeverAI

function FAI.Export(silent)
    if type(InCombatLockdown) == "function" and InCombatLockdown() then
        if not silent then FAI.Message("请脱离战斗后再生成快照。已有快照未被覆盖。") end
        return false
    end
    if type(ForeverAICharDB) == "table" and ForeverAICharDB.schema_version and ForeverAICharDB.schema_version ~= 1 then
        if not silent then FAI.Message("已有存档版本不受支持，未覆盖。请先备份并更新插件。") end
        return false
    end
    local ok, result = pcall(function() return FAI.Encode(FAI.Collect()) end)
    if not ok then
        if not silent then FAI.Message("采集未完成，已有快照未被覆盖。可开启游戏脚本错误查看详情。") end
        return false
    end
    if #result > 1000000 then
        if not silent then FAI.Message("快照过大，未覆盖已有存档。") end
        return false
    end
    ForeverAICharDB = ForeverAICharDB or {}
    ForeverAICharDB.schema_version = 1
    ForeverAICharDB.snapshot_json = result
    if not silent then FAI.Message("快照已生成；请手动 /reload 或退出游戏写入磁盘。网页会自动导入。") end
    return true
end
