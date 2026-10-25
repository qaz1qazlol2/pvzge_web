# -*- coding: utf-8 -*-
"""给 index.js 接 LB（Loonboon / MiniGame_D / 保龄球）分支 —— 完全照 ZBT 的模样。

对照关系
--------
ZBT                          LB
MiniGame_C                   MiniGame_D
RemadeZombotany = 24         Loonboon = 25        ← MusicSortEnum
ZBT_*（378 条）              LB_*（433 条）       ← MusicEnum
__cys_fam = "ZBT"            __cys_fam = "LB"
rk_ZBT_*                     rk_LB_*

9 处接线
--------
L1 MusicSortEnum += Loonboon=25
L2 MusicEnum += 55 条 LB_*，MusicAmount 378 → 433
L3 沙盒强制类型列表 += "MiniGame_D"
L4 加载器三元链 += MiniGame_D 分支
L5 case 11 路由三元链 += MiniGame_D → case 9001
L6 插入 case 9001（记 __cys_target / __cys_fam，先播 CYS_Start）
L7 switchMusic += Loonboon 的世界分派
L8 Victory / Lose += LB 分支
L9 __CYS_TBL += LB 家族表
L10 switchMusicSort 的 isJam 清空列表 += Loonboon

⚠️ 每处都先断言锚点唯一，命中数不对立刻中止 —— 不猜。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_lb_data import build_tracks, dur, SRC  # noqa: E402

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")

TYPE_TAG = "MiniGame_D"
SORT_MEMBER = "Loonboon"
NEW_CASE = 9001          # 避开已有 case 号（patcher.js 也用 9001 这个套路）

# CYS 表：素材没有 Fallback，Jam 六风格统一落到 Ballad
CYS_JAM = ["Ballad", "Punk", "Pop", "Rap", "Eightbit", "Metal"]

# ⚠️ 世界枚举名 ≠ 音频名。WorldMusic 里 Iceage 的成员叫 Ice：
#     t.Beach="Beach", t.Ice="Iceage"
# 写 w.Iceage 会得到 undefined（语法合法但永不命中）。
WORLD_ENUM = {
    "Egypt": "Egypt", "Pirate": "Pirate", "Cowboy": "Cowboy",
    "Kongfu": "Kongfu", "Future": "Future", "Dark": "Dark",
    "Beach": "Beach", "Iceage": "Ice", "Lostcity": "Lostcity",
    "Sky": "Sky", "Dino": "Dino", "Modern": "Modern",
    "Ballad": "Ballad", "Punk": "Punk", "Pop": "Pop",
    "Rap": "Rap", "Eightbit": "Eightbit", "Metal": "Metal",
    "Eighties": "Eighties", "Tutorial": "Tutorial",
}


def W(name):
    """世界名 → 枚举成员名（w.<这个>）"""
    return WORLD_ENUM[name]

changes = []


def need(js, needle, label, count=1):
    n = js.count(needle)
    if n != count:
        raise SystemExit("!! %s 锚点命中 %d 次（期望 %d）\n   %r" %
                         (label, n, count, needle[:120]))
    return js


def step(tag, msg):
    changes.append((tag, msg))


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig_len = len(js)

    # 已经打过补丁？
    if f".{SORT_MEMBER}=" in js:
        print("已存在 Loonboon 枚举，跳过（如需重跑请先 git checkout）")
        return 0

    # ================= L1 MusicSortEnum += Loonboon=25 =================
    m_sort = re.search(r't\[t\.RemadeZombotany=(\d+)\]="RemadeZombotany"', js)
    if not m_sort:
        raise SystemExit("!! L1 找不到 RemadeZombotany")
    base = int(m_sort.group(1)) + 1
    anchor_l1 = m_sort.group(0) + ","
    need(js, anchor_l1, "L1")
    js = js.replace(anchor_l1,
                    m_sort.group(0) + f',t[t.{SORT_MEMBER}={base}]="{SORT_MEMBER}",', 1)
    step("L1 MusicSortEnum", f"新增 {SORT_MEMBER}={base}")

    # ================= L2 MusicEnum += LB_* =================
    m_am = re.search(r',([A-Za-z_$][\w$]*)\[([A-Za-z_$][\w$]*)\.MusicAmount=(\d+)\]'
                     r'="MusicAmount"', js)
    if not m_am:
        raise SystemExit("!! L2 找不到 MusicAmount")
    EN, EP, amount = m_am.group(1), m_am.group(2), int(m_am.group(3))

    tracks = build_tracks()
    names = [t[0] for t in tracks]

    items = ",".join(
        f'{EP}[{EP}.{n}={amount + i}]="{n}"' for i, n in enumerate(names))
    new_am = (f',{items},{EP}[{EP}.MusicAmount={amount + len(names)}]'
              f'="MusicAmount"')
    js = js[:m_am.start()] + new_am + js[m_am.end():]
    step("L2 MusicEnum",
         f"新增 {len(names)} 条（{amount}..{amount + len(names) - 1}），"
         f"MusicAmount {amount}→{amount + len(names)}")

    # ================= L3 沙盒强制类型列表 =================
    a3 = '"MiniGame_A","MiniGame_B","Normal","Zomboss","KongfuBoss","MiniGame_C")'
    need(js, a3, "L3")
    js = js.replace(
        a3,
        '"MiniGame_A","MiniGame_B","Normal","Zomboss","KongfuBoss",'
        '"MiniGame_C","' + TYPE_TAG + '")', 1)
    step("L3 沙盒类型列表", f'追加 "{TYPE_TAG}"')

    # ================= L4 加载器三元链 =================
    # 现状：..."MiniGame_C"==(null==a?void 0:a.MusicType)?s.push("MiniGame_C"):null!=a&&a.IsDangerRoom...
    a4 = ('"MiniGame_C"==(null==(a=null))')  # 占位，实际用正则
    m4 = re.search(
        r'("MiniGame_C"==\(null==([A-Za-z_$][\w$]*)\?void 0:\2\.MusicType\)'
        r'\?([A-Za-z_$][\w$]*)\.push\("MiniGame_C"\):)', js)
    if not m4:
        raise SystemExit("!! L4 找不到加载器三元链")
    v4 = m4.group(2)
    ins4 = (f'"{TYPE_TAG}"==(null=={v4}?void 0:{v4}.MusicType)'
            f'?{m4.group(3)}.push("{TYPE_TAG}"):')
    js = js[:m4.end(1)] + ins4 + js[m4.end(1):]
    step("L4 加载器三元链", f'新增 "{TYPE_TAG}" 分支')

    # ================= L5 case 11 路由三元链 =================
    a5 = '"MiniGame_C"===e.t0?17:18'
    need(js, a5, "L5")
    js = js.replace(a5, f'"MiniGame_C"===e.t0?17:"{TYPE_TAG}"===e.t0?{NEW_CASE}:18', 1)
    step("L5 路由三元链", f"{TYPE_TAG} → case {NEW_CASE}")

    # ================= L6 插入 case 9001 =================
    # ⚠️ 必须插在 case 18 之前。case 18 会 fall through 到 case 19，
    #    插在 18 和 19 之间会让普通关卡也走进来。
    a6 = 'case 18:this.startingMusic='
    need(js, a6, "L6")
    m6 = re.search(r'case 18:this\.startingMusic=([A-Za-z_$][\w$]*)\.CYS_Start;', js)
    if not m6:
        raise SystemExit("!! L6 找不到 case 18 主体")
    ME = m6.group(1)
    body6 = (f'case {NEW_CASE}:return window.__cys_target={ME}.{SORT_MEMBER},'
             f'window.__cys_fam="LB",this.startingMusic={ME}.CYS_Start,'
             f'e.abrupt("break",19);')
    js = js[:m6.start()] + body6 + js[m6.start():]
    step("L6 case 9001", "记 __cys_target / __cys_fam，先播 CYS_Start")

    # ================= L7 switchMusic 的 Loonboon 世界分派 =================
    a7 = "this.isJam=!1,o){t.next=270;break}"
    need(js, a7, "L7")
    m7 = re.search(r"switchMusic=function\(\)\{var t=S\(n\(\)\.mark\(\(function t\("
                   r"([A-Za-z_$][\w$]*),([A-Za-z_$][\w$]*),", js)
    if not m7:
        raise SystemExit("!! L7 解析不出 switchMusic 形参")
    world_v, sort_v = m7.group(1), m7.group(2)

    # 世界 → 主音轨。Eighties 复用 Ballad（素材没有 LB_Eighties）
    main_worlds = ["Egypt", "Pirate", "Cowboy", "Kongfu", "Future", "Dark",
                   "Beach", "Iceage", "Lostcity", "Sky", "Dino", "Modern",
                   "Ballad", "Punk", "Pop", "Rap", "Eightbit", "Metal"]
    cases7 = "".join(
        f'case w.{W(w)}:u=A.LB_{w};break;' for w in main_worlds)
    cases7 += 'case w.Eighties:u=A.LB_Ballad;break;'
    block7 = (f'if({sort_v}==v.{SORT_MEMBER}){{switch({world_v}){{'
              f'{cases7}default:u=A.LB_Ballad;}}g=!0,t.next=270;break}}')
    js = js.replace(a7, a7 + block7, 1)
    step("L7 switchMusic 世界分派", f"{len(main_worlds) + 1} 个世界")

    # ================= L8a Victory =================
    # LB 素材：Pirate/Cowboy/Future/Dark/Beach/Iceage/Lostcity/Dino/Modern/Eighties
    # 其余（Egypt/Kongfu/Sky/Tutorial）用通用 LB_Victory
    vic_worlds = ["Pirate", "Cowboy", "Future", "Dark", "Beach", "Iceage",
                  "Lostcity", "Dino", "Modern", "Eighties"]
    vcases = "".join(f'case w.{W(w)}:u=A.LB_Victory_{w};break;' for w in vic_worlds)
    for j in [x for x in CYS_JAM if x not in vic_worlds]:
        vcases += f'case w.{W(j)}:u=A.LB_Victory_Eighties;break;'
    block8a = (f'if({sort_v}==v.Victory&&window.__mts=="{TYPE_TAG}")'
               f'{{switch({world_v}){{{vcases}'
               f'default:u=A.LB_Victory;}}g=!1,s=1,t.next=270;break}}')

    a8 = 'if(' + sort_v + '==v.Victory&&window.__mts=="MiniGame_C")'
    need(js, a8, "L8a")
    js = js.replace(a8, block8a + a8, 1)
    step("L8a Victory", f"{len(vic_worlds)} 个分世界 + 6 Jam 别名 + 通用")

    # ================= L8b Lose =================
    lose_worlds = ["Pirate", "Cowboy", "Future", "Dark", "Beach", "Iceage",
                   "Lostcity", "Dino", "Modern", "Eighties"]
    lcases = "".join(f'case w.{W(w)}:u=A.LB_Lose_{w};break;' for w in lose_worlds)
    for j in [x for x in CYS_JAM if x not in lose_worlds]:
        lcases += f'case w.{W(j)}:u=A.LB_Lose_Eighties;break;'
    block8b = (f'if({sort_v}==v.Lose&&window.__mts=="{TYPE_TAG}")'
               f'{{switch({world_v}){{{lcases}'
               f'default:u=A.LB_Lose;}}g=!1,s=1,t.next=270;break}}')

    a8b = 'if(' + sort_v + '==v.Lose&&window.__mts=="MiniGame_C")'
    need(js, a8b, "L8b")
    js = js.replace(a8b, block8b + a8b, 1)
    step("L8b Lose", f"{len(lose_worlds)} 个分世界 + 6 Jam 别名 + 通用")

    # ================= L9 __CYS_TBL += LB =================
    # 原结构：window.__CYS_TBL={UB:{...},MG:{...},ZBT:{...}};
    #                                    ↑ 这个 } 关 ZBT，下一个 } 关整个表
    # 所以锚点 "Fallback:A.ZBT_CYS_Fallback}};" 里的两个 } 分别关 ZBT 和表。
    # 替换时必须**只保留一个 }**（关 ZBT），再接 ",LB:{...}" ，最后自己补关闭。
    a9 = 'Tutorial:A.ZBT_CYS_Tutorial,Fallback:A.ZBT_CYS_Fallback}};'
    need(js, a9, "L9")
    cys_w = ["Egypt", "Pirate", "Cowboy", "Kongfu", "Future", "Dark", "Beach",
             "Iceage", "Lostcity", "Sky", "Dino", "Modern", "Ballad", "Tutorial"]
    entries = "".join(f'{W(w)}:A.LB_CYS_{w},' for w in cys_w)
    # 素材没有 Fallback / Punk 等，Jam 六风格与 Fallback 统一落 Ballad。
    # ⚠️ Ballad 已在 cys_w 里，Jam 列表也含 Ballad —— 必须先排除，
    #    否则对象字面量里出现重复键（JS 合法但会被后值覆盖，且 Object.keys 变少）。
    jam_extra = [j for j in CYS_JAM if j not in cys_w]
    entries += "".join(f'{W(j)}:A.LB_CYS_Ballad,' for j in jam_extra)
    entries += "Eighties:A.LB_CYS_Ballad,Fallback:A.LB_CYS_Ballad"
    js = js.replace(
        a9,
        'Tutorial:A.ZBT_CYS_Tutorial,Fallback:A.ZBT_CYS_Fallback},'
        'LB:{' + entries + '}};', 1)
    step("L9 __CYS_TBL",
         f"LB 家族 {len(cys_w) + len(jam_extra) + 2} 个键"
         f"（Jam 别名 {len(jam_extra)} 个，Ballad 已含故不重复）")

    # ================= L10 isJam 清空列表 =================
    a10 = "e==v.RemadeZombotany||e==v.Victory"
    need(js, a10, "L10")
    js = js.replace(a10, f"e==v.RemadeZombotany||e==v.{SORT_MEMBER}||e==v.Victory", 1)
    step("L10 isJam 清空列表", f"+= {SORT_MEMBER}")

    # ================= 收尾 =================
    print("=== 接线结果 ===")
    for tag, msg in changes:
        print(f"  {tag:<24} {msg}")
    print()
    print(f"字符数 {orig_len:,} → {len(js):,}")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
