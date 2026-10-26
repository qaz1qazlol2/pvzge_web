# -*- coding: utf-8 -*-
"""禅境花园 BGM 轮换修复 —— 验证。

逻辑推演（纯 JS 语义）
---------------------
修复前：
    播放完 → releaseSlot → byId.delete(id)
    getPosition() -> [0, null]      pos = 0
    getDuration() -> null           dur = null
    0 > null  ->  0 > 0  ->  false   ⇒ 永远 setVolume，永不换曲

修复后：
    播放中：dur = 20.03 (有效)  ⇒ _ambSeen = true
    播完后：dur = null          ⇒ null==dur && _ambSeen  ⇒ 换曲
    新曲开始：playAmb 复位 _ambSeen = false
    ⇒ 冷启动时 dur=null 但 _ambSeen=false，不会误跳
"""
import io
import os
import sys

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")
MAN = os.path.join(REPO, "docs", "audio", "manifest.json")

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


js = io.open(JS, encoding="utf-8", errors="replace").read()

print("=== 1. 结构断言 ===")
ck("this._ambSeen=!1" in js, "playAmb 复位 _ambSeen")
ck("null!=e.t3&&(this._ambSeen=!0)" in js, "播放中标记 _ambSeen")
ck("null==e.t3&&this._ambSeen" in js, "播完（dur=null）触发换曲")
ck("e.t2>e.t3" in js, "原 pos>dur 判断保留（作补充）")
# 3 处：playAmb 复位、musicControl 置真、musicControl 读取
ck(js.count("_ambSeen") == 3, "_ambSeen 出现 3 次（1 复位 + 1 置真 + 1 读取）")

print()
print("=== 2. 逻辑真值表 ===")


def should_rotate(pos, dur, seen):
    """复刻补丁后的条件：!(pos > dur || (dur == null && seen)) 取反"""
    return bool(pos > (0 if dur is None else dur)
                or (dur is None and seen))


CASES = [
    ("播放中 (pos=12, dur=20, seen=T)", 12, 20, True, False),
    ("刚起播 (pos=0, dur=None, seen=F)", 0, None, False, False),
    ("播完被回收 (pos=0, dur=None, seen=T)", 0, None, True, True),
    ("播到末尾但未回收 (pos=19.9, dur=20, seen=T)", 19.9, 20, True, False),
    ("极短曲播完 (pos=0, dur=None, seen=T)", 0, None, True, True),
]
for name, pos, dur, seen, want in CASES:
    got = should_rotate(pos, dur, seen)
    ck(got == want, f"{name} → 换曲={got}（期望 {want}）")

print()
print("=== 3. 音轨齐全（18 首，8~40 秒）===")
import json
man = json.loads(open(MAN, "rb").read().decode("utf-8"))
missing = [f"Music_ZenGarden_{i}" for i in range(18)
           if f"Music_ZenGarden_{i}" not in man]
ck(not missing, "18 条都在 manifest" + ("" if not missing else f"，缺 {missing}"))

import subprocess
PROBE = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\ffprobe.EXE"
durs = []
for i in range(18):
    p = os.path.join(REPO, "docs", "audio", man[f"Music_ZenGarden_{i}"].replace("/", os.sep))
    if not os.path.exists(p):
        durs.append(None)
        continue
    r = subprocess.run([PROBE, "-v", "quiet", "-show_entries",
                        "format=duration", "-of", "csv=p=0", p],
                       capture_output=True, text=True)
    try:
        durs.append(float(r.stdout.strip()))
    except ValueError:
        durs.append(None)

ok_files = [d for d in durs if d]
ck(len(ok_files) == 18, f"18 个 mp3 文件都在（量到 {len(ok_files)} 个时长）")
ck(all(2 < d < 600 for d in ok_files), "时长都在合理范围（2s~10min）")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ 禅境花园 BGM 轮换修复验证通过")
print()
print("说明：真实轮换还需浏览器实跑（见 check_boot.js + 手动进禅境花园）")
