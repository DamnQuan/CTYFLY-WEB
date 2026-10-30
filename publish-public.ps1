# 发布到公开仓库 CTYFLY-WEB
#
# 用法（Windows PowerShell 5.1）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File publish-public.ps1            # 预览
#   powershell -NoProfile -ExecutionPolicy Bypass -File publish-public.ps1 -Execute   # 提交并推送
#
# 规则：
# 1) 以本地 main 的代码树为基础发布，保留公开仓库自身提交历史，只追加一条 release 提交
# 2) 内部内容不发布：deploy/、交接文档/、运维手册.md、CONTEXT.md、
#    backend/requirements.snapshot.txt、.git-blame-ignore-revs、.audit-tmp
# 3) 已脱敏/裁剪的文件保留公开仓库版本：README.md、check-all.ps1、
#    backend/app/requestinfo.py、backend/seed_transfer_demo.py、
#    backend/tests/test_ipv6_capture.py、.github/dependabot.yml、.github/workflows/ci.yml
# 4) 其余文件一律以开发版为准

param([switch]$Execute)

$ErrorActionPreference = 'Stop'
$Src = Split-Path -Parent $MyInvocation.MyCommand.Path
$Remote = 'public'
$Branch = 'main'

$Exclude = @(
  'deploy',
  '交接文档',
  '运维手册.md',
  'CONTEXT.md',
  'backend/requirements.snapshot.txt',
  '.git-blame-ignore-revs',
  '.audit-tmp'
)

$KeepPublic = @(
  'README.md',
  'check-all.ps1',
  'backend/app/requestinfo.py',
  'backend/seed_transfer_demo.py',
  'backend/tests/test_ipv6_capture.py',
  '.github/dependabot.yml',
  '.github/workflows/ci.yml'
)

git -C $Src fetch $Remote | Out-Null

$idx = Join-Path $Src '.git\publish.index'
if (Test-Path $idx) { Remove-Item $idx -Force }
$env:GIT_INDEX_FILE = $idx
try {
  git -C $Src read-tree $Branch

  foreach ($p in $Exclude) {
    git -C $Src rm --cached --ignore-unmatch -r --quiet -- $p | Out-Null
  }

  foreach ($p in $KeepPublic) {
    $spec = $Remote + '/' + $Branch + ':' + $p
    $obj = git -C $Src rev-parse $spec 2>$null
    if (-not $obj) { continue }
    $line = git -C $Src ls-tree ("$Remote/$Branch") -- $p
    if (-not $line) { continue }
    $mode = ($line -split '\s+')[0]
    git -C $Src update-index --add --cacheinfo ("{0},{1},{2}" -f $mode, $obj.Trim(), $p) | Out-Null
  }

  $tree = (git -C $Src write-tree).Trim()
  $parent = (git -C $Src rev-parse "$Remote/$Branch").Trim()
  $devSha = (git -C $Src rev-parse --short $Branch).Trim()
  $devMsg = (git -C $Src log -1 --pretty=%s $Branch).Trim()
}
finally {
  Remove-Item Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
  if (Test-Path $idx) { Remove-Item $idx -Force }
}

Write-Host "开发分支 : $Branch @ $devSha  ($devMsg)"
Write-Host "公开仓库 : $Remote/$Branch @ $($parent.Substring(0,7))"
Write-Host "不发布   : $($Exclude -join ', ')"
Write-Host "保留公开版: $($KeepPublic -join ', ')"
Write-Host ''
Write-Host '=== 本次将产生的变更（相对公开仓库）==='
git -C $Src diff --stat "$Remote/$Branch" $tree | Select-Object -Last 50
Write-Host ''

if (-not $Execute) {
  Write-Host '预览完成。加 -Execute 实际提交并推送。'
  exit 0
}

$msgFile = Join-Path $env:TEMP 'ctyfly-release-msg.txt'
$msgBody = "release: 同步开发版 $devSha`r`n`r`n来源提交: $devSha $devMsg`r`n说明: 公开版保留脱敏/裁剪内容；deploy/、交接文档/ 等不发布。"
[IO.File]::WriteAllText($msgFile, $msgBody, (New-Object System.Text.UTF8Encoding($false)))

$newCommit = (git -C $Src commit-tree $tree -p $parent -F $msgFile).Trim()
git -C $Src push $Remote "${newCommit}:$Branch"
Write-Host "已发布: $($newCommit.Substring(0,7))"
