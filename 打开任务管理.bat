@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 电力市场前沿追踪 - 每日任务管理

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [错误] 没有检测到 Python，请先安装 Python 3.9 以上版本。
  echo.
  pause
  exit /b 1
)

start "任务管理服务" /min python task_server.py --port 8765
timeout /t 2 >nul
start "" http://127.0.0.1:8765/tasks.html
exit /b 0
