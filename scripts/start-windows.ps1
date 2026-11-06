$ErrorActionPreference = "Stop"
Push-Location (Join-Path $PSScriptRoot "..")
try {
    uv sync --extra dev
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }
    uv run foreverai serve @args
    if ($LASTEXITCODE -ne 0) { throw "服务未完成启动或运行" }
} finally {
    Pop-Location
}
