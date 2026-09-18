#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把游戏目录打包进 launcher exe 的尾部，生成「单文件 exe」。

用法:
    python pack.py <launcher.exe> <游戏目录> [输出exe]

归档布局（追加在 exe 末尾）:
    [exe 原始字节][所有文件的数据块][index JSON (UTF-8)][uint64 indexLength][8字节 "PVZGEARC"]

index: {"v":1,"e":[["相对路径", offset, storedLen, rawLen, method], ...]}
    method: 0=store(原样)  1=deflate(已压缩)
"""
import json
import os
import struct
import sys
import zlib

# 必须最早导入：Windows 下 stdout 走管道时会退回 cp936，中文全乱码。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

MAGIC = b"PVZGEARC"
FOOTER = 16
CHUNK = 4 * 1024 * 1024

# 这些后缀用 deflate（文本类），其余原样存储
DEFLATE_EXT = {".js", ".mjs", ".json", ".html", ".htm", ".css", ".svg",
               ".txt", ".xml", ".map", ".wasm"}

# 排除的文件（我们自己生成的备份，不该进发布包）
EXCLUDE_SUBSTR = (".bak", ".orig_bak", ".b_full", ".b_pre", ".b_victory")


def should_exclude(rel):
    low = rel.lower()
    if any(s in low for s in EXCLUDE_SUBSTR):
        return True
    base = os.path.basename(low)
    if base.startswith(".") or base in ("thumbs.db", "desktop.ini"):
        return True
    return False


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return "%.2f %s" % (n, u)
        n /= 1024.0


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    launcher = sys.argv[1]
    gamedir = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else None

    if not os.path.isfile(launcher):
        print("!! 找不到 launcher exe:", launcher); return 1
    if not os.path.isdir(gamedir):
        print("!! 找不到游戏目录:", gamedir); return 1
    if not os.path.isfile(os.path.join(gamedir, "index.html")):
        print("!! 该目录下没有 index.html，可能不是游戏目录:", gamedir)
    if not out:
        base = os.path.splitext(os.path.basename(launcher))[0]
        out = os.path.join(os.path.dirname(os.path.abspath(launcher)),
                           base + "-single.exe")
    out = os.path.abspath(out)

    # 先收集文件列表
    files = []
    skipped = []
    for dirpath, dirnames, filenames in os.walk(gamedir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, gamedir).replace("\\", "/")
            if should_exclude(rel):
                skipped.append(rel)
                continue
            try:
                sz = os.path.getsize(full)
            except OSError:
                continue
            files.append((full, rel, sz))
    files.sort(key=lambda x: x[1])

    total_raw = sum(f[2] for f in files)
    print("=" * 70)
    print("  launcher :", launcher, "(%s)" % human(os.path.getsize(launcher)))
    print("  游戏目录 :", gamedir)
    print("  文件数   : %d   原始总量 %s" % (len(files), human(total_raw)))
    print("  排除     : %d 个（备份/隐藏文件）" % len(skipped))
    print("  输出     :", out)
    print("=" * 70)
    print("  正在写入…")

    # 拷 exe + 追加数据
    with open(out, "wb") as fo:
        with open(launcher, "rb") as fi:
            while True:
                b = fi.read(CHUNK)
                if not b:
                    break
                fo.write(b)
        base_len = fo.tell()

        entries = []
        done_raw = 0
        for i, (full, rel, sz) in enumerate(files, 1):
            ext = os.path.splitext(rel)[1].lower()
            method = 1 if ext in DEFLATE_EXT else 0
            offset = fo.tell()

            if method == 1:
                # 关键：wbits=-15 输出「裸 deflate」。.NET 的 DeflateStream 只认裸 deflate，
                # 默认的 zlib 格式(带 2 字节头 + adler32 尾)会解压失败。
                comp = zlib.compressobj(9, zlib.DEFLATED, -15)
                stored = 0
                with open(full, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        cb = comp.compress(b)
                        if cb:
                            fo.write(cb)
                            stored += len(cb)
                    cb = comp.flush()
                    if cb:
                        fo.write(cb)
                        stored += len(cb)
                # 若压缩后反而更大，就退回 store（需要重写该段，简单起见保留 deflate 结果即可）
            else:
                stored = 0
                with open(full, "rb") as f:
                    while True:
                        b = f.read(CHUNK)
                        if not b:
                            break
                        fo.write(b)
                        stored += len(b)

            entries.append([rel, offset, stored, sz, method])
            done_raw += sz
            if i % 500 == 0 or i == len(files):
                pct = 100.0 * done_raw / max(total_raw, 1)
                sys.stdout.write("\r  进度 %5.1f%%  (%d/%d)  已写 %s   " %
                                 (pct, i, len(files), human(fo.tell() - base_len)))
                sys.stdout.flush()

        # index + footer
        index = json.dumps({"v": 1, "e": entries}, ensure_ascii=False,
                           separators=(",", ":")).encode("utf-8")
        fo.write(index)
        fo.write(struct.pack("<Q", len(index)))
        fo.write(MAGIC)

    print()
    print("=" * 70)
    print("  完成:", out)
    print("  exe 大小: %s   内嵌数据: %s" %
          (human(os.path.getsize(out)), human(os.path.getsize(out) - base_len)))
    print("  index: %s / %d 条目" % (human(len(index)), len(entries)))
    print("  压缩条目 deflate=%d  store=%d" %
          (sum(1 for e in entries if e[4] == 1), sum(1 for e in entries if e[4] == 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
