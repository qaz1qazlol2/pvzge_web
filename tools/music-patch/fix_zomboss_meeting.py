# -*- coding: utf-8 -*-
"""修 Meeting Zomboss 只循环第一段、第二段永远不播。

现象
----
海盗 Zomboss（pirate25）的 Meeting 有两段音乐：

    Dialogue_Zomboss_Start   11.8s   musicLength 8.5
    Dialogue_Zomboss_LP      12.8s   musicLength 10.5

实际只听到第一段在反复，LP 段从不出现。

根因：竞态，不是重复次数的问题
------------------------------
NPC_Enter 里原本是：

    u.playMusic(Dialogue_Zomboss_Start, !1, 1/0), i.nextToPlay = Dialogue_Zomboss_LP

`playMusic` 是 async 且**没有被 await**。它内部转 `playBGM`，
而 `playBGM` 在**收尾**（case 35）会执行 `this.nextToPlay = null`：

    case 35: this.nextToPlay=null, this.currentMusicType=e, this.waiting=!1

于是顺序变成：

    1. playMusic 启动（同步阶段把 leftRepeat 设成 Infinity）
    2. NPC_Enter 立刻写 i.nextToPlay = LP
    3. playBGM 异步收尾 —— 把 nextToPlay 清成 null   ← 第 2 步被覆盖
    4. 播到 musicLength(8.5s) → changeLoopPlayer()
       nextToPlay 是 null、nextSortToPlay 也是 null
       → 走 case 40 重播 currentMusic，而 currentMusic 还是 Start
       ⇒ **Start 无限重播，LP 永远轮不到**

修法
----
把「设 LP + 放开重复」挪到 playMusic 完成之后：

    u.playMusic(Start, !1, 1).then(function(){
        i.nextToPlay = Dialogue_Zomboss_LP,
        i.leftRepeat = 1/0
    })

- repeat 传 1：Start 只播一遍（8.5s 到 musicLength 即交棒）
- `.then` 里再设 nextToPlay：这时 playBGM 已经清完，不会再被覆盖
- `leftRepeat = 1/0`：让 LP 段的推进判定(`leftRepeat>0`)保持有效，
  LP 播到 10.5s 会再次 changeLoopPlayer，而 nextToPlay 仍是 LP ⇒ 自然循环

直到世界 Zomboss Intro 接管：`switchMusicSort(ZombossIntro)` → `playBGM`
会把 nextToPlay 清掉并换曲，LP 循环自动结束。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

OLD = ("u.playMusic(c.Dialogue_Zomboss_Start,!1,1/0),"
       "i.nextToPlay=c.Dialogue_Zomboss_LP")
NEW = ("u.playMusic(c.Dialogue_Zomboss_Start,!1,1).then((function(){"
       "i.nextToPlay=c.Dialogue_Zomboss_LP,i.leftRepeat=1/0}))")


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    if "Dialogue_Zomboss_Start,!1,1).then(" in js:
        print("已修过，跳过")
        return 0

    n = js.count(OLD)
    print(f"锚点命中: {n} 次")
    if n != 1:
        raise SystemExit("锚点不唯一，中止")

    js = js.replace(OLD, NEW, 1)
    print()
    print("=== 改后 ===")
    i = js.find("Dialogue_Zomboss_Start,!1,1).then(")
    print(" ", js[max(0, i - 60):i + 160])
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
