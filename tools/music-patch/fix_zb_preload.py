# -*- coding: utf-8 -*-
"""修正 ZombossIntro 里的 `c`（预加载提示）指向对应世界的 Stage0。

背景
----
case 270 里 `this.nextToPlay=c` —— `c` 是**预加载下一首**的提示。
原来的每个世界 case 都是 `u=A.ZBI_<世界>,g=!1,c=A.ZB_Stage0`，
也就是 Intro 分世界、但预加载提示统一指通用 Stage0。

现在 Stage0 也分世界了（10 个世界有素材），`c` 必须一起走，
否则会预加载到错的曲子。

⚠️ 不能无脑全替换：
   Eighties 的 Intro 复用 ZBI_Future（本来就没 ZB_Intro_Eighties 素材），
   但它**有** ZB_Stage0_Eighties —— 所以 Eighties 也要改 c。
   Kongfu 的 Intro 复用 ZBI_Egypt，而且**没有** ZB_Stage0_Kongfu，
   必须保持 c=A.ZB_Stage0 通用。
   Lostcity 原本就是 c=A.ZB_Stage0_Lostcity，不动。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

# case 号 → 世界名（switchMusic 的世界分派表）
CASE_WORLD = {
    100: "Egypt", 102: "Pirate", 104: "Cowboy", 106: "Future",
    108: "Dark", 110: "Beach", 112: "Iceage", 114: "Lostcity",
    116: "Eighties", 118: "Sky", 120: "Kongfu", 266: "Dino",
    268: "Modern",
}

# 有 ZB_Stage0_<世界> 素材的世界
HAS_STAGE0 = {"Beach", "Cowboy", "Dark", "Dino", "Egypt", "Future",
              "Iceage", "Modern", "Pirate", "Sky", "Lostcity"}


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    changes = []
    # 匹配 `a==v.ZombossIntro?(u=A.ZBI_x,g=!1,c=A.ZB_Stage0,a=v.ZombossStage0)`
    pat = re.compile(
        r'a==v\.ZombossIntro\?\(u=A\.ZBI_(\w+),g=!1,c=A\.ZB_Stage0,'
        r'a=v\.ZombossStage0\)')

    out = []
    last = 0
    for m in pat.finditer(js):
        # 往前找最近的 case 号
        prev = None
        for cm in re.finditer(r'case (\d+):', js[:m.start()]):
            prev = cm
        case = int(prev.group(1)) if prev else -1
        world = CASE_WORLD.get(case)

        if world and world in HAS_STAGE0:
            repl = (f'a==v.ZombossIntro?(u=A.ZBI_{m.group(1)},g=!1,'
                    f'c=A.ZB_Stage0_{world},a=v.ZombossStage0)')
            out.append(js[last:m.start()])
            out.append(repl)
            last = m.end()
            changes.append((f"case {case} {world}",
                            f"c: ZB_Stage0 → ZB_Stage0_{world}"))
        else:
            changes.append((f"case {case} {world or '?'}",
                            "保持通用 ZB_Stage0（该世界无素材）"))

    out.append(js[last:])
    js2 = "".join(out)

    print("=== 修正结果 ===")
    for tag, msg in changes:
        print(f"  {tag:<22} {msg}")
    print()
    print(f"字符数 {orig:,} → {len(js2):,}")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js2)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
