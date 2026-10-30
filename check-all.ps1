<#
一键跑完所有工程化门禁，与 CI 完全同一条命令链

用法：
    powershell -NoProfile -File .\check-all.ps1 # 全部
    powershell -NoProfile -File .\check-all.ps1 -Backend # 只跑后端
    powershell -NoProfile -File .\check-all.ps1 -Frontend # 只跑前端
    powershell -NoProfile -File .\check-all.ps1 -Smoke -SmokeTokenFile .audit-tmp\test-admin-token.txt
        在门禁之后追加全站冒烟，默认打测试站，可用 -SmokeBase 改地址

说明，写给接手人：
- 后端依赖：pip install -r backend/requirements.lock -r backend/requirements-dev.txt
  lock 是「可安装的精确锁」，与生产同版本；requirements.snapshot.txt 只是环境基线快照
- 前端依赖：cd frontend; npm ci
- 测试用临时 SQLite 库，**绝不碰 backend/data/ctyfly.db**，见 tests/conftest.py
- 冒烟需要管理员令牌与本机 Chromium 内核浏览器，见 deploy/smoke/README.md
- CI，.github/workflows/ci.yml 跑的就是下面这几步；本地先绿再推，能省一轮往返
#>
param(
    [switch]$Backend,
    [switch]$Frontend,
    [switch]$Smoke,
    [string]$SmokeBase = 'https://test.ccflysim.cn',
    [string]$SmokeTokenFile = ''
)
$ErrorActionPreference = 'Continue'
if (-not $Backend -and -not $Frontend) { $Backend = $true; $Frontend = $true }

$root = $PSScriptRoot
$results = [System.Collections.Generic.List[object]]::new()

function Run-Gate {
    param([string]$Name, [string]$WorkDir, [string]$Command)
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    Push-Location (Join-Path $root $WorkDir)
    try {
        $out = Invoke-Expression $Command 2>&1 | Out-String
        $code = $LASTEXITCODE
        $tail = ($out.Trim() -split "`n" | Select-Object -Last 2) -join ' | '
        Write-Host "  $tail"
        $results.Add([pscustomobject]@{ 门禁 = $Name; 结果 = $(if ($code -eq 0) { 'PASS' } else { "FAIL($code)" }) })
        return ($code -eq 0)
    } finally { Pop-Location }
}

$ok = $true
if ($Backend) {
    if (-not (Run-Gate -Name '后端 ruff'      -WorkDir 'backend' -Command 'python -m ruff check .')) { $ok = $false }
    if (-not (Run-Gate -Name '后端 pytest'    -WorkDir 'backend' -Command 'python -m pytest -q'))     { $ok = $false }
}
if ($Frontend) {
    if (-not (Run-Gate -Name '桌宠素材校验'  -WorkDir 'frontend' -Command 'npm run check:pet'))       { $ok = $false }
    if (-not (Run-Gate -Name '前端 ESLint'    -WorkDir 'frontend' -Command 'npm run lint'))            { $ok = $false }
    if (-not (Run-Gate -Name '前端逻辑测试'   -WorkDir 'frontend' -Command 'npm run test'))            { $ok = $false }
    if (-not (Run-Gate -Name '前端构建'       -WorkDir 'frontend' -Command 'npm run build'))           { $ok = $false }
}

if ($Smoke) {
    Write-Host "`n=== 全站冒烟 ===" -ForegroundColor Cyan
    if (-not $SmokeTokenFile -or -not (Test-Path $SmokeTokenFile)) {
        Write-Host '  失败：需要 -SmokeTokenFile 指向有效的管理员令牌文件' -ForegroundColor Red
        $results.Add([pscustomobject]@{ 门禁 = '全站冒烟'; 结果 = 'FAIL' })
        $ok = $false
    } else {
        $smokeScript = Join-Path $root 'deploy\smoke.ps1'
        $tokenPath = (Resolve-Path $SmokeTokenFile).Path
        $out = & powershell -NoProfile -File $smokeScript -BaseUrl $SmokeBase -TokenFile $tokenPath 2>&1 | Out-String
        $code = $LASTEXITCODE
        $tail = ($out.Trim() -split "`n" | Select-Object -Last 2) -join ' | '
        Write-Host "  $tail"
        $results.Add([pscustomobject]@{ 门禁 = '全站冒烟'; 结果 = $(if ($code -eq 0) { 'PASS' } else { "FAIL($code)" }) })
        if ($code -ne 0) { $ok = $false }
    }
}

Write-Host "`n=== 汇总 ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize | Out-String | Write-Host
if ($ok) {
    Write-Host "全部通过 ✓" -ForegroundColor Green
    if (-not $Smoke) {
        Write-Host "提醒：门禁只证明「代码可运行、测试通过」。上主站前建议再跑一次全站冒烟："
        Write-Host "      powershell -NoProfile -File .\check-all.ps1 -Smoke -SmokeTokenFile <令牌文件>"
    }
    exit 0
} else {
    Write-Host "有门禁未通过 ✗" -ForegroundColor Red
    exit 1
}
