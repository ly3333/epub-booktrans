@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

rem NOTE: keep this file pure ASCII (see booktrans.cmd for why).
rem Chinese output comes from Python; English here is intentional.

if not exist ".venv\Scripts\python.exe" (
  echo [!] Python environment not found.
  echo     Run setup.cmd first.
  echo.
  pause
  exit /b 2
)

if "%~1"=="" (
  echo Drag an .epub file onto this file to start translating.
  echo Or use the command line:  booktrans.cmd make "book.epub"
  echo.
  pause
  exit /b 1
)

echo Input: %~nx1
echo Translating. A typical book takes 20-60 minutes; you can leave it running.
echo.
".venv\Scripts\python.exe" -m booktrans make "%~1" --out "%~dp0out"
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" goto :failed

echo Done. Output folder: %~dp0out
echo.
pause
exit /b 0

:failed
echo [X] Exit code %RC%. See the messages above, and logs\run-*.log
echo.
pause
exit /b %RC%
