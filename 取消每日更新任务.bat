@echo off
chcp 936 >nul
cd /d "%~dp0"
title 取消每日自动更新

python "crawler\schedule.py" remove
echo.
pause
exit /b 0
