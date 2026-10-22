@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [!] 还没安装依赖。
  echo     先双击运行 setup.cmd。
  echo.
  pause
  exit /b 2
)

".venv\Scripts\python.exe" -m booktrans %*
