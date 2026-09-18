# -*- coding: utf-8 -*-
"""从 tools/launcher/src/Program.cs 抽取可复用的内核类，生成 tools/webserver/src/Shared.cs。
抽取：HttpMime / PayloadArchive / MiniHttpServer（按大括号配对精确切块）。

路径按本文件所在位置自动推导，无需参数：
    python tools/webserver/extract_shared.py
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))                 # tools/webserver
SRC = os.path.normpath(os.path.join(HERE, "..", "launcher", "src", "Program.cs"))
OUTDIR = os.path.join(HERE, "src")
OUT = os.path.join(OUTDIR, "Shared.cs")

WANT = ["HttpMime", "PayloadArchive", "MiniHttpServer"]

if not os.path.isfile(SRC):
    raise SystemExit("找不到源文件: %s" % SRC)

src = open(SRC, encoding="utf-8").read()


def find_class(src, name):
    """返回 (start, end) —— 含前面的 banner 注释行到类结束的 '}'"""
    m = re.search(r"^( *)internal (?:static |sealed )?class " + re.escape(name) + r"\b", src, re.M)
    if not m:
        raise SystemExit("找不到类: " + name)
    # 往前吞掉紧邻的注释行（// ==== ... 或 // 说明）
    start = m.start()
    lines = src[:start].split("\n")
    li = len(lines) - 1
    while li - 1 >= 0:
        prev = lines[li - 1].strip()
        if prev.startswith("//") or prev == "":
            li -= 1
        else:
            break
    start = len("\n".join(lines[:li])) + (1 if li > 0 else 0)
    # 大括号配对
    j = src.index("{", m.end())
    depth = 0
    k = j
    while k < len(src):
        c = src[k]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return start, k + 1
        k += 1
    raise SystemExit("大括号不配对: " + name)


chunks = []
for n in WANT:
    s, e = find_class(src, n)
    chunks.append(src[s:e])
    print(f"  抽取 {n}: {e - s} 字符")

os.makedirs(OUTDIR, exist_ok=True)
header = """// 本文件由工具自动生成（tools/webserver/extract_shared.py 从 tools/launcher/src/Program.cs 抽取），请勿手改。
// 内容：HttpMime（MIME 表）/ PayloadArchive（尾部归档读取）/ MiniHttpServer（HTTP 服务器）
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace PvzgeWeb
{
"""
body = "\n\n".join(chunks)
open(OUT, "w", encoding="utf-8").write(header + body + "\n}\n")
print("  已写出:", OUT, os.path.getsize(OUT), "字节")
