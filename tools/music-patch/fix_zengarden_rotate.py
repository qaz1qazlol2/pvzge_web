# -*- coding: utf-8 -*-
"""修禅境花园 BGM 不轮换（上游原生 bug）。

根因
----
`ZenGarden.musicControl()` 每秒检查：

    pos = (await Music_Aud.getPosition()).position
    dur = await Music_Aud.getDuration()
    if (pos > dur) playAmb();   // 换下一首
    else Music_Aud.setVolume()

播放中：pos 递增到 dur，`pos > dur` 几乎永远不成立 —— 换曲靠的是
**播完之后**的状态。而播完时 `el.onended` 触发 `releaseSlot()`，
把该 id 从 `byId` 删掉，于是：

    getSlot(id) -> null
    getPosition() -> [0, null]      pos = 0
    getDuration() -> null           dur = null

判断变成 `0 > null` → `0 > 0` → **false**，于是走 setVolume 分支
（而且 setVolume 也因为 slot 没了直接 return）。

⇒ 结果就是用户看到的现象：**进场景播第一首，之后再也不换。**

为什么不能简单改成 `pos >= dur`
--------------------------------
刚 `play()` 时 `el.duration` 还是 NaN（元数据未加载），`getDuration()`
也返回 null，`0 >= null` 同样为 true ⇒ 开局就会被误判成「播完了」，
可能连着跳过好几首。**需要区分「还没加载」和「已经播完」。**

修法
----
用「曾经拿到过有效 duration」当锚点：

    dur != null        -> 说明确实在播，记 _ambSeen = true
    dur == null 且 _ambSeen  -> 曾经播过、现在没了 = 播完被回收 -> 换曲

新一首开始时（playAmb 里）把 `_ambSeen` 复位。
这样冷启动的 null 不会误触发，播完的 null 一定触发。

锚点（各 1 处）
---------------
1. `case 4:this.Music_Aud=e.sent;`  （playAmb 拿到新音频）
2. `case 13:if(e.t3=e.sent,!(e.t2>e.t3))`  （musicControl 判定）
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

# 1) playAmb：新曲开始时复位「见过有效时长」标记
OLD1 = 'case 4:this.Music_Aud=e.sent;case 5:case"end":return e.stop()}'
NEW1 = ('case 4:this.Music_Aud=e.sent,this._ambSeen=!1;'
        'case 5:case"end":return e.stop()}')

# 2) musicControl：把「播放中」和「播完被回收」区分开
OLD2 = ('case 13:if(e.t3=e.sent,!(e.t2>e.t3)){e.next=19;break}'
        'return e.next=17,this.playAmb(r);')
NEW2 = ('case 13:if(e.t3=e.sent,null!=e.t3&&(this._ambSeen=!0),'
        '!(e.t2>e.t3||null==e.t3&&this._ambSeen)){e.next=19;break}'
        'return e.next=17,this.playAmb(r);')


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    if "this._ambSeen" in js:
        print("已修过，跳过")
        return 0

    n1, n2 = js.count(OLD1), js.count(OLD2)
    print("锚点命中：playAmb=%d  musicControl=%d" % (n1, n2))
    if n1 != 1 or n2 != 1:
        raise SystemExit("锚点不唯一，中止")

    js = js.replace(OLD1, NEW1, 1).replace(OLD2, NEW2, 1)

    print()
    print("=== 改后 playAmb 尾部 ===")
    i = js.find("case 4:this.Music_Aud=e.sent,this._ambSeen")
    print(" ", js[i:i + 96])
    print()
    print("=== 改后 musicControl case 13 ===")
    j = js.find("case 13:if(e.t3=e.sent,null!=e.t3")
    print(" ", js[j:j + 200])
    print()
    print("字符数 %s -> %s" % (f"{orig:,}", f"{len(js):,}"))

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
