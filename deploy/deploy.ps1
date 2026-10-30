# CTYFLY 一键部署脚本，⚠️ 本脚本发的是**主站/生产** /opt/ctyfly；只发测试环境请用 deploy-test.ps1
#
# 站规，站长 2026-10-05 明确：默认只发 test；站长说「上主站」才跑本脚本。
#
# 用法，在仓库根目录或任意位置运行：
# powershell -File deploy\deploy.ps1 # 前端 + 后端 全量部署，默认
#   powershell -File deploy\deploy.ps1 -Frontend    # 只部署前端
#   powershell -File deploy\deploy.ps1 -Backend     # 只部署后端
#   powershell -File deploy\deploy.ps1 -SkipBuild   # 前端不再重新构建，直接上传现有 dist
# powershell -File deploy\deploy.ps1 -AllowDirty # 工作区有未提交改动时仍继续，默认中止
#
# 前置条件：
# - 本机已配置到 root@YOUR_SERVER_IP 的 SSH 免密登录，ssh root@YOUR_SERVER_IP echo ok 能通
#   - frontend\npm 可用
#
# 行为说明：
# - 部署前先做 SSH 连通性预检；工作区有未提交改动时默认中止，-AllowDirty 放行。
# 仓库根那份永不入库的未跟踪 *.pdf 调查报告已自动豁免，不算脏
#   - 前端：npm run build → 打包 dist → 上传 → 服务器先解包到 dist.new-<时间戳>，
# 成功后旧 dist 改名 dist-bak-<时间戳>、新目录原子改名为 dist，自动只保留最近 3 份备份
#   - 后端：打包 backend\app → 上传 → 服务器先解包到 app.new-<时间戳>，成功后旧 app
#           改名 app-bak-<时间戳>、新目录原子改名为 app → 清理 __pycache__ → systemctl restart ctyfly
#   - 任一服务器端步骤失败立即中止：旧版本原封不动，服务不重启
# - 结束后在服务器上做健康检查，/api/health 与首页状态码
#   - 回滚：脚本会打印本次备份目录名，出问题时在服务器上执行
#           前端: cd /opt/ctyfly/frontend && rm -rf dist && mv dist-bak-<时间戳> dist
#           后端: cd /opt/ctyfly/backend && rm -rf app && mv app-bak-<时间戳> app && systemctl restart ctyfly
param(
  [switch]$Frontend,
  [switch]$Backend,
  [switch]$SkipBuild,
  [switch]$AllowDirty,
  [string]$Server = 'root@YOUR_SERVER_IP',
  [string]$RemoteRoot = '/opt/ctyfly'
)

$ErrorActionPreference = 'Stop'
# 以脚本所在目录定位仓库根，本脚本在 deploy\ 下
$Root = Split-Path -Parent $PSScriptRoot
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$BackupName = $null

function Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Assert-Exit($step) {
  if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ $step 失败（exit=$LASTEXITCODE），部署中止。服务不受影响（旧版本仍在运行）。" -ForegroundColor Red
    exit $LASTEXITCODE
  }
}

# 不指定范围时默认两端都发
if (-not $Frontend -and -not $Backend) { $Frontend = $true; $Backend = $true }

# ---- 部署前检查 1：SSH 连通性预检，不通直接中止，避免上传一半才发现连不上----
Step 'SSH 预检'
ssh $Server 'echo ok' | Out-Null
Assert-Exit "SSH 预检 ($Server)"
Write-Host "  $Server 可达"

# ---- 部署前检查 2：工作区脏检查 ----
# 默认：有未提交改动就中止，防止「服务器上跑的版本和仓库里的对不上」。确认要带改动发布时加 -AllowDirty。
# 豁免：仓库根那份永不入库的未跟踪 *.pdf，调查报告不算脏，不影响判定。
Step '检查工作区'
# -c core.quotepath=false：中文文件名按原样输出，默认八进制转义+引号会破坏尾部匹配
$dirty = @(git -C $Root -c core.quotepath=false status --porcelain) |
    Where-Object { $_ -notmatch '^\?\?\s+.*\.pdf"?$' }
if ($dirty.Count -gt 0) {
  $dirty | ForEach-Object { Write-Host "  未提交: $_" -ForegroundColor Yellow }
  if (-not $AllowDirty) {
    Write-Host '✗ 工作区有未提交改动，默认中止部署（确认要带改动发布时加 -AllowDirty 重跑）。' -ForegroundColor Red
    Write-Host '  注：仓库根的未跟踪 *.pdf（永不入库的调查报告）已豁免，不影响本判定。'
    exit 1
  }
  Write-Host '  ⚠ 已指定 -AllowDirty，带着未提交改动继续部署（风险自担）。' -ForegroundColor Yellow
} else {
  Write-Host '  工作区干净（未跟踪的 *.pdf 已豁免）'
}

