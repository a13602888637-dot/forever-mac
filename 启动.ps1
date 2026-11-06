$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    uv sync --extra dev
    if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }
    uv run python scripts/first_run.py @args
    if ($LASTEXITCODE -ne 0) { throw "服务未完成启动或运行" }
} finally {
    Pop-Location
}
