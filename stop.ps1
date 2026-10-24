# 停止服务并保留数据（Windows PowerShell）。
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose down
exit $LASTEXITCODE
