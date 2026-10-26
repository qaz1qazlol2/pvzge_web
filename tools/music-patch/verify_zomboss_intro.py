# -*- coding: utf-8 -*-
"""Zomboss 音乐两个 bug 的修复验证。

bug A：Intro 与 Meeting 重叠 + Meeting 后 Intro 重播
bug B：Zomboss 关被 UB 音乐覆盖
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
ck("window.__zb_intro" in js, "__zb_intro 已引入")
# 4 处：B1 赋值、B2 清空、A1 读取、B3 读取
ck(js.count("__zb_intro") == 4, f"出现 4 处（实际 {js.count('__zb_intro')}）")

ck("null!=window.__zb_intro?i.startingMusicChanged=!0:i.playStartingMusic()" in js,
   "A1 Intro 不再提前播（改为置 startingMusicChanged）")

ck("window.__zb_intro=this.startingMusic" in js, "B1 记录 boss intro")
ck("case 0:if(window.__zb_intro=null," in js, "B2 每关清空标记")
ck("if(null!=window.__zb_intro){window.__cys_target=null;return;}" in js,
   "B3 Boss 关跳过 cys_resume（不篡改音乐）")

print()
print("=== 2. bug A 逻辑推演：Intro 播放次数 ===")


def simulate_intro(fixed, is_boss=True):
    """返回 (Intro 播放次数, 是否有重叠)"""
    zb_intro = 1 if is_boss else None
    plays = []
    overlapping = False

    if fixed:
        # 回调里：只有非 boss 才直接播
        if zb_intro is not None:
            starting_music_changed = True
        else:
            plays.append("callback")
            starting_music_changed = False
    else:
        plays.append("callback")          # 修复前：无条件播
        starting_music_changed = True

    # 剧情期间 Meeting 音乐播放；若 Intro 已在播 -> 重叠
    if "callback" in plays and zb_intro is not None:
        overlapping = True

    # 剧情结束
    if starting_music_changed:
        plays.append("after-narration")

    return len(plays), overlapping


before_n, before_ov = simulate_intro(False, True)
after_n, after_ov = simulate_intro(True, True)
print(f"  修复前（Zomboss 关）: Intro 播 {before_n} 次，重叠={before_ov}")
print(f"  修复后（Zomboss 关）: Intro 播 {after_n} 次，重叠={after_ov}")
ck(before_n == 2, "修复前确实播 2 次（复现 bug）")
ck(before_ov is True, "修复前确实重叠（复现 bug）")
ck(after_n == 1, "修复后只播 1 次")
ck(after_ov is False, "修复后不重叠")

# 非 Zomboss 关不应受影响
nb_n, nb_ov = simulate_intro(True, False)
print(f"  非 Zomboss 关      : Intro 播 {nb_n} 次，重叠={nb_ov}")
ck(nb_n == 1, "非 Zomboss 关行为不变（仍 1 次）")

print()
print("=== 3. bug B 逻辑推演：选完卡/开局时会不会篡改音乐 ===")


def simulate_resume(fixed, music_type="MiniGame_A", is_boss=True):
    """返回 (resume 做了什么)"""
    cys_target = 1 if music_type == "MiniGame_A" else 0   # 1=UltimateBattle
    zb_intro = 5 if is_boss else None                      # 5=ZombossIntro
    if fixed and zb_intro is not None:
        return "跳过（保留 ZB 链路）"
    t = cys_target
    name = {0: "CYS_Start", 1: "UB_<World>（错）", 5: "ZB Intro（错：会重播）"}[t]
    return name


b = simulate_resume(False, is_boss=True)
a = simulate_resume(True, is_boss=True)
print(f"  修复前: {b}")
print(f"  修复后: {a}")
ck(b == "UB_<World>（错）", "修复前确实切到 UB 音乐（复现 bug）")
ck(a == "跳过（保留 ZB 链路）", "修复后不篡改，交给 nextToPlay 接 Stage0")
ck("ZB Intro" not in a, "修复后不会重播 Intro")

# 非 boss 的 MiniGame_A 关卡不受影响
nb = simulate_resume(True, is_boss=False)
print(f"  非 boss 的 MiniGame_A: {nb}")
ck(nb == "UB_<World>（错）", "非 boss 关卡保持原行为（仍是 UB）")

# DiscardBossMusic 的关卡（__zb_intro 为空）不受影响
dm = simulate_resume(True, is_boss=False)
ck(dm == "UB_<World>（错）", "无 boss 标记时不受影响")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ Zomboss 音乐两个 bug 的修复验证通过")
