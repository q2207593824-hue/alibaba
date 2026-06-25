@echo off
setlocal enabledelayedexpansion

REM A方案：生成可发给客户的本机部署包（Windows）
REM 输出目录：frontend\release

set ROOT=%~dp0..
cd /d "%ROOT%"

echo [1/4] 构建后端EXE...
python "backend\build_backend_exe.py"
if errorlevel 1 (
  echo 后端构建失败
  exit /b 1
)

echo [2/4] 安装前端依赖...
cd /d "%ROOT%\frontend"
call pnpm install
if errorlevel 1 (
  echo 前端依赖安装失败
  exit /b 1
)

echo [3/4] 执行桌面端打包...
call pnpm run desktop:build
if errorlevel 1 (
  echo 桌面端打包失败
  exit /b 1
)

echo [4/4] 打包完成
echo 产物目录：%ROOT%\frontend\release
echo 可直接发给客户：AliAutoPublish-*.exe（portable）或 AliAutoPublish-*.zip

endlocal
