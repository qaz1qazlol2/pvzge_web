# -*- coding: utf-8 -*-
"""修 Zomboss 关卡的两个音乐 bug。

bug A：Intro 与 Meeting Zomboss 重叠，且 Meeting 结束后 Intro 再播一次
--------------------------------------------------------------------
`_promise_start` 里，有 intro 剧情时：

    this.isIntroNarrating = true
    scheduleOnce(() => {
        i.playStartingMusic(),     // ← 立刻播 ZBI（Intro）
        tt.SetFlow(r),             // ← 紧接着启动剧情（Meeting Zomboss）
    }, 1)

于是 ZBI 与 Dialogue_Zomboss_Start 撞在一起；
剧情结束时又因为 `startingMusicChanged` 再调一次 `playStartingMusic()`，
Intro 就播了第二遍。用户描述的三点全部对上。

修法：有剧情时**先不播 Intro**，只把 `startingMusicChanged` 置真，
让剧情结束时的既有逻辑去播一次。
⇒ 顺序变成「Meeting → Intro」，各一次，不重叠。

⚠️ 只对 Zomboss 关生效（判据 `window.__zb_intro`），
   非 Zomboss 的普通剧情关保持原行为，不扩大改动面。

bug B：Zomboss 关错误使用 UB 音乐（fork 引入）
----------------------------------------------
Zomboss 关卡的关卡数据里 `MusicType = "MiniGame_A"`（上游也是），
所以 `module_SetLevelDefinition` 会：

    window.__cys_target = ge.UltimateBattle
    window.__cys_fam = "UB"
    this.startingMusic = ge.CYS_Start

随后 `module_SetZombossBattleModuleProperties` 把 `startingMusic` 改成
`ZombossIntro`（这才是对的）。

但**选完卡开始游戏**时 `gameStart()` 会调 `window.__cys_resume()`，
它按 `__cys_target` 切到 `UltimateBattle` ⇒ **UB 音乐盖掉了 ZB Intro**。

这是我们的 `__cys_target` 机制带进来的，上游没有这条路径。

修法：**Boss 关直接跳过这次恢复**。

为什么不能改成「切回 ZombossIntro」
-----------------------------------
`ZombossIntro` 那个 case 里 `c=A.ZB_Stage0`（nextToPlay），
Intro 播完后引擎本来就会自己接 Stage0。
`__cys_resume` 是在 Intro **之后**才触发的（gameStart 里调），
若这里改成切回 ZombossIntro，等于把 Intro 再播一遍。

所以 Boss 关只清掉 `__cys_target`、直接 return，不碰音频，
让原生 nextToPlay 链路自己接 Stage0。

判据仍然是 Boss 模块记录的 `window.__zb_intro`
（每个关卡定义开始时清空，避免串关）。

锚点（各 1 处）
--------------
A1  `i.playStartingMusic(),tt.SetFlow(r)`
B1  `null!=t&&t.DiscardBossMusic||(this.startingMusic=...)`
B2  `case 0:if(this.levelDefinition=t,`
B3  `window.__cys_resume=function(){var _t=window.__cys_target;if(_t==null)return;`
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

A1_OLD = "i.playStartingMusic(),tt.SetFlow(r)"
A1_NEW = "null!=window.__zb_intro?i.startingMusicChanged=!0:i.playStartingMusic(),tt.SetFlow(r)"

B1_OLD = ("null!=t&&t.DiscardBossMusic||(this.startingMusic="
          "t.UseKongfuBossMusic?ge.KongfuBossIntro:ge.ZombossIntro)")
B1_NEW = ("null!=t&&t.DiscardBossMusic||(this.startingMusic="
          "t.UseKongfuBossMusic?ge.KongfuBossIntro:ge.ZombossIntro,"
          "window.__zb_intro=this.startingMusic)")

B2_OLD = "case 0:if(this.levelDefinition=t,"
B2_NEW = "case 0:if(window.__zb_intro=null,this.levelDefinition=t,"

B3_OLD = ("window.__cys_resume=function(){var _t=window.__cys_target;"
          "if(_t==null)return;")
B3_NEW = ("window.__cys_resume=function(){var _t=window.__cys_target;"
          "if(_t==null)return;if(null!=window.__zb_intro)"
          "{window.__cys_target=null;return;}")


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    if "window.__zb_intro" in js:
        print("已修过，跳过")
        return 0

    pairs = [
        ("A1 Intro 不再提前播", A1_OLD, A1_NEW),
        ("B1 记录 boss intro", B1_OLD, B1_NEW),
        ("B2 每关清空标记", B2_OLD, B2_NEW),
        ("B3 cys_resume 改用 intro", B3_OLD, B3_NEW),
    ]
    for tag, old, _ in pairs:
        n = js.count(old)
        print(f"  锚点 {tag:<26} {n} 次")
        if n != 1:
            raise SystemExit(f"!! {tag} 锚点不唯一，中止")

    for _, old, new in pairs:
        js = js.replace(old, new, 1)

    print()
    print(f"字符数 {orig:,} -> {len(js):,}")
    print(f"__zb_intro 出现 {js.count('__zb_intro')} 处（应为 5）")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
