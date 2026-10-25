# -*- coding: utf-8 -*-
"""ZB 分世界 + 教程关家族选卡 —— index.js 代码层。

一、ZB 分段改成分世界
----------------------
现状（全局硬编码，只有 Lostcity 特例）：

    case 30: if(a!=v.ZombossStage0){t.next=36;break}
             u=e==w.Lostcity?A.ZB_Stage0_Lostcity:A.ZB_Stage0,g=!0,s=1/0,t.next=270;break;
    case 36: ... u=A.ZB_Stage1 ...
    case 42: ... u=A.ZB_Stage2 ...
    case 48: ... u=A.ZB_Stage2_Start,c=A.ZB_Stage2,a=v.ZombossStage2 ...

改成按 `e`（世界）选 ZB_<段>_<世界>，没有该世界素材就回落到原有通用曲。

⚠️ 世界枚举名：Iceage 的成员叫 `Ice`，不是 Iceage。

二、教程关（w.Tutorial）补家族分支
-----------------------------------
现状 case 85 只分三路：Lose→88 / Leave→92 / 其余→96（LP_Tutorial）。
所以教程关即使 MusicType=MiniGame_A，也只会播 LP_Tutorial，
`UB_Tutorial` / `MG_Tutorial` / `ZBT_Tutorial` 这些素材永远用不到。

改成 case 96 里按 MusicType 分派（用 `t.t1`，case 85 已经存了 a），
顺序照 ZBT 的惯例：Lose → Leave 已在 88/92，其余在这里判定。

⚠️ `t.t1` 是跨 case 共享的状态机变量，case 85 赋值后 96 仍可读。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

# 有分世界素材的世界（按素材清单实测）
STAGE0_WORLDS = ["Beach", "Cowboy", "Dark", "Dino", "Egypt", "Future",
                 "Iceage", "Modern", "Pirate", "Sky"]
STAGE1_WORLDS = ["Beach", "Cowboy", "Dark", "Dino", "Egypt", "Future",
                 "Iceage", "Lostcity", "Modern", "Pirate", "Sky"]
STAGE2_WORLDS = STAGE1_WORLDS
STAGE2S_WORLDS = STAGE1_WORLDS

WORLD_ENUM = {
    "Egypt": "Egypt", "Pirate": "Pirate", "Cowboy": "Cowboy",
    "Kongfu": "Kongfu", "Future": "Future", "Dark": "Dark",
    "Beach": "Beach", "Iceage": "Ice", "Lostcity": "Lostcity",
    "Sky": "Sky", "Dino": "Dino", "Modern": "Modern",
}

changes = []


def W(w):
    return WORLD_ENUM[w]


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    if "ZB_Stage0_Beach" in js:
        print("已接线，跳过（如需重跑请先 git checkout）")
        return 0

    # ================= 零、MusicEnum 补 51 个成员 =================
    # ⚠️ 少了这步，A.ZB_Stage0_Beach 是 undefined ⇒ playBGM 收到 undefined
    #    会被 `if(!isNaN(e))` 挡掉，直接静音。
    import re
    m_am = re.search(r',([A-Za-z_$][\w$]*)\[([A-Za-z_$][\w$]*)\.MusicAmount=(\d+)\]'
                     r'="MusicAmount"', js)
    if not m_am:
        raise SystemExit("!! 找不到 MusicAmount")
    EP, amount = m_am.group(2), int(m_am.group(3))

    # 顺序必须与 Musics 数组完全一致（铁律 #1）
    NEW_TRACKS = (
        ["ZB_Intro_Beach", "ZB_Intro_Eighties", "ZB_Intro_Modern"]
        + [f"ZB_Stage0_{x}" for x in STAGE0_WORLDS]
        + [f"ZB_Stage1_{x}" for x in STAGE1_WORLDS]
        + [f"ZB_Stage2_{x}" for x in STAGE1_WORLDS]
        + [f"ZB_Stage2_Start_{x}" for x in STAGE1_WORLDS]
        + ["UB_Tutorial", "MG_Tutorial", "ZBT_Tutorial",
           "CYS_LP_Tutorial", "VIC_Tutorial"]
    )
    absent = [n for n in NEW_TRACKS if f'.{n}=' not in js]
    if absent:
        items = ",".join(
            f'{EP}[{EP}.{n}={amount + i}]="{n}"'
            for i, n in enumerate(absent))
        new_am = (f',{items},{EP}[{EP}.MusicAmount={amount + len(absent)}]'
                  f'="MusicAmount"')
        js = js[:m_am.start()] + new_am + js[m_am.end():]
        changes.append(("Z0 MusicEnum",
                        f"新增 {len(absent)} 条（{amount}..{amount + len(absent) - 1}），"
                        f"MusicAmount {amount}→{amount + len(absent)}"))
    else:
        changes.append(("Z0 MusicEnum", "已存在，跳过"))

    # ================= 一、ZB Stage0 =================
    old30 = ("case 30:if(a!=v.ZombossStage0){t.next=36;break}"
             "u=e==w.Lostcity?A.ZB_Stage0_Lostcity:A.ZB_Stage0,"
             "g=!0,s=1/0,t.next=270;break;")
    new30 = ("case 30:if(a!=v.ZombossStage0){t.next=36;break}"
             "switch(e){"
             + "".join(f'case w.{W(x)}:u=A.ZB_Stage0_{x};break;'
                       for x in STAGE0_WORLDS)
             + 'default:u=(e==w.Lostcity?A.ZB_Stage0_Lostcity:A.ZB_Stage0);}'
               "g=!0,s=1/0,t.next=270;break;")
    if js.count(old30) != 1:
        raise SystemExit(f"!! Stage0 锚点命中 {js.count(old30)} 次")
    js = js.replace(old30, new30, 1)
    changes.append(("ZB Stage0", f"{len(STAGE0_WORLDS)} 世界 + Lostcity/通用回落"))

    # ================= 二、ZB Stage1 =================
    old36 = ("case 36:if(a!=v.ZombossStage1){t.next=42;break}"
             "u=A.ZB_Stage1,g=!0,s=1/0,t.next=270;break;")
    new36 = ("case 36:if(a!=v.ZombossStage1){t.next=42;break}"
             "switch(e){"
             + "".join(f'case w.{W(x)}:u=A.ZB_Stage1_{x};break;'
                       for x in STAGE1_WORLDS)
             + "default:u=A.ZB_Stage1;}"
               "g=!0,s=1/0,t.next=270;break;")
    if js.count(old36) != 1:
        raise SystemExit(f"!! Stage1 锚点命中 {js.count(old36)} 次")
    js = js.replace(old36, new36, 1)
    changes.append(("ZB Stage1", f"{len(STAGE1_WORLDS)} 世界 + 通用回落"))

    # ================= 三、ZB Stage2 =================
    old42 = ("case 42:if(a!=v.ZombossStage2){t.next=48;break}"
             "u=A.ZB_Stage2,g=!0,s=1/0,t.next=270;break;")
    new42 = ("case 42:if(a!=v.ZombossStage2){t.next=48;break}"
             "switch(e){"
             + "".join(f'case w.{W(x)}:u=A.ZB_Stage2_{x};break;'
                       for x in STAGE2_WORLDS)
             + "default:u=A.ZB_Stage2;}"
               "g=!0,s=1/0,t.next=270;break;")
    if js.count(old42) != 1:
        raise SystemExit(f"!! Stage2 锚点命中 {js.count(old42)} 次")
    js = js.replace(old42, new42, 1)
    changes.append(("ZB Stage2", f"{len(STAGE2_WORLDS)} 世界 + 通用回落"))

    # ================= 四、ZB Stage2_Start =================
    # ⚠️ 这里同时改 u 和 c（c 是"下一首"提示），两者都要按世界走
    old48 = ("case 48:if(a!=v.ZombossStage2_start){t.next=56;break}"
             "u=A.ZB_Stage2_Start,c=A.ZB_Stage2,g=!0,s=1/0,"
             "a=v.ZombossStage2,t.next=270;break;")
    new48 = ("case 48:if(a!=v.ZombossStage2_start){t.next=56;break}"
             "switch(e){"
             + "".join(f'case w.{W(x)}:u=A.ZB_Stage2_Start_{x};'
                       f'c=A.ZB_Stage2_{x};break;'
                       for x in STAGE2S_WORLDS)
             + "default:u=A.ZB_Stage2_Start,c=A.ZB_Stage2;}"
               "g=!0,s=1/0,a=v.ZombossStage2,t.next=270;break;")
    if js.count(old48) != 1:
        raise SystemExit(f"!! Stage2_Start 锚点命中 {js.count(old48)} 次")
    js = js.replace(old48, new48, 1)
    changes.append(("ZB Stage2_Start",
                    f"{len(STAGE2S_WORLDS)} 世界 + 通用回落（含 c 下一首提示）"))

    # ================= 五、教程关按家族选卡 =================
    old96 = "case 96:return u=A.LP_Tutorial,g=!0,t.abrupt(\"break\",99);"
    new96 = (
        'case 96:return t.t1===v.UltimateBattle'
        '?(u=A.UB_Tutorial,g=!0,t.abrupt("break",99))'
        ':t.t1===v.DemonstrateMinigame'
        '?(u=A.MG_Tutorial,g=!0,t.abrupt("break",99))'
        ':t.t1===v.RemadeZombotany'
        '?(u=A.ZBT_Tutorial,g=!0,t.abrupt("break",99))'
        ':t.t1===v.Loonboon'
        '?(u=A.LB_Tutorial,g=!0,t.abrupt("break",99))'
        ':t.t1===v.Victory'
        '?(u=A.VIC_Tutorial,g=!1,s=1,t.abrupt("break",99))'
        ':t.t1===v.CYS_Start||t.t1===v.CYS_LP'
        '?(u=A.CYS_LP_Tutorial,g=!0,t.abrupt("break",99))'
        ':(u=A.LP_Tutorial,g=!0,t.abrupt("break",99));'
    )
    if js.count(old96) != 1:
        raise SystemExit(f"!! Tutorial case 96 锚点命中 {js.count(old96)} 次")
    js = js.replace(old96, new96, 1)
    changes.append(("教程选卡",
                    "MiniGame_A/B/C/D → UB/MG/ZBT/LB_Tutorial；"
                    "Victory → VIC_Tutorial；CYS → CYS_LP_Tutorial"))

    print("=== 接线结果 ===")
    for tag, msg in changes:
        print(f"  {tag:<20} {msg}")
    print()
    print(f"字符数 {orig:,} → {len(js):,}")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
