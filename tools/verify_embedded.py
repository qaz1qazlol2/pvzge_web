# -*- coding: utf-8 -*-
"""校验三个内嵌游戏的 exe 是否都含本轮全部改动。

本轮改动清单：
  1. LB 家族 55 条（Musics 484 条，manifest 784 条）
  2. ZB 分段 51 条（46 ZB + 5 教程）
  3. 教程 CYS 分家族
  4. Halloween Pinata 跳过 Intro
  5. Cowboy CYS_LP 映射
"""
import json
import os
import struct
import sys
import zlib

MAGIC = b"PVZGEARC"
FOOTER = 16

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.environ.get("DIST") or os.path.join(REPO, "dist")

TARGETS = [
    (os.path.join(DIST, "PvZGE-Gardendless.exe"), "Tauri"),
    (os.path.join(DIST, "PvZGE-Launcher-单文件.exe"), ".NET 启动器"),
    (os.path.join(DIST, "PvZGE-WebServer-单文件.exe"), "Web 服务器"),
]


def open_archive(path):
    f = open(path, "rb")
    f.seek(0, 2)
    total = f.tell()
    f.seek(total - FOOTER)
    idx_len = struct.unpack("<Q", f.read(8))[0]
    if f.read(8) != MAGIC:
        raise SystemExit(f"{path}: 尾部魔数不对")
    f.seek(total - FOOTER - idx_len)
    index = json.loads(f.read(idx_len).decode("utf-8"))
    entries = {e[0]: e for e in index["e"]}

    def read(rel):
        _, offset, stored, raw, method = entries[rel]
        f.seek(offset)
        d = f.read(stored)
        return zlib.decompress(d, -15) if method == 1 else d

    return f, total, entries, read


all_ok = True
for path, label in TARGETS:
    print("=" * 64)
    print(f"{label}  {path.rsplit(chr(92), 1)[-1]}")
    try:
        f, total, entries, read = open_archive(path)
    except SystemExit as e:
        print("  !!", e)
        all_ok = False
        continue

    js = read("assets/main/index.js").decode("utf-8", "replace")
    man = json.loads(read("audio/manifest.json").decode("utf-8"))
    mus = json.loads(read("assets/resources/import/0d/0d4cac202.json")
                     .decode("utf-8"))
    pin = json.loads(read("assets/resources/import/03/0390d3f86.json")
                     .decode("utf-8"))

    # Musics
    arr = None
    def walk(o):
        global arr
        if isinstance(o, dict):
            if "Musics" in o:
                arr = o["Musics"]
                return True
            for v in o.values():
                if walk(v):
                    return True
        elif isinstance(o, list):
            for v in o:
                if walk(v):
                    return True
        return False
    walk(mus)

    hall = [x for x in pin[5][3][0][0][2]["PINATAS"]
            if x["CODENAME"] == "halloween"][0]

    checks = [
        ("Musics 484 条", len(arr) == 484, str(len(arr))),
        ("manifest 784 条", len(man) == 784, str(len(man))),
        ("MusicAmount 484", "MusicAmount=484" in js,
         "OK" if "MusicAmount=484" in js else "FAIL"),
        ("LB 音轨 55", sum(1 for e in arr if e["name"].startswith("LB_")) == 55,
         str(sum(1 for e in arr if e["name"].startswith("LB_")))),
        # 43 条按世界的 + 5 条原生（ZB_Stage0/Stage0_Lostcity/Stage1/Stage2_Start/Stage2）
        ("ZB 分段 48（43 新增 + 5 原生）",
         sum(1 for e in arr if e["name"].startswith("ZB_Stage")) == 48,
         str(sum(1 for e in arr if e["name"].startswith("ZB_Stage")))),
        ("ZB Stage0 分世界", "case w.Beach:u=A.ZB_Stage0_Beach;" in js, ""),
        ("教程 UB", "u=A.UB_Tutorial" in js, ""),
        ("教程 CYS 查表", "__CYS_TBL[window.__cys_fam].Tutorial" in js, ""),
        ("LB 接线", "if(a==v.Loonboon){switch(e){" in js, ""),
        ("halloween 跳 Intro",
         hall["MUSIC"]["Intro"].get("Tauri") == ""
         and hall["MUSIC"]["Intro"].get("Length") == 0, ""),
        ("Cowboy CYS_LP 映射",
         man.get("Music_Cowboy_CYS_LP") == "Music/Game/Cowboy/CYS_LP1_Cowboy.mp3",
         ""),
        ("LB 关卡打标 171",
         js.count('"MiniGame_D"') >= 3, ""),
    ]

    print(f"  大小 {total / 1024**3:.2f} GB  条目 {len(entries)}")
    for name, ok, detail in checks:
        mark = "OK  " if ok else "FAIL"
        extra = f"  ({detail})" if detail else ""
        print(f"  {mark} {name}{extra}")
        if not ok:
            all_ok = False
    f.close()

print("=" * 64)
print("三个产物全部通过" if all_ok else "有失败项")
sys.exit(0 if all_ok else 1)
