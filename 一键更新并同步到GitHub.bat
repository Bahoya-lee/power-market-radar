@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 电力市场研究前沿追踪 - 更新并同步到 GitHub

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0同步到GitHub.ps1"
set "CODE=%ERRORLEVEL%"

echo.
if "%CODE%"=="0" (
  echo   正在打开本地网站…
  start "" "index.html"
) else (
  echo   同步没有完成，请查看上面的提示。
)
echo.
pause
exit /b %CODE%

