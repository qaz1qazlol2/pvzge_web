#!/usr/bin/env bash
# =====================================================================
#  PvZ2 Gardendless —— 一键构建
#
#  产出（默认落到 <仓库>/dist/）:
#    PvZGE-Gardendless.exe          Tauri 桌面壳 + 内嵌游戏，双击即玩
#    PvZGE-WebServer.exe            Web 服务器本体（用 --root 指定游戏目录）
#    PvZGE-WebServer-单文件.exe      Web 服务器 + 内嵌游戏
#    PvZGE-Launcher.exe             .NET / WebView2 启动器本体
#    PvZGE-Launcher-单文件.exe      .NET / WebView2 启动器 + 内嵌游戏
#
#  用法:
#    bash build.sh              全部（tauri + web + launcher）
#    bash build.sh tauri        只做 Tauri 桌面版
#    bash build.sh web          只做 Web 服务器（本体 + 单文件）
#    bash build.sh launcher     只做 .NET / WebView2 启动器（本体 + 单文件）
#    bash build.sh check        只打印探测到的环境和路径，不构建
#
#  环境变量:
#    GAMEDIR       游戏目录（含 index.html），默认 <仓库>/docs
#    DIST          产物输出目录，默认 <仓库>/dist
#                  （刻意不叫 OUTDIR —— 那会撞上 MSBuild 的 OutDir 属性，
#                    导致 dotnet 把整套运行时 DLL 也吐进产物目录）
#    PYTHON        python 命令，默认自动探测（python3 / python / py）
#    DOTNET        dotnet 命令，默认自动探测
#    SKIP_BUILD=1  跳过 exe 编译，复用已有产物（只想重新打包时用）
#
#  例:
#    DIST=D:/发布 bash build.sh web
#
#  依赖: Python 3（打包/校验）、.NET 10 SDK（web / launcher）、
#        Rust + MSVC（tauri，需 Visual Studio「使用 C++ 的桌面开发」）
# =====================================================================
set -u

# ---------- 路径（全部从脚本位置推导，不写死任何机器路径）----------
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ws() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
ROOT="$(ws "$SELF_DIR")"
T="$ROOT/tools"

GAMEDIR="${GAMEDIR:-$ROOT/docs}"
DIST="${DIST:-$ROOT/dist}"
WHAT="${1:-all}"

# ---------- 工具探测 ----------
detect_python() {
  local c
  for c in "${PYTHON:-}" python3 python py; do
    [ -n "$c" ] || continue
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
      printf '%s' "$c"; return 0
    fi
  done
  return 1
}
detect_dotnet() {
  local c
  for c in "${DOTNET:-}" dotnet; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 && { printf '%s' "$c"; return 0; }
  done
  return 1
}
detect_cargo() {
  local c
  for c in "${CARGO:-}" "$HOME/.cargo/bin/cargo.exe" "$HOME/.cargo/bin/cargo" cargo; do
    [ -n "$c" ] || continue
    [ -x "$c" ] && { printf '%s' "$c"; return 0; }
    command -v "$c" >/dev/null 2>&1 && { printf '%s' "$c"; return 0; }
  done
  return 1
}

PY="$(detect_python || true)"
DOTNET="$(detect_dotnet || true)"
CARGO="$(detect_cargo || true)"

# ---------- 组件路径 ----------
TAURI_DIR="$T/tauri-app"
TAURI_EXE="$TAURI_DIR/src-tauri/target/release/pvzge.exe"
WS_DIR="$T/webserver"
WS_EXE="$WS_DIR/publish/PvZGE-WebServer.exe"
LN_DIR="$T/launcher"
LN_EXE="$LN_DIR/publish/PvZGE-Launcher.exe"
PACK="$LN_DIR/pack.py"
VERIFY="$LN_DIR/verify_pack.py"

ver() { "$@" 2>/dev/null | head -1 || true; }

