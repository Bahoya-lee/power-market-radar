@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 取消每日自动更新

python "crawler\schedule.py" remove
echo.
pause
exit /b 0
