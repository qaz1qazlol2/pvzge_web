@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title PvZGE 单文件打包工具

rem ========================= 配置（按需改这里） =========================
rem 游戏目录（必须含 index.html）—— 相对本脚本推导：tools\launcher\ 的上两级是仓库根
set "HERE=%~dp0"
set "GAMEDIR=%HERE%..\..\docs"

rem 输出 exe 的完整路径
set "OUTEXE=%~dp0PvZGE-Gardendless-单文件.exe"

rem 是否重新编译启动器主程序：1=编译(需 .NET SDK)  0=直接用现成的
set "REBUILD=1"
rem =====================================================================

set "HERE=%~dp0"

rem ---------- 找 Python ----------
rem 不写死解释器路径（可用环境变量 PYTHON 覆盖）
set "PY=%PYTHON%"
if not defined PY for %%I in (python.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY for %%I in (python3.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY for %%I in (py.exe) do if not defined PY set "PY=%%~$PATH:I"
if not defined PY (
  echo [错误] 找不到 Python，打包需要它。
  echo        装一个 Python 3 并加入 PATH 即可。
  echo.
  pause
  exit /b 1
)

if not exist "%HERE%pack.py" (
  echo [错误] 同目录下缺 pack.py
  pause
  exit /b 1
)

rem ---------- 1) 基础 exe ----------
set "BASE=%HERE%publish\PvZGE-Launcher.exe"

if "%REBUILD%"=="1" (
  set "HAVEDOTNET=0"
  for %%I in (dotnet.exe) do if not "%%~$PATH:I"=="" set "HAVEDOTNET=1"
  if "!HAVEDOTNET!"=="1" (
    echo [1/3] 编译启动器主程序...
    pushd "%HERE%src"
    dotnet publish PvZGE-Launcher.csproj -c Release -o "%HERE%publish" --nologo
    set "RC=!errorlevel!"
    popd
    if not "!RC!"=="0" (
      echo [警告] 编译失败，改用现成的 exe
    )
  ) else (
    echo [1/3] 没找到 .NET SDK，跳过编译，使用现成的 PvZGE-Launcher.exe
    echo        ^(想自己编译请装 .NET 10 SDK：https://dotnet.microsoft.com/download^)
  )
) else (
  echo [1/3] 按要求跳过编译
)

if not exist "%BASE%" (
  echo.
  echo [错误] 找不到基础 exe：
  echo         %BASE%
  echo        请先编译一次，或把 PvZGE-Launcher.exe 放到 publish\ 下。
  pause
  exit /b 1
)

rem ---------- 2) 检查游戏目录 ----------
if not exist "%GAMEDIR%\index.html" (
  echo.
  echo [错误] 游戏目录不对（里面没有 index.html）：
  echo         %GAMEDIR%
  echo        请修改本脚本顶部的 GAMEDIR。
  pause
  exit /b 1
)

if exist "%OUTEXE%" (
  echo.
  echo [提示] 输出文件已存在，将被覆盖：
  echo         %OUTEXE%
)

rem ---------- 3) 打包 ----------
echo.
echo [2/3] 打包资源到 exe（约 1.5 GB，需要几分钟）...
echo.
"%PY%" "%HERE%pack.py" "%BASE%" "%GAMEDIR%" "%OUTEXE%"
if errorlevel 1 (
  echo.
  echo [错误] 打包失败。
  pause
  exit /b 1
)

echo.
echo [3/3] 全部完成！直接双击运行：
echo.
echo    %OUTEXE%
echo.
pause
exit /b 0
