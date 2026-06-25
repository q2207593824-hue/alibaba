# 交付前自检：本机 backend 健康、会员登录、云端管理员配置 revision
param(
  [string]$BackendBase = "http://127.0.0.1:8000",
  [string]$CloudBase = "https://echo-yiwu.cloud",
  [string]$MemberUser = $env:ACCEPTANCE_MEMBER_USER,
  [string]$MemberPass = $env:ACCEPTANCE_MEMBER_PASS
)

$ErrorActionPreference = "Stop"

if (-not $MemberUser -or -not $MemberPass) {
  Write-Host "[SKIP] 未设置会员账号：请设置环境变量 ACCEPTANCE_MEMBER_USER / ACCEPTANCE_MEMBER_PASS" -ForegroundColor Yellow
  exit 2
}

function Test-Health($url, $expectService) {
  $r = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 15
  if ($r.service -ne $expectService) {
    throw "health service=$($r.service) expected $expectService"
  }
  Write-Host "[OK] health $url -> $($r.service)"
}

function Test-Login($base, $user, $pass) {
  $body = @{ username = $user; password = $pass } | ConvertTo-Json -Compress
  $r = Invoke-RestMethod -Method POST -Uri "$base/api/membership/auth/login" `
    -ContentType "application/json" -Body $body -TimeoutSec 60
  if (-not $r.success) { throw "login failed: $($r | ConvertTo-Json -Compress)" }
  if (-not $r.data.token) { throw "login missing token" }
  Write-Host "[OK] login $base user=$user role=$($r.data.role)"
  return $r.data.token
}

Write-Host "=== 1) Local backend ==="
try {
  Test-Health $BackendBase "ali-auto-publish-backend"
} catch {
  Write-Host "[FAIL] $_" -ForegroundColor Red
  exit 1
}

Write-Host "=== 2) Member login (via local proxy -> cloud) ==="
try {
  $null = Test-Login $BackendBase $MemberUser $MemberPass
} catch {
  Write-Host "[FAIL] $_" -ForegroundColor Red
  exit 1
}

Write-Host "=== Done ==="
