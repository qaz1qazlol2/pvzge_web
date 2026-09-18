#!/usr/bin/env bash
# =====================================================================
#  编译 Tauri 桌面壳（Rust + MSVC）
#
#  为什么不直接 `cargo build`：
#  本机 Visual Studio 的 vcvars64.bat 依赖 reg.exe，在部分受限环境里跑不通，
#  所以这里手工把 MSVC / Windows SDK 的 PATH、INCLUDE、LIB 注进去。
#
#  用法:
#    bash build_tauri.sh [src-tauri 目录]     # 默认本脚本同级的 src-tauri
#
#  全部路径都会自动探测；也可以用环境变量覆盖:
#    MSVC_DIR      .../VC/Tools/MSVC/<版本>
#    SDK_BASE      .../Windows Kits/10
#    SDKVER        10.0.x.x
#    CARGO         cargo 可执行文件路径
#    CARGO_HOME / RUSTUP_HOME
#    PVZGE_PROXY   需要走代理时设置，例如 http://127.0.0.1:19132
#                  （不设置就用环境里已有的 HTTP(S)_PROXY；脚本不会自己写死代理）
#    CHECK_ONLY=1  只做环境检查（探测 MSVC/SDK/Rust），不编译
# =====================================================================
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ws() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
PROJ="${1:-$SELF_DIR/src-tauri}"

