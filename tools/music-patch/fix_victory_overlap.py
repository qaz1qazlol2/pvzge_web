# -*- coding: utf-8 -*-
"""修胜利/outro 时旧 MiniGame 音乐与新音乐重叠约 1 秒。

现象
----
所有僵尸死亡、进入 outro 时，原来的 MiniGame 音乐不会立刻停，
会和 Victory 音乐叠在一起约一秒少一点。

根因
----
胜利有两条路径，只有一条停了旧音乐：

  LOD 分支（u = this.IsLOD 为真）：
      he.stopMusic(), ... he.switchMusicSort(ge.Victory, ...)     ← 有 stopMusic
  普通关卡 / 迷你游戏（else 分支）：
      he.switchMusicSort(ge.Victory, ...)                          ← 没有！

`stopMusic()` → `currentTauriAudio.stop()` → `audio_destroy` → `destroy(id)`
走 `releaseSlot`，`pause()` + 清 src，**立即静音**。

而没有 stopMusic 时，旧音乐只能由 `switchMusicSort → switchMusic → playBGM`
里的 `S.fadeOut()` 收走：

    case 21: if(o=t.t1, null==S||S.fadeOut(), ...)

这里 `fadeOut()` 不传时长，`stepMs = undefined/30 = NaN`，
`setInterval(NaN)` 退化成「尽快跑」，30 步实测约 0.4 秒；
而 `playBGM` 在调用 fadeOut 之后**立刻**就换上新音乐开始播。
⇒ 这 0.4~1 秒里两首同时在响。

MiniGame 音乐（CYS / UB / MG / ZBT 世界曲）本身是长循环，
且音量没有降到 0 之前一直在发声，所以重叠特别明显。

修法
----
1. 在 else 分支的胜利处补上 `he.stopMusic()`，与 LOD 分支对齐 ——
   这是消除重叠的主修。
   ⚠️ 必须在 switchMusicSort **之前**调用，顺序反了就没用。

2. `game-audio.js` 的 `fadeOut` 给一个显式默认时长（600ms），
   避免 `NaN` 间隔这种不可预期行为（保底，让其它调用点也稳定）。

锚点
----
J1  `this.gameWon=!0,J.waterall(),t)switch(he.soundManager().currentMusicType)`
    （else 分支开头，紧跟 Victory 切换）
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

# else 分支：this.gameWon=!0, J.waterall(), t) switch(...)
# 在 gameWon 之后、switch 之前插入 stopMusic
OLD = ("this.gameWon=!0,J.waterall(),t)switch("
       "he.soundManager().currentMusicType){case de.LP_Tutorial:break;"
       "default:he.switchMusicSort(ge.Victory,!1,!1,!0,!0)}")

NEW = ("this.gameWon=!0,he.stopMusic(),J.waterall(),t)switch("
       "he.soundManager().currentMusicType){case de.LP_Tutorial:break;"
       "default:he.switchMusicSort(ge.Victory,!1,!1,!0,!0)}")


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    if "this.gameWon=!0,he.stopMusic(),J.waterall()" in js:
        print("已修过，跳过")
        return 0

    n = js.count(OLD)
    print(f"锚点命中: {n} 次")
    if n != 1:
        raise SystemExit("锚点不唯一，中止")

    js = js.replace(OLD, NEW, 1)
    print()
    print("=== 改后 ===")
    i = js.find("this.gameWon=!0,he.stopMusic(),J.waterall()")
    print(" ", js[i:i + 200])
    print()
    print(f"字符数 {orig:,} -> {len(js):,}")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))