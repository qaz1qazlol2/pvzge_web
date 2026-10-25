# -*- coding: utf-8 -*-
"""ZB 分段 + 教程选卡 验证。"""
import io
import json
import os
import re
import sys

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")
MUSICS = os.path.join(REPO, "docs", "assets", "resources", "import",
                      "0d", "0d4cac202.json")
MAN = os.path.join(REPO, "docs", "audio", "manifest.json")

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


js = io.open(JS, encoding="utf-8", errors="replace").read()

print("=== 1. 结构断言 ===")
ck("switch(e){case w.Beach:u=A.ZB_Stage0_Beach;" in js, "ZB Stage0 分世界")
ck("switch(e){case w.Beach:u=A.ZB_Stage1_Beach;" in js, "ZB Stage1 分世界")
ck("switch(e){case w.Beach:u=A.ZB_Stage2_Beach;" in js, "ZB Stage2 分世界")
ck("case w.Beach:u=A.ZB_Stage2_Start_Beach;c=A.ZB_Stage2_Beach" in js,
   "ZB Stage2_Start 分世界（含 c）")
ck("case w.Ice:u=A.ZB_Stage0_Iceage;" in js, "冰窟用 w.Ice 而非 w.Iceage")
ck("u=A.UB_Tutorial" in js, "教程 UB_Tutorial")
ck("u=A.MG_Tutorial" in js, "教程 MG_Tutorial")
ck("u=A.ZBT_Tutorial" in js, "教程 ZBT_Tutorial")
ck("u=A.LB_Tutorial" in js, "教程 LB_Tutorial")
ck("u=A.VIC_Tutorial" in js, "教程 VIC_Tutorial")
# CYS 已改为查 __CYS_TBL[__cys_fam].Tutorial，只剩兜底字面量
ck("__CYS_TBL[window.__cys_fam].Tutorial" in js, "教程 CYS 查家族表")
ck("A.CYS_LP_Tutorial" in js, "教程 CYS 兜底 CYS_LP_Tutorial")

print()
print("=== 2. 枚举 / 下标 / MusicAmount ===")
m_am = re.search(r'\.MusicAmount=(\d+)\]="MusicAmount"', js)
amount = int(m_am.group(1)) if m_am else -1

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
musics = json.loads(raw[start:end])

ck(amount == len(musics), f"MusicAmount({amount}) == Musics({len(musics)})")

vals = {}
seg = js[js.find('t("MusicEnum"'):js.find('t("MusicEnum"') + 60000]
for name, v in re.findall(r't\[t\.(\w+)=(\d+)\]="\w+"', seg):
    vals[name] = int(v)

# 新增的 51 条逐个核对
NEW = (["ZB_Intro_Beach", "ZB_Intro_Eighties", "ZB_Intro_Modern"]
       + [e["name"] for e in musics[436:446]]
       + [e["name"] for e in musics[446:457]]
       + [e["name"] for e in musics[457:468]]
       + [e["name"] for e in musics[468:479]]
       + ["UB_Tutorial", "MG_Tutorial", "ZBT_Tutorial",
          "CYS_LP_Tutorial", "VIC_Tutorial"])
bad = []
for e in musics:
    if e["name"] not in NEW:
        continue
    ev = vals.get(e["name"])
    idx = musics.index(e)
    if ev != idx:
        bad.append((e["name"], ev, idx))
ck(not bad, f"新增 {len(NEW)} 条下标全对齐" +
   ("" if not bad else f"，错位 {bad[:3]}"))

# 全部枚举的代号引用都在 Musics 里
refs = set(re.findall(r'A\.((?:ZB|UB|MG|ZBT|LB)_\w+)', js))
missing = refs - {e["name"] for e in musics}
ck(not missing, f"代码引用的音轨都在 Musics 里" +
   ("" if not missing else f"，缺 {sorted(missing)[:5]}"))

print()
print("=== 3. manifest / 音频 ===")
man = json.loads(open(MAN, "rb").read().decode("utf-8"))
miss_man, miss_file = [], []
for e in musics:
    if e["name"] not in NEW:
        continue
    k = e["tauri"]
    if k not in man:
        miss_man.append(k)
    elif not os.path.exists(os.path.join(REPO, "docs", "audio", man[k])):
        miss_file.append(k)
ck(not miss_man, f"manifest 补齐" + ("" if not miss_man else f"，缺 {miss_man[:3]}"))
ck(not miss_file, f"音频文件在" + ("" if not miss_file else f"，缺 {miss_file[:3]}"))

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ 全部通过")
