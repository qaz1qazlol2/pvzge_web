# -*- coding: utf-8 -*-
"""Meeting Zomboss 两段音乐的修复验证。

复刻三个关键行为：
  1. playBGM 收尾会把 nextToPlay 清成 null（异步）
  2. update 里 leftRepeat > 0 才检查 position >= musicLength
  3. changeLoopPlayer：nextToPlay 有值就播它，没有就重播 currentMusic
"""
import io
import os
import sys

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


js = io.open(JS, encoding="utf-8", errors="replace").read()

print("=== 1. 结构断言 ===")
ck("Dialogue_Zomboss_Start,!1,1).then(" in js, "改为先播一次再设 LP")
ck("i.nextToPlay=c.Dialogue_Zomboss_LP,i.leftRepeat=1/0" in js,
   "nextToPlay + leftRepeat 在 .then 里设置")
ck("Dialogue_Zomboss_Start,!1,1/0)" not in js, "旧的 1/0（无穷重复）已移除")

print()
print("=== 2. 时序模拟 ===")


def simulate(fixed, seconds=60):
    START, LP = "Start", "LP"
    LEN = {START: 8.5, LP: 10.5}

    current = START
    next_to_play = None
    left_repeat = float("inf") if not fixed else 0
    log = [current]
    t = 0.0

    # ---- playBGM 收尾（异步）----
    if fixed:
        # 修复后：.then 在 playBGM 完成后才写，不会被清
        next_to_play = LP
        left_repeat = float("inf")
    # 修复前：NPC_Enter 立刻写 LP，随后被 playBGM 的 case 35 清成 null
    #         → next_to_play 保持 None

    while t < seconds:
        t += LEN[current]
        # update: leftRepeat > 0 才检查
        if left_repeat > 0:
            if t >= LEN[current]:
                # changeLoopPlayer
                if next_to_play is not None:
                    current = next_to_play
                    # LP 的下一首仍是 LP ⇒ 自然循环
                else:
                    pass  # 没有下一首 → 重播 current
                log.append(current)
        left_repeat -= 1 if left_repeat != float("inf") else 0

    return log


before = simulate(False)
after = simulate(True)

from itertools import groupby

def summarise(log):
    runs = [(k, len(list(g))) for k, g in groupby(log)]
    return runs


print(f"  修复前（60s）: {summarise(before)}")
print(f"  修复后（60s）: {summarise(after)}")
print()

b = summarise(before)
a = summarise(after)

ck(len(b) == 1 and b[0][0] == "Start",
   "修复前只有 Start 在重复（复现 bug）")
ck(len(a) >= 2 and a[0][0] == "Start" and a[1][0] == "LP",
   "修复后 Start → LP 正确交接")
ck(a[0][1] == 1, "Start 只播 1 次")
ck(a[-1][0] == "LP" and a[-1][1] >= 2, "LP 持续循环")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ Meeting Zomboss 两段交接修复验证通过")
print()
print("说明：真实效果需进 pirate25 实跑确认")
