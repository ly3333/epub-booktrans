@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

rem NOTE: keep this file pure ASCII.
rem cmd.exe parses .cmd files using the system code page; a UTF-8 Chinese
rem comment will eat the first character of the following line
rem (symptom: "'cho' is not recognized as an internal command").
rem All Chinese messages are printed by Python instead.

if not exist ".venv\Scripts\python.exe" (
  echo [!] Python environment not found.
  echo     Run setup.cmd first.
  echo.
  pause
  exit /b 2
)

".venv\Scripts\python.exe" -m booktrans %*
