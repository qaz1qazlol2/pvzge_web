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

  * MusicSortEnum   + MiniGameC = 24
  * MusicEnum       + 25 条 RZ_*（260..284），MusicAmount 260 → 285
  * Musics          + 25 条 {name,tauri,musicLength}
  * manifest.json   + 25 个 key → inGame/RZ_*/*.mp3
  * 音频文件         audio/Music/inGame/RZ_*/<名字>.mp3（独立目录，绝不覆盖上游）

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
SORT_MEMBER = "MiniGameC"    # MusicSortEnum 的成员名

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
    dict(name="RZ_Egypt",    world="Egypt",    world_enum="Egypt",    src_uuid="89b35a32", music_len=182.5, duration=186.24),
    dict(name="RZ_Pirate",   world="Pirate",   world_enum="Pirate",   src_uuid="b7000001", music_len=182.5, duration=186.24),
    dict(name="RZ_Cowboy",   world="Cowboy",   world_enum="Cowboy",   src_uuid="b7000002", music_len=181,   duration=182.88),
    dict(name="RZ_Kongfu",   world="Kongfu",   world_enum="Kongfu",   src_uuid="b7000003", music_len=181,   duration=183.312),
    dict(name="RZ_Future",   world="Future",   world_enum="Future",   src_uuid="b7000004", music_len=181,   duration=184.152),
    dict(name="RZ_Dark",     world="Dark",     world_enum="Dark",     src_uuid="b7000005", music_len=181,   duration=185.496),
    dict(name="RZ_Beach",    world="Beach",    world_enum="Beach",    src_uuid="b7000006", music_len=182.5, duration=186.24),
    dict(name="RZ_Iceage",   world="Iceage",   world_enum="Ice",      src_uuid="b7000007", music_len=182.5, duration=186.24),
    dict(name="RZ_Lostcity", world="Lostcity", world_enum="Lostcity", src_uuid="b7000008", music_len=181,   duration=184.872),
    dict(name="RZ_Sky",      world="Sky",      world_enum="Sky",      src_uuid="b7000009", music_len=181,   duration=181.577143),
    dict(name="RZ_Dino",     world="Dino",     world_enum="Dino",     src_uuid="b700000a", music_len=181,   duration=184.416),
    dict(name="RZ_Modern",   world="Modern",   world_enum="Modern",   src_uuid="b700000b", music_len=181,   duration=184.344),
    dict(name="RZ_Victory",  world="All",      world_enum=None,       src_uuid="b700000c", music_len=3,     duration=6.024),
]

# 每个世界一条的结算曲。命名用口述简称（冰窟 → RZ_IC_Victory）。
# RZ_Victory 保留作 switch 的 default 兜底。
VICTORY_TRACKS = [
    dict(name="RZ_AE_Victory",  world="Egypt",    world_enum="Egypt",    src_uuid="b700000d", music_len=3, duration=6.024),
    dict(name="RZ_PI_Victory",  world="Pirate",   world_enum="Pirate",   src_uuid="b700000e", music_len=3, duration=6.024),
    dict(name="RZ_COW_Victory", world="Cowboy",   world_enum="Cowboy",   src_uuid="b700000f", music_len=3, duration=6.024),
    dict(name="RZ_KF_Victory",  world="Kongfu",   world_enum="Kongfu",   src_uuid="b7000010", music_len=3, duration=6.024),
    dict(name="RZ_FF_Victory",  world="Future",   world_enum="Future",   src_uuid="b7000011", music_len=3, duration=6.024),
    dict(name="RZ_DA_Victory",  world="Dark",     world_enum="Dark",     src_uuid="b7000012", music_len=3, duration=6.024),
    dict(name="RZ_BWB_Victory", world="Beach",    world_enum="Beach",    src_uuid="b7000013", music_len=3, duration=6.024),
    dict(name="RZ_IC_Victory",  world="Iceage",   world_enum="Ice",      src_uuid="b7000014", music_len=3, duration=6.024),
    dict(name="RZ_LC_Victory",  world="Lostcity", world_enum="Lostcity", src_uuid="b7000015", music_len=3, duration=6.024),
    dict(name="RZ_SK_Victory",  world="Sky",      world_enum="Sky",      src_uuid="b7000016", music_len=3, duration=6.024),
    dict(name="RZ_JM_Victory",  world="Dino",     world_enum="Dino",     src_uuid="b7000017", music_len=3, duration=6.024),
    dict(name="RZ_MD_Victory",  world="Modern",   world_enum="Modern",   src_uuid="b7000018", music_len=3, duration=6.024),
]

