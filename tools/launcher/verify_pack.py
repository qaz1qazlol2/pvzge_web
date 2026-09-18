#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验单文件 exe 的内嵌归档：索引可读 + 解压内容与磁盘一致。"""
import json
import os
import struct
import sys
import zlib

def main():
    # 默认值全部相对本脚本推导（tools/launcher/ 的上两级是仓库根），不写死机器路径
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    exe = sys.argv[1] if len(sys.argv) > 1 else os.path.join(repo, "dist", "PvZGE-Gardendless.exe")
    game = sys.argv[2] if len(sys.argv) > 2 else os.path.join(repo, "docs")
    exe = os.path.abspath(exe)
    game = os.path.abspath(game)

    print("exe :", exe)
    print("大小:", "%.2f GB" % (os.path.getsize(exe) / 1024.0 / 1024 / 1024))

    f = open(exe, "rb")
    f.seek(-16, 2)
    foot = f.read(16)
    idxlen = struct.unpack("<Q", foot[:8])[0]
    magic = foot[8:]
    print("magic:", magic)
    if magic != b"PVZGEARC":
        print("!! magic 不对")
        return 1
    f.seek(-16 - idxlen, 2)
    idx = json.loads(f.read(idxlen).decode("utf-8"))
    entries = {e[0]: e for e in idx["e"]}
    print("index: %d 条目" % len(entries))

    targets = [
        "index.html",
        "application.js",
        "tmpPatch.js",
        "src/system.bundle.js",
        "assets/main/index.js",
        "assets/resources/config.json",
        "assets/resources/import/0a/0a278bb49.json",
        "assets/resources/native/89/89b35a32.mp3",
        "assets/resources/native/b7/b7000006.mp3",
        "cocos-js/assets/spine-17c81aa0.wasm",
    ]
    ok = True
    print()
    print("%-48s %-4s %12s %12s  %s" % ("条目", "方法", "存储", "原始", "结果"))
    print("-" * 100)
    for rel in targets:
        e = entries.get(rel)
        if not e:
            print("%-48s 缺失!!" % rel)
            ok = False
            continue
        _, off, slen, rawlen, method = e
        f.seek(off)
        data = f.read(slen)
        disk_path = os.path.join(game, rel.replace("/", os.sep))
        if not os.path.isfile(disk_path):
            print("%-48s 磁盘无此文件，跳过" % rel)
            continue
        disk = open(disk_path, "rb").read()
        if method == 0:
            good = (data == disk)
            res = "store 一致" if good else "store 不符!!"
        else:
            try:
                d = zlib.decompressobj(-15)
                out = d.decompress(data) + d.flush()
                good = (out == disk)
                res = "裸deflate 解压一致" if good else "裸deflate 内容不符!!"
            except Exception as ex:
                good = False
                res = "裸deflate 失败: %s" % ex
        ok = ok and good
        print("%-48s %-4d %12d %12d  %s" % (rel, method, slen, rawlen, res))

    print()
    print("RESULT:", "ALL OK" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
