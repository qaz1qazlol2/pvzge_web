# -*- coding: utf-8 -*-
"""教程关 CYS 按家族选 —— 验证。

链条
----
1. 教程关 MusicType=MiniGame_A/B/C/D
2. case 11 路由 → case 14/16/17/9001 → 设 `__cys_fam` = UB/MG/ZBT/LB
3. `startingMusic = CYS_Start`
4. 进 case 116/85（w.Tutorial）→ case 85 存 t.t1 → case 96 分派
5. CYS_Start 分支 → 查 `__CYS_TBL[__cys_fam].Tutorial`

所以要验的是：
  a) 四家族的 __CYS_TBL 都有 Tutorial 键
  b) 这些键指向的音轨都在 Musics 里
  c) case 96 的 CYS 分支确实查表而不是写死 CYS_LP_Tutorial
  d) 兜底仍在（无 __cys_fam 时 → CYS_LP_Tutorial）
"""
import io
import json
import os
import re
import sys

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")
MUSICS = os.path.join(REPO, "docs", "assets", "resources", "import",
                      "0d", "0d4cac202.json")

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


js = io.open(JS, encoding="utf-8", errors="replace").read()

# Musics
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
names = {e["name"] for e in musics}
vals = {e["name"]: idx for idx, e in enumerate(musics)}

print("=== 1. case 96 的 CYS 分支查表 ===")
k = js.find("t.t1===v.CYS_Start?")
ck(k > 0, "CYS_Start 分支存在")
seg96 = js[k:k + 900] if k > 0 else ""
ck("__CYS_TBL[window.__cys_fam].Tutorial" in seg96, "查家族 Tutorial 键")
ck("A.CYS_LP_Tutorial" in seg96, "保留兜底 CYS_LP_Tutorial")
ck("L=v.CYS_LP,g=!1" in seg96, "CYS_Start 是前奏（g=!1, 设 L）")
# ⚠️ 不能用正则跨嵌套括号，直接找 CYS_LP 分支的尾巴
j = seg96.find("t.t1===v.CYS_LP?")
ck(j > 0 and ",g=!0,t.abrupt" in seg96[j:j + 400],
   "CYS_LP 是循环（g=!0）")

print()
print("=== 2. 四家族的 Tutorial CYS 键 ===")
tbl_s = js.find("window.__CYS_TBL={")
tbl_e = js.find("};", tbl_s) + 2
tbl = js[tbl_s:tbl_e]
FAM_WANT = {"UB": "UB_CYS_Tutorial", "MG": "MG_CYS_Tutorial",
            "ZBT": "ZBT_CYS_Tutorial", "LB": "LB_CYS_Tutorial"}
for fam, want in FAM_WANT.items():
    # ⚠️ LB 是最后一个家族，紧跟 `}}`（家族}))  +  表}），
    #    用 lookahead `(?=,|$)` 会漏掉，改成只找 `FAM:{` 到下一个 `},{` 或结尾
    m = re.search(re.escape(fam) + r":\{(.*?)\}(?=\}(?:,|;|$)|,\w+:)", tbl, re.S)
    if not m:
        # 退化：直接取 fam:{ 之后 1200 字符找 Tutorial
        i = tbl.find(fam + ":{")
        body = tbl[i:i + 1200] if i >= 0 else ""
        got = re.search(r"Tutorial:A\.(\w+)", body)
        ck(got and got.group(1) == want,
           f"{fam}.Tutorial → {got.group(1) if got else '(缺)'}")
        continue
    body = m.group(1)
    got = re.search(r"Tutorial:A\.(\w+)", body)
    ok = got and got.group(1) == want
    ck(ok, f"{fam}.Tutorial → {got.group(1) if got else '(缺)'}" +
       ("" if ok else f"（期望 {want}）"))

print()
print("=== 3. 这些音轨在 Musics 里且下标正确 ===")
ENUM = {}
seg = js[js.find('t("MusicEnum"'):js.find('t("MusicEnum"') + 60000]
for n, v in re.findall(r't\[t\.(\w+)=(\d+)\]="\w+"', seg):
    ENUM[n] = int(v)
for want in FAM_WANT.values():
    ok_m = want in names
    ok_e = ENUM.get(want) == vals.get(want)
    ck(ok_m and ok_e,
       f"{want:<20} Musics={'有' if ok_m else '缺'} 枚举={'对齐' if ok_e else '错位'}")

print()
print("=== 4. 教程关能否拿到 __cys_fam ===")
# case 14/16/17/9001 都要设 __cys_fam
for tag, needle, fam in [
        ("case 14", 'case 14:return window.__cys_target=ge.UltimateBattle', "UB"),
        ("case 16", 'case 16:return window.__cys_target=ge.DemonstrateMinigame', "MG"),
        ("case 17", 'case 17:return window.__cys_target=ge.RemadeZombotany', "ZBT"),
        ("case 9001", 'case 9001:return window.__cys_target=ge.Loonboon', "LB")]:
    i = js.find(needle)
    ok = i > 0 and f'window.__cys_fam="{fam}"' in js[i:i + 200]
    ck(ok, f"{tag} 设 __cys_fam={fam}")

print()
print("=== 5. 无 MusicType 的教程关仍走主线 ===")
ck(":(u=A.LP_Tutorial,g=!0,t.abrupt" in js, "兜底 LP_Tutorial 保留")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ 教程 CYS 分家族全部就位")
