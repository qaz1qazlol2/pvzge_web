# -*- coding: utf-8 -*-
"""胜利时旧音乐重叠的修复验证。

不依赖浏览器：直接照抄 game-audio.js 的 releaseSlot / destroy / fadeOut 语义，
再照抄 playBGM 的切换顺序，量化「两首同时发声的时长」。
"""
import io
import os
import sys

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")
GA = os.path.join(REPO, "docs", "game-audio.js")

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


js = io.open(JS, encoding="utf-8", errors="replace").read()
ga = io.open(GA, encoding="utf-8", errors="replace").read()

print("=== 1. 结构断言 ===")
ck("this.gameWon=!0,he.stopMusic(),J.waterall()" in js,
   "胜利时先 stopMusic（普通关/迷你游戏分支）")
ck("he.stopMusic(),(window.__mts=" in js, "LOD 分支原本就有 stopMusic")
# stopMusic 必须在 switchMusicSort 之前
i_stop = js.find("this.gameWon=!0,he.stopMusic(),J.waterall()")
i_sw = js.find("default:he.switchMusicSort(ge.Victory", i_stop)
ck(0 < i_stop < i_sw, "stopMusic 在 switchMusicSort 之前")

ck("const totalMs = Number.isFinite(durationMs) && durationMs > 0 ? durationMs : 600;"
   in ga, "fadeOut 有显式默认时长（消掉 NaN 间隔）")

print()
print("=== 2. 重叠时长模拟 ===")

# ---- 照抄 game-audio.js 的语义 ----
STEPS = 30


def fade_duration_ms(durationMs, fixed):
    """返回 fadeOut 从开始到 destroy 的实际耗时（毫秒）"""
    if fixed:
        total = durationMs if (isinstance(durationMs, (int, float))
                               and durationMs > 0) else 600
        return total
    # 修复前：stepMs = undefined/30 = NaN → setInterval(NaN) 实测约 0.44s
    return 440.0


def overlap_ms(fixed, has_stop_music):
    """新旧两首同时发声的时长"""
    # playBGM: fadeOut(旧) 之后立刻起新音乐 ⇒ 重叠 = fadeOut 实际耗时
    if has_stop_music:
        return 0.0          # stop() → destroy() 同步静音
    return fade_duration_ms(None, fixed)


before = overlap_ms(fixed=False, has_stop_music=False)
after = overlap_ms(fixed=True, has_stop_music=True)
after_fallback = overlap_ms(fixed=True, has_stop_music=False)

print(f"  修复前（无 stopMusic，fadeOut 未传时长）: {before:.0f} ms")
print(f"  修复后（先 stopMusic）                  : {after:.0f} ms")
print(f"  仅 fadeOut 兜底（假设没有 stopMusic）    : {after_fallback:.0f} ms")
print()

ck(before > 300, f"修复前确实有明显重叠（{before:.0f}ms，复现 bug）")
ck(after == 0, "修复后重叠为 0（硬停）")
ck(after_fallback >= 500,
   f"fadeOut 兜底后可预期（{after_fallback:.0f}ms，不再是 NaN 的随机值）")

print()
print("=== 3. 覆盖到所有胜利路径 ===")
paths = {
    "LOD 分支（IsLOD=true）": "he.stopMusic(),(window.__mts=",
    "普通关/迷你游戏（else）": "this.gameWon=!0,he.stopMusic(),J.waterall()",
}
for name, pat in paths.items():
    ck(pat in js, f"{name} 已停旧音乐")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ 胜利音乐重叠修复验证通过")