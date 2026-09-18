#!/usr/bin/env bash
# =====================================================================
#  实测 Web 服务器：--info / 首页 / mp3 字节一致 / wasm MIME / Range / 目录穿越
#  用法: bash test_ws.sh [exe路径] [游戏目录]
#  默认: exe = tools/webserver/publish/PvZGE-WebServer.exe   游戏目录 = <仓库>/docs
# =====================================================================
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ws() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
HERE="$(ws "$SELF_DIR")"
ROOT="$(ws "$(cd "$SELF_DIR/../.." && pwd)")"

EXE="${1:-$HERE/publish/PvZGE-WebServer.exe}"
G="${2:-$ROOT/docs}"
PORT="${PORT:-8150}"
TMP="${TMPDIR:-/tmp}/pvzge_ws_test.log"

if [ ! -f "$EXE" ]; then
  echo "[错误] 找不到 Web 服务器 exe: $EXE"
  echo "       先跑 bash build.sh web，或把 exe 路径作为第一个参数传进来。"
  exit 1
fi
if [ ! -f "$G/index.html" ]; then
  echo "[错误] 游戏目录不对（无 index.html）: $G"
  exit 1
fi

echo "=== --info（无内嵌）==="
"$EXE" --info 2>&1
echo
echo "=== 起服务（磁盘目录模式，端口 $PORT）==="
"$EXE" --root "$G" --port "$PORT" > "$TMP" 2>&1 &
PID=$!
sleep 4
B="http://127.0.0.1:$PORT"
echo "  首页 HTTP: $(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$B/")"
echo "  标题: $(curl -s --max-time 10 "$B/" | grep -oE '<title>[^<]*' | head -1)"
echo "  Egypt mp3 服务: $(curl -s --max-time 30 "$B/assets/resources/native/89/89b35a32.mp3" | wc -c) 字节"
echo "  Egypt mp3 磁盘: $(stat -c %s "$G/assets/resources/native/89/89b35a32.mp3") 字节"
echo "  wasm MIME: $(curl -sI --max-time 10 "$B/cocos-js/assets/spine-17c81aa0.wasm" | grep -i content-type)"
echo "  Range: $(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'Range: bytes=0-99' "$B/assets/resources/native/89/89b35a32.mp3")"
echo "  穿越: $(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$B/..%2f..%2fWindows/win.ini")"
echo "  --- 启动信息 ---"
head -8 "$TMP"
kill $PID 2>/dev/null
echo "  已停止"
