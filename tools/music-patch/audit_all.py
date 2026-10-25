# -*- coding: utf-8 -*-
"""全面盘点：哪些做了，哪些没做。只读，不改任何文件。"""
import glob
import io
import json
import os
import re
import subprocess

REPO = r"D:\git\pvzge_web"
DOCS = os.path.join(REPO, "docs")
IMP = os.path.join(DOCS, "assets", "resources", "import")
SRC = r"D:\temp\音乐补丁\custom_music"
musics_json = os.path.join(IMP, "0d", "0d4cac202.json")

# ---- 读 Musics ----
raw = io.open(musics_json, encoding="utf-8", errors="replace").read()
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
arr = json.loads(raw[start:end])
names = {e["name"] for e in arr}

js = io.open(os.path.join(DOCS, "assets", "main", "index.js"),
             encoding="utf-8", errors="replace").read()
man = json.loads(open(os.path.join(DOCS, "audio", "manifest.json"),
                      "rb").read().decode("utf-8"))

src_files = {f[:-4] for f in os.listdir(SRC) if f.endswith(".mp3")}

print("=" * 68)
print("  PvZGE 音乐改造 —— 全面盘点")
print("=" * 68)
print()

# ============ 1. 四家族的完整性 ============
print("① 四类平级家族的音轨完整度")
print("-" * 68)
FAMS = {"UB": "MiniGame_A", "MG": "MiniGame_B", "ZBT": "MiniGame_C",
        "LB": "MiniGame_D"}
print(f"{'家族':<6}{'MusicType':<14}{'主音轨':>7}{'CYS':>6}{'Victory':>9}{'Lose':>6}")
print("-" * 68)
for fam, mt in FAMS.items():
    pre = fam + "_"
    main = [n for n in names if n.startswith(pre)
            and not any(x in n for x in ("CYS", "Victory", "Lose", "Leave"))]
    cys = [n for n in names if n.startswith(pre + "CYS")]
    vic = [n for n in names if n.startswith(pre + "Victory")]
    los = [n for n in names if n.startswith(pre + "Lose")]
    print(f"{fam:<6}{mt:<14}{len(main):>7}{len(cys):>6}{len(vic):>9}{len(los):>6}")

print()
print("  素材里各家可用的数量（上限）:")
for fam in FAMS:
    n = len([f for f in src_files if f.startswith(fam + "_")])
    print(f"    {fam:<6} {n}")

# ============ 2. ZB 僵王分段 ============
print()
print("② ZB（僵王博士）分段")
print("-" * 68)
zb_src = sorted(f for f in src_files if f.startswith("ZB_"))
zb_have = sorted(n for n in names if n.startswith("ZB_"))
print(f"  素材 ZB_*: {len(zb_src)} 个")
print(f"  仓库 ZB_*: {len(zb_have)} 个（其中 {len([n for n in zb_have if 'Kongfu' in n])} 个是功夫原版）")
missing_zb = [f for f in zb_src if f not in names]
print(f"  未接入: {len(missing_zb)} 个")
# 分类
for seg in ["Intro", "Stage0", "Stage1", "Stage2_Start", "Stage2"]:
    m = [f for f in missing_zb if f"_{seg}_" in f or f.endswith(f"_{seg}")]
    print(f"    {seg:<14} {len(m)}")

# ============ 3. 教程 ============
print()
print("③ 教程关槽位")
print("-" * 68)
NEED = []
for fam in FAMS:
    for suf in ["Tutorial", "CYS_Tutorial", "Victory_Tutorial", "Lose_Tutorial"]:
        NEED.append(f"{fam}_{suf}")
NEED += ["CYS_Start_Tutorial", "CYS_LP_Tutorial", "VIC_Tutorial",
         "LOSE_Tutorial", "LEAVE_Tutorial"]
have = [n for n in NEED if n in names]
miss = [n for n in NEED if n not in names]
print(f"  需要 {len(NEED)} 个槽位，已有 {len(have)}，缺 {len(miss)}")
if miss:
    for n in miss:
        src_ok = n in src_files
        print(f"    {n:<28} {'素材有' if src_ok else '素材也没有'}")

# ============ 4. 关卡打标 ============
print()
print("④ 关卡打标")
print("-" * 68)
dist = {}
for p in glob.glob(os.path.join(IMP, "**", "*.json"), recursive=True):
    try:
        b = open(p, "rb").read()
    except OSError:
        continue
    if b"MusicType" not in b:
        continue
    try:
        d = json.loads(b.decode("utf-8"))
    except Exception:
        continue

    def walk(o):
        if isinstance(o, dict):
            if o.get("objclass") == "LevelDefinition":
                t = (o.get("objdata") or {}).get("MusicType")
                dist[t] = dist.get(t, 0) + 1
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)
for k in sorted(dist, key=lambda x: (x is None, x or "")):
    print(f"  {str(k):<14} {dist[k]}")

