#!/usr/bin/env bash
# =====================================================================
#  实测 Tauri 单文件 exe：跑起来 → 查 WebView2 用户目录 / 缓存 / origin
#  用法: bash test_singlefile.sh [exe路径]
# =====================================================================
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ws() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
HERE="$(ws "$SELF_DIR")"

EXE="${1:-$HERE/src-tauri/target/release/pvzge-single.exe}"
BASE="${LOCALAPPDATA:-$HOME/AppData/Local}/com.pvzge.launcher"

echo "=== exe 信息 ==="
ls -la "$EXE"
echo "  尾部 magic: $(tail -c 8 "$EXE")"

echo
echo "=== 先清掉旧的 WebView2 用户目录，便于观察 ==="
taskkill //IM pvzge.exe //F >/dev/null 2>&1
taskkill //IM pvzge-single.exe //F >/dev/null 2>&1
sleep 1
rm -rf "$BASE" 2>/dev/null
echo "  已清理（若有）"

echo
echo "=== 启动 ==="
"$EXE" &
sleep 30

echo
echo "=== WebView2 用户目录 ==="
ls -la "$BASE" 2>&1 | head -8
echo "  缓存体积:"
du -sh "$BASE/EBWebView/Default/Cache" 2>/dev/null || echo "    无 Cache"
du -sh "$BASE/EBWebView/Default/Code Cache" 2>/dev/null || echo "    无 Code Cache"
echo "  Default 下重点项:"
ls "$BASE/EBWebView/Default" 2>/dev/null | grep -iE "local storage|indexeddb|session storage|Cache" || true

echo
echo "=== 进程还在吗（在=窗口正常开着）==="
tasklist 2>/dev/null | grep -i "pvzge" | head -5 || echo "  没进程了（可能崩了）"

echo
echo "=== 关闭 ==="
taskkill //IM pvzge.exe //F >/dev/null 2>&1
sleep 1
echo "  已关闭"
