#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_music.py —— 把 RemadeZombotany（内部类型 MiniGame_C）的音乐定制
重放到游戏数据文件上。适配游戏 0.16.0+。

背景
----
0.16.0 把音频链路整个换了：

  0.14.0                          0.16.0
  ------------------------------------------------------------------
  resources/native/<uuid>.mp3     audio/Music/Game/<世界>/*.mp3
  config.json 的 uuids + paths    audio/manifest.json（key → 相对路径）
  Musics: {name,path,world,type}  Musics: {name, tauri, musicLength}
  import/0a/0a278bb49.json        import/0d/0d4cac202.json
                                  （内容哈希当文件名，上游一变就得重新找）

所以本脚本不再碰 config.json 的 uuids/paths，也**不按固定路径**找 Musics ——
它会在 import/ 目录里搜索 `"Musics":[` 唯一出现的位置。

`tauri` 是 manifest 的 key，不是路径。播放时由 game-audio.js 查表拼 URL：

    MusicEnum(数字) → bgms[i] {tauri, musicLength}
                    → manifest[tauri] → audio/<相对路径>

定制的范围
----------
RemadeZombotany 是**独立的音乐类型**，不复用上游的 MG_ / VIC_ / UB_ 任何一条：

  * MusicSortEnum   + RemadeZombotany = 24
  * MusicEnum       + 25 条 ZBT_*（260..284），MusicAmount 260 → 285
  * Musics          + 25 条 {name,tauri,musicLength}
  * manifest.json   + 25 个 key → inGame/ZBT_*/*.mp3
  * 音频文件         audio/Music/inGame/ZBT_*/<名字>.mp3（独立目录，绝不覆盖上游）

为什么 victory 也要分世界：RemadeZombotany 是独立曲库，各世界的结算曲也要能
单独换。上游自己的 VIC_* 只服务它自己的模式，不与我们共用。

用法
----
    python apply_music.py                # 应用（默认）
    python apply_music.py --check        # 只看会改什么，不落盘
    python apply_music.py --verify       # 只校验当前状态
    python apply_music.py --gen-import   # 顺便补 import json / 复制缺的音频