# ============ 5. 代码接线 ============
print()
print("⑤ index.js 接线（LB 11 处）")
print("-" * 68)
CHECKS = [
    ("L1 MusicSortEnum", 't[t.Loonboon=25]="Loonboon"'),
    ("L3 沙盒列表", '"KongfuBoss","MiniGame_C","MiniGame_D")'),
    ("L4 加载器三元链", '"MiniGame_D"==(null=='),
    ("L5 路由", '"MiniGame_D"===e.t0?9001'),
    ("L6 case 9001", "case 9001:return window.__cys_target="),
    ("L7 switchMusic", "if(a==v.Loonboon){switch(e){"),
    ("L8a Victory", 'if(a==v.Victory&&window.__mts=="MiniGame_D")'),
    ("L8b Lose", 'if(a==v.Lose&&window.__mts=="MiniGame_D")'),
    ("L9 __CYS_TBL", "LB:{Egypt:A.LB_CYS_Egypt"),
    ("L10 isJam 守卫", "e==v.RemadeZombotany||e==v.Loonboon||e==v.Victory"),
    ("Z1 ZB Stage0 分世界", "case w.Beach:u=A.ZB_Stage0_Beach;"),
    ("Z2 ZB Stage1 分世界", "case w.Beach:u=A.ZB_Stage1_Beach;"),
    ("Z3 ZB Stage2 分世界", "case w.Beach:u=A.ZB_Stage2_Beach;"),
    ("Z4 ZB Stage2_Start", "u=A.ZB_Stage2_Start_Beach;c=A.ZB_Stage2_Beach"),
    ("T1 教程 UB", "u=A.UB_Tutorial"),
    ("T2 教程 MG", "u=A.MG_Tutorial"),
    ("T3 教程 ZBT", "u=A.ZBT_Tutorial"),
    ("T4 教程 LB", "u=A.LB_Tutorial"),
    ("T5 教程 VIC", "u=A.VIC_Tutorial"),
    ("T6 教程 CYS_LP", "u=A.CYS_LP_Tutorial"),
]
for label, needle in CHECKS:
    print(f"  {label:<20} {'OK' if needle in js else 'FAIL'}")

# MusicAmount 动态核对（不写死数字）
m_am = re.search(r'\.MusicAmount=(\d+)\]="MusicAmount"', js)
am = int(m_am.group(1)) if m_am else -1
print(f"  {'L2 MusicAmount':<20} "
      f"{'OK' if am == len(arr) else 'FAIL'}  ({am} vs Musics {len(arr)})")

# ============ 6. 音频完整性 ============
print()
print("⑥ 音频与 manifest")
print("-" * 68)
lb_entries = [e for e in arr if e["name"].startswith("LB_")]
bad_man, bad_file = [], []
for e in lb_entries:
    k = e["tauri"]
    if k not in man:
        bad_man.append(k)
    elif not os.path.exists(os.path.join(DOCS, "audio", man[k])):
        bad_file.append(k)
print(f"  LB 条目 {len(lb_entries)}")
print(f"  manifest 缺 key: {len(bad_man)}")
print(f"  音频文件缺: {len(bad_file)}")
print(f"  manifest 总条目: {len(man)}")

# ============ 7. 构建与提交 ============
print()
print("⑦ 构建与提交")
print("-" * 68)
r = subprocess.run(["git", "-C", REPO, "status", "--porcelain"],
                   capture_output=True, text=True, encoding="utf-8")
dirty = [l for l in (r.stdout or "").splitlines() if l.strip()]
print(f"  未提交改动: {len(dirty)} 项")
r = subprocess.run(["git", "-C", REPO, "log", "--oneline", "-1"],
                   capture_output=True, text=True, encoding="utf-8")
print(f"  HEAD: {(r.stdout or '').strip()}")
dist = os.path.join(REPO, "dist")
if os.path.isdir(dist):
    import time
    exes = [f for f in os.listdir(dist) if f.endswith(".exe")]
    for f in sorted(exes):
        p = os.path.join(dist, f)
        age = (time.time() - os.path.getmtime(p)) / 3600
        print(f"  dist/{f:<32} {age:>6.1f} 小时前")