# ================= 前端 =================
if ($Frontend) {
  if (-not $SkipBuild) {
    Step '前端构建 (npm run build)'
    Push-Location (Join-Path $Root 'frontend')
    npm run build
    Assert-Exit 'npm run build'
    Pop-Location
  } else {
    Step '跳过构建（使用现有 dist）'
    if (-not (Test-Path (Join-Path $Root 'frontend\dist\index.html'))) {
      Write-Host '✗ dist\index.html 不存在，无法跳过构建。' -ForegroundColor Red
      exit 1
    }
  }

  Step '前端打包上传'
  $Tar = Join-Path $env:TEMP 'ctyfly-dist.tar.gz'
  # 注意：必须打包 dist 的「内容」，-C dist .，不能带上 dist 这一层目录，
  # 否则服务器解包后会变成 dist/dist/index.html，首页直接 403，这个坑踩过。
  tar -czf $Tar -C (Join-Path $Root 'frontend\dist') .
  Assert-Exit '打包 dist'
  # 自检：压缩包顶层必须直接有 index.html，全量扫描，不能只看前几行 —— index.html 往往排在后面
  $listing = tar -tzf $Tar
  if (-not ($listing | Where-Object { $_ -match '^\.?/?index\.html$' })) {
    Write-Host '✗ 压缩包结构不对（顶层没有 index.html），已中止。前几项：' -ForegroundColor Red
    $listing | Select-Object -First 6 | ForEach-Object { Write-Host "    $_" }
    exit 1
  }
  scp -q $Tar "${Server}:/tmp/ctyfly-dist.tar.gz"; Assert-Exit '上传 dist'
  scp -q (Join-Path $PSScriptRoot 'remote-swap.sh') "${Server}:/tmp/ctyfly-swap.sh"; Assert-Exit '上传换目录助手'

  Step '服务器端换目录（原子解包，旧版本自动备份）'
  # CRLF/BOM 兜底清理后执行，remote-swap.sh 内部：先解包到 dist.new-$Stamp，成功后才换名
  ssh $Server "sed -i 's/\r$//;s/^\xEF\xBB\xBF//' /tmp/ctyfly-swap.sh && bash /tmp/ctyfly-swap.sh $Stamp"
  Assert-Exit '服务器换目录'
  ssh $Server 'rm -f /tmp/ctyfly-swap.sh'

  $out = ssh $Server "ls -d $RemoteRoot/frontend/dist-bak-$Stamp 2>/dev/null || true"
  if ($out) { $script:BackupName = "dist-bak-$Stamp" }
  if (-not $BackupName) {
    Write-Host "✗ 未在服务器上确认备份目录 dist-bak-$Stamp，中止（请先排查服务器端输出再重试）。" -ForegroundColor Red
    exit 1
  }
}

# ================= 后端 =================
if ($Backend) {
  Step '后端打包上传'
  $TarB = Join-Path $env:TEMP 'ctyfly-backend.tar.gz'
  tar -czf $TarB -C (Join-Path $Root 'backend') app
  Assert-Exit '打包 backend/app'
  scp -q $TarB "${Server}:/tmp/ctyfly-backend.tar.gz"; Assert-Exit '上传 backend/app'

  Step 'sidecar 代码同步（navdata-planner）'
  # 为什么需要这一步：sidecar 不在 backend/app 里，deploy 的 app 包覆盖不到它，
  # 2026-10-05 就因为「仓库里 route-analyzer 早已修好、服务器上一直是旧版」排查了很久。
  # 为什么这里不需要单独重启 sidecar：后端进程自己 spawn 它
  #routers/navdata.py：subprocess.Popen ["node","server.js"], cwd=NAVDATA_SIDECAR_DIR，
  # 且 systemd 默认 KillMode=control-group 会随 ctyfly 重启一并杀掉子进程 ——
  # 所以下面的 systemctl restart ctyfly 会自动用新代码重建 sidecar。
  # Navdata/nd.db3，110MB AIRAC 属数据不入包，也不会被解包动作删除。
  $TarN = Join-Path $env:TEMP 'ctyfly-navdata.tar.gz'
  tar -czf $TarN -C (Join-Path $Root 'backend') `
      --exclude='navdata-planner/Navdata/*.db3*' --exclude='navdata-planner/node_modules' `
      navdata-planner
  Assert-Exit '打包 navdata-planner'
  scp -q $TarN "${Server}:/tmp/ctyfly-navdata.tar.gz"; Assert-Exit '上传 navdata-planner'
  ssh $Server "set -e; cd $RemoteRoot/backend && tar -xzf /tmp/ctyfly-navdata.tar.gz && rm -f /tmp/ctyfly-navdata.tar.gz && chown -R ctyfly:ctyfly navdata-planner && test -f navdata-planner/server.js"
  Assert-Exit '同步 navdata-planner'
  $airac = ssh $Server "test -f $RemoteRoot/backend/navdata-planner/Navdata/nd.db3 && echo yes || echo no"
  if ("$airac".Trim() -ne 'yes') {
    Write-Host "  ⚠ 未发现 AIRAC 数据 $RemoteRoot/backend/navdata-planner/Navdata/nd.db3" -ForegroundColor Yellow
    Write-Host "    航线 distance_nm 推导与航路规划会失败/为空——请按运维手册安装 AIRAC 后再发。" -ForegroundColor Yellow
  } else {
    Write-Host "  sidecar 代码已同步，AIRAC 数据在位"
  }

  Step '服务器端原子解包 + 重启 ctyfly'
  # 原子化流程，全用 && 串联，任一步失败即中止：旧 app 原封不动，服务不重启：
  # 1 解包到新目录 app.new-$Stamp，--strip-components=1 去掉包内顶层 app/ 这一层
  # 2 清理新目录里的 __pycache__
  # 3 旧 app 改名 app-bak-$Stamp，保留备份，出问题可用它回滚
  # 4 新目录原子改名为 app
  # 5 systemctl restart ctyfly
  $remote = "set -e; cd $RemoteRoot/backend && " +
    "rm -rf app.new-$Stamp app-bak-$Stamp && " +
    "mkdir app.new-$Stamp && " +
    "tar -xzf /tmp/ctyfly-backend.tar.gz -C app.new-$Stamp --strip-components=1 && " +
    "rm -f /tmp/ctyfly-backend.tar.gz && " +
    "find app.new-$Stamp -name __pycache__ -type d -exec rm -rf {} + && " +
    "mv app app-bak-$Stamp && " +
    "mv app.new-$Stamp app && " +
    "chown -R ctyfly:ctyfly app && " +
    "systemctl restart ctyfly && sleep 4 && systemctl is-active ctyfly"
  ssh $Server $remote
  if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ 后端原子解包/重启失败（exit=$LASTEXITCODE），部署中止。旧 app 原封不动，服务未重启。" -ForegroundColor Red
    exit $LASTEXITCODE
  }
  Write-Host "  本次后端备份: $RemoteRoot/backend/app-bak-$Stamp"
}

