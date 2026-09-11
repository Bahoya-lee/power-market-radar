$ErrorActionPreference = "Stop"

try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
} catch {}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host ("== " + $Message) -ForegroundColor Cyan
}

function Stop-WithError([string]$Message) {
    Write-Host ""
    Write-Host ("[失败] " + $Message) -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  电力市场研究前沿追踪 · 更新并同步到 GitHub" -ForegroundColor White
Write-Host "  ------------------------------------------------------------" -ForegroundColor DarkGray

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Stop-WithError "没有检测到 Python。请先安装 Python 3.9 以上版本，并勾选 Add Python to PATH。"
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Stop-WithError "没有检测到 Git。请先安装 Git for Windows。"
}

if (-not (Test-Path -LiteralPath (Join-Path $Root ".git"))) {
    Stop-WithError "当前目录不是 Git 仓库，无法同步到 GitHub。"
}

Write-Step "1/5 检查 GitHub 登录状态"
& git -c http.sslBackend=openssl -c http.proxy= ls-remote --heads origin | Out-Null
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "GitHub 登录或网络检查失败。请先完成登录授权，再重新运行本脚本。"
}

Write-Step "2/5 抓取并刷新本地数据"
& python "crawler\run.py"
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "数据更新失败。请检查网络、代理或 arXiv 提示后重试。"
}

Write-Step "3/5 暂存变更"
& git config http.sslBackend openssl
& git config http.proxy ""
& git add -A
if ($LASTEXITCODE -ne 0) {
    Stop-WithError "Git 暂存失败。"
}

& git diff --cached --quiet
$HasChanges = ($LASTEXITCODE -ne 0)

if ($HasChanges) {
    Write-Step "4/5 提交变更"
    $Message = "Update literature data " + (Get-Date -Format "yyyy-MM-dd HH:mm")
    & git commit -m $Message
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "Git 提交失败。请检查仓库状态。"
    }
} else {
    Write-Step "4/5 没有检测到新的数据变化"
}

Write-Step "5/5 推送到 GitHub"
& git -c http.sslBackend=openssl -c http.proxy= push
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  GitHub 推送失败。" -ForegroundColor Yellow
    Write-Host "  如果弹出登录窗口，请完成 GitHub 授权后重新运行本脚本。" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "  同步完成。" -ForegroundColor Green
Write-Host "  仓库：https://github.com/Bahoya-lee/power-market-radar" -ForegroundColor DarkGray
Write-Host "  网站：https://bahoya-lee.github.io/power-market-radar/" -ForegroundColor DarkGray
exit 0
