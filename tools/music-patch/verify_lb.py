# -*- coding: utf-8 -*-
"""LB 体系三层验证：结构断言 + 枚举下标 + manifest"""

# -*- coding: utf-8 -*-
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
ck('t[t.Loonboon=25]="Loonboon"' in js, "MusicSortEnum.Loonboon=25")
ck('"MiniGame_D"==(null==' in js, "加载器三元链")
ck('"MiniGame_D"===e.t0?9001' in js, "路由三元链 → 9001")
ck("case 9001:return window.__cys_target=" in js, "case 9001 主体")
ck('window.__cys_fam="LB"' in js, "__cys_fam=LB")
ck("if(a==v.Loonboon){switch(e){" in js, "switchMusic 世界分派")
ck('if(a==v.Victory&&window.__mts=="MiniGame_D")' in js, "Victory 分支")
ck('if(a==v.Lose&&window.__mts=="MiniGame_D")' in js, "Lose 分支")
ck("LB:{Egypt:A.LB_CYS_Egypt" in js, "__CYS_TBL LB 家族")
ck("e==v.RemadeZombotany||e==v.Loonboon||e==v.Victory" in js, "isJam 清空列表")
ck('"KongfuBoss","MiniGame_C","MiniGame_D")' in js, "沙盒类型列表")

print()
print("=== 2. 枚举 / 下标 / MusicAmount ===")
m_am = re.search(r'\.MusicAmount=(\d+)\]="MusicAmount"', js)
amount = int(m_am.group(1)) if m_am else -1

# MusicEnum 成员
EN, EP = None, None
m_enum = re.search(r'([A-Za-z_$][\w$]*)\(\\?"MusicEnum\\?",\s*function\s*\(([A-Za-z_$][\w$]*)\)',
                   js)
m_enum2 = re.search(r't\("MusicEnum",function\(([A-Za-z_$][\w$]*)\)', js)
if m_enum2:
    EP = m_enum2.group(1)
vals = {}
for name, v in re.findall(r't\[t\.(\w+)=(\d+)\]="\w+"',
                          js[js.find('t("MusicEnum"'):js.find('t("MusicEnum"') + 40000]):
    vals[name] = int(v)

# Musics 数组
raw = io.open(MUSICS, encoding="utf-8", errors="replace").read()
i = raw.find('{"name":"WorldMap"')
start = raw.rfind("[", 0, i)
depth = 0
end = None
for k in range(start, len(raw)):
    if raw[k] == "[":
        depth += 1
    elif raw[k] == "]":
        depth -= 1
        if depth == 0:
            end = k + 1
            break
musics = json.loads(raw[start:end])

ck(amount == len(musics), f"MusicAmount({amount}) == Musics 长度({len(musics)})")

lb = [m["name"] for m in musics if m["name"].startswith("LB_")]
ck(len(lb) == 55, f"Musics 里 LB 条目 = {len(lb)}（期望 55）")

# 逐个检查 LB 的下标 == 枚举值
bad = []
for idx, nm in enumerate(musics):
    if not nm["name"].startswith("LB_"):
        continue
    ev = vals.get(nm["name"])
    if ev != idx:
        bad.append((nm["name"], ev, idx))
ck(not bad, f"LB 全部下标对齐" + ("" if not bad else f"，错位 {len(bad)} 处：{bad[:3]}"))

print()
print("=== 3. manifest ===")
man = json.loads(open(MAN, "rb").read().decode("utf-8"))
missing = []
for m in musics:
    if not m["name"].startswith("LB_"):
        continue
    k = m["tauri"]
    if k not in man:
        missing.append(k)
    elif not os.path.exists(os.path.join(REPO, "docs", "audio", man[k])):
        missing.append(k + " (文件缺失)")
ck(not missing, f"manifest 55 个 key 全部就位" + ("" if not missing else f"，缺 {missing[:3]}"))

# 每个 LB 音频文件存在且非空
files_bad = []
for nm in lb:
    p = os.path.join(REPO, "docs", "audio", "Music", "inGame", nm, nm + ".mp3")
    if not os.path.exists(p) or os.path.getsize(p) < 1000:
        files_bad.append(nm)
ck(not files_bad, "55 个音频文件都在" + ("" if not files_bad else f"，缺 {files_bad[:3]}"))

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ 全部通过")
