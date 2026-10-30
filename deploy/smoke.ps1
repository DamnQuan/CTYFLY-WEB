<#
全站冒烟入口，逐路由检查白屏、JS 异常、5xx 与登录态。

用法：
    powershell -NoProfile -File deploy\smoke.ps1 -TokenFile .audit-tmp\test-admin-token.txt
    powershell -NoProfile -File deploy\smoke.ps1 -BaseUrl https://ccflysim.cn -TokenFile .audit-tmp\prod-admin-token.txt
    powershell -NoProfile -File deploy\smoke.ps1 -TokenFile token.txt -Browser "C:\Program Files\Google\Chrome\Application\chrome.exe"

说明：
- 首次运行会在 deploy\smoke 下安装 playwright-core，需要能访问 npm 源
- 浏览器默认自动探测本机 Edge 或 Chrome，也可以用 -Browser 显式指定
- 令牌必须是管理员账号，后台页面需要它才能通过守卫
- 报告与截图默认写到系统临时目录的 ctyfly-smoke，用 -Out 可改到固定目录
#>
param(
    [string]$BaseUrl = 'https://test.ccflysim.cn',
    [Parameter(Mandatory = $true)][string]$TokenFile,
    [string]$Browser = '',
    [string]$Out = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$smokeDir = Join-Path $PSScriptRoot 'smoke'

if (-not (Test-Path (Join-Path $smokeDir 'node_modules\playwright-core'))) {
    Write-Host '首次运行，正在安装 playwright-core ...' -ForegroundColor Cyan
    npm install --prefix $smokeDir --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'playwright-core 安装失败' }
}

if (-not (Test-Path $TokenFile)) { throw "令牌文件不存在: $TokenFile" }

$env:SMOKE_BASE = $BaseUrl
$env:SMOKE_TOKEN_FILE = (Resolve-Path $TokenFile).Path
if ($Browser) { $env:SMOKE_BROWSER = $Browser }
if ($Out) { $env:SMOKE_OUT = [IO.Path]::GetFullPath($Out) }

Push-Location $smokeDir
try {
    node smoke.js
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