FALLBACK_VICTORY = "RZ_Victory"
ALL_TRACKS = TRACKS + VICTORY_TRACKS


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
    """音频相对 audio/ 的路径：Music/inGame/RZ_Egypt/RZ_Egypt.mp3"""
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
    """给 0.16.0 的 index.js 打 MiniGameC 补丁。返回 (新文本, 改动列表)。"""
    changes = []
    orig = js
    EN, EP = find_enum_alias(js, "MusicEnum")          # 音乐枚举别名 + 参数
    SORT, SP = find_enum_alias(js, "MusicSortEnum")    # 排序枚举
    WORLD, _ = find_enum_alias(js, "WorldMusic")       # 世界枚举

    # ---- S1: MusicSortEnum += MiniGameC ----
    if re.search(r"\b" + SP + r"\[" + SP + r"\.MiniGameC=", js):
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

    # ---- S2: MusicEnum += 25 条 RZ_*，MusicAmount 顺延 ----
    if f'.{TRACKS[0]["name"]}=' in js:
        changes.append(("S2 MusicEnum", "已存在，跳过"))
    else:
        m = re.search(r"," + re.escape(EP) + r"\[" + re.escape(EP) +
                      r"\.MusicAmount=(\d+)\]=\"MusicAmount\"", js)
        if not m:
            raise Fail("S2 找不到 MusicAmount 哨兵")
        base = int(m.group(1))
        items = ",".join(f'{EP}[{EP}.{t["name"]}={base + i}]="{t["name"]}"'
                         for i, t in enumerate(ALL_TRACKS))
        new = (f',{items},{EP}[{EP}.MusicAmount={base + len(ALL_TRACKS)}]'
               f'="MusicAmount"')
        js = js[:m.start()] + new + js[m.end():]
        changes.append(("S2 MusicEnum",
                        f"新增 {len(ALL_TRACKS)} 条（{base}.."
                        f"{base + len(ALL_TRACKS) - 1}），"
                        f"MusicAmount {base}→{base + len(ALL_TRACKS)}"))

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

    # ---- S7: switchMusic 的 MiniGameC 分支（按世界选曲）----
    # 0.16.0 的 switchMusic 是 regenerator 状态机，形如：
    #     case 7: ... this.isJam=!1,o){t.next=270;break}
    #             if(a!=v.Victory||...UltimateBattle){t.next=20;break}
    #             u=A.UB_Victory,...
    # 每个分支都是「if(条件不满足){跳到下一个 case} 本体 t.next=270;break;」
    # 所以插入一个**独立语句块**即可：条件成立就处理并跳出（t.next=270），
    # 不成立就自然往下滑到原有的判定。**不需要改任何 case 编号**。
    if re.search(re.escape(SORT_MEMBER) + r"\)\{switch\(", js):
        changes.append(("S7 switchMusic 分支", "已存在，跳过"))
    else:
        anchor = "this.isJam=!1,o){t.next=270;break}"
        pos = js.find(anchor)
        if pos < 0:
            raise Fail("S7 找不到 switchMusic 的 isJam 锚点")
        # 形参：(e=world, a=sort, ...)
        m_sig = re.search(r"mark\(\(function t\((\w+),(\w+),", js[js.find("switchMusic=function("):])
        if not m_sig:
            raise Fail("S7 解析不出 switchMusic 的形参")
        world_var, sort_var = m_sig.group(1), m_sig.group(2)

        cases = "".join(
            f'case {WORLD}.{t["world_enum"]}:u={EN}.{t["name"]};break;'
            for t in TRACKS if t["world_enum"])
        block = (f'if({sort_var}=={SORT}.{SORT_MEMBER}){{switch({world_var}){{'
                 f'{cases}default:u={EN}.RZ_Future;}}g=!0,t.next=270;break}}')
        cut = pos + len(anchor)
        js = js[:cut] + block + js[cut:]
        changes.append(("S7 switchMusic 分支",
                        f"插入 {len(TRACKS) - 1} 个世界分支"))

    # ---- S8: Victory 也按世界选曲 ----
    # 插在 UltimateBattle 那个 Victory 分支之后（它已 `break;`，后面是 case 20 标签），
    # 同样是独立语句块，不碰 case 编号。
    if re.search(r"currentMusicSort==" + re.escape(SORT) + r"\." + SORT_MEMBER
                 + r"&&|currentMusicSort==" + re.escape(SORT) + r"\." + SORT_MEMBER
                 + r"\)\{switch", js):
        changes.append(("S8 Victory 按世界选曲", "已存在，跳过"))
    else:
        anchor = f"u={EN}.UB_Victory,g=!1,s=1,t.next=270;break;"
        pos = js.find(anchor)
        if pos < 0:
            raise Fail("S8 找不到 UltimateBattle 的 Victory 分支")
        vcases = "".join(
            f'case {WORLD}.{t["world_enum"]}:u={EN}.{t["name"]};break;'
            for t in VICTORY_TRACKS if t["world_enum"])
        block = (f'if({sort_var}=={SORT}.Victory&&this.currentMusicSort=='
                 f'{SORT}.{SORT_MEMBER}){{switch({world_var}){{'
                 f'{vcases}default:u={EN}.{FALLBACK_VICTORY};}}g=!1,s=1,'
                 f't.next=270;break}}')
        cut = pos + len(anchor)
        js = js[:cut] + block + js[cut:]
        changes.append(("S8 Victory 按世界选曲",
                        f"插入 {len(VICTORY_TRACKS)} 个世界分支，"
                        f"default 保留 {FALLBACK_VICTORY}"))

    return js, changes, ([] if js == orig else ["index.js"])


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
    """追加 25 条 RZ 条目；已存在则只同步 musicLength。"""
    changes = []
    orig = text
    anchor = '{"name":"Dialogue_Dave_LP"'   # Musics 的最后一条
    m_anchor = text.find(anchor)
    if m_anchor < 0:
        raise Fail("找不到 Musics 的最后一条（Dialogue_Dave_LP）")

    def build(t):
        return ('{"name":"%s","tauri":"%s","musicLength":%s}'
                % (t["name"], manifest_key(t), _num(t["music_len"])))

    if f'"{TRACKS[0]["name"]}"' in text:
        changes.append(("M1 Musics", "已存在，同步 musicLength"))
        for t in ALL_TRACKS:
            pat = re.compile(r'("name":"' + re.escape(t["name"]) +
                             r'","tauri":"[^"]*","musicLength":)([0-9.]+)')
            mm = pat.search(text)
            if not mm:
                raise Fail(f"Musics 缺 {t['name']}")
            new = _num(t["music_len"])
            if mm.group(2) != new:
                text = text[:mm.start(2)] + new + text[mm.end(2):]
                changes.append((f"  {t['name']}",
                                f"musicLength {mm.group(2)} → {new}"))
    else:
        items = ",".join(build(t) for t in ALL_TRACKS)
        # 插在最后一条之后
        end = text.find("}", m_anchor)
        if end < 0:
            raise Fail("Musics 锚点结构异常")
        text = text[:end + 1] + "," + items + text[end + 1:]
        changes.append(("M1 Musics", f"追加 {len(ALL_TRACKS)} 条"))

    return text, changes, ([] if text == orig else ["musics"])


