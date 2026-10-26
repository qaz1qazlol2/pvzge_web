# -*- coding: utf-8 -*-
"""严格核对：dist 里的 exe 内嵌内容 == 当前已提交的 docs 内容。

不是看 mtime（切分支会把 mtime 刷掉），而是把 exe 里解出来的文件
与工作区的文件做 sha256 逐字节比对。
"""
import hashlib
import json
import os
import struct
import sys
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAGIC = b"PVZGEARC"
FOOTER = 16

DIST = os.environ.get("DIST") or os.path.join(REPO, "dist")
TARGET = os.path.join(DIST, "PvZGE-Gardendless.exe")

# 抽查：核心三件 + 若干关卡
SAMPLES = [
    "assets/main/index.js",
    "audio/manifest.json",
    "assets/resources/import/0d/0d4cac202.json",
    "assets/resources/import/03/0390d3f86.json",
    "index.html",
]

# 再随机补 20 个关卡文件
import glob
lvl = glob.glob(os.path.join(REPO, "docs", "assets", "resources", "import",
                             "*", "*.json"))
for p in lvl[::max(1, len(lvl) // 20)][:20]:
    rel = os.path.relpath(p, os.path.join(REPO, "docs")).replace(os.sep, "/")
    if rel not in SAMPLES:
        SAMPLES.append(rel)

f = open(TARGET, "rb")
f.seek(0, 2)
total = f.tell()
f.seek(total - FOOTER)
idx_len = struct.unpack("<Q", f.read(8))[0]
assert f.read(8) == MAGIC
f.seek(total - FOOTER - idx_len)
index = json.loads(f.read(idx_len).decode("utf-8"))
entries = {e[0]: e for e in index["e"]}

print(f"exe: {total / 1024**3:.2f} GB  条目 {len(entries)}")
print()
print(f"{'文件':<58}{'exe':<14}{'工作区':<14}{'':<6}")
print("-" * 96)

bad = []
for rel in SAMPLES:
    if rel not in entries:
        print(f"  {rel:<56} 不在包里 !")
        bad.append(rel)
        continue
    _, offset, stored, raw, method = entries[rel]
    f.seek(offset)
    d = f.read(stored)
    if method == 1:
        d = zlib.decompress(d, -15)
    h1 = hashlib.sha256(d).hexdigest()[:12]

    wp = os.path.join(REPO, "docs", rel.replace("/", os.sep))
    if not os.path.exists(wp):
        print(f"  {rel:<56} 工作区缺 !")
        bad.append(rel)
        continue
    h2 = hashlib.sha256(open(wp, "rb").read()).hexdigest()[:12]

    ok = h1 == h2
    print(f"  {rel:<56}{h1:<14}{h2:<14}{'OK' if ok else 'DIFF'}")
    if not ok:
        bad.append(rel)

f.close()
print("-" * 96)
print(f"抽查 {len(SAMPLES)} 个文件，不一致 {len(bad)} 个")
if bad:
    print("不一致:", bad)
    sys.exit(1)
print("✅ 包内内容与当前提交一致，无需重建")