退出码：0 成功 / 1 失败
"""

import argparse
import json
import os
import re
import shutil
import sys

# 必须最早导入：Windows 下 stdout 走管道时会退回 cp936，中文全乱码。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

TYPE_TAG = "MiniGame_C"      # 对外 MusicType 字符串（游戏里叫 RemadeZombotany）
SORT_MEMBER = "RemadeZombotany"    # MusicSortEnum 的成员名

# 音频根目录（相对 docs/audio/）。0.16.0 起音频从 native/ 搬到这里。
# 注意别写成 "audio/Music/..."：audio_abs() 已经拼了 docs/audio/ 前缀。
AUDIO_ROOT = os.path.join("Music", "inGame")

# --------------------------------------------------------------------------
# 音轨清单
# --------------------------------------------------------------------------
# name       —— 音轨名，也是 Musics 的 name 和 manifest 的 key 后缀
# world      —— Musics 条目的 world 用途（这里只用于目录分组）
# world_enum —— index.js 里 WorldMusic 枚举的成员名（Iceage 的成员叫 Ice）
# src_uuid   —— 旧版 native/<uuid>.mp3 的文件名（迁移时从这里取音频）
# music_len  —— 循环点秒数（Musics 的 musicLength）
# duration   —— 音频真实时长
TRACKS = [
    dict(name="ZBT_Egypt",    world="Egypt",    world_enum="Egypt",    src_uuid="89b35a32", music_len=181, duration=184.941),
    dict(name="ZBT_Pirate",   world="Pirate",   world_enum="Pirate",   src_uuid="b7000001", music_len=181, duration=184.941),
    dict(name="ZBT_Cowboy",   world="Cowboy",   world_enum="Cowboy",   src_uuid="b7000002", music_len=181,   duration=184.941),
    dict(name="ZBT_Kongfu",   world="Kongfu",   world_enum="Kongfu",   src_uuid="b7000003", music_len=181,   duration=184.941),
    dict(name="ZBT_Future",   world="Future",   world_enum="Future",   src_uuid="b7000004", music_len=181,   duration=184.941),
    dict(name="ZBT_Dark",     world="Dark",     world_enum="Dark",     src_uuid="b7000005", music_len=181,   duration=184.941),
    dict(name="ZBT_Beach",    world="Beach",    world_enum="Beach",    src_uuid="b7000006", music_len=181, duration=185.000),
    dict(name="ZBT_Iceage",   world="Iceage",   world_enum="Ice",      src_uuid="b7000007", music_len=181, duration=184.941),
    dict(name="ZBT_Lostcity", world="Lostcity", world_enum="Lostcity", src_uuid="b7000008", music_len=181,   duration=184.941),
    dict(name="ZBT_Sky",      world="Sky",      world_enum="Sky",      src_uuid="b7000009", music_len=181,   duration=184.941),
    dict(name="ZBT_Dino",     world="Dino",     world_enum="Dino",     src_uuid="b700000a", music_len=181,   duration=184.941),
    dict(name="ZBT_Modern",   world="Modern",   world_enum="Modern",   src_uuid="b700000b", music_len=193,   duration=196.539),
    # ⚠️ ZBT_Victory 用的是补丁里的 ZBT_Victory.mp3（4.760s / 192k），
    # 不是早期那个 96k / 5.993s 的占位文件。
    # musicLength 按补丁规则 = 实测时长 - 0.05。
    dict(name="ZBT_Victory",  world="All",      world_enum=None,       src_uuid="b700000c", music_len=4.71,  duration=4.760),
]

FALLBACK_VICTORY = "ZBT_Victory"

# --------------------------------------------------------------------------
# 炫光魔音游（Jam 世界）的曲目
# --------------------------------------------------------------------------
# 这些世界在引擎里走 isJam 分支（`this.isJam=!0`，动态分层变奏），
# 曲目结构与常规世界不同。八零世界（Eighties）在引擎里复用 Ballad 的分支，
# 所以 Eighties 映射到 ZBT_Ballad（与外部补丁的别名处理一致）。
#
# ⚠️ 追加在 ALL_TRACKS 的**最末尾**，这样已有的 260..284 下标不会挪动。
JAM_TRACKS = [
    dict(name="ZBT_Ballad",   world="Ballad",   world_enum="Ballad",   src_uuid="b7000019", music_len=181, duration=184.941),
    dict(name="ZBT_Punk",     world="Punk",     world_enum="Punk",     src_uuid="b700001a", music_len=181, duration=184.941),
    dict(name="ZBT_Pop",      world="Pop",      world_enum="Pop",      src_uuid="b700001b", music_len=181, duration=184.941),
    dict(name="ZBT_Rap",      world="Rap",      world_enum="Rap",      src_uuid="b700001c", music_len=181, duration=184.941),
    dict(name="ZBT_Eightbit", world="Eightbit", world_enum="Eightbit", src_uuid="b700001d", music_len=181, duration=184.941),
    dict(name="ZBT_Metal",    world="Metal",    world_enum="Metal",    src_uuid="b700001e", music_len=181, duration=184.941),
]

# 世界枚举值 → 实际使用的音轨。Eighties 复用 Ballad 的曲子。
WORLD_ALIASES = {"Eighties": "ZBT_Ballad"}


# --------------------------------------------------------------------------
# Jam 世界的 UB / MG 曲目（劫持引擎已有条目）
# --------------------------------------------------------------------------
# 和 ZBT_* 完全不同的一套做法 —— 这里**不新增条目**，而是直接改引擎里
# 已经存在的 UB_Punk / MG_Punk 等 12 条的 tauri 指向我们的音频。
#
# 为什么这么做（外部补丁的经验）：
#   引擎的 switchMusic 里，Jam 世界的分支本来就写死了
#       case 122: a==v.UltimateBattle ? (u=A.UB_Ballad, ...)
#                 a==v.DemonstrateMinigame ? (u=A.MG_Ballad, ...)
#   这些 A.UB_Ballad / A.MG_Ballad 是**枚举下标**，而 Musics 里对应的条目
#   原本指向 Music_Future_UB / Music_Future_MG（官方偷懒复用了 Future 的曲子）。
#   所以只要把那条目的 tauri 换掉，整条链路一行代码都不用改。
#
# ⚠️ 名字大小写必须跟引擎一致：引擎用 `UB_EightBit`（大写 B），
#    而补丁文件名是 `UB_Eightbit.mp3`，转换时要注意。
#
# musicLength 也按补丁的规则走「实际时长 - 0.05」，强制由 update 跳轨
# （Cocos 的 AudioClip 自然播完会把 currentTime 清零，导致循环接轨失效）。
JAM_UBMG_TRACKS = [
    dict(name="UB_Ballad",   jam="Ballad",   fam="UB", music_len=185.547, duration=185.597),
    dict(name="UB_Punk",     jam="Punk",     fam="UB", music_len=185.547, duration=185.597),
    dict(name="UB_Pop",      jam="Pop",      fam="UB", music_len=185.547, duration=185.597),
    dict(name="UB_Rap",      jam="Rap",      fam="UB", music_len=185.547, duration=185.597),
    dict(name="UB_EightBit", jam="Eightbit", fam="UB", music_len=185.547, duration=185.597),
    dict(name="UB_Metal",    jam="Metal",    fam="UB", music_len=185.547, duration=185.597),
    dict(name="MG_Ballad",   jam="Ballad",   fam="MG", music_len=184.805, duration=184.855),
    dict(name="MG_Punk",     jam="Punk",     fam="MG", music_len=184.805, duration=184.855),
    dict(name="MG_Pop",      jam="Pop",      fam="MG", music_len=184.805, duration=184.855),
    dict(name="MG_Rap",      jam="Rap",      fam="MG", music_len=184.805, duration=184.855),
    dict(name="MG_EightBit", jam="Eightbit", fam="MG", music_len=184.805, duration=184.855),
    dict(name="MG_Metal",    jam="Metal",    fam="MG", music_len=184.805, duration=184.855),
]


# --------------------------------------------------------------------------
# 选卡前奏（CYS = Choose Your Seeds）
# --------------------------------------------------------------------------
# 进关卡先播一小段循环前奏，玩家摆好卡按开始后再切到正曲。
# 三套各按家族分开：UB（极限战斗）/ MG（演示小游戏）/ ZBT（RemadeZombotany）。
# ⚠️ LB（保龄球）不做 —— 用户明确排除。
#
# musicLength 取自外部补丁 patcher.js 的硬编码规则：
#   UB_CYS 8.5 / MG_CYS 10.5 / ZBT_CYS 8.7
#
# ⚠️ 各家族覆盖的世界**不一样**，不能按同一份清单生成：
#   UB / MG  19 个世界（含 6 个 Jam：Ballad/Punk/Pop/Rap/Eightbit/Metal）+ Tutorial
#   ZBT      14 个世界 + Fallback —— 缺 Punk/Pop/Rap/Eightbit/Metal 五条 jam 前奏，
#            那五个世界由 Fallback 兜底（与外部补丁的做法一致）
#
# ⚠️ 三套都要有 Fallback 通用前奏：
#   开局时 Jam 风格还没定（Ballad/Punk/… 由 boombox 后切），选卡阶段只需要一条通用的。
#   查表时先按世界查，查不到就落到 Fallback，再查不到才回退官方曲。
#
# 这些条目同样**追加在末尾**，不打乱已有下标。
_CYS_COMMON = ["Egypt", "Pirate", "Cowboy", "Kongfu", "Future", "Dark",
               "Beach", "Iceage", "Lostcity", "Sky", "Dino", "Modern"]
_CYS_JAM = ["Ballad", "Punk", "Pop", "Rap", "Eightbit", "Metal"]

CYS_TRACKS = []
for _fam, _ml, _dur in (("UB", 8.5, 9.05), ("MG", 10.5, 10.55)):
    for _w in _CYS_COMMON + _CYS_JAM + ["Tutorial"]:
        CYS_TRACKS.append(dict(name=f"{_fam}_CYS_{_w}", fam=_fam,
                               cys_world=_w, music_len=_ml, duration=_dur))
    # 通用兜底（Jam 世界开局风格未定，用它）
    CYS_TRACKS.append(dict(name=f"{_fam}_CYS_Fallback", fam=_fam,
                           cys_world="Fallback", music_len=_ml, duration=_dur))
for _w in _CYS_COMMON + ["Ballad"] + ["Tutorial"]:
    CYS_TRACKS.append(dict(name=f"ZBT_CYS_{_w}", fam="ZBT",
                           cys_world=_w, music_len=8.7, duration=8.75))
CYS_TRACKS.append(dict(name="ZBT_CYS_Fallback", fam="ZBT",
                       cys_world="Fallback", music_len=8.7, duration=8.75))

ALL_TRACKS = TRACKS + JAM_TRACKS + CYS_TRACKS


class Fail(Exception):
    pass


def read_text(p):
    with open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_text(p, s):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def _num(v):
    """整数就写成整数，否则保留小数。"""
    return str(int(v)) if float(v) == int(v) else repr(float(v))


def audio_rel(t):
    """音频相对 audio/ 的路径：Music/inGame/ZBT_Egypt/ZBT_Egypt.mp3"""
    return "%s/%s/%s.mp3" % (AUDIO_ROOT.replace("\\", "/"), t["name"], t["name"])


def audio_abs(repo, t):
    return os.path.join(repo, "docs", "audio", audio_rel(t).replace("/", os.sep))


def manifest_key(t):
    """manifest 的 key。加 rk_ 前缀避免与上游 key 撞车。"""
    return "rk_" + t["name"]


# --------------------------------------------------------------------------
# 0.16.0 的 index.js 锚点
# --------------------------------------------------------------------------
def find_enum_alias(js, enum_name):
    """返回 (枚举别名, 参数名)。例：A = t('MusicEnum', function(t){...})"""
    m = re.search(r"([A-Za-z_$][\w$]*)\s*=\s*[A-Za-z_$][\w$]*\(\"" +
                  re.escape(enum_name) + r"\",\s*function\s*\(([A-Za-z_$][\w$]*)\)",
                  js)
    if not m:
        raise Fail(f"找不到 {enum_name} 的定义")
    return m.group(1), m.group(2)


def patch_index_js(js):
    """给 0.16.0 的 index.js 打 RemadeZombotany 补丁。返回 (新文本, 改动列表)。"""
    changes = []
    orig = js
    EN, EP = find_enum_alias(js, "MusicEnum")          # 音乐枚举别名 + 参数
    SORT, SP = find_enum_alias(js, "MusicSortEnum")    # 排序枚举
    WORLD, _ = find_enum_alias(js, "WorldMusic")       # 世界枚举

    # ---- S1: MusicSortEnum += RemadeZombotany ----
    if re.search(r"\b" + SP + r"\[" + SP + r"\.RemadeZombotany=", js):
        changes.append(("S1 MusicSortEnum", "已存在，跳过"))
    else:
        tail = js.find("t}({}))", js.find('"MusicSortEnum"'))
        if tail < 0:
            raise Fail("S1 找不到 MusicSortEnum 的收尾")
        # 当前最大成员值
        seg_start = js.find('"MusicSortEnum"')
        vals = [int(v) for _, v in re.findall(
            r"t\[t\.(\w+)=(\d+)\]=\"", js[seg_start:tail])]
        base = max(vals) + 1 if vals else 0
        # 原版收尾是 `,t[t.Stage4_LP=23]="Stage4_LP",t}({}))`
        # 注意末尾那个逗号 —— 插到这里要**自带尾逗号、不带前导逗号**，
        # 否则会变成 `,,` 且缺分隔符。
        ins = f'{SP}[{SP}.{SORT_MEMBER}={base}]="{SORT_MEMBER}",'
        js = js[:tail] + ins + js[tail:]
        changes.append(("S1 MusicSortEnum", f"新增 {SORT_MEMBER}={base}"))

    # ---- S2: MusicEnum 重排 RZ 段 ----
    # 不再「只追加」—— 增删条目后后面的下标必须整体前移，
    # 否则「枚举值 == Musics 下标」这条铁律就被破坏，bgms[i] 会取到别人的曲子。
    #
    # 做法：整段重建。以第一條 RZ 成员的原始值为基准，按 ALL_TRACKS 的顺序
    # 连续编号。这样加、删、换序都能一次到位，且天然幂等。
    m_am = re.search(r"," + re.escape(EP) + r"\[" + re.escape(EP) +
                     r"\.MusicAmount=(\d+)\]=\"MusicAmount\"", js)
    if not m_am:
        raise Fail("S2 找不到 MusicAmount 哨兵")

    # 改名后条目有三个前缀：ZBT_*（主曲/结算）、UB_CYS_*、MG_CYS_*。
    # 正则必须都覆盖，否则会漏掉 40 条 CYS 前奏。
    _NAME_ALT = r"(?:ZBT|UB_CYS|MG_CYS)_\w+"
    pat_first = re.compile(r"(?:," + re.escape(EP) + r"\[" + re.escape(EP) +
                           r"\.(" + _NAME_ALT + r")=(\d+)\]=\""
                           r"(?:" + _NAME_ALT + r")\")")
    m_first = pat_first.search(js)
    if not m_first:
        # 一条都没有：整段新插到 MusicAmount 前面
        base = int(m_am.group(1))
        items = ",".join(f'{EP}[{EP}.{t["name"]}={base + i}]="{t["name"]}"'
                         for i, t in enumerate(ALL_TRACKS))
        new = (f',{items},{EP}[{EP}.MusicAmount={base + len(ALL_TRACKS)}]'
               f'="MusicAmount"')
        js = js[:m_am.start()] + new + js[m_am.end():]
        changes.append(("S2 MusicEnum",
                        f"新建 {len(ALL_TRACKS)} 条，"
                        f"MusicAmount {base}→{base + len(ALL_TRACKS)}"))
    else:
        base = int(m_first.group(2))
        # 现状成员（顺序 + 下标）
        cur = re.findall(r"," + re.escape(EP) + r"\[" + re.escape(EP) +
                         r"\.(" + _NAME_ALT + r")=(\d+)\]=\""
                         r"(?:" + _NAME_ALT + r")\"", js)
        cur_names = [c[0] for c in cur]
        want_names = [t["name"] for t in ALL_TRACKS]
        dropped = [n for n in cur_names if n not in want_names]
        added = [n for n in want_names if n not in cur_names]
        renum = [n for i, n in enumerate(want_names)
                 if n in cur_names and int(dict(
                     (c[0], c[1]) for c in cur).get(n, -1)) != base + i]

        if not dropped and not added and not renum:
            changes.append(("S2 MusicEnum", "布局一致，跳过"))
        else:
            items = ",".join(f'{EP}[{EP}.{t["name"]}={base + i}]="{t["name"]}"'
                             for i, t in enumerate(ALL_TRACKS))
            new = (f",{items},{EP}[{EP}.MusicAmount={base + len(ALL_TRACKS)}]"
                   f'="MusicAmount"')
            js = js[:m_first.start()] + new + js[m_am.end():]
            desc = []
            if dropped:
                desc.append(f"删 {len(dropped)} 条")
            if added:
                desc.append(f"加 {len(added)} 条")
            if renum:
                desc.append(f"前移 {len(renum)} 条")
            changes.append(("S2 MusicEnum",
                            f"{'、'.join(desc)}；共 {len(ALL_TRACKS)} 条，"
                            f"MusicAmount={base + len(ALL_TRACKS)}"
                            ))

    # ---- S3: 沙盒强制类型列表 ----
    needle = '"MiniGame_A","MiniGame_B","Normal","Zomboss","KongfuBoss")'
    if needle.replace("KongfuBoss\")", f'KongfuBoss","{TYPE_TAG}")') in js:
        changes.append(("S3 沙盒类型列表", "已存在，跳过"))
    elif needle in js:
        js = js.replace(needle,
                        needle[:-1] + f',"{TYPE_TAG}")', 1)
        changes.append(("S3 沙盒类型列表", f'追加 "{TYPE_TAG}"'))
    else:
        raise Fail("S3 找不到沙盒强制类型列表")

    # ---- S4: 加载器三元链（MusicType → 资源包列表）----
    if f'"{TYPE_TAG}"==(null==' in js:
        changes.append(("S4 加载器三元链", "已存在，跳过"))
    else:
        pat = (r'("MiniGame_B"==\(null==([A-Za-z_$][\w$]*)\?void 0:\2\.MusicType\)'
               r'\?([A-Za-z_$][\w$]*)\.push\("MiniGame_B"\):)')
        m = re.search(pat, js)
        if not m:
            raise Fail("S4 找不到加载器三元链")
        v, arr = m.group(2), m.group(3)
        ins = (f'"{TYPE_TAG}"==(null=={v}?void 0:{v}.MusicType)'
               f'?{arr}.push("{TYPE_TAG}"):')
        js = js[:m.end(1)] + ins + js[m.end(1):]
        changes.append(("S4 加载器三元链", f'新增 "{TYPE_TAG}" 分支'))

    # ---- S5: levelController 的 MusicType → 起始音乐 ----
    if re.search(r'"' + re.escape(TYPE_TAG) + r'"===\w+\.t0', js):
        changes.append(("S5 levelController", "已存在，跳过"))
    else:
        m = re.search(r'"MiniGame_B"===([A-Za-z_$][\w$]*)\.t0\?(\d+):(\d+)', js)
        if not m:
            raise Fail("S5 找不到 MusicType 判定三元链")
        var, case_b, case_def = m.group(1), int(m.group(2)), int(m.group(3))
        # 在 MiniGame_B 分支和 else 之间插一个新 case 号
        new_case = case_b + 1
        # MiniGame_B 的 case 体 + 紧邻的下一个 case 整体后移
        js = re.sub(r'(case 16:return this\.startingMusic=[\w$.]+'
                    r',e\.abrupt\("break",19\);)',
                    r'\1', js)  # 仅确认存在
        # 改三元链：MiniGame_B→16, MiniGame_C→新号, else→原 else
        js = js[:m.start()] + (
            f'"MiniGame_B"==={var}.t0?{case_b}:"{TYPE_TAG}"==={var}.t0?'
            f'{new_case}:{case_def}') + js[m.end():]
        changes.append(("S5 levelController",
                        f"新增 {TYPE_TAG}→case {new_case}"))

        # S6: 插入 case 体（在 case 18 前）
        pat6 = r"case 18:this\.startingMusic=([A-Za-z_$][\w$]*)\.CYS_Start;"
        m6 = re.search(pat6, js)
        if not m6:
            raise Fail("S6 找不到 case 18 分支")
        ME = m6.group(1)
        body = (f'case {new_case}:return this.startingMusic={ME}.{SORT_MEMBER},'
                f'e.abrupt("break",19);')
        js = js[:m6.start()] + body + js[m6.start():]
        changes.append(("S6 levelController 分支",
                        f"插入 case {new_case}"))

    # ---- S7: switchMusic 的 RemadeZombotany 分支（按世界选曲）----
    # 0.16.0 的 switchMusic 是 regenerator 状态机，形如：
    #     case 7: ... this.isJam=!1,o){t.next=270;break}
    #             if(a!=v.Victory||...UltimateBattle){t.next=20;break}
    #             u=A.UB_Victory,...
    # 每个分支都是「if(条件不满足){跳到下一个 case} 本体 t.next=270;break;」
    # 所以插入一个**独立语句块**即可：条件成立就处理并跳出（t.next=270），
    # 不成立就自然往下滑到原有的判定。**不需要改任何 case 编号**。
    # 形参必须先解析（S7 跳过时 S7b 也要用）
    m_sig = re.search(r"mark\(\(function t\((\w+),(\w+),",
                      js[js.find("switchMusic=function("):])
    if not m_sig:
        raise Fail("S7 解析不出 switchMusic 的形参")
    world_var, sort_var = m_sig.group(1), m_sig.group(2)

    if re.search(re.escape(SORT_MEMBER) + r"\)\{switch\(", js):
        changes.append(("S7 switchMusic 分支", "已存在，跳过"))
    else:
        anchor = "this.isJam=!1,o){t.next=270;break}"
        pos = js.find(anchor)
        if pos < 0:
            raise Fail("S7 找不到 switchMusic 的 isJam 锚点")

        cases = "".join(
            f'case {WORLD}.{t["world_enum"]}:u={EN}.{t["name"]};break;'
            for t in TRACKS if t["world_enum"])
        block = (f'if({sort_var}=={SORT}.{SORT_MEMBER}){{switch({world_var}){{'
                 f'{cases}default:u={EN}.ZBT_Future;}}g=!0,t.next=270;break}}')
        cut = pos + len(anchor)
        js = js[:cut] + block + js[cut:]
        changes.append(("S7 switchMusic 分支",
                        f"插入 {len(TRACKS) - 1} 个世界分支"))

    # ---- S7b: 把 Jam 世界的 case 补进已有的 RemadeZombotany switch ----
    # S7 只插了一次，之后新增音轨（如 Jam 世界）不会自动进 switch。
    # 这里逐个检查 case 是否存在，缺的就补进去；已有的一条也不动。
    m_sw = re.search(r"if\(" + re.escape(sort_var) + r"==" + re.escape(SORT)
                     + r"\." + SORT_MEMBER + r"\)\{switch\(" +
                     re.escape(world_var) + r"\)\{(.*?)default:", js, re.S)
    if not m_sw:
        raise Fail("S7b 找不到 RemadeZombotany 的 switch 块")
    body = m_sw.group(1)
    missing = [t for t in JAM_TRACKS
               if f'case {WORLD}.{t["world_enum"]}:u={EN}.{t["name"]};' not in body]
    # 世界别名：引擎把 Eighties 归到 Ballad 的曲目，但 case 上得单独立一条，
    # 否则 Eighties 的关会落到 default。
    alias_cases = [(alias, target) for alias, target in WORLD_ALIASES.items()
                   if f"case {WORLD}.{alias}:" not in body]
    if not missing and not alias_cases:
        changes.append(("S7b Jam 世界 case", "已存在，跳过"))
    else:
        add = "".join(f'case {WORLD}.{t["world_enum"]}:u={EN}.{t["name"]};break;'
                      for t in missing)
        add += "".join(f'case {WORLD}.{alias}:u={EN}.{target};break;'
                       for alias, target in alias_cases)
        ins_at = m_sw.start(1) + len(body)
        js = js[:ins_at] + add + js[ins_at:]
        desc = [t["name"] for t in missing]
        desc += [f"{a}→{b}(别名)" for a, b in alias_cases]
        changes.append(("S7b Jam 世界 case", "补充 " + ", ".join(desc)))

    # ---- S8: Victory 判定 ----
    # 目标：UB / MG / ZBT 三种 MiniGame 关卡打出各自的结算曲，
    # 而不是落回大世界的默认结算曲（ArenaStage 的 Music="Dark" → VIC_Dark）。
    #
    # 走过三条弯路，记录清楚，别再重犯
    # ------------------------------------
    # ① 原版 0.16.0（master 分支）里 **ZBT 的 Victory 块是死代码**：
    #       ...u=A.UB_Victory,g=!1,s=1,t.next=270;break;
    #       if(a==v.Victory&&this.currentMusicSort==v.RemadeZombotany){switch(e){...}}
    #    它被插在 UB 的 `break;` 之后，永远不执行。
    #    所以「原版怎么弄的」在这件事上没有可参考的先例 —— 它压根没生效过。
    #
    # ② 用 currentMusicSort 判定不可靠：它是**播放态**，会被
    #       hugeWaveMusic() → Stage2/3/4_Start
    #       switchMusic 收尾 → currentMusicSort = a
    #       levelController 对话流程 → NaN
    #    改写，结算时未必还是 UltimateBattle / DemonstrateMinigame。
    #
    # ③ 用 window.__levelMt 全局变量也不行：写成 onLoad / case 11 / case 14-17
    #    都会因为「关卡加载路径不一致」（沙盒分支绕过路由、LOD 走另一套、
    #    自定义关卡可能不触发 module_SetLevelDefinition）而残留上一关的值。
    #    现象就是：先打 UB 再打 ZBT → ZBT 结算放的是 UB 的曲子。
    #
    # 最终方案：**在结算那一刻直接读关卡自己声明的 MusicType**。
    # ------------------------------------
    # 结算点在 levelController 的 win 流程里，那里 `this` 就是关卡控制器，
    # `this.levelDefinition` 是本关的 LevelDefinition.objdata，一定有 MusicType。
    # 不再引入任何全局状态，也就没有残留问题。
    #
    # 三家统一判定（按用户要求，ZBT 与未来的 LB 都照 UB/MG 的格式）：
    #   只把条件从 currentMusicSort 换成 「本关 MusicType」，
    #   形态仍是原来的层叠 `if(a!=...){next=N;break}`，不额外插入块。

    # 1) 在结算前把本关的 MusicType 放到一个局部变量里，
    #    随后的三条判定都读它。
    #    插在 `if(this.gameWon=!0,J.waterall(),t)` 前面 ——
    #    这是普通胜利分支的入口，`this` 是关卡控制器。
    win_anchor = "this.gameWon=!0,J.waterall(),t)switch(he.soundManager().currentMusicType)"
    if "window.__mts=" in js:
        changes.append(("S8a 取关卡类型", "已存在，跳过"))
    else:
        if win_anchor not in js:
            raise Fail("S8a 找不到普通胜利分支")
        js = js.replace(
            win_anchor,
            "(window.__mts=(this.levelDefinition||{}).MusicType),"
            "this.gameWon=!0,J.waterall(),t)"
            "switch(he.soundManager().currentMusicType)", 1)
        changes.append(("S8a 取关卡类型", "结算前读本关 MusicType"))

    # 2) UB / MG / ZBT 三家判定改用本关 MusicType。
    #    ZBT 必须在 UB 之前，且用**正向判定**（命中跳出、未命中下滑），
    #    否则带 next 跳转会跳过 UB。
    #
    #    ⚠️ 注意原版 ZBT 块是死代码，这里要把它从 break 之后**搬到 UB 之前**。
    lm = "window.__mts"
    zbt_good = (f'if(a=={SORT}.Victory&&{lm}=="{TYPE_TAG}")'
                f'{{u={EN}.{FALLBACK_VICTORY},g=!1,s=1,t.next=270;break}}')

    # 先删掉所有历史形态的 ZBT 块（死代码 / 错误形态）
    for bad in (
        # 原版：插在 break 之后（死代码）
        f'if(a=={SORT}.Victory&&this.currentMusicSort=={SORT}.{SORT_MEMBER})'
        f'{{switch({WORLD}x){{}}}}',
        f'if(a=={SORT}.Victory&&this.currentMusicSort=={SORT}.{SORT_MEMBER})'
        f'{{switch(e){{case w.Egypt:u={EN}.ZBT_AE_Victory;break;'
        f'case w.Pirate:u={EN}.ZBT_PI_Victory;break;'
        f'case w.Cowboy:u={EN}.ZBT_COW_Victory;break;'
        f'case w.Kongfu:u={EN}.ZBT_KF_Victory;break;'
        f'case w.Future:u={EN}.ZBT_FF_Victory;break;'
        f'case w.Dark:u={EN}.ZBT_DA_Victory;break;'
        f'case w.Beach:u={EN}.ZBT_BWB_Victory;break;'
        f'case w.Ice:u={EN}.ZBT_IC_Victory;break;'
        f'case w.Lostcity:u={EN}.ZBT_LC_Victory;break;'
        f'case w.Sky:u={EN}.ZBT_SK_Victory;break;'
        f'case w.Dino:u={EN}.ZBT_JM_Victory;break;'
        f'case w.Modern:u={EN}.ZBT_MD_Victory;break;'
        f'default:u={EN}.{FALLBACK_VICTORY};}}g=!1,s=1,t.next=270;break}}',
        # 中间版本：正向块但放在 break 之后
        f'if(a=={SORT}.Victory&&this.currentMusicSort=={SORT}.{SORT_MEMBER})'
        f'{{u={EN}.{FALLBACK_VICTORY},g=!1,s=1,t.next=270;break}}',
        # 错误形态：带 next 跳转（会跳过 UB）
        f'if(a!={SORT}.Victory||window.__levelMt!="{TYPE_TAG}")'
        f'{{t.next=20;break}}u={EN}.{FALLBACK_VICTORY},g=!1,s=1,t.next=270;break;',
        # 上一版：用 __lm 的正向块
        f'if(a=={SORT}.Victory&&window.__lm=="{TYPE_TAG}")'
        f'{{u={EN}.{FALLBACK_VICTORY},g=!1,s=1,t.next=270;break}}',
        # 上一版的 resolve 前缀
        f'{lm}=window.__levelMt;',
        f'window.__lm=window.__levelMt;',
    ):
        if bad in js:
            js = js.replace(bad, "", 1)

    # 清掉各种 resolve 残留（逗号表达式那几版）
    for pat in (
        r'(?:\w+=window\.__levelMt,\w+==null&&this\.currentMusicSort==[\w$]+\.'
        r'UltimateBattle&&\(\w+="MiniGame_A"\),\w+==null&&this\.currentMusicSort'
        r'==[\w$]+\.DemonstrateMinigame&&\(\w+="MiniGame_B"\),'
        r'\w+==null&&this\.currentMusicSort==[\w$]+\.\w+&&\(\w+="MiniGame_C"\)[;,]?)',
        r'window\.__lm=\([^;]*\)\.__levelMt[^;]*;',
        r'window\.__lm=\(window\.__levelMt[^;]*\)[^;]*;',
    ):
        js = re.sub(pat, "", js)

    # 找 UB 判定并插 ZBT（若还没插过）
    ub_pat = re.compile(
        r'if\(a!=[\w$]+\.Victory\|\|(?:this\.currentMusicSort!='
        r'[\w$]+\.UltimateBattle|window\.__levelMt!="MiniGame_C"'
        r'&&window\.__levelMt!="MiniGame_A"|window\.__lm!="MiniGame_A"'
        r'|window\.__mts!="MiniGame_A")\)')
    m_ub = ub_pat.search(js)
    if not m_ub:
        raise Fail("S8 找不到 UB 的 Victory 判定")
    if zbt_good not in js:
        js = js[:m_ub.start()] + zbt_good + js[m_ub.start():]
        changes.append(("S8b ZBT 判定", "正向块插在 UB 之前"))
    else:
        changes.append(("S8b ZBT 判定", "已存在，跳过"))

    # UB / MG 的条件替换成本关 MusicType
    n = 0
    for old_re, new in (
        (r'if\(a!=([\w$]+)\.Victory\|\|(?:this\.currentMusicSort!=\1\.UltimateBattle'
         r'|window\.__levelMt!="MiniGame_C"&&window\.__levelMt!="MiniGame_A"'
         r'|window\.__lm!="MiniGame_A")\)',
         f'if(a!=v.Victory||window.__mts!="MiniGame_A")'),
        (r'if\(a!=([\w$]+)\.Victory\|\|(?:this\.currentMusicSort!=\1\.DemonstrateMinigame'
         r'|window\.__levelMt!="MiniGame_C"&&window\.__levelMt!="MiniGame_B"'
         r'|window\.__lm!="MiniGame_B")\)',
         f'if(a!=v.Victory||window.__mts!="MiniGame_B")'),
    ):
        m2 = re.search(old_re, js)
        if m2:
            js = js[:m2.start()] + new + js[m2.end():]
            n += 1
    if n:
        changes.append(("S8c UB/MG 判定", f"{n} 处改用本关 MusicType"))
    else:
        changes.append(("S8c UB/MG 判定", "已存在，跳过"))

    # ---- S9: 选卡前奏（CYS）----
    # 0.16.0 里 CYS_Start 只服务「普通关卡」：levelController 给无 MusicType 的关卡
    # 设 startingMusic=CYS_Start，而 MiniGame_A/B/C 直接跳各自分支，**不播前奏**。
    #
    # 做法分两半：
    #   a) levelController 的 case 14/16/17：把 MiniGame_A/B/C 的 startingMusic 记到
    #      window.__cys_target，先给 CYS_Start，开局时再切回。
    #   b) switchMusic 里 CYS_Start / CYS_LP 两个档位改成查家族表：
    #      按 window.__cys_fam（'UB'/'MG'/'ZBT'）和世界选对应前奏曲。
    #
    # 只改 UB/MG/ZBT 三套；LB 不碰（用户明确排除）。
    cys_map = {}
    for t in CYS_TRACKS:
        cys_map.setdefault(t["fam"], {})[t["cys_world"]] = t["name"]

    js, ch = _patch_cys(js, EN, SORT, WORLD, SORT_MEMBER, cys_map, changes)
    changes.extend(ch)

    return js, changes, ([] if js == orig else ["index.html"])


def _js_obj(d):
    """把 {世界: 音轨名} 写成 JS 对象字面量（值用枚举成员）。"""
    return ("{" + ",".join(f"{k}:A.{v}" for k, v in d.items()) + "}")


def _patch_cys(js, EN, SORT, WORLD, SORT_MEMBER, cys_map, changes):
    """选卡前奏补丁。返回 (新 js, 改动列表)。"""
    out = []

    # --- a) 全局家族表 ---
    # ⚠️ 插入位置必须落在**语句位**。这个 bundle 里 switchMusic 是这么定义的：
    #     e}a(e,t);var o=e.prototype;return o.switchMusic=function(){...}
    # 所以「switchMusic=function(){」前面是 `return o.` —— 在那里插东西会变成
    # `return o.window.__CYS_TBL=...`，把整个类方法表拆掉，游戏直接起不来。
    # 正确位置是 `return` **之前**（`;var o=e.prototype;` 之后），那是语句边界。
    marker = "window.__CYS_TBL="
    if marker in js:
        out.append(("S9a CYS 家族表", "已存在，跳过"))
    else:
        tbl = "window.__CYS_TBL={" + ",".join(
            f'{fam}:{_js_obj(d)}' for fam, d in cys_map.items()) + "};"
        anchor = "return o.switchMusic=function(){"
        pos = js.find(anchor)
        if pos < 0:
            raise Fail("S9a 找不到 switchMusic 的 return 锚点")
        boot = (tbl
                + "window.__cys_fam=null;window.__cys_target=null;"
                  "window.__cys_sm=null;"
                  "window.__cys_resume=function(){"
                  "var _t=window.__cys_target;"
                  "if(_t==null)return;"
                  # 告诉 S9f 那段「选卡后切哪首」的钩子：切这个，别切 Stage1_Start
                  "window.__cys_keep=_t;"
                  "window.__cys_fam=null;"
                  "var _n=0,_go=function(){"
                  "try{"
                  # 实例可能还没拿到（resume 早于第一次 switchMusicSort），
                  # 没拿到就等下一轮，别把 target 丢掉。
                  "var _m=window.__cys_sm;"
                  "if(!_m||typeof _m.switchMusicSort!=='function'){"
                  "if(_n++<50){setTimeout(_go,50);}return;}"
                  "window.__cys_target=null;"
                  "try{_m.currentTauriAudio&&_m.currentTauriAudio.stop();}catch(_x){}"
                  "try{_m.currentTauriAudio=null;_m.waiting=!1;}catch(_x){}"
                  "var _p=_m.switchMusicSort(_t,!1,!1,!0);"
                  # switchMusicSort 是 async，返回 Promise。等它完成后再看结果。
                  "var _chk=function(){"
                  "try{"
                  "var _cur=_m.currentMusicType;"
                  "if(_cur==null||isNaN(_cur)){"
                  "if(_n++<20){setTimeout(_chk,80);}return;}"
                  "}catch(_e){}"
                  "};"
                  "if(_p&&typeof _p.then==='function'){_p.then(_chk,_chk);}else{_chk();}"
                  "}catch(_e){if(window.__DBG_MUSIC)console.error('[cys] '+_e);}"
                  "};_go();"
                  "};")
        js = js[:pos] + boot + js[pos:]
        out.append(("S9a CYS 家族表", f"{sum(len(d) for d in cys_map.values())} 条"))

    # --- b) levelController：记下目标，先播前奏 ---
    # 原样：case 14:return this.startingMusic=ge.UltimateBattle,e.abrupt("break",19);
    #       case 16:return this.startingMusic=ge.DemonstrateMinigame,e.abrupt("break",19);
    #       case 17:return this.startingMusic=ge.RemadeZombotany,e.abrupt("break",19);
    fam_of_case = {"UltimateBattle": "UB", "DemonstrateMinigame": "MG",
                   SORT_MEMBER: "ZBT"}
    done = []
    for member, fam in fam_of_case.items():
        pat = (r'return this\.startingMusic=(' + r'[A-Za-z_$][\w$]*'
               + r')\(' + r'\.' + re.escape(member) + r'\),e\.abrupt\("break",(\d+)\);')
        pat = (r'return this\.startingMusic=([A-Za-z_$][\w$]*)\.'
               + re.escape(member) + r',e\.abrupt\("break",(\d+)\);')
        m = re.search(pat, js)
        if not m:
            continue
        if f'window.__cys_fam="{fam}"' in js:
            continue
        ME, brk = m.group(1), m.group(2)
        new = (f'return window.__cys_target={ME}.{member},'
               f'window.__cys_fam="{fam}",'
               f'this.startingMusic={ME}.CYS_Start,'
               f'e.abrupt("break",{brk});')
        js = js[:m.start()] + new + js[m.end():]
        done.append(fam)
    if done:
        out.append(("S9b 关卡入口", f"{', '.join(done)} 改为先播前奏"))
    else:
        out.append(("S9b 关卡入口", "已存在，跳过"))

    # --- c) 开局：从 CYS 切回正曲 ---
    # 挂载点选得对不对，直接决定「点了开始但前奏还在响」会不会发生。
    #
    # 时间线（实测顺序）：
    #   c.letsRock()               ← 玩家点「开始」按钮
    #       ↓ 收卡槽、镜头移动                       ← 这期间还是选卡音乐
    #   readySetPlant()
    #       ↓ Ready(0.6s) + Set(0.6s) + Plant(1s)    ← 还在选卡音乐
    #   c.gameStart()              ← **真正开局**，僵尸开始出、计时开始
    #
    # 太早（letsRock）会把选卡音乐提前掐断，玩家还在看卡组时就换成战斗曲了；
    # 太晚（readySetPlant 中间）又会有明显延迟。
    # 正确位置就是 levelController 的 c.gameStart —— 开局那一刻。
    #
    # 其余两处保留作兜底（resume 幂等，先到的生效，后到的因为 target 已清空而 no-op）。
    if "window.__cys_resume()" in js:
        out.append(("S9c 开局切回", "已存在，跳过"))
    else:
        n = 0
        # 主钩子：levelController.gameStart（真开局）
        main_anchor = "c.gameStart=function(){if(!this.gameStarted){"
        if main_anchor in js:
            js = js.replace(main_anchor,
                            main_anchor + "window.__cys_resume();", 1)
            n += 1
        # 兜底 1：卡片区 gameStart
        fb1 = "if(!this.gameStarted){this.gameStarted=!0,this.CFs"
        if fb1 in js:
            js = js.replace(fb1,
                            "if(!this.gameStarted){window.__cys_resume(),"
                            "this.gameStarted=!0,this.CFs", 1)
            n += 1
        # 兜底 2：readySetPlant 的末尾
        fb2 = "case 15:t.gameStart()"
        if fb2 in js:
            js = js.replace(fb2, "case 15:window.__cys_resume(),t.gameStart()", 1)
            n += 1
        if n == 0:
            raise Fail("S9c 找不到 gameStart 锚点")
        out.append(("S9c 开局切回", f"{n} 处（主钩子在 levelController.gameStart）"))

    # --- d) switchMusic：CYS_Start / CYS_LP 按家族选曲 ---
    # 每个世界分支里都是 `a==v.CYS_Start?(u=A.CYS_Start_X,L=v.CYS_LP,g=!1)`
    # 换成查表：__CYS_TBL[fam][世界] || __CYS_TBL[fam].Fallback || 原值
    #
    # ⚠️ 为什么要有 Fallback 这一级：
    #   开局时 Jam 世界还没确定风格（Ballad/Punk/Pop/… 由 boombox 后切），
    #   所以选卡前奏**只需要一条通用的**就够了。
    #   ZBT 只做了 14 个世界 + Fallback 一条通用前奏，
    #   Jam 世界（Punk/Pop/Rap/Eightbit/Metal）查不到 → 用 Fallback 兜底。
    #   不加这一级的话会落到官方的 CYS_Start_Eighties，听到的就是原版曲。
    pat_start = (r'a==v\.CYS_Start\?\(u=A\.(CYS_Start_(\w+)),L=v\.CYS_LP,g=!1\)')
    n_start = len(re.findall(pat_start, js))

    def repl_start(m):
        orig = m.group(1)
        sfx = m.group(2)
        return (f'a==v.CYS_Start?(u=((window.__cys_fam&&window.__CYS_TBL'
                f'[window.__cys_fam]&&(window.__CYS_TBL[window.__cys_fam].{sfx}'
                f'||window.__CYS_TBL[window.__cys_fam].Fallback))'
                f'||A.{orig}),L=v.CYS_LP,g=!1)')

    def repl_lp(m):
        orig = m.group(1)
        sfx = m.group(2)
        return (f'a==v.CYS_LP&&(u=((window.__cys_fam&&window.__CYS_TBL'
                f'[window.__cys_fam]&&(window.__CYS_TBL[window.__cys_fam].{sfx}'
                f'||window.__CYS_TBL[window.__cys_fam].Fallback))'
                f'||A.{orig}),g=!0)')

    if "Fallback))" in js and "window.__CYS_TBL[window.__cys_fam].Fallback" in js:
        out.append(("S9d CYS 选曲", "已存在，跳过"))
    else:
        # 已经是旧版（无 Fallback 链）的话先还原不了，直接整体重写一次
        js = re.sub(
            r'a==v\.CYS_Start\?\(u=\(\(window\.__cys_fam&&window\.__CYS_TBL'
            r'\[window\.__cys_fam\]&&window\.__CYS_TBL\[window\.__cys_fam\]\.(\w+)\)'
            r'\|\|A\.(CYS_Start_\w+)\),L=v\.CYS_LP,g=!1\)',
            lambda m: (f'a==v.CYS_Start?(u=((window.__cys_fam&&window.__CYS_TBL'
                       f'[window.__cys_fam]&&(window.__CYS_TBL[window.__cys_fam].{m.group(1)}'
                       f'||window.__CYS_TBL[window.__cys_fam].Fallback))'
                       f'||A.{m.group(2)}),L=v.CYS_LP,g=!1)'), js)
        js = re.sub(
            r'a==v\.CYS_LP&&\(u=\(\(window\.__cys_fam&&window\.__CYS_TBL'
            r'\[window\.__cys_fam\]&&window\.__CYS_TBL\[window\.__cys_fam\]\.(\w+)\)'
            r'\|\|A\.(CYS_LP_\w+)\),g=!0\)',
            lambda m: (f'a==v.CYS_LP&&(u=((window.__cys_fam&&window.__CYS_TBL'
                       f'[window.__cys_fam]&&(window.__CYS_TBL[window.__cys_fam].{m.group(1)}'
                       f'||window.__CYS_TBL[window.__cys_fam].Fallback))'
                       f'||A.{m.group(2)}),g=!0)'), js)
        js = re.sub(pat_start, repl_start, js)
        n_lp = len(re.findall(r'a==v\.CYS_LP&&\(u=A\.(CYS_LP_(\w+)),g=!0\)', js))
        js = re.sub(r'a==v\.CYS_LP&&\(u=A\.(CYS_LP_(\w+)),g=!0\)', repl_lp, js)
        out.append(("S9d CYS 选曲",
                    f"CYS_Start {n_start} 处 / CYS_LP {n_lp} 处（缺世界用 Fallback）"))

    # --- f) 选卡结束后别让引擎把 nextSortToPlay 改回 Stage1_Start ---
    # 引擎在 gameStart 里有一段：
    #   var a=pe.component.currentMusicSort;
    #   a!=ge.CYS_LP&&a!=ge.CYS_Start||pe.component&&(
    #       pe.component.nextSortToPlay=ge.Stage1_Start)
    # 意思是「还在播选卡曲的话，下一首切世界正曲」。
    # 对 MiniGame 关卡这是错的 —— 我们要切 UB/MG/RemadeZombotany，不是世界 Stage1。
    # 用户听到的「大世界 Egypt 音乐」就是这条来的。
    #
    # 解法：resume 时把目标存进 __cys_keep，这里消费并清空它。
    old_line = ("a!=ge.CYS_LP&&a!=ge.CYS_Start||pe.component&&"
                "(pe.component.nextSortToPlay=ge.Stage1_Start)")
    new_line = ("a!=ge.CYS_LP&&a!=ge.CYS_Start||pe.component&&"
                "(pe.component.nextSortToPlay=(function(){"
                "var _k=window.__cys_keep;window.__cys_keep=null;"
                "return _k!=null?_k:ge.Stage1_Start})())")
    # ⚠️ 检测必须看**原始串**在不在，不能只看 __cys_keep ——
    # resume 里早就写了 __cys_keep，用它判断会永远误判成"已存在"。
    if old_line not in js:
        out.append(("S9f 选卡后切曲", "已改写，跳过"))
    else:
        js = js.replace(old_line, new_line, 1)
        out.append(("S9f 选卡后切曲", "改为优先用 __cys_keep"))

    # --- e) 记住 soundManager 实例，供 __cys_resume 调用 ---
    # ⚠️ 这里踩过一个很隐蔽的坑，记录清楚：
    #
    # switchMusicSort 是这么定义的（**注意末尾的 ()，外层是个 IIFE**）：
    #     o.switchMusicSort=function(){
    #         var t=S(n().mark(...));
    #         return function(e,a,r,_){return t.apply(this,arguments)}
    #     }(),
    #
    # 外层 IIFE 被立即调用，那里的 `this` 是 **window**，不是 SoundManager 实例。
    # 一开始我把 `window.__cys_sm=this` 插在 IIFE 开头，结果 __cys_sm 一直指向
    # window —— resume 里所有 `_m.waiting` / `_m.switchMusicSort` 都是 undefined，
    # 异常又被 catch 吞掉，表现为「点了开始前奏不停」且**没有任何报错**。
    #
    # 而且不能只靠 switchMusicSort 赋值：它要等第一次切歌才被调用，
    # 而 resume 可能更早触发。所以主力挂 onLoad（组件一加载就拿到实例），
    # switchMusicSort 里再兜一次。
    if "window.__cys_sm=" in js and "window.__cys_sm=this" in js:
        out.append(("S9e 实例引用", "已存在，跳过"))
    else:
        done = []
        # 主力：SoundManager 的 onLoad（用 musicJson 定位，唯一）
        onload_anchor = ('o.onLoad=function(){this.CurrentMusicSPD=M.getRandomFromRange('
                         'l.MusicSpeedRange)')
        if onload_anchor in js:
            js = js.replace(
                onload_anchor,
                "o.onLoad=function(){window.__cys_sm=this;"
                "this.CurrentMusicSPD=M.getRandomFromRange(l.MusicSpeedRange)", 1)
            done.append("onLoad")
        # 兜底：switchMusicSort 的包装函数（这里的 this 才是实例）
        wrap_anchor = ("return function(e,a,r,_){return t.apply(this,arguments)}}(),"
                       "o.insertMusic=")
        if wrap_anchor in js:
            js = js.replace(
                wrap_anchor,
                "return function(e,a,r,_){window.__cys_sm=this;"
                "return t.apply(this,arguments)}}(),o.insertMusic=", 1)
            done.append("switchMusicSort")
        if not done:
            raise Fail("S9e 找不到实例记录锚点")
        out.append(("S9e 实例引用", " + ".join(done)))

    # --- g) Jam 世界：切到 UB/MG/ZBT 前先放行（对应外部补丁第 835 行）---
    # switchMusicSort 的守卫是：
    #     if(void 0===a&&...,void 0===r&&...,void 0===_&&...,
    #        e!=this.currentMusicSort && !this.isJam){ t.next=5;break }
    #     return t.abrupt("return", this.currentMusicType)
    #
    # 只要 isJam 为 true 就直接返回当前曲、什么都不做。
    # Jam 世界（Ballad/Punk/Pop/Rap/Eightbit/Metal）以及玄光魔音游的关卡
    # 会被置 isJam=!0，于是我们的 UB/MG/ZBT 曲永远切不过去。
    #
    # 外部补丁的做法就是「切之前先把 isJam 清掉」：
    #     if(this.isJam&&(cys标志)&&t!=this.currentMusicSort){this.isJam=!1;}
    #
    # 这里用同样的条件，只是把「cys 标志」换成「目标是 UB/MG/RemadeZombotany」。
    # 插在 if 的条件序列里（逗号表达式），是表达式位，安全。
    # ⚠️ 必须把 Victory / Lose / Leave 也算进来。
    #
    # 这三个是「终态」——离开战斗时 e 会变成它们。
    # 如果只在 UB/MG/ZBT 时清 isJam，Jam 关打到一半就再也不会清，
    # 紧接着的 `e!=current && !this.isJam` 直接为 false，
    # switchMusicSort 原样返回，switchMusic 压根没进 ——
    # 表现就是「Jam 关结算/失败没有音乐」。
    #
    # 用户 2026-10-24 实测：只有切过音乐才复现，
    # 因为没切时 e == currentMusicSort，第一个条件就短路了。
    #
    # 不能一律清 isJam —— Jam 世界内部切风格（Ballad→Punk）要保持 true。
    jam_guard = (f"e!=this.currentMusicSort&&(e=={SORT}.UltimateBattle"
                 f"||e=={SORT}.DemonstrateMinigame||e=={SORT}.{SORT_MEMBER}"
                 f"||e=={SORT}.Victory||e=={SORT}.Lose||e=={SORT}.Leave)"
                 f"&&(this.isJam=!1),")
    _jam_done = (f"e=={SORT}.Victory" in js
                 and f"e=={SORT}.Lose" in js
                 and f"e!=this.currentMusicSort&&(e=={SORT}.UltimateBattle" in js)
    if _jam_done:
        out.append(("S9g Jam 放行", "已含 Victory/Lose/Leave，跳过"))
    else:
        anchor = "void 0===_&&(_=!0),e!=this.currentMusicSort&&!this.isJam){"
        if anchor not in js:
            raise Fail("S9g 找不到 switchMusicSort 的守卫")
        js = js.replace(anchor, "void 0===_&&(_=!0)," + jam_guard
                        + "e!=this.currentMusicSort&&!this.isJam){", 1)
        out.append(("S9g Jam 放行", "isJam 时先放行 UB/MG/RemadeZombotany"))

    # --- h) Jam 世界的 RemadeZombotany 分支：**不需要单独加** ---
    # 曾经试过在每个 Jam 世界的分支入口（case 122 / 146 / …）插
    #     case 122:if(a==v.RemadeZombotany){u=A.ZBT_Ballad,...}
    # 但那是死代码 —— 因为 switchMusic 在 case 7 就有一段前置判定：
    #     if(a==v.RemadeZombotany){switch(e){ ... case w.Eighties:u=A.ZBT_Ballad; ... default:u=A.ZBT_Future; }}
    # 它覆盖所有世界（含 default），并且直接 t.next=270 跳到播放，
    # 根本走不到后面的世界分派 case。
    #
    # 所以 Jam 世界 + MiniGame_C 已经不依赖这里的任何改动，
    # 靠 S7 / S7b 就够了。外部补丁同样没有给 Jam 分支加 ZBT case。

    return js, out


# --------------------------------------------------------------------------
# Musics 数组（在 import/ 里按内容搜索，不依赖文件名）
# --------------------------------------------------------------------------
def find_musics_json(repo):
    """返回 (路径, 文本)。0.16.0 起文件名是内容哈希，不能写死。"""
    root = os.path.join(repo, "docs", "assets", "resources", "import")
    hits = []
    for r, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".json"):
                continue
            p = os.path.join(r, f)
            try:
                with open(p, "rb") as fh:
                    if b'"Musics":[' in fh.read():
                        hits.append(p)
            except OSError:
                pass
    if not hits:
        raise Fail("在 import/ 里找不到含 Musics 的文件")
    if len(hits) > 1:
        hits.sort(key=os.path.getsize, reverse=True)
    return hits[0], read_text(hits[0])


def patch_musics(repo, text):
    """把 Musics 里的 RZ 段整体重写成 ALL_TRACKS。

    为什么不是「只追加」：增删条目后这一段必须整体重排，
    否则「枚举值 == Musics 下标」被破坏，bgms[i] 就会取到别人的曲子。

    整段重写还有个好处：天然幂等，加/删/换序都一次到位。
    RZ 段在 Musics 里是**连续**的（从 ZBT_Egypt 开始到最后一个 ZBT_* 结束），
    所以可以安全地整块替换。
    """
    changes = []
    orig = text

    def build(t):
        return ('{"name":"%s","tauri":"%s","musicLength":%s}'
                % (t["name"], manifest_key(t), _num(t["music_len"])))

    # 定位 RZ 段：从第一条 RZ 条目到最后一个连续的 RZ 条目
    pat_entry = re.compile(r'\{"name":"((?:ZBT|UB_CYS|MG_CYS)_\w+)","tauri":"[^"]*",'
                           r'"musicLength":[0-9.]+\}')
    spans = [(m.start(), m.end()) for m in pat_entry.finditer(text)]
    if not spans:
        # Musics 里还没有任何 RZ 条目：整段追加到最后一条之后
        anchor = '{"name":"Dialogue_Dave_LP"'
        m_anchor = text.find(anchor)
        if m_anchor < 0:
            raise Fail("找不到 Musics 的最后一条（Dialogue_Dave_LP）")
        end = text.find("}", m_anchor)
        if end < 0:
            raise Fail("Musics 锚点结构异常")
        items = ",".join(build(t) for t in ALL_TRACKS)
        text = text[:end + 1] + "," + items + text[end + 1:]
        changes.append(("M1 Musics", f"新建 {len(ALL_TRACKS)} 条"))
        return text, changes, ([] if text == orig else ["musics"])

    # RZ 段应当是连续的，取首尾
    seg_start, seg_end = spans[0][0], spans[-1][1]
    cur_names = [m.group(1) for m in
                 pat_entry.finditer(text[seg_start:seg_end])]
    want_names = [t["name"] for t in ALL_TRACKS]

    dropped = [n for n in cur_names if n not in want_names]
    added = [n for n in want_names if n not in cur_names]
    order_ok = [n for n in cur_names if n in want_names] == \
               [n for n in want_names if n in cur_names]

    # musicLength 也要同步（单独统计，避免把 length 变更也算成结构变更）
    len_fix = 0
    for t in ALL_TRACKS:
        mm = re.search(r'("name":"' + re.escape(t["name"]) +
                       r'","tauri":"[^"]*","musicLength":)([0-9.]+)', text)
        if mm and mm.group(2) != _num(t["music_len"]):
            len_fix += 1

    if not dropped and not added and order_ok and not len_fix:
        changes.append(("M1 Musics", "布局一致，跳过"))
        return text, changes, ([] if text == orig else ["musics"])

    items = ",".join(build(t) for t in ALL_TRACKS)
    text = text[:seg_start] + items + text[seg_end:]

    desc = []
    if dropped:
        desc.append(f"删 {len(dropped)} 条")
    if added:
        desc.append(f"加 {len(added)} 条")
    if not order_ok:
        desc.append("重排")
    if len_fix:
        desc.append(f"修 {len_fix} 个 musicLength")
    changes.append(("M1 Musics",
                    f"{'、'.join(desc)}；RZ 段 {len(want_names)} 条"
                    ))

    return text, changes, ([] if text == orig else ["musics"])


def patch_jam_ubmg(repo, text):
    """劫持引擎已有的 UB_Punk / MG_Punk 等 12 条，改它们的 tauri 和 musicLength。

    这是外部补丁的核心手法 —— **不新增条目**，只改已有条目的指向。
    好处是 switchMusic 里的 `u=A.UB_Ballad` 等下标完全不用动，
    兼容性最好。

    这些条目原本指向 Music_Future_UB / Music_Future_MG
    （官方偷懒用 Future 的曲子顶替所有 Jam 风格）。
    """
    changes = []
    orig = text
    touched = 0
    for t in JAM_UBMG_TRACKS:
        key = "rk_" + t["name"]  # 与 ZBT_* 同一套 manifest 前缀，避免撞上游 key
        pat = re.compile(r'("name":"' + re.escape(t["name"]) +
                         r'","tauri":")([^"]*)(")')
        m = pat.search(text)
        if not m:
            raise Fail(f"Musics 里找不到条目 {t['name']}")
        if m.group(2) != key:
            text = text[:m.start(2)] + key + text[m.end(2):]
            touched += 1
        # 同步 musicLength
        pat2 = re.compile(r'("name":"' + re.escape(t["name"]) +
                          r'","tauri":"[^"]*","musicLength":)([0-9.]+)')
        m2 = pat2.search(text)
        if m2:
            new = _num(t["music_len"])
            if m2.group(2) != new:
                text = text[:m2.start(2)] + new + text[m2.end(2):]
                touched += 1
    if touched:
        changes.append(("MJ Jam 的 UB/MG 条目",
                        f"劫持 {len(JAM_UBMG_TRACKS)} 条（tauri + musicLength）"))
    else:
        changes.append(("MJ Jam 的 UB/MG 条目", "已存在，跳过"))
    return text, changes, ([] if text == orig else ["musics"])


# --------------------------------------------------------------------------
# manifest.json
# --------------------------------------------------------------------------
def patch_manifest(repo):
    """在 docs/audio/manifest.json 里注册 RZ 音轨的 key，并清掉已废弃的。

    只注册缺失的 key；上游 key 一律不碰。
    """
    p = os.path.join(repo, "docs", "audio", "manifest.json")
    if not os.path.exists(p):
        raise Fail(f"找不到 {p}")
    text = read_text(p)
    changes = []
    orig = text
    # Jam 的 UB/MG 走同一套 rk_ 前缀，也要注册
    wanted = ALL_TRACKS + JAM_UBMG_TRACKS
    want_keys = {manifest_key(t) for t in wanted}
    absent = [t for t in wanted if manifest_key(t) not in text]

    if absent:
        m = re.search(r'\n\}\s*$', text)
        if not m:
            raise Fail("manifest.json 结构异常（找不到结尾 }）")
        items = "".join(',\n  "%s": "%s"' % (manifest_key(t), audio_rel(t))
                        for t in absent)
        text = text[:m.start()] + items + text[m.start():]

    if absent or removed:
        desc = []
        if absent:
            desc.append(f"注册 {len(absent)} 个 key")
        if removed:
            desc.append(f"删除 {len(removed)} 个废弃 key")
        changes.append(("A1 manifest", "，".join(desc)))
    else:
        changes.append(("A1 manifest", "已存在，跳过"))
    return text, changes, ([] if text == orig else ["manifest.json"])


# --------------------------------------------------------------------------
# 音频文件
# --------------------------------------------------------------------------
def migrate_audio(repo, dry=False):
    """把旧 native/<uuid>.mp3 搬到 audio/Music/inGame/<RZ名>/<RZ名>.mp3。"""
    out = []
    for t in ALL_TRACKS:
        dst = audio_abs(repo, t)
        if os.path.exists(dst):
            out.append((t["name"], "已在位"))
            continue
        # 来源 1：旧 native 目录（<< 0.16.0 的布局）
        src = os.path.join(repo, "docs", "assets", "resources", "native",
                           t["src_uuid"][:2], t["src_uuid"] + ".mp3")
        if not os.path.exists(src):
            out.append((t["name"], f"缺源文件 {t['src_uuid']}.mp3"))
            continue
        if dry:
            out.append((t["name"], "待复制"))
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        out.append((t["name"], "已复制"))
    return out


# --------------------------------------------------------------------------
# import json（0.16 起由音频目录直接提供，不再需要 Cocos AudioClip 描述）
# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def verify(repo):
    problems = []
    js = read_text(os.path.join(repo, "docs", "assets", "main", "index.js"))
    EN, EP = find_enum_alias(js, "MusicEnum")
    SORT, SP = find_enum_alias(js, "MusicSortEnum")

    if f".{SORT_MEMBER}=" not in js:
        problems.append("index.js: 缺 MusicSortEnum.RemadeZombotany")
    if f'.{TRACKS[0]["name"]}=' not in js:
        problems.append("index.js: 缺 ZBT_* 枚举")
    if f'"{TYPE_TAG}"==(null==' not in js:
        problems.append("index.js: 缺加载器三元链")
    if not re.search(r'"' + re.escape(TYPE_TAG) + r'"===', js):
        problems.append("index.js: 缺 levelController 判定")
    if not re.search(re.escape(SORT_MEMBER) + r"\)\{switch|"
                     + re.escape(SORT_MEMBER) + r"\)\{u=", js):
        problems.append("index.js: 缺 switchMusic 的 RemadeZombotany 分支")

    # Musics
    try:
        mj_path, mj = find_musics_json(repo)
        for t in ALL_TRACKS:
            if f'"name":"{t["name"]}"' not in mj:
                problems.append(f"Musics 缺 {t['name']}")
        # 枚举值 == Musics 下标（铁律）
        vals = {k: int(v) for k, v in re.findall(
            re.escape(EP) + r"\[" + re.escape(EP) + r"\.(\w+)=(\d+)\]=\"", js)}
        obj = json.loads(mj)
        musics = None

        def walk(o):
            nonlocal musics
            if isinstance(o, dict):
                if "Musics" in o:
                    musics = o["Musics"]
                    return True
                for v in o.values():
                    if walk(v):
                        return True
            elif isinstance(o, list):
                for v in o:
                    if walk(v):
                        return True
            return False
        walk(obj)
        if musics is None:
            problems.append("Musics 数组解析失败")
        else:
            for t in ALL_TRACKS:
                v = vals.get(t["name"])
                if v is None:
                    problems.append(f"枚举缺 {t['name']}")
                    continue
                idx = next((i for i, e in enumerate(musics)
                            if isinstance(e, dict) and e.get("name") == t["name"]),
                           None)
                if idx is None:
                    problems.append(f"Musics 缺 {t['name']}")
                elif idx != v:
                    problems.append(f"{t['name']} 下标错位：枚举={v} Musics={idx}")
    except Fail as ex:
        problems.append(str(ex))

    # manifest
    mp = os.path.join(repo, "docs", "audio", "manifest.json")
    if os.path.exists(mp):
        man = json.loads(read_text(mp))
        for t in ALL_TRACKS + JAM_UBMG_TRACKS:
            k = manifest_key(t)
            if k not in man:
                problems.append(f"manifest 缺 {k}")
            elif man[k] != audio_rel(t):
                problems.append(f"manifest {k} 路径不对：{man[k]}")
    else:
        problems.append("缺 audio/manifest.json")

    # 音频文件
    for t in ALL_TRACKS + JAM_UBMG_TRACKS:
        if not os.path.exists(audio_abs(repo, t)):
            problems.append(f"缺音频 {audio_rel(t)}")

    if problems:
        print(f"❌ {len(problems)} 个问题：")
        for p in problems:
            print("   " + p)
    return problems


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="重放 RemadeZombotany（MiniGame_C）音乐定制")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(here)))
    ap.add_argument("--check", action="store_true", help="只看会改什么，不落盘")
    ap.add_argument("--verify", action="store_true", help="只校验当前状态")
    ap.add_argument("--gen-import", action="store_true",
                    help="顺便迁移音频文件（从旧 native/ 复制）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, "docs")):
        print(f"❌ 不是有效的仓库根目录（找不到 docs/）：{repo}")
        return 1
    print(f"仓库：{repo}")
    print()

    if args.verify:
        return 0 if not verify(repo) else 1

    try:
        js_p = os.path.join(repo, "docs", "assets", "main", "index.js")
        src = read_text(js_p)
        dst, changes, touched = patch_index_js(src)
        print("── index.js ──")
        for name, desc in changes:
            print(f"   {name:28s} {desc}")
        if touched and not args.check:
            write_text(js_p, dst)
            print(f"   → 已写入（{len(src):,} → {len(dst):,} 字符）")
        elif touched:
            print(f"   → dry-run，未写入（将 {len(src):,} → {len(dst):,} 字符）")
        print()

        mj_path, mj_src = find_musics_json(repo)
        mj_dst, mchanges, mtouched = patch_musics(repo, mj_src)
        # Jam 的 UB/MG 是「劫持已有条目」，必须在 patch_musics 之后跑
        mj_dst, jchanges, jtouched = patch_jam_ubmg(repo, mj_dst)
        mchanges = mchanges + jchanges
        if jtouched and not mtouched:
            mtouched = jtouched
        print(f"── Musics（{os.path.relpath(mj_path, repo)}）──")
        for name, desc in mchanges:
            print(f"   {name:28s} {desc}")
        if mtouched and not args.check:
            write_text(mj_path, mj_dst)
            print(f"   → 已写入（{len(mj_src):,} → {len(mj_dst):,} 字符）")
        elif mtouched:
            print(f"   → dry-run，未写入")
        print()

        man_p = os.path.join(repo, "docs", "audio", "manifest.json")
        man_src = read_text(man_p)
        man_dst, achanges, atouched = patch_manifest(repo)
        print("── audio/manifest.json ──")
        for name, desc in achanges:
            print(f"   {name:28s} {desc}")
        if atouched and not args.check:
            write_text(man_p, man_dst)
            print(f"   → 已写入（{len(man_src):,} → {len(man_dst):,} 字符）")
        elif atouched:
            print("   → dry-run，未写入")
        print()

        print("── 音频文件 ──")
        for name, desc in migrate_audio(repo, dry=args.check):
            print(f"   {name:28s} {desc}")
        print()

    except Fail as ex:
        print(f"❌ {ex}")
        return 1

    if args.check:
        print("（dry-run 完成，没有改动任何文件）")
        return 0

    print("── 最终校验 ──")
    print()
    problems = verify(repo)
    if problems:
        return 1
    print(f"✅ 校验通过（{len(ALL_TRACKS)} 条 RemadeZombotany 音轨）")
    print()
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
