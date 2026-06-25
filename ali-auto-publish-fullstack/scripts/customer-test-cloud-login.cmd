@echo off
chcp 65001 >nul
setlocal
echo ========================================
echo  Ali Auto Publish - 云端登录连通测试
echo ========================================
echo.

if "%ACCEPTANCE_MEMBER_USER%"=="" (
  echo 请先设置环境变量 ACCEPTANCE_MEMBER_USER 和 ACCEPTANCE_MEMBER_PASS
  echo 示例:
  echo   set ACCEPTANCE_MEMBER_USER=您的会员账号
  echo   set ACCEPTANCE_MEMBER_PASS=您的密码
  goto :end
)

set "USER=%ACCEPTANCE_MEMBER_USER%"
set "PASS=%ACCEPTANCE_MEMBER_PASS%"

echo 正在请求 https://echo-yiwu.cloud/api/membership/auth/login ...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$body = @{ username='%USER%'; password='%PASS%' } | ConvertTo-Json -Compress; " ^
  "try { " ^
  "  $r = Invoke-RestMethod -Method POST -Uri 'https://echo-yiwu.cloud/api/membership/auth/login' -ContentType 'application/json' -Body $body; " ^
  "  if ($r.success) { Write-Host '成功: 可以连接云端，账号密码正确' -ForegroundColor Green; $r.data | Format-List } " ^
  "  else { Write-Host ('失败: ' + ($r | ConvertTo-Json -Compress)) -ForegroundColor Red } " ^
  "} catch { Write-Host ('失败: ' + $_.Exception.Message) -ForegroundColor Red; if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message } }"

:end
echo.
echo 若此处成功但软件仍提示密码错，请卸载旧版后安装最新安装包，并把 runtime.log 发给技术支持。
echo 日志位置: %%AppData%%\AliAutoPublish\runtime.log
echo.
pause
