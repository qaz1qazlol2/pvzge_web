#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PvZ2 Gardendless 本地服务器（独立版，供一键启动脚本使用）
用法: python server.py [--root <游戏目录>] [--port 8123] [--open]
"""
import argparse, datetime, http.server, os, socketserver, sys, threading, webbrowser

EXTRA_MIME = {
    ".wasm": "application/wasm",
    ".js": "text/javascript", ".mjs": "text/javascript",
    ".json": "application/json",
    ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
    ".bin": "application/octet-stream",
    ".pvr": "application/octet-stream", ".astc": "application/octet-stream",
    ".pkm": "application/octet-stream",
    ".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2",
    ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
    ".css": "text/css", ".html": "text/html",
}


def make_handler(root, quiet, logfile):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def guess_type(self, path):
            ext = os.path.splitext(path)[1].lower()
            if ext in EXTRA_MIME:
                return EXTRA_MIME[ext]
            return super().guess_type(path)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, fmt, *args):
            line = "[%s] %s %s" % (datetime.datetime.now().strftime("%H:%M:%S"),
                                   self.address_string(), fmt % args)
            if not quiet:
                print(line, flush=True)
            if logfile:
                try:
                    with open(logfile, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                except Exception:
                    pass

    return Handler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--open", action="store_true", help="启动后用默认浏览器打开")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--logfile", default=None)
    a = ap.parse_args()

    root = a.root or os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
    if not os.path.isdir(root):
        print("!! 目录不存在:", root)
        print("   用 --root 指定游戏目录，或把游戏放到同级的 web\\ 下")
        return 1
    if not os.path.isfile(os.path.join(root, "index.html")):
        print("!! 该目录下没有 index.html，可能不是正确的游戏目录:", root)

    handler = make_handler(root, a.quiet, a.logfile)
    for port in range(a.port, a.port + 10):
        try:
            httpd = Server(("127.0.0.1", port), handler)
            break
        except OSError as e:
            print("端口 %d 占用(%s)，试下一个…" % (port, e))
    else:
        print("!! 找不到可用端口")
        return 1

    url = "http://127.0.0.1:%d/" % port
    print("=" * 56)
    print("  PvZ2 Gardendless 本地服务器")
    print("  目录:", root)
    print("  地址:", url)
    print("  Ctrl+C 停止")
    print("=" * 56)
    if a.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
