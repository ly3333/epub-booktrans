@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

if "%~1"=="" (
  echo 把 epub 文件拖到本文件上松手，即可开始翻译。
  echo 命令行用法： booktrans.cmd make "书.epub"
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [!] 还没安装依赖，先双击运行 setup.cmd。
  echo.
  pause
  exit /b 2
)

echo 开始处理： %~nx1
echo （首次运行要调用模型接口，按书的长度大约 20~60 分钟，可以挂着不管）
echo.
".venv\Scripts\python.exe" -m booktrans make "%~1" --out "%~dp0out"
set RC=%ERRORLEVEL%
echo.
if "%RC%"=="0" (
  echo 完成。成品在 out 目录： %~dp0out
) else (
  echo 退出码 %RC%，出错了。日志在 logs 目录，最近一个 run-*.log。
)
echo.
pause
exit /b %RC%