# ---------- 环境自检 ----------
show_env() {
  echo "----------------------------------------------------------------------"
  echo "  仓库根   : $ROOT"
  echo "  游戏目录 : $GAMEDIR  $([ -f "$GAMEDIR/index.html" ] && echo '(index.html 存在)' || echo '!! 没有 index.html')"
  echo "  输出目录 : $DIST"
  echo "  Python   : ${PY:-（没找到）}  $( [ -n "$PY" ] && ver "$PY" --version)"
  echo "  .NET     : ${DOTNET:-（没找到）}  $( [ -n "$DOTNET" ] && ver "$DOTNET" --version)"
  echo "  Cargo    : ${CARGO:-（没找到）}  $( [ -n "$CARGO" ] && ver "$CARGO" --version)"
  echo "----------------------------------------------------------------------"
  echo "  组件产物:"
  printf "    %-46s %s\n" "tauri : ${TAURI_EXE#$ROOT/}" "$([ -f "$TAURI_EXE" ] && echo "已存在 $(stat -c %s "$TAURI_EXE") 字节" || echo '尚未编译')"
  printf "    %-46s %s\n" "web   : ${WS_EXE#$ROOT/}" "$([ -f "$WS_EXE" ] && echo "已存在 $(stat -c %s "$WS_EXE") 字节" || echo '尚未编译')"
  printf "    %-46s %s\n" "ln    : ${LN_EXE#$ROOT/}" "$([ -f "$LN_EXE" ] && echo "已存在 $(stat -c %s "$LN_EXE") 字节" || echo '尚未编译')"
  echo "----------------------------------------------------------------------"
}

if [ "$WHAT" = "check" ]; then
  echo "======================================================================"
  echo "  环境自检（不构建）"
  show_env
  if [ -n "$PY" ] && [ -f "$T/sync_version.py" ]; then
    echo "  版本号一致性（真源 = docs/index.html 里的游戏版本）:"
    "$PY" "$T/sync_version.py" --check 2>&1 | sed 's/^/    /'
  fi
  exit 0
fi

if [ ! -f "$GAMEDIR/index.html" ]; then
  echo "[错误] 游戏目录不对（没有 index.html）: $GAMEDIR"
  echo "       用 GAMEDIR=/path/to/docs 指定。"
  exit 1
fi
if [ -z "$PY" ]; then
  echo "[错误] 找不到 Python 3（打包/校验需要）。用 PYTHON=... 指定。"
  exit 1
fi
mkdir -p "$DIST"

echo "======================================================================"
echo "  PvZ2 Gardendless 一键构建"
echo "  范围: $WHAT"
show_env

# ---------- 版本号同步 ----------
# 五个 exe 的版本来自 4 处彼此独立的配置（tauri.conf.json / Cargo.toml /
# Cargo.lock / 两个 csproj）。这里在每次构建前按唯一真源统一刷一遍，
# 所以上游把游戏升到 0.15 之后，下一次构建出来的 5 个 exe 就都是 0.15。
SYNCVER="$T/sync_version.py"
APPVER=""
if [ -f "$SYNCVER" ]; then
  echo "──── 版本号同步 ────"
  APPVER="$("$PY" "$SYNCVER" --value 2>/dev/null || true)"
  if [ -n "$APPVER" ]; then
    "$PY" "$SYNCVER" 2>&1 | sed 's/^/   /'
  else
    echo "   [警告] 版本号探测失败，沿用配置里的现有值。"
    echo "   [提示] 上游标题格式变了就手工指定："
    echo "          python tools/sync_version.py --set X.Y.Z"
  fi
  echo "   >> 本次构建版本: ${APPVER:-（未知，沿用配置值）}"
  echo "----------------------------------------------------------------------"
fi

# 编译/打包 + 校验
pack_and_verify() {   # $1=基础exe  $2=输出exe
  echo "      打包 -> $2"
  "$PY" "$PACK" "$1" "$GAMEDIR" "$2" 2>&1 | tail -4
  echo "      校验:"
  "$PY" "$VERIFY" "$2" "$GAMEDIR" 2>&1 | tail -3
}

