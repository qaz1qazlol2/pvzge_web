# -*- coding: utf-8 -*-
"""接入 ZB（僵王博士）分段音轨 + 教程关缺口 —— 照 ZBT/LB 的模式。

分两批
------
A) ZB 分段 46 条
   Intro 3（Beach/Eighties/Modern）/ Stage0 10 / Stage1 11 /
   Stage2_Start 11 / Stage2 11

   ⚠️ 素材里 Stage2 目录**混了 Stage2_Start 的副本**，
   分类时必须先判 Stage2_Start 再判 Stage2，否则会重复计数。

B) 教程关缺口（素材里有的才接）
   UB_Tutorial / MG_Tutorial / ZBT_Tutorial   （LB_Tutorial 已有）
   CYS_LP_Tutorial / VIC_Tutorial

musicLength 规则
----------------
Stage0=55 / Stage1=62 / Stage2_Start=4 / Stage2=57  照官方硬编码
（这几段是循环段，官方调过循环点；实测「有声结束」：
 Stage0 55.3~55.8、Stage1 63.0、Stage2_Start 3.4、Stage2 58.4
 —— 官方值都在附近，直接沿用）

Intro 是**一次性**（g=!1，播完切 Stage0），没有循环点概念，
按「实测 − 0.05」算。
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

REPO = r"D:\git\pvzge_web"
SRC = r"D:\temp\音乐补丁\custom_music"
DOCS = os.path.join(REPO, "docs")
AUDIO_ROOT = os.path.join(DOCS, "audio", "Music", "inGame")
MANIFEST = os.path.join(DOCS, "audio", "manifest.json")
MUSICS = os.path.join(DOCS, "assets", "resources", "import",
                      "0d", "0d4cac202.json")
PROBE = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\ffprobe.EXE"

# 官方硬编码循环点
HARD_LEN = {
    "Stage0": 55.0,
    "Stage1": 62.0,
    "Stage2_Start": 4.0,
    "Stage2": 57.0,
}

WORLDS = ["Egypt", "Pirate", "Cowboy", "Kongfu", "Future", "Dark", "Beach",
          "Iceage", "Lostcity", "Sky", "Dino", "Modern", "Eighties",
          "Ballad", "Punk", "Pop", "Rap", "Eightbit", "Metal", "Tutorial"]

# 教程缺口（素材里确实有的那几个）
TUTORIAL_EXTRA = [
    ("UB_Tutorial", "UB_CYS_Tutorial"),      # 同行便于对照，仅说明用途
    ("MG_Tutorial", "MG_CYS_Tutorial"),
    ("ZBT_Tutorial", "ZBT_CYS_Tutorial"),
    ("CYS_LP_Tutorial", None),
    ("VIC_Tutorial", None),
]


def dur(p):
    r = subprocess.run([PROBE, "-v", "quiet", "-show_entries",
                        "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return -1.0


def classify(src_name):
    """ZB_Stage2_Start_X 必须先于 ZB_Stage2_X 判断。"""
    n = src_name
    for seg in ("Intro", "Stage0", "Stage1", "Stage2_Start", "Stage2"):
        pre = f"ZB_{seg}_"
        if n.startswith(pre):
            return seg, n[len(pre):]
    return None, None


def build_zb_tracks():
    """返回 [(track_name, src_file, music_len, duration)]"""
    out = []
    files = sorted(f for f in os.listdir(SRC) if f.startswith("ZB_") and f.endswith(".mp3"))
    for f in files:
        base = f[:-4]
        seg, world = classify(base)
        if not seg:
            print("  !! 无法分类:", base)
            continue
        p = os.path.join(SRC, f)
        d = dur(p)
        if seg == "Intro":
            ml = round(d - 0.05, 2)
        else:
            ml = HARD_LEN[seg]
        out.append((base, f, ml, d))
    return out


def build_tutorial_tracks():
    out = []
    for name, _ in TUTORIAL_EXTRA:
        f = name + ".mp3"
        p = os.path.join(SRC, f)
        if not os.path.exists(p):
            print(f"  !! 素材缺 {f}，跳过")
            continue
        d = dur(p)
        # ⚠️ 判据不能只看 endswith("_Tutorial") ——
        #    CYS_LP_Tutorial / VIC_Tutorial 也以它结尾，但它们是短前奏。
        if name in ("UB_Tutorial", "MG_Tutorial", "ZBT_Tutorial",
                    "LB_Tutorial"):
            ml = 181.0                     # 家族主音轨，照 181 惯例
        elif name == "CYS_LP_Tutorial":
            ml = 18.0                      # 官方：教程 CYS 循环 18s
        else:
            ml = round(d - 0.05, 2)        # 其余按 实测 − 0.05
        out.append((name, f, ml, d))
    return out


def main(apply=False):
    zb = build_zb_tracks()
    tut = build_tutorial_tracks()
    allt = zb + tut

    print(f"=== 待接入 {len(allt)} 条 ===")
    print(f"  ZB 分段: {len(zb)}")
    for seg in ("Intro", "Stage0", "Stage1", "Stage2_Start", "Stage2"):
        n = sum(1 for a, _, _, _ in zb if classify(a)[0] == seg)
        print(f"    {seg:<14} {n}")
    print(f"  教程缺口: {len(tut)}")
    for a, _, ml, d in tut:
        print(f"    {a:<20} len={ml:<7} 实测={d:.3f}")
    print()

    if not apply:
        print("[dry-run] 加 --apply 执行")
        return 0

    # ---------- 1) 复制音频 ----------
    print("=== 1/3 复制音频 ===")
    copied = 0
    for name, src, ml, d in allt:
        dst_dir = os.path.join(AUDIO_ROOT, name)
        dst = os.path.join(dst_dir, name + ".mp3")
        if os.path.exists(dst):
            continue
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(os.path.join(SRC, src), dst)
        copied += 1
    print(f"  新复制 {copied}")

    # ---------- 2) manifest ----------
    print()
    print("=== 2/3 manifest ===")
    data = open(MANIFEST, "rb").read()
    new_lines = []
    for name, src, ml, d in allt:
        key = "rk_" + name
        if ('"%s"' % key).encode() in data:
            continue
        rel = "Music/inGame/%s/%s.mp3" % (name, name)
        new_lines.append('  "%s": "%s"' % (key, rel))
    print(f"  待新增 {len(new_lines)} 个 key")
    if new_lines:
        close = data.rfind(b"\n}")
        if close < 0:
            raise SystemExit("manifest 结构异常")
        head = data[:close].rstrip()
        body = head + b"," + b"".join(
            b"\n" + l.encode("utf-8") + b"," for l in new_lines[:-1])
        body += b"\n" + new_lines[-1].encode("utf-8")
        out = body + data[close:]
        json.loads(out.decode("utf-8"))
        open(MANIFEST, "wb").write(out)
        print("  已写入")

    # ---------- 3) Musics ----------
    print()
    print("=== 3/3 Musics ===")
    raw = io.open(MUSICS, encoding="utf-8", errors="replace").read()
    i = raw.find('{"name":"WorldMap"')
    start = raw.rfind("[", 0, i)
    depth = 0
    for k in range(start, len(raw)):
        if raw[k] == "[":
            depth += 1
        elif raw[k] == "]":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    seg_txt = raw[start:end]
    arr = json.loads(seg_txt)
    exist = {e["name"] for e in arr}

    absent = [(n, ml) for n, _, ml, _ in allt if n not in exist]
    print(f"  现有 {len(arr)} 条，待追加 {len(absent)} 条")

    if absent:
        def num(v):
            return str(int(v)) if float(v) == int(v) else repr(float(v))

        items = ",".join(
            '{"name":"%s","tauri":"rk_%s","musicLength":%s}' % (n, n, num(ml))
            for n, ml in absent)
        new_seg = seg_txt[:-1] + "," + items + "]"
        out = raw[:start] + new_seg + raw[end:]
        chk = json.loads(new_seg)
        print(f"  新 Musics: {len(chk)} 条")
        # 顺序校验
        tail = [e["name"] for e in chk[len(arr):]]
        assert tail == [n for n, _ in absent], "追加顺序不一致"
        io.open(MUSICS, "w", encoding="utf-8", newline="").write(out)
        print("  已写入")

    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
