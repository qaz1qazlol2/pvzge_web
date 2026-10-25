# -*- coding: utf-8 -*-
"""把 ZB_Intro_<世界> 接进 ZombossIntro（只 3 个世界有素材）。

现状：每个世界的 case 里都是 `u=A.ZBI_<世界>`（原生短版 6s）。
素材新增了 ZB_Intro_Beach / ZB_Intro_Eighties / ZB_Intro_Modern，
比原生 ZBI 长（8.3 / 8.3 / 9.7s），是完整的开场。

⚠️ 只替换有素材的 3 个世界，其余保持 ZBI_*（原生版）。
⚠️ Eighties 现在用的是 ZBI_Future，要换成 ZB_Intro_Eighties。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

CASE_WORLD = {
    100: "Egypt", 102: "Pirate", 104: "Cowboy", 106: "Future",
    108: "Dark", 110: "Beach", 112: "Iceage", 114: "Lostcity",
    116: "Eighties", 118: "Sky", 120: "Kongfu", 266: "Dino",
    268: "Modern",
}

# 有 ZB_Intro_<世界> 素材的
HAS_INTRO = {"Beach", "Eighties", "Modern"}


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    # 匹配 `u=A.ZBI_xxx,g=!1,c=...`
    pat = re.compile(r'a==v\.ZombossIntro\?\(u=A\.ZBI_(\w+),g=!1,c=')

    out, last, changes = [], 0, []
    for m in pat.finditer(js):
        prev = None
        for cm in re.finditer(r'case (\d+):', js[:m.start()]):
            prev = cm
        case = int(prev.group(1)) if prev else -1
        world = CASE_WORLD.get(case)

        if world in HAS_INTRO:
            repl = (f'a==v.ZombossIntro?(u=A.ZB_Intro_{world},g=!1,c=')
            out.append(js[last:m.start()])
            out.append(repl)
            last = m.end()
            changes.append((f"case {case} {world}",
                            f"ZBI_{m.group(1)} → ZB_Intro_{world}"))
        else:
            changes.append((f"case {case} {world or '?'}",
                            f"保持 ZBI_{m.group(1)}（无 Intro 素材）"))

    out.append(js[last:])
    js2 = "".join(out)

    print("=== 结果 ===")
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
