# 启动或重建服务（Windows PowerShell）。输出含访问口令，请勿转发。
# 用法：powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location $PSScriptRoot

if (-not $env:TG_FEED_LAN_IP) {
    $route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric | Select-Object -First 1
    if ($route) {
        $env:TG_FEED_LAN_IP = Get-NetIPAddress -InterfaceIndex $route.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty IPAddress
    }
}

New-Item -ItemType Directory -Force -Path data | Out-Null
docker compose up -d --build --wait --wait-timeout 90
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$key = (Get-Content -Raw data/access_token).Trim()
Write-Host "电脑访问：http://127.0.0.1:8978/?k=$key"
if ($env:TG_FEED_LAN_IP) {
    Write-Host "手机 / 平板（同一 Wi-Fi）：http://$($env:TG_FEED_LAN_IP):8978/?k=$key"
}
Write-Host '以上链接包含访问口令，请勿转发。停止：.\stop.ps1'
