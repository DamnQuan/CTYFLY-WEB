<#
.SYNOPSIS
  安装 / 更新 AIRAC 数据，nd.db3 + cycle 元数据到 test 和/或主站。

.DESCRIPTION
  站规：默认只装 test，装主站必须显式 -Target main / both。

  为什么需要这个脚本，每一步都是真实踩过的坑，细节见 install-airdata.sh 头部：
   1. sidecar 全局只有一个实例监听 127.0.0.1:4173，由「先启动的那个后端」拉起，两个环境共用。
      实测证据：cts 在跑时 /api/status 返回
      database=/opt/ctyfly/backend/navdata-planner/Navdata/nd.db3 —— 即 test 的规划也读主站数据。
      ⇒ 两环境必须同 cycle，且重启顺序固定「先主站、后 test」。
   2. 不能带 nd.db3-shm / nd.db3-wal 过去，别处的 SQLite WAL 副产物会锁表或报损坏。
   3. 不要用 md5 判断数据一致性，SQLite 页布局变化必然不同，会误报漂移；
      用 cycle_info.txt 与 config 表的 CycleName 比对。
   4. 换数据必须在服务停止时做，否则 sidecar 持旧句柄；校验读库用只读打开，避免污染属主。

.PARAMETER Source
  新 cycle 的 Navdata 目录，含 nd.db3 / cycle_info.txt / cycle.json。
.PARAMETER Target
  test，默认| main | both。
.PARAMETER Force
  目标已是同 cycle 也强制重装。
.PARAMETER SkipServiceRestart
  只换文件、不重启服务，排障用；换完不会生效。

.EXAMPLE
  # 只装 test，默认，主站不动
  .\install-airdata.ps1 -Source "D:\BaiduNetdiskDownload\Navigraph_AIRAC_Cycle_2610\Navdata"

.EXAMPLE
  # 两站一起装，推荐：同 cycle + 先主站后 test 的顺序由脚本保证
  .\install-airdata.ps1 -Source "D:\BaiduNetdiskDownload\Navigraph_AIRAC_Cycle_2610\Navdata" -Target both
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Source,
  [ValidateSet('test', 'main', 'both')][string]$Target = 'test',
  [switch]$Force,
  [switch]$SkipServiceRestart
)

$ErrorActionPreference = 'Stop'
$Server = 'root@YOUR_SERVER_IP'
$Here = $PSScriptRoot

function Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }
function Assert-Exit($what) {
  if ($LASTEXITCODE -ne 0) { Write-Host "✗ $what 失败（exit $LASTEXITCODE）" -ForegroundColor Red; exit 1 }
}

Step '校验本地数据源'
$srcPath = (Resolve-Path $Source).Path
foreach ($f in @('nd.db3', 'cycle_info.txt', 'cycle.json')) {
  if (-not (Test-Path (Join-Path $srcPath $f))) { Write-Host "✗ 源目录缺少 $f：$srcPath" -ForegroundColor Red; exit 1 }
}
$cycleLine = (Get-Content (Join-Path $srcPath 'cycle_info.txt') | Select-String 'AIRAC cycle' | Select-Object -First 1).Line
$cycle = ($cycleLine -replace '[^0-9]', '')
if (-not $cycle) { Write-Host "✗ 读不出 cycle（cycle_info.txt：$cycleLine）" -ForegroundColor Red; exit 1 }
$dbSize = (Get-Item (Join-Path $srcPath 'nd.db3')).Length
Write-Host "  源 cycle = $cycle，nd.db3 = $([math]::Round($dbSize / 1MB, 1)) MB"
Write-Host "  有效期为下一 cycle 生效前的最后一天，以 config 表 CycleEndDate 为准"
if (Test-Path (Join-Path $srcPath 'nd.db3-wal')) { Write-Host '  （源目录里的 -wal/-shm 不会上传）' -ForegroundColor DarkGray }

Step 'SSH 预检'
ssh -o BatchMode=yes -o ConnectTimeout=12 $Server 'echo ok' | Out-Null
Assert-Exit 'SSH 预检'
Write-Host "  $Server 可达"

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$remoteTmp = "/tmp/airac-$stamp"

Step "上传数据到服务器 $remoteTmp（约 $([math]::Round($dbSize / 1MB, 1)) MB，视网络 1–3 分钟）"
ssh $Server "mkdir -p $remoteTmp"
Assert-Exit '创建暂存目录'
$sw = [Diagnostics.Stopwatch]::StartNew()
foreach ($f in @('nd.db3', 'cycle_info.txt', 'cycle.json')) {
  scp -q (Join-Path $srcPath $f) "${Server}:$remoteTmp/"
  Assert-Exit "上传 $f"
  Write-Host "  ✓ $f"
}
$sw.Stop()
Write-Host "  上传用时 $([math]::Round($sw.Elapsed.TotalSeconds, 1))s"

Step '上传换装 worker'
scp -q (Join-Path $Here 'install-airdata.sh') "${Server}:/tmp/install-airdata-$stamp.sh"
Assert-Exit '上传 worker'

Step "换装（Target=$Target）"
$forceArg = if ($Force) { '1' } else { '0' }
$skipArg = if ($SkipServiceRestart) { '1' } else { '0' }
# 远程命令一律走脚本文件：PowerShell 会吃掉内联 ssh 命令里的引号与管道
ssh $Server "sed -i 's/\r$//' /tmp/install-airdata-$stamp.sh && bash /tmp/install-airdata-$stamp.sh $remoteTmp $cycle $stamp $forceArg $Target $skipArg"
$workerExit = $LASTEXITCODE

Step '清理服务器临时文件'
ssh $Server "rm -rf $remoteTmp /tmp/install-airdata-$stamp.sh"

if ($workerExit -ne 0) { Write-Host "✗ worker 退出码 $workerExit，请查看上面的输出" -ForegroundColor Red; exit $workerExit }
Write-Host "`n完成。回滚方式：把对应环境的 Navdata-bak-<旧cycle>-$stamp 改回 Navdata，再 systemctl restart 对应服务。" -ForegroundColor Green
if ($Target -eq 'test') { Write-Host '提示：只装了 test。sidecar 两站共用，若要真正切到新 cycle，主站也要装（-Target both）。' -ForegroundColor Yellow }
