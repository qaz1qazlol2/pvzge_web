@echo off
chcp 65001 >nul
setlocal
title PvZ2 Gardendless 本地启动器

rem ==================== 可改配置 ====================
set "PORT=8123"
rem 游戏目录：优先用脚本同级的 web\，没有再回落到下面的绝对路径
set "DEFAULT_ROOT=D:\git\pvzge_web\docs"
rem ==================================================

set "HERE=%~dp0"
set "ROOT="
if exist "%HERE%web\index.html" set "ROOT=%HERE%web"
if not defined ROOT if exist "%DEFAULT_ROOT%\index.html" set "ROOT=%DEFAULT_ROOT%"
if not defined ROOT (
  echo [错误] 找不到游戏目录。请二选一：
  echo        1^) 把游戏文件放到本脚本同级的 web\ 目录下
  echo        2^) 修改本脚本里的 DEFAULT_ROOT
  echo.
  pause
  exit /b 1
)

if not exist "%HERE%server.py" (
  echo [错误] 找不到同目录下的 server.py
  pause
  exit /b 1
)

rem ---------- 找 Python ----------
set "PY="
if exist "C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not defined PY for %%I in (python.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY for %%I in (python3.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY (
  echo [错误] 找不到 Python。
  echo        请改用 PvZGE-Launcher.exe（WebView2 版，不依赖 Python）。
  echo.
  pause
  exit /b 1
)

rem ---------- 已在运行就直接开浏览器 ----------
curl -s -o nul --max-time 2 "http://127.0.0.1:%PORT%/" >nul 2>nul
if not errorlevel 1 (
  echo 服务器已在 127.0.0.1:%PORT% 运行，直接打开浏览器…
  start "" "http://127.0.0.1:%PORT%/"
  exit /b 0
)

echo 正在启动本地服务器…
echo   目录: %ROOT%
echo   地址: http://127.0.0.1:%PORT%/
echo.
start "PvZGE Server (关闭此窗口即停止)" /min "%PY%" "%HERE%server.py" --root "%ROOT%" --port %PORT% --open

timeout /t 2 >nul
exit /b 0
