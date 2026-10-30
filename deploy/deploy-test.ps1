#!/usr/bin/env pwsh
# CTYFLY 测试环境部署，test.ccflysim.cn = 独立代码/数据库，主站零影响
# 用法: powershell -File deploy\deploy-test.ps1 [-Frontend|-Backend]，缺省两者都发
param([switch]$Frontend, [switch]$Backend)
if (-not $Frontend -and -not $Backend) { $Frontend = $true; $Backend = $true }
$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Server = 'root@YOUR_SERVER_IP'
$RemoteRoot = '/opt/ctyfly-test'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
function Step($t) { Write-Host "== $t ==" -ForegroundColor Cyan }
function Assert-Exit($t) { if ($LASTEXITCODE -ne 0) { Write-Host "✗ ${t} 失败（exit=$LASTEXITCODE），中止。" -ForegroundColor Red; exit $LASTEXITCODE } }

ssh -4 -o ConnectTimeout=10 -o BatchMode=yes $Server 'echo ok' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host '✗ SSH 预检失败，服务器不可达。' -ForegroundColor Red; exit 1 }

if ($Frontend) {
  Step '前端构建 (npm run build)'
  Push-Location (Join-Path $Root 'frontend'); npm run build; Assert-Exit 'npm run build'; Pop-Location
  Step '前端打包上传'
  $TarF = Join-Path $env:TEMP 'ctyfly-test-dist.tar.gz'
  tar -czf $TarF -C (Join-Path $Root 'frontend') dist
  Assert-Exit '打包 dist'
  scp -4 -q $TarF "${Server}:/tmp/ctyfly-test-dist.tar.gz"; Assert-Exit '上传 dist'
  Step '服务器端原子换目录'
  ssh -4 -o BatchMode=yes $Server ("set -e; cd $RemoteRoot/frontend && " +
    "rm -rf dist.new dist-bak && mkdir dist.new && " +
    "tar -xzf /tmp/ctyfly-test-dist.tar.gz -C dist.new --strip-components=1 && " +
    "rm -f /tmp/ctyfly-test-dist.tar.gz && " +
    "rm -rf dist-bak && mv dist dist-bak && mv dist.new dist && " +
    "chown -R ctyfly:ctyfly dist")
  Assert-Exit '服务器端换目录'
  Write-Host '  测试环境前端已更新'
}