# ---------- [1] Tauri 桌面版 ----------
do_tauri() {
  echo
  echo "──── Tauri 桌面单文件版 ────"
  if [ "${SKIP_BUILD:-0}" != "1" ]; then
    if [ -z "$CARGO" ]; then
      echo "      [跳过] 没找到 cargo（装 Rust 或指定 CARGO=...）"
    else
      bash "$TAURI_DIR/build_tauri.sh" "$TAURI_DIR/src-tauri" 2>&1 | grep -E "Finished|error|EXITCODE" | tail -4
    fi
  else
    echo "      跳过编译（SKIP_BUILD=1）"
  fi
  if [ ! -f "$TAURI_EXE" ]; then
    echo "      [错误] 没找到 Tauri exe，跳过打包: $TAURI_EXE"
    return 1
  fi
  pack_and_verify "$TAURI_EXE" "$DIST/PvZGE-Gardendless.exe"
}

# ---------- [2] Web 服务器 ----------
do_web() {
  echo
  echo "──── Web 服务器 ────"
  if [ "${SKIP_BUILD:-0}" != "1" ]; then
    if [ -z "$DOTNET" ]; then
      echo "      [跳过编译] 没找到 dotnet"
    else
      echo "      刷新 Shared.cs（从 launcher/src/Program.cs 抽取）..."
      "$PY" "$WS_DIR/extract_shared.py" 2>&1 | tail -4
      echo "      dotnet publish..."
      "$DOTNET" publish "$WS_DIR/src/PvZGE-WebServer.csproj" -c Release -o "$WS_DIR/publish" --nologo 2>&1 \
        | grep -E "PvZGE-WebServer ->|error|warning CS" | tail -3
    fi
  else
    echo "      跳过编译（SKIP_BUILD=1）"
  fi
  if [ ! -f "$WS_EXE" ]; then
    echo "      [错误] 没找到 WebServer exe: $WS_EXE"
    return 1
  fi
  cp "$WS_EXE" "$DIST/PvZGE-WebServer.exe"
  echo "      已复制本体 -> $DIST/PvZGE-WebServer.exe"
  pack_and_verify "$WS_EXE" "$DIST/PvZGE-WebServer-单文件.exe"
}

# ---------- [3] .NET / WebView2 启动器 ----------
do_launcher() {
  echo
  echo "──── .NET / WebView2 启动器 ────"
  if [ "${SKIP_BUILD:-0}" != "1" ]; then
    if [ -z "$DOTNET" ]; then
      echo "      [跳过编译] 没找到 dotnet"
    else
      "$DOTNET" publish "$LN_DIR/src/PvZGE-Launcher.csproj" -c Release -o "$LN_DIR/publish" --nologo 2>&1 \
        | grep -E "PvZGE-Launcher ->|error|warning CS" | tail -3
    fi
  else
    echo "      跳过编译（SKIP_BUILD=1）"
  fi
  if [ ! -f "$LN_EXE" ]; then
    echo "      [错误] 没找到 Launcher exe: $LN_EXE"
    return 1
  fi
  cp "$LN_EXE" "$DIST/PvZGE-Launcher.exe"
  echo "      已复制本体 -> $DIST/PvZGE-Launcher.exe"
  pack_and_verify "$LN_EXE" "$DIST/PvZGE-Launcher-单文件.exe"
}

case "$WHAT" in
  tauri)    do_tauri ;;
  web)      do_web ;;
  launcher) do_launcher ;;
  all)      do_tauri; do_web; do_launcher ;;
  *) echo "未知范围: $WHAT（可选 tauri / web / launcher / all / check）"; exit 1 ;;
esac

echo
echo "──── 成品校验（五个 exe 的版本号 / 图标是否一致）────"
if [ -f "$T/verify_exe.py" ]; then
  "$PY" "$T/verify_exe.py" --dist "$DIST" 2>&1 | tail -14 | sed 's/^/  /'
else
  echo "  [跳过] 找不到 tools/verify_exe.py"
fi

echo
echo "======================================================================"
echo "  完成。产物目录: $DIST"
ls -la "$DIST" 2>/dev/null | tail -n +2
echo "======================================================================"