# --------------------------------------------------------------------------
# manifest.json
# --------------------------------------------------------------------------
def patch_manifest(repo):
    """在 docs/audio/manifest.json 里注册 25 个 key。"""
    p = os.path.join(repo, "docs", "audio", "manifest.json")
    if not os.path.exists(p):
        raise Fail(f"找不到 {p}")
    text = read_text(p)
    changes = []
    orig = text
    if manifest_key(TRACKS[0]) in text:
        changes.append(("A1 manifest", "已存在，跳过"))
        return text, changes, ([] if text == orig else [])
    # 插在最后一个键之后
    m = re.search(r'\n\}\s*$', text)
    if not m:
        raise Fail("manifest.json 结构异常（找不到结尾 }）")
    items = "".join(',\n  "%s": "%s"' % (manifest_key(t), audio_rel(t))
                    for t in ALL_TRACKS)
    text = text[:m.start()] + items + text[m.start():]
    changes.append(("A1 manifest", f"注册 {len(ALL_TRACKS)} 个 key"))
    return text, changes, ["manifest.json"]


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
def check_import_jsons(repo):
    """0.16.0 用 game-audio.js + <audio> 播，不再走 Cocos AudioClip。

    所以 import/<uuid>.json 里的 RZ 条目**不再是必需的**。这里只报告残留，
    不做任何删除 —— 留着也不影响运行。
    """
    stale = []
    imp = os.path.join(repo, "docs", "assets", "resources", "import", "b7")
    if os.path.isdir(imp):
        for f in sorted(os.listdir(imp)):
            if f.startswith("b70000"):
                stale.append(f)
    return stale


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def verify(repo):
    problems = []
    js = read_text(os.path.join(repo, "docs", "assets", "main", "index.js"))
    EN, EP = find_enum_alias(js, "MusicEnum")
    SORT, SP = find_enum_alias(js, "MusicSortEnum")

    if f".{SORT_MEMBER}=" not in js:
        problems.append("index.js: 缺 MusicSortEnum.MiniGameC")
    if f'.{TRACKS[0]["name"]}=' not in js:
        problems.append("index.js: 缺 RZ_* 枚举")
    if f'"{TYPE_TAG}"==(null==' not in js:
        problems.append("index.js: 缺加载器三元链")
    if not re.search(r'"' + re.escape(TYPE_TAG) + r'"===', js):
        problems.append("index.js: 缺 levelController 判定")
    if not re.search(re.escape(SORT_MEMBER) + r"\)\{switch|"
                     + re.escape(SORT_MEMBER) + r"\)\{u=", js):
        problems.append("index.js: 缺 switchMusic 的 MiniGameC 分支")

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
        for t in ALL_TRACKS:
            k = manifest_key(t)
            if k not in man:
                problems.append(f"manifest 缺 {k}")
            elif man[k] != audio_rel(t):
                problems.append(f"manifest {k} 路径不对：{man[k]}")
    else:
        problems.append("缺 audio/manifest.json")

    # 音频文件
    for t in ALL_TRACKS:
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