# ---------- 自动探测 MSVC 工具链 ----------
find_msvc() {
  local vs="" c="" base="" vswhere
  vswhere="/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
  if [ -x "$vswhere" ]; then
    vs="$("$vswhere" -latest -products '*' \
          -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 \
          -property installationPath 2>/dev/null | tr -d '\r')"
    if [ -n "$vs" ]; then
      vs="$(cygpath -u "$vs" 2>/dev/null || echo "$vs")"
      c="$(ls -d "$vs"/VC/Tools/MSVC/* 2>/dev/null | sort -V | tail -1)"
      [ -n "$c" ] && { printf '%s' "$c"; return 0; }
    fi
  fi
  for base in "/d/Program Files/Microsoft Visual Studio" \
              "/c/Program Files/Microsoft Visual Studio" \
              "/c/Program Files (x86)/Microsoft Visual Studio"; do
    [ -d "$base" ] || continue
    c="$(ls -d "$base"/*/*/VC/Tools/MSVC/* 2>/dev/null | sort -V | tail -1)"
    [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

# ---------- 自动探测 Windows SDK ----------
find_sdk_base() {
  local b
  for b in "/c/Program Files (x86)/Windows Kits/10" "/c/Program Files/Windows Kits/10"; do
    [ -d "$b" ] && { printf '%s' "$b"; return 0; }
  done
  return 1
}
find_sdkver() {
  ls -d "$1"/Include/* 2>/dev/null | sort -V | tail -1 | sed 's#.*/##'
}

MSVC="${MSVC_DIR:-$(find_msvc || true)}"
SDK="${SDK_BASE:-$(find_sdk_base || true)}"
SDK="${SDK:-/c/Program Files (x86)/Windows Kits/10}"
SDKVER="${SDKVER:-$(find_sdkver "$SDK" || true)}"

echo "======================================================================"
echo "  Tauri 桌面壳构建"
echo "  工程    : $PROJ"
echo "  MSVC    : ${MSVC:-（没找到）}"
echo "  SDK     : $SDK"
echo "  SDKVER  : ${SDKVER:-（没找到）}"
echo "======================================================================"

if [ -z "$MSVC" ] || [ -z "$SDKVER" ]; then
  echo "[错误] 没探测到 MSVC / Windows SDK。"
  echo "       装了 Visual Studio（勾选「使用 C++ 的桌面开发」）再跑；"
  echo "       或者用 MSVC_DIR / SDK_BASE / SDKVER 环境变量手工指定。"
  exit 1
fi

# ---------- 检查工具链文件 ----------
echo
echo "=== 检查工具链文件 ==="
miss=0
for f in "$MSVC/bin/Hostx64/x64/link.exe" "$MSVC/bin/Hostx64/x64/cl.exe" \
         "$SDK/bin/$SDKVER/x64/rc.exe" "$MSVC/lib/x64" "$SDK/Lib/$SDKVER/ucrt/x64"; do
  if [ -e "$f" ]; then echo "  OK   $f"; else echo "  缺失 $f"; miss=1; fi
done
[ "$miss" = "1" ] && echo "  （有缺失项，接着试，失败再看具体报错）"

# ---------- PATH：MSVC 与 SDK 的 x64 工具 ----------
export PATH="$MSVC/bin/Hostx64/x64:$SDK/bin/$SDKVER/x64:$PATH"

# ---------- INCLUDE / LIB（Windows 形式、分号分隔）----------
MSVC_W="$(printf '%s' "$(ws "$MSVC")" | tr '/' '\\')"
SDK_W="$(printf '%s' "$(ws "$SDK")" | tr '/' '\\')"
export INCLUDE="$MSVC_W\\include;$SDK_W\\Include\\$SDKVER\\ucrt;$SDK_W\\Include\\$SDKVER\\um;$SDK_W\\Include\\$SDKVER\\shared;$SDK_W\\Include\\$SDKVER\\winrt"
export LIB="$MSVC_W\\lib\\x64;$SDK_W\\Lib\\$SDKVER\\ucrt\\x64;$SDK_W\\Lib\\$SDKVER\\um\\x64"

# ---------- Rust / Cargo ----------
CARGO="${CARGO:-}"
if [ -z "$CARGO" ]; then
  for c in "$HOME/.cargo/bin/cargo.exe" "$HOME/.cargo/bin/cargo"; do
    [ -x "$c" ] && { CARGO="$c"; break; }
  done
fi
if [ -z "$CARGO" ] && command -v cargo >/dev/null 2>&1; then CARGO="$(command -v cargo)"; fi
if [ -z "$CARGO" ]; then
  echo "[错误] 找不到 cargo。装 Rust：https://rustup.rs/ ，或用 CARGO=... 指定。"
  exit 1
fi

export CARGO_HOME="$(ws "${CARGO_HOME:-$HOME/.cargo}")"
export RUSTUP_HOME="$(ws "${RUSTUP_HOME:-$HOME/.rustup}")"
export CARGO_NET_RETRY="${CARGO_NET_RETRY:-5}"
export RUST_BACKTRACE="${RUST_BACKTRACE:-1}"

# 代理：只在显式给出时才注入，避免写死别人的本地端口
if [ -n "${PVZGE_PROXY:-}" ]; then
  export HTTP_PROXY="$PVZGE_PROXY"
  export HTTPS_PROXY="$PVZGE_PROXY"
  echo "  代理    : $PVZGE_PROXY（来自 PVZGE_PROXY）"
elif [ -n "${HTTPS_PROXY:-}" ]; then
  echo "  代理    : $HTTPS_PROXY（来自环境）"
else
  echo "  代理    : 未使用"
fi

echo
echo "=== rustc ==="
"$CARGO" --version
RUSTC="$(dirname "$CARGO")/rustc.exe"
[ -x "$RUSTC" ] || RUSTC="$(dirname "$CARGO")/rustc"
[ -x "$RUSTC" ] && "$RUSTC" --version

echo
echo "=== 校验 link.exe 可见 ==="
command -v link.exe || echo "  (PATH 里没有 link.exe —— 接着试，失败再看具体报错)"

if [ "${CHECK_ONLY:-0}" = "1" ]; then
  echo
  echo "  CHECK_ONLY=1 —— 只做环境检查，不编译。"
  exit 0
fi

echo
echo "=== cargo build --release ==="
cd "$PROJ" || { echo "[错误] 目录不存在: $PROJ"; exit 1; }
"$CARGO" build --release
RC=$?
echo "EXITCODE=$RC"
exit $RC
