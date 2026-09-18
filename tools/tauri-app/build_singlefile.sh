#!/usr/bin/env bash
# =====================================================================
#  一键：构建 Tauri 应用 → 把游戏资源追加到 exe 尾部 → 得到单文件 exe
#
#  用法: bash build_singlefile.sh [游戏目录] [输出exe]
#        默认游戏目录 <仓库>/docs
#        默认输出     tools/tauri-app/src-tauri/target/release/pvzge-single.exe
#
#  环境变量: PYTHON=python3   SKIP_BUILD=1（跳过 cargo，复用已有 exe）
# =====================================================================
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ws() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
HERE="$(ws "$SELF_DIR")"
ROOT="$(ws "$(cd "$SELF_DIR/../.." && pwd)")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python py; do
    command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }
  done
fi

GAMEDIR="${1:-$ROOT/docs}"
OUT="${2:-$HERE/src-tauri/target/release/pvzge-single.exe}"
APP_EXE="$HERE/src-tauri/target/release/pvzge.exe"

echo "======================================================================"
echo "  PvZ2 Gardendless —— Tauri 单文件打包"
echo "  游戏目录: $GAMEDIR"
echo "  输出:     $OUT"
echo "======================================================================"

if [ -z "$PY" ]; then
  echo "[错误] 找不到 Python 3（打包脚本需要）。用 PYTHON=... 指定。"
  exit 1
fi

echo
echo "[1/3] 构建 Tauri 应用（Rust + MSVC）..."
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  bash "$HERE/build_tauri.sh" "$HERE/src-tauri" 2>&1 | tail -6
else
  echo "      SKIP_BUILD=1，跳过"
fi

if [ ! -f "$APP_EXE" ]; then
  echo "[错误] 没找到构建产物: $APP_EXE"
  exit 1
fi
echo "      产物: $(stat -c %s "$APP_EXE") 字节"

echo
echo "[2/3] 打包资源到 exe 尾部（约 1.4 GB，需要几分钟）..."
rm -f "$OUT"
"$PY" "$ROOT/tools/launcher/pack.py" "$APP_EXE" "$GAMEDIR" "$OUT"
RC=$?
if [ $RC -ne 0 ]; then
  echo "[错误] 打包失败"
  exit 1
fi

echo
echo "[3/3] 校验归档..."
"$PY" "$ROOT/tools/launcher/verify_pack.py" "$OUT" "$GAMEDIR" | tail -6

echo
echo "======================================================================"
echo "  完成: $OUT"
echo "  大小: $(stat -c %s "$OUT") 字节"
echo "======================================================================"
