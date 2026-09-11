@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 注册每日自动更新

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [错误] 没有检测到 Python，请先安装 Python 3.9 以上版本。
  echo.
  pause
  exit /b 1
)

echo.
echo   ============================================================
echo     注册「每日自动更新」任务
echo   ============================================================
echo.
echo   任务会在每天指定时间自动抓取最新文献并刷新网站数据。
echo   电脑需要处于开机且已登录状态，错过的时间点不会自动补跑。
echo.
set "T=08:30"
set /p "T=请输入每天更新时间（24小时制，例如 08:30），直接回车表示 %T%："
if "%T%"=="" set "T=08:30"
echo.

python "crawler\schedule.py" install --time %T%
echo.
pause
exit /b 0
