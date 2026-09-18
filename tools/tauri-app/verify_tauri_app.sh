#!/usr/bin/env bash
# =====================================================================
#  Tauri 壳实测（开发用）：
#    1) 测量增量重建时间（改一行 → 重建）
#    2) 重新打包 → 以 --log 运行 → 用请求日志证明游戏实际加载了哪些文件
#
#  用法: bash verify_tauri_app.sh [游戏目录]
# =====================================================================
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ws() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
HERE="$(ws "$SELF_DIR")"
ROOT="$(ws "$(cd "$SELF_DIR/../.." && pwd)")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python py; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
fi

GAMEDIR="${1:-$ROOT/docs}"
APP="$HERE/src-tauri/target/release/pvzge.exe"
OUT="$HERE/src-tauri/target/release/pvzge-single.exe"
LOG="$HERE/build_incremental.log"
BASE="${LOCALAPPDATA:-$HOME/AppData/Local}/com.pvzge.launcher"

echo "=============================================================="
echo "[1] 增量重建计时（touch 一个源文件后重新构建）"
echo "=============================================================="
touch "$HERE/src-tauri/src/main.rs"
T0=$(date +%s)
bash "$HERE/build_tauri.sh" "$HERE/src-tauri" > "$LOG" 2>&1
T1=$(date +%s)
echo "  >>> 增量重建耗时: $((T1-T0)) 秒"
grep -E "Finished|Compiling pvzge|error" "$LOG" | tail -5
ls -la "$APP"

echo
echo "=============================================================="
echo "[2] 重新打包单文件"
echo "=============================================================="
rm -f "$OUT"
"$PY" "$ROOT/tools/launcher/pack.py" "$APP" "$GAMEDIR" "$OUT" 2>&1 | tail -5
ls -la "$OUT"

echo
echo "=============================================================="
echo "[3] 以 --log 运行 35 秒，看游戏到底请求了哪些文件"
echo "=============================================================="
rm -rf "$BASE" 2>/dev/null
"$OUT" --log &
sleep 35
taskkill //IM pvzge.exe //F >/dev/null 2>&1
taskkill //IM pvzge-single.exe //F >/dev/null 2>&1
sleep 1

REQ="$BASE/requests.log"
if [ -f "$REQ" ]; then
  echo "  请求总数: $(wc -l < "$REQ")"
  echo "  --- 按状态统计 ---"
  awk '{print $1}' "$REQ" | sort | uniq -c | sort -rn | head -5
  echo "  --- 前 20 条 ---"
  head -20 "$REQ"
  echo "  --- 关键文件是否被请求 ---"
  for f in "/index.html" "assets/main/index.js" "assets/resources/config.json" "cocos-js/cc.js" "assets/resources/native/89/89b35a32.mp3"; do
    n=$(grep -c " $f\$" "$REQ" 2>/dev/null || echo 0)
    echo "    $f  ->  $n 次"
  done
else
  echo "  !! 没有 requests.log（页面可能没发起请求）"
fi

echo
echo "  --- WebView2 的 origin（从 leveldb 读） ---"
"$PY" - "$BASE" <<'PYEOF' 2>/dev/null
import os, re, sys
ld = os.path.join(sys.argv[1], "EBWebView", "Default", "Local Storage", "leveldb")
if os.path.isdir(ld):
    for fn in sorted(os.listdir(ld)):
        fp = os.path.join(ld, fn)
        if os.path.isfile(fp):
            b = open(fp, "rb").read()
            o = sorted(set(x.decode() for x in re.findall(rb"https?://[A-Za-z0-9\.\-:\[\]]+", b)))
            k = sorted(set(x.decode() for x in re.findall(rb"PvZ2_[A-Za-z]+", b)))
            print(f"    {fn}: origins={o} keys={k}")
else:
    print("    leveldb 不存在")
PYEOF
