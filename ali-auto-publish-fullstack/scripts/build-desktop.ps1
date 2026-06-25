# Build Windows desktop installer (run on dev machine)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Frontend = Join-Path $Root "frontend"
$DeployJson = Join-Path $Frontend "electron\desktop.deploy.json"
$ConfigJson = Join-Path $Root "data\config.json"

Write-Host "==> Ali Auto Publish desktop build" -ForegroundColor Cyan
Write-Host "Root: $Root"

if (Test-Path $ConfigJson) {
    $cfg = Get-Content $ConfigJson -Raw -Encoding UTF8 | ConvertFrom-Json
    $adminKey = [string]$cfg.payment.admin_api_key
    if ($adminKey -and ($adminKey -ne "change-me-admin")) {
        $deployPayload = @{ admin_api_key = $adminKey }
        $deployPayload | ConvertTo-Json -Compress | Set-Content $DeployJson -Encoding UTF8 -NoNewline
        Write-Host "[ok] desktop.deploy.json from data/config.json (admin_api_key injected)" -ForegroundColor Green
    } else {
        Write-Host "[warn] data/config.json admin_api_key is placeholder" -ForegroundColor Yellow
    }
} else {
    Write-Host "[warn] config not found: $ConfigJson" -ForegroundColor Yellow
}

foreach ($proc in @("Ali Auto Publish", "ali-backend", "ali-backend-service", "pyinstaller")) {
    Get-Process -Name $proc -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

Set-Location $Frontend
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    throw "pnpm not found. Install Node.js 18+ and: npm install -g pnpm"
}

Write-Host "==> Fetch ChromeDriver (bundled for offline bind-shop)..." -ForegroundColor Cyan
$Py = Join-Path $Root "backend\venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
& $Py (Join-Path $Root "scripts\fetch_chromedriver.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host "[warn] ChromeDriver prefetch failed; build continues (runtime may download)" -ForegroundColor Yellow
}

pnpm install
pnpm run desktop:build

$release = Join-Path $Frontend "release"
Write-Host ""
Write-Host "==> Done. Deliverables:" -ForegroundColor Green
Get-ChildItem $release -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in ".exe", ".zip" } |
    ForEach-Object { Write-Host ("  {0}  ({1:N1} MB)" -f $_.Name, ($_.Length / 1MB)) }

Write-Host ""
Write-Host "See docs for customer handoff." -ForegroundColor Yellow