if ($Backend) {
  Step '后端打包上传'
  $TarB = Join-Path $env:TEMP 'ctyfly-test-backend.tar.gz'
  tar -czf $TarB -C (Join-Path $Root 'backend') app
  Assert-Exit '打包 backend/app'
  scp -4 -q $TarB "${Server}:/tmp/ctyfly-test-backend.tar.gz"; Assert-Exit '上传 backend/app'
  Step 'sidecar 代码同步（navdata-planner）'
  # 同 deploy.ps1：sidecar 不在 app 包里；后端会自己 spawn 它，routers/navdata.py，
  # systemd 重启 ctyfly-test 时一并重建，所以只需同步代码。AIRAC 的 nd.db3 不入包。
  $TarN = Join-Path $env:TEMP 'ctyfly-test-navdata.tar.gz'
  tar -czf $TarN -C (Join-Path $Root 'backend') `
      --exclude='navdata-planner/Navdata/*.db3*' --exclude='navdata-planner/node_modules' `
      navdata-planner
  Assert-Exit '打包 navdata-planner'
  scp -4 -q $TarN "${Server}:/tmp/ctyfly-test-navdata.tar.gz"; Assert-Exit '上传 navdata-planner'
  ssh -4 -o BatchMode=yes $Server ("set -e; cd $RemoteRoot/backend && " +
    "mkdir -p navdata-planner && tar -xzf /tmp/ctyfly-test-navdata.tar.gz && " +
    "rm -f /tmp/ctyfly-test-navdata.tar.gz && chown -R ctyfly:ctyfly navdata-planner && " +
    "test -f navdata-planner/server.js")
  Assert-Exit '同步 navdata-planner'

  Step 'AIRAC 数据就绪检查（test 环境）'
  # navdistance.py 直接读 NAVDATA_SIDECAR_DIR/Navdata/nd.db3 算距离，缺文件不会报错、
  # 只会让 distance_nm 静默为 NULL，2026-10-05 踩过；这里缺就自动从主站那份同源数据
  # 在服务器内部 cp，110MB 同盘复制，秒级，不占上行带宽。
  $exists = ssh -4 -o BatchMode=yes $Server "test -f $RemoteRoot/backend/navdata-planner/Navdata/nd.db3 && echo yes || echo no"
  if ("$exists".Trim() -ne 'yes') {
    Write-Host '  测试环境缺 AIRAC nd.db3，从主站同源数据复制…' -ForegroundColor Yellow
    ssh -4 -o BatchMode=yes $Server ("set -e; src=/opt/ctyfly/backend/navdata-planner/Navdata/nd.db3; " +
      "dst=$RemoteRoot/backend/navdata-planner/Navdata/nd.db3; " +
      "test -f `$src || { echo '主站也没有 AIRAC，无法复制'; exit 1; }; " +
      "mkdir -p `$(dirname `$dst) && cp `$src `$dst && " +
      "cp -f `$(dirname `$src)/cycle_info.txt `$(dirname `$dst)/ 2>/dev/null || true; " +
      "cp -f `$(dirname `$src)/cycle.json `$(dirname `$dst)/ 2>/dev/null || true; " +
      "chown -R ctyfly:ctyfly $RemoteRoot/backend/navdata-planner && " +
      "ls -l `$dst")
    Assert-Exit '复制 AIRAC 数据'
  } else {
    # 不能用 md5 比 AIRAC：SQLite 的 backup/cp 产物页布局与原文件不同，md5 必然不同
    #2026-10-05 因此误报过一次。改比 cycle 元数据文件 + 文件尺寸，二者都不需要
    # 在 SQL 里转义引号，最省事也够用，cycle_info.txt 写明 AIRAC cycle 与有效期。
    $cmp = ssh -4 -o BatchMode=yes $Server ("cmp -s /opt/ctyfly/backend/navdata-planner/Navdata/cycle_info.txt " +
      "$RemoteRoot/backend/navdata-planner/Navdata/cycle_info.txt && echo same || echo diff")
    $cycle = ssh -4 -o BatchMode=yes $Server "head -3 /opt/ctyfly/backend/navdata-planner/Navdata/cycle_info.txt | tr '\n' ' '"
    if ("$cmp".Trim() -eq 'same') {
      Write-Host "  AIRAC 与主站同 cycle：$("$cycle".Trim())"
    } elseif ("$cmp".Trim() -eq 'diff') {
      Write-Host "  ⚠ 测试环境 AIRAC cycle 与主站不一致（主站：$("$cycle".Trim())）" -ForegroundColor Yellow
      Write-Host '    如需对齐：删掉测试环境那份 nd.db3/cycle_info.txt，重跑本脚本会自动从主站复制。' -ForegroundColor Yellow
    } else {
      Write-Host '  ⚠ 未找到 cycle_info.txt（老数据没有该元数据文件），无法比对 cycle；' -ForegroundColor Yellow
      Write-Host '    至少确认两侧 nd.db3 尺寸一致，必要时重新从主站复制 AIRAC。' -ForegroundColor Yellow
    }
    $sizes = ssh -4 -o BatchMode=yes $Server ("stat -c %s /opt/ctyfly/backend/navdata-planner/Navdata/nd.db3; " +
      "stat -c %s $RemoteRoot/backend/navdata-planner/Navdata/nd.db3")
    $sz = @("$sizes".Trim() -split "\s+")
    if ($sz.Count -ge 2 -and $sz[0] -ne $sz[1]) {
      Write-Host "  ⚠ 两侧 nd.db3 尺寸不同（主站 $($sz[0]) / 测试 $($sz[1])）——建议核对 AIRAC" -ForegroundColor Yellow
    }
  }

  Step '服务器端原子解包 + 重启 ctyfly-test'
  ssh -4 -o BatchMode=yes $Server ("set -e; cd $RemoteRoot/backend && " +
    "rm -rf app.new app-bak && mkdir app.new && " +
    "tar -xzf /tmp/ctyfly-test-backend.tar.gz -C app.new --strip-components=1 && " +
    "rm -f /tmp/ctyfly-test-backend.tar.gz && " +
    "find app.new -name __pycache__ -type d -exec rm -rf {} + && " +
    "rm -rf app-bak && mv app app-bak && mv app.new app && " +
    "chown -R ctyfly:ctyfly app && " +
    "systemctl restart ctyfly-test && sleep 4 && systemctl is-active ctyfly-test")
  Assert-Exit '后端原子解包/重启'
  Write-Host '  测试环境后端已更新'
}

Step '健康检查（test.ccflysim.cn）'
$health = ssh -4 -o BatchMode=yes $Server "curl -s --max-time 8 http://127.0.0.1:3016/api/health"
Write-Host "  后端 API: $health" -ForegroundColor Green
$code = ssh -4 -o BatchMode=yes $Server "curl -s -o /dev/null -w '%{http_code}' --max-time 8 --resolve test.ccflysim.cn:443:127.0.0.1 https://test.ccflysim.cn/"
Write-Host "  首页(HTTPS): HTTP $code" -ForegroundColor Green
Step '部署完成（仅测试环境，主站未动）'