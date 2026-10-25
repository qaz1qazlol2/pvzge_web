# -*- coding: utf-8 -*-
"""给 PVZGE 加 LB（Loonboon / MiniGame_D / 保龄球）音乐体系 —— 照 ZBT 的模样。

数据层：音频文件 + manifest + Musics。
代码层在另一个脚本。

命名约定（完全照 ZBT）
----------------------
ZBT 的做法：  manifest key = "rk_" + 名字
              音频路径   = Music/inGame/<名字>/<名字>.mp3
              Musics     = {name, tauri:"rk_<名字>", musicLength}

LB 完全一样。

musicLength 规则（照 ZBT 实测确认）
-----------------------------------
ZBT_Victory   cfg=4.71  实际 4.760  → 实测 - 0.05
ZBT_Lose      cfg=7.03  实际 7.083  → 实测 - 0.05

所以：
  主音轨      181（Modern 用 193，照 ZBT 特例）
  CYS/Lose/Victory   实测 - 0.05
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

REPO = r"D:\git\pvzge_web"
SRC = r"D:\temp\音乐补丁\custom_music"
DOCS = os.path.join(REPO, "docs")
AUDIO_ROOT = os.path.join(DOCS, "audio", "Music", "inGame")
MANIFEST = os.path.join(DOCS, "audio", "manifest.json")
FFPROBE = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\ffprobe.EXE"

# 主音轨：世界名 → 音频名（BSMT 素材里 LB_<世界>）
MAIN_WORLDS = [
    ("Egypt", "Egypt"), ("Pirate", "Pirate"), ("Cowboy", "Cowboy"),
    ("Kongfu", "Kongfu"), ("Future", "Future"), ("Dark", "Dark"),
    ("Beach", "Beach"), ("Iceage", "Iceage"), ("Lostcity", "Lostcity"),
    ("Sky", "Sky"), ("Dino", "Dino"), ("Modern", "Modern"),
    ("Ballad", "Ballad"), ("Punk", "Punk"), ("Pop", "Pop"),
    ("Rap", "Rap"), ("Eightbit", "Eightbit"), ("Metal", "Metal"),
    ("Tutorial", "Tutorial"),
]

# CYS：素材里的名字
CYS_WORLDS = [
    "Egypt", "Pirate", "Cowboy", "Kongfu", "Future", "Dark", "Beach",
    "Iceage", "Lostcity", "Sky", "Dino", "Modern", "Ballad", "Tutorial",
]

# Victory：通用 + 分世界
VICTORY_WORLDS = [
    "Beach", "Cowboy", "Dark", "Dino", "Eighties", "Future",
    "Iceage", "Lostcity", "Modern", "Pirate",
]

# Lose：通用 + 分世界
LOSE_WORLDS = [
    "Beach", "Cowboy", "Dark", "Dino", "Eighties", "Future",
    "Iceage", "Lostcity", "Modern", "Pirate",
]


def dur(p):
    r = subprocess.run([FFPROBE, "-v", "quiet", "-show_entries",
                        "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return -1.0


def build_tracks():
    """返回 [(track_name, src_file, music_len, duration)]"""
    out = []

    for _, w in MAIN_WORLDS:
        name = f"LB_{w}"
        src = f"{name}.mp3"
        out.append((name, src, 193 if w == "Modern" else 181, None))

    for w in CYS_WORLDS:
        name = f"LB_CYS_{w}"
        src = f"{name}.mp3"
        out.append((name, src, None, "dur-0.05"))

    # 通用 Victory（不带世界后缀）
    out.append(("LB_Victory", "LB_Victory.mp3", None, "dur-0.05"))
    for w in VICTORY_WORLDS:
        name = f"LB_Victory_{w}"
        out.append((name, f"{name}.mp3", None, "dur-0.05"))

    # 通用 Lose
    out.append(("LB_Lose", "LB_Lose.mp3", None, "dur-0.05"))
    for w in LOSE_WORLDS:
        name = f"LB_Lose_{w}"
        out.append((name, f"{name}.mp3", None, "dur-0.05"))

    return out


def main(apply=False):
    tracks = build_tracks()
    print(f"=== LB 音轨清单：{len(tracks)} 条 ===")

    rows = []
    missing = []
    for name, src, fixed_len, formula in tracks:
        p = os.path.join(SRC, src)
        if not os.path.exists(p):
            missing.append(src)
            continue
        d = dur(p)
        if fixed_len is not None:
            ml = fixed_len
        else:
            ml = round(d - 0.05, 2)
        rows.append((name, src, ml, d))

    if missing:
        print(f"!! 缺素材 {len(missing)} 个：")
        for m in missing:
            print("   ", m)
        if apply:
            raise SystemExit("缺素材，中止")

    print(f"  可用 {len(rows)} 条")
    print()
    print(f"{'音轨名':<26}{'musicLength':>12}{'实测':>9}")
    print("-" * 50)
    for name, src, ml, d in rows:
        print(f"{name:<26}{ml:>12}{d:>9.3f}")

    if not apply:
        print()
        print("[dry-run] 未落盘。加 --apply 执行。")
        return 0

    # ---------- 1) 复制音频 ----------
    print()
    print("=== 1/3 复制音频 ===")
    copied = 0
    for name, src, ml, d in rows:
        dst_dir = os.path.join(AUDIO_ROOT, name)
        dst = os.path.join(dst_dir, name + ".mp3")
        if os.path.exists(dst):
            continue
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(os.path.join(SRC, src), dst)
        copied += 1
    print(f"  新复制 {copied} 个，已有 {len(rows) - copied} 个")

    # ---------- 2) manifest ----------
    print()
    print("=== 2/3 manifest ===")
    # 按字节操作，保住文件原有的混用换行符（549 CRLF + 131 LF）。
    # 用文本模式重写整文件会让 git 把 551 行全标成改动。
    data = open(MANIFEST, "rb").read()

    new_lines = []
    for name, src, ml, d in rows:
        key = "rk_" + name
        if ('"%s"' % key).encode() in data:
            continue
        rel = "Music/inGame/%s/%s.mp3" % (name, name)
        new_lines.append('  "%s": "%s"' % (key, rel))

    added = len(new_lines)
    if new_lines:
        # 结尾形如：...Modern.mp3"\n}\r\n
        # 在最后那个 \n} 之前插入：先给原本最后一行补逗号，再追加新行
        close = data.rfind(b"\n}")
        if close < 0:
            raise SystemExit("manifest 结构异常（找不到结尾 }）")
        head = data[:close]
        seg = head.rstrip()
        # ⚠️ 行间必须是 ",\n"，只加 "\n" 会让 JSON 缺分隔符
        body = seg + b"," + b"".join(
            b"\n" + l.encode("utf-8") + b"," for l in new_lines[:-1])
        body += b"\n" + new_lines[-1].encode("utf-8")
        out = body + data[close:]

        json.loads(out.decode("utf-8"))  # 先校验
        open(MANIFEST, "wb").write(out)
        print("  新增 %d 个 key，已写入" % added)
    else:
        print("  无需新增")

    # 校验（用统一读法，避免 newline 干扰）
    man = json.loads(open(MANIFEST, "rb").read().decode("utf-8"))
    miss = [n for n, _, _, _ in rows if ("rk_" + n) not in man]
    print("  manifest 条目:", len(man), " 缺失:", miss if miss else 0)

    print()
    print("完成。下一步：跑 patch_lb_index.py 处理代码层。")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
