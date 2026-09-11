@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 电力市场研究前沿追踪 - 数据更新

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [错误] 没有检测到 Python。
  echo   请先安装 Python 3.9 或更高版本：https://www.python.org/downloads/
  echo   安装时记得勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 1
)

python "crawler\run.py" %*
if errorlevel 1 (
  echo.
  echo   [失败] 更新没有完成，请查看上面的错误提示。
  echo   常见原因：网络不通、公司/校园网需要代理、数据源临时限流。
  echo   如果是网络问题，可以先双击「打开网站.bat」查看上一次抓到的数据。
  echo.
  pause
  exit /b 1
)

echo   正在打开网站…
start "" "index.html"
timeout /t 3 >nul
exit /b 0
