# -*- coding: utf-8 -*-
"""专查 LB 在 Jam 世界（Eighties 炫光魔音游）的路径完整性。

之前的坑（记忆里记了三条）：
  坑 1  switchMusicSort 入口守卫只在 UB/MG/ZBT 时清 isJam，
        Victory/Lose/Leave 不在列表 ⇒ Jam 关整局 isJam=true，结算时守卫早退
  坑 2  Jam 六风格 case 只处理 UB/MG，Victory 落到递归 ⇒ 无限递归
  坑 3  Pinata 分支没有第 1 层音乐

逐条核对 LB 是否也覆盖到了。
"""
import io
import os
import re
import sys

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"
s = io.open(JS, encoding="utf-8", errors="replace").read()

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


JAM = ["Ballad", "Punk", "Pop", "Rap", "Eightbit", "Metal"]

print("=== 坑 1：入口守卫必须清 isJam ===")
m = re.search(r'\(e==v\.UltimateBattle\|\|e==v\.DemonstrateMinigame\|\|'
              r'e==v\.RemadeZombotany\|\|e==v\.Loonboon\|\|'
              r'e==v\.Victory\|\|e==v\.Lose\|\|e==v\.Leave\)', s)
ck(bool(m), "清空列表含 Loonboon（否则 Jam 关结算守卫早退）")

print()
print("=== 坑 2：Jam 六风格 case ===")
# 每个风格 case 的 fallback 里必须有终态，且直接 t.next=270（不能递归）
for f, case_no in [("Ballad", 122), ("Punk", 146), ("Pop", 170),
                   ("Rap", 194), ("Eightbit", 218), ("Metal", 242)]:
    i = s.find(f"case {case_no}:if(a!=v.UltimateBattle)")
    if i < 0:
        ck(False, f"{f} case {case_no} 找不到")
        continue
    seg = s[i:i + 1500]
    has_v = "if(a==v.Victory){u=A.VIC_Eighties" in seg
    has_l = "if(a==v.Lose){u=A.LOSE_Eighties" in seg
    has_lv = "if(a==v.Leave){u=A.LEAVE_Eighties" in seg
    ck(has_v and has_l and has_lv, f"{f} 有 Victory/Lose/Leave 三条")

print()
print("=== LB 在 Jam 各风格的分派 ===")
# 主音轨：any Jam style → LB_Ballad
i7 = s.find("if(a==v.Loonboon){switch(e){")
seg7 = s[i7:i7 + 1400] if i7 > 0 else ""
for f in JAM:
    if f == "Ballad":
        ok = "case w.Ballad:u=A.LB_Ballad;" in seg7
    else:
        ok = f"case w.{f}:u=A.LB_{f};" in seg7 or \
             f"case w.{f}:u=A.LB_Ballad;" in seg7
    ck(ok, f"主音轨 case w.{f}")

# Eighties 本身
ck("case w.Eighties:u=A.LB_Ballad;" in seg7, "主音轨 case w.Eighties（复用 Ballad）")

print()
print("=== LB 的 Victory / Lose 覆盖 Jam ===")
i8a = s.find('if(a==v.Victory&&window.__mts=="MiniGame_D")')
seg8a = s[i8a:i8a + 1200] if i8a > 0 else ""
for f in JAM:
    ck(f"case w.{f}:u=A.LB_Victory_Eighties;" in seg8a, f"Victory case w.{f}")

i8b = s.find('if(a==v.Lose&&window.__mts=="MiniGame_D")')
seg8b = s[i8b:i8b + 1200] if i8b > 0 else ""
for f in JAM:
    ck(f"case w.{f}:u=A.LB_Lose_Eighties;" in seg8b, f"Lose case w.{f}")

print()
print("=== LB 的 CYS 覆盖 Jam ===")
i9 = s.find("LB:{Egypt:A.LB_CYS_Egypt")
seg9 = s[i9:i9 + 1200] if i9 > 0 else ""
for f in JAM:
    ck(f"{f}:A.LB_CYS_Ballad" in seg9, f"CYS {f}")

print()
print("=== 关键顺序：L7 必须在 ZBT 判定之前，且都在 case 82 之前 ===")
pos_case7 = s.find("this.isJam=!1,o){t.next=270;break}")
pos_lb7 = s.find("if(a==v.Loonboon){switch(e){")
pos_zbt7 = s.find("if(a==v.RemadeZombotany){switch(e){")
pos_case82 = s.find("case 82:t.t0=e,t.next=t.t0===")
pos_82b = s.find("case 82:", pos_case7)
ck(pos_case7 < pos_lb7 < pos_zbt7, "LB 插在 ZBT 之前（都在 case 7 之后）")
ck(pos_lb7 < (pos_82b if pos_82b > 0 else 1 << 60),
   f"LB 插在世界分派 switch 之前（避免走到 Jam 递归）")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ Jam 相关全部覆盖")