# ================= 健康检查 =================
Step '健康检查（在服务器上执行）'
$health = ssh $Server "curl -s --max-time 8 http://127.0.0.1:3015/api/health"
if ($health -match '"ok":true') {
  Write-Host "  后端 API: $health" -ForegroundColor Green
} else {
  Write-Host "  ✗ 后端健康检查未通过: $health" -ForegroundColor Red
  Write-Host "  查看日志: ssh $Server 'journalctl -u ctyfly -n 40 --no-pager'"
  if ($Backend) {
    Write-Host "  立即回滚: ssh $Server ""cd $RemoteRoot/backend && rm -rf app && mv app-bak-$Stamp app && systemctl restart ctyfly""" -ForegroundColor Yellow
  }
  exit 1
}
$page = ssh $Server "curl -s -o /dev/null -w '%{http_code}' --max-time 8 --resolve ccflysim.cn:443:127.0.0.1 https://ccflysim.cn/"
if ("$page".Trim() -ne '200') {
  Write-Host "  ✗ 首页返回 HTTP $page（应为 200）—— 前端可能没解包到正确位置。" -ForegroundColor Red
  if ($Frontend) {
    Write-Host "  立即回滚: ssh $Server ""cd $RemoteRoot/frontend && rm -rf dist && mv $BackupName dist""" -ForegroundColor Yellow
  }
  exit 1
}
Write-Host "  首页(HTTPS): HTTP $page" -ForegroundColor Green
# 以下页面只打印状态码供人工确认，不做断言、不影响退出码
foreach ($p in @('/privacy', '/login', '/register')) {
  $code = ssh $Server "curl -s -o /dev/null -w '%{http_code}' --max-time 8 --resolve ccflysim.cn:443:127.0.0.1 https://ccflysim.cn$p"
  # SSH 偶发瞬断时 $code 为空/null，判空防止 .Trim 抛异常把成功部署标成 exit 1
  if ([string]::IsNullOrWhiteSpace([string]$code)) {
    Write-Host "  ${p}: HTTP ?（探测未返回，多为 SSH 瞬断，可人工复核）" -ForegroundColor Yellow
  } else {
    Write-Host "  ${p}: HTTP $($code.Trim())"
  }
}

# ================= 汇总 =================
Step '部署完成'
if ($Frontend) {
  Write-Host "  前端已更新。本次备份: $RemoteRoot/frontend/$BackupName"
  $rollback = 'ssh ' + $Server + ' "cd ' + $RemoteRoot + '/frontend && rm -rf dist && mv ' + $BackupName + ' dist"'
  Write-Host '  回滚（如需）: ' -NoNewline
  Write-Host $rollback
}
if ($Backend) {
  Write-Host "  后端已更新。本次备份: $RemoteRoot/backend/app-bak-$Stamp"
  $rollbackB = 'ssh ' + $Server + ' "cd ' + $RemoteRoot + '/backend && rm -rf app && mv app-bak-' + $Stamp + ' app && systemctl restart ctyfly"'
  Write-Host '  回滚（如需）: ' -NoNewline
  Write-Host $rollbackB
}
Write-Host '  建议打开 https://ccflysim.cn 实际点一遍核心页面。'
