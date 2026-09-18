#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_music.py —— 把 MiniGame_C 音乐定制重放到游戏数据文件上。

用途
----
上游发布新版本后，docs/ 下的三个文件会被官方版本覆盖（它们是压缩单行文件，
git merge 无法处理）。本脚本把音乐改动重新打到官方新文件上。

它做三件事：
  1. 改 docs/assets/main/index.js        —— 8 处：枚举 + 选曲/加载逻辑
  2. 改 docs/assets/resources/config.json —— 13 个音频 uuid + 路径注册
  3. 改 docs/assets/resources/import/0a/0a278bb49.json —— 13 条 Musics 条目

另外可生成 13 个 import/*.json（Cocos 的 AudioClip 描述），并检查 13 个 mp3 是否在位。

特点
----
* 幂等：已打过补丁的文件会被识别并跳过，重复运行安全。
* 动态：枚举值、paths 下标、case 编号都按当前文件内容实时计算，
  上游新增音乐条目也不会错位。
* 抗改名：terser 会重命名局部变量，脚本用正则捕获别名而非硬编码。

用法
----
    python apply_music.py --repo D:/git/pvzge_web          # 应用（默认）
    python apply_music.py --repo D:/git/pvzge_web --check   # 只看会改什么，不落盘
    python apply_music.py --repo D:/git/pvzge_web --verify  # 只校验当前状态
    python apply_music.py --repo D:/git/pvzge_web --gen-import   # 顺便重建 import json

退出码：0 成功 / 1 失败 / 2 已是最新（无需改动）
"""

import argparse
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# 音轨清单：改这里就能增删音轨
# --------------------------------------------------------------------------
# name       —— 音轨名（也是 Musics 条目的 name、import json 的 _name）
# world      —— Musics 条目的 world 字段
# world_enum —— index.js 里 WorldMusic 枚举的成员名（注意 Iceage 的成员叫 Ice）
# dir        —— 资源子目录名（可选；默认 = world 小写。RZ_Victory 归在 victory\）
# uuid       —— 8 字符短 uuid，也是磁盘文件名
# music_len  —— 循环点秒数（Musics 的 musicLength）
# duration   —— 音频真实时长（import json 的 _duration）
TRACKS = [
    dict(name="RZ_Egypt",    world="Egypt",    world_enum="Egypt",    uuid="89b35a32", music_len=182.5, duration=186.24),
    dict(name="RZ_Pirate",   world="Pirate",   world_enum="Pirate",   uuid="b7000001", music_len=182.5, duration=186.24),
    dict(name="RZ_Cowboy",   world="Cowboy",   world_enum="Cowboy",   uuid="b7000002", music_len=181,   duration=182.88),
    dict(name="RZ_Kongfu",   world="Kongfu",   world_enum="Kongfu",   uuid="b7000003", music_len=181,   duration=183.312),
    dict(name="RZ_Future",   world="Future",   world_enum="Future",   uuid="b7000004", music_len=181,   duration=184.152),
    dict(name="RZ_Dark",     world="Dark",     world_enum="Dark",     uuid="b7000005", music_len=181,   duration=185.496),
    dict(name="RZ_Beach",    world="Beach",    world_enum="Beach",    uuid="b7000006", music_len=182.5, duration=186.24),
    dict(name="RZ_Iceage",   world="Iceage",   world_enum="Ice",      uuid="b7000007", music_len=181,   duration=184.968),
    dict(name="RZ_Lostcity", world="Lostcity", world_enum="Lostcity", uuid="b7000008", music_len=181,   duration=184.872),
    dict(name="RZ_Sky",      world="Sky",      world_enum="Sky",      uuid="b7000009", music_len=181,   duration=181.577143),
    dict(name="RZ_Dino",     world="Dino",     world_enum="Dino",     uuid="b700000a", music_len=181,   duration=184.416),
    dict(name="RZ_Modern",   world="Modern",   world_enum="Modern",   uuid="b700000b", music_len=181,   duration=184.344),
    dict(name="RZ_Victory",  world="All",      world_enum=None,       uuid="b700000c", music_len=3,     duration=6.024, dir="victory"),
]


def folder(t):
    """音轨的资源子目录：默认 world 小写，可用 dir 覆盖。"""
    return t.get("dir") or t["world"].lower()



TYPE_TAG = "MiniGame_C"        # 对外 MusicType 字符串，也是 Musics 的 type
SORT_MEMBER = "MiniGameC"      # MusicSortEnum 的成员名（内部名，无下划线）
CASE_WINDOW = 40000            # 扫描 case 编号时的窗口半径（字符）


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
class Fail(Exception):
    pass


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw.decode("utf-8")


def write_text(path, text):
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def sub_exact(text, old, new, label):
    """唯一的精确字符串替换；出现 0 次或多次都算失败。"""
    n = text.count(old)
    if n != 1:
        raise Fail(f"[{label}] 锚点出现 {n} 次（应为 1）：{old[:80]!r}")
    return text.replace(old, new, 1)


def find_alias(text, module_name):
    """捕获 <alias> = t("ModuleName", ...) 里的别名。"""
    m = re.search(r'([A-Za-z_$][\w$]*)\s*=\s*t\(\s*"' + re.escape(module_name) + r'"', text)
    if not m:
        raise Fail(f"找不到模块别名：{module_name}")
    return m.group(1)


def enum_param(text, alias, module_name):
    """捕获枚举定义里那个局部参数名（terser 会改名）。"""
    pat = (re.escape(alias) + r'\s*=\s*t\(\s*"' + re.escape(module_name)
           + r'"\s*,\s*function\s*\(\s*([A-Za-z_$][\w$]*)\s*\)')
    m = re.search(pat, text)
    if not m:
        raise Fail(f"找不到 {module_name} 的定义参数名")
    return m.group(1)


# --------------------------------------------------------------------------
# index.js 的 8 处补丁
# --------------------------------------------------------------------------
def discover_js(text):
    """动态发现 index.js 里的别名、枚举参数名、空闲 case 编号。"""
    k = find_alias(text, "MusicSortEnum")
    g = find_alias(text, "MusicEnum")
    u = find_alias(text, "WorldMusic")
    kp = enum_param(text, k, "MusicSortEnum")
    gp = enum_param(text, g, "MusicEnum")
    return dict(K=k, G=g, U=u, K_PARAM=kp, G_PARAM=gp)


def next_sort_value(text, alias, param):
    """MusicSortEnum 的下一个空闲数值（= 当前枚举内最大值 + 1）。

    必须严格限定在 MusicSortEnum 自己的函数体内 —— 相邻的 MusicEnum 定义
    紧接着出现，若窗口开太大会把它的成员值（如 259）也算进来。
    """
    start = text.find(f'{alias}=t("MusicSortEnum"')
    if start == -1:
        raise Fail("找不到 MusicSortEnum 定义")
    close = f",{param}}}({{}}))"
    end = text.find(close, start)
    if end == -1:
        raise Fail("找不到 MusicSortEnum 的收尾")
    body = text[start:end]
    nums = [int(m.group(1)) for m in re.finditer(
        re.escape(param) + r'\.\w+=(\d+)\]', body)]
    if not nums:
        raise Fail("MusicSortEnum 里没解析出任何数值")
    return max(nums) + 1


def next_case_state(text, anchor_pos, var, field, window=400):
    """levelController 状态机里给 MiniGame_C 用的新状态号。

    只从 **MusicType 判定链本身**取数，链形如
        `"MiniGame_A"===X?14:"MiniGame_B"===X?16:18`
    状态号按 +2 递增，所以取链上最大值 +2（上游整体换号时会自动跟着走）。
    窗口刻意开得很小：开大了会把同一个函数里别处的三元数字（如 94）也算进来。
    """
    lo = max(0, anchor_pos - window)
    hi = min(len(text), anchor_pos + window)
    seg = text[lo:hi]
    key = re.escape(var) + r'\.' + re.escape(field)
    nums = [int(n) for n in re.findall(key + r'\?(\d+):', seg)]
    nums += [int(b) for _, b in re.findall(key + r'\?(\d+):(\d+)', seg)]
    if not nums:
        raise Fail("P5 附近解析不到状态号")
    return max(nums) + 2


def patch_index_js(text, dry=False):
    """返回 (新文本, 改动列表)。已打过补丁则原样返回。"""
    changes = []
    info = discover_js(text)
    K, G, U = info["K"], info["G"], info["U"]
    KP, GP = info["K_PARAM"], info["G_PARAM"]
    orig = text

    # ---- P1: MusicSortEnum 增加 MiniGameC = 24 ----
    if f".{SORT_MEMBER}=" in text:
        changes.append(("P1 MusicSortEnum", "已存在，跳过"))
    else:
        val = next_sort_value(text, K, KP)
        needle = f",{KP}}}({{}}))"
        pos = text.find(f'{K}=t("MusicSortEnum"')
        if pos == -1:
            raise Fail("P1 找不到 MusicSortEnum")
        end = text.find(needle, pos)
        if end == -1:
            raise Fail("P1 找不到 MusicSortEnum 的收尾")
        ins = f',{KP}[{KP}.{SORT_MEMBER}={val}]="{SORT_MEMBER}"'
        text = text[:end] + ins + text[end:]
        changes.append(("P1 MusicSortEnum", f"新增 {SORT_MEMBER}={val}"))

    # ---- P2: MusicEnum 增加 13 条 RZ_*，MusicAmount 顺延 ----
    if ".RZ_Egypt=" in text:
        changes.append(("P2 MusicEnum", "已存在，跳过"))
    else:
        pat = (r',' + re.escape(GP) + r'\[' + re.escape(GP)
               + r'\.MusicAmount=(\d+)\]="MusicAmount"')
        m = re.search(pat, text)
        if not m:
            raise Fail("P2 找不到 MusicAmount 哨兵")
        base = int(m.group(1))
        entries = ",".join(
            f'{GP}[{GP}.{t["name"]}={base + i}]="{t["name"]}"'
            for i, t in enumerate(TRACKS)
        )
        new_sentinel = (f',{entries},{GP}[{GP}.MusicAmount={base + len(TRACKS)}]'
                        f'="MusicAmount"')
        text = text[:m.start()] + new_sentinel + text[m.end():]
        changes.append(("P2 MusicEnum",
                        f"新增 {len(TRACKS)} 条 RZ_*（{base}..{base + len(TRACKS) - 1}），"
                        f"MusicAmount {base}→{base + len(TRACKS)}"))

    # ---- P3: 加载器三元链增加 MiniGame_C 分支 ----
    if f'"{TYPE_TAG}"==(null==' in text:
        changes.append(("P3 加载器三元链", "已存在，跳过"))
    else:
        pat = (r'("MiniGame_B"==\(null==([A-Za-z_$][\w$]*)\?void 0:\2\.MusicType\)'
               r'\?[A-Za-z_$][\w$]*\.push\("MiniGame_B"\):)')
        m = re.search(pat, text)
        if not m:
            raise Fail("P3 找不到加载器三元链")
        v = m.group(2)
        arr = re.search(r'([A-Za-z_$][\w$]*)\.push\("MiniGame_B"\)', m.group(1)).group(1)
        ins = (f'"{TYPE_TAG}"==(null=={v}?void 0:{v}.MusicType)'
               f'?{arr}.push("{TYPE_TAG}"):')
        text = text[:m.end(1)] + ins + text[m.end(1):]
        changes.append(("P3 加载器三元链", f'新增 "{TYPE_TAG}" 分支'))

    # ---- P4: 沙盒模式强制类型列表 ----
    if f'MiniGame_C")' in text and '"KongfuBoss","MiniGame_C"' in text:
        changes.append(("P4 沙盒类型列表", "已存在，跳过"))
    else:
        old = '"MiniGame_A","MiniGame_B","Normal","Zomboss","KongfuBoss")'
        new = '"MiniGame_A","MiniGame_B","Normal","Zomboss","KongfuBoss","MiniGame_C")'
        text = sub_exact(text, old, new, "P4 沙盒类型列表")
        changes.append(("P4 沙盒类型列表", f'追加 "{TYPE_TAG}"'))

    # ---- P5 + P6: levelController 的 MusicType 判定与起始音乐 ----
    if f'"{TYPE_TAG}"===e.t0' in text or re.search(r'"MiniGame_C"===[\w$]+\.', text):
        changes.append(("P5 levelController 判定", "已存在，跳过"))
    else:
        m = re.search(r'("MiniGame_B"===([A-Za-z_$][\w$]*)\.([A-Za-z_$][\w$]*)\?16:)18', text)
        if not m:
            raise Fail("P5 找不到 MusicType 判定链")
        var, field = m.group(2), m.group(3)
        case_no = next_case_state(text, m.start(), var, field)
        # 插在尾部那个 else 值（18）之前：
        #   "MiniGame_B"===x?16:18  →  "MiniGame_B"===x?16:"MiniGame_C"===x?<n>:18
        text = (text[:m.end(1)] + f'"{TYPE_TAG}"==={var}.{field}?{case_no}:'
                + text[m.end(1):])
        changes.append(("P5 levelController 判定",
                        f'新增 "{TYPE_TAG}"→case {case_no}'))

        # P6: 插入 case <case_no> 的分支体
        pat6 = r'case 18:this\.startingMusic=([A-Za-z_$][\w$]*)\.CYS_Start;'
        m6 = re.search(pat6, text)
        if not m6:
            raise Fail("P6 找不到 case 18 分支")
        ME = m6.group(1)
        body = (f'case {case_no}:return this.startingMusic={ME}.{SORT_MEMBER},'
                f'e.abrupt("break",19);')
        text = text[:m6.start()] + body + text[m6.start():]
        changes.append(("P6 levelController 分支",
                        f"插入 case {case_no} → {ME}.{SORT_MEMBER}"))

    # ---- P7: switchMusic 顶部插入按世界选曲的 switch ----
    if re.search(re.escape(K) + r'\.' + SORT_MEMBER + r'\)\{switch\(', text):
        changes.append(("P7 switchMusic 世界分支", "已存在，跳过"))
    else:
        pat = (r'if\(this\.isJam=!1,([A-Za-z_$][\w$]*)==' + re.escape(K)
               + r'\.Victory&&this\.currentMusicSort==' + re.escape(K)
               + r'\.UltimateBattle\)')
        m = re.search(pat, text)
        if not m:
            raise Fail("P7 找不到 switchMusic 的 isJam/Victory 判定")
        world_var = m.group(1)
        EN, SORT, WORLD = G, K, U
        # 找出承载世界名的变量：switch(?) 的实参在后续代码里是 t
        wv = re.search(r'e==' + re.escape(K) + r'\.\w+\{switch\(([A-Za-z_$][\w$]*)\)',
                       text)
        wv_name = wv.group(1) if wv else "t"
        cases = []
        for t in TRACKS:
            if not t["world_enum"]:
                continue
            cases.append(f'case {WORLD}.{t["world_enum"]}:'
                         f'S={EN}.{t["name"]};break;')
        fallback = next(t["name"] for t in TRACKS if t["world"] == "Future")
        block = (f'if(this.isJam=!1,e=={SORT}.{SORT_MEMBER}){{switch({wv_name}){{'
                 + "".join(cases)
                 + f'default:S={EN}.{fallback},this.isJam=!0}}g=!0}}else ')
        text = text[:m.start()] + block + text[m.start():]
        changes.append(("P7 switchMusic 世界分支",
                        f'插入 {len(cases)} 个世界分支'))

    # ---- P8: Victory 结算曲 ----
    if re.search(re.escape(K) + r'\.' + SORT_MEMBER + r'\)S=' + re.escape(G)
                 + r'\.RZ_Victory', text):
        changes.append(("P8 Victory 结算曲", "已存在，跳过"))
    else:
        pat = (r'(else if\(e==' + re.escape(K) + r'\.Victory&&this\.currentMusicSort=='
               + re.escape(K) + r'\.DemonstrateMinigame\)S=' + re.escape(G)
               + r'\.MG_Victory,g=!1,r=1;)')
        m = re.search(pat, text)
        if not m:
            raise Fail("P8 找不到 MG_Victory 结算分支")
        ins = (f'else if(e=={K}.Victory&&this.currentMusicSort=={K}.{SORT_MEMBER})'
               f'S={G}.RZ_Victory,g=!1,r=1;')
        text = text[:m.end(1)] + ins + text[m.end(1):]
        changes.append(("P8 Victory 结算曲", "新增 RZ_Victory 分支"))

    return text, changes, ([] if text == orig else ["index.js"])


# --------------------------------------------------------------------------
# config.json 的 2 处补丁
# --------------------------------------------------------------------------
def patch_config_json(text, dry=False):
    changes = []
    obj = json.loads(text)

    if any("RZ_" in str(v) for v in obj["paths"].values()):
        return text, [("C1 config.json", "已存在，跳过")], []

    # ---- C1: uuids 追加 ----
    m = re.search(r'("uuids":\[)', text)
    if not m:
        raise Fail("C1 找不到 uuids 数组")
    uuids_len = len(obj["uuids"])
    add = ",".join(f'"{t["uuid"]}"' for t in TRACKS)
    # 插到 uuids 数组的末尾（即 "],"paths":{ 之前）
    tail = re.search(r'\],"paths":\{', text)
    if not tail:
        raise Fail("C1 找不到 uuids 数组结尾")
    text = text[:tail.start()] + "," + add + text[tail.start():]
    changes.append(("C1 uuids", f"追加 {len(TRACKS)} 个 uuid"))

    # ---- C2: paths 追加（下标 = 补丁前 uuids 长度）----
    last_key = max(int(k) for k in obj["paths"])
    pat = re.compile(r'"' + str(last_key) + r'":\[[^\]]*\]')
    m2 = pat.search(text)
    if not m2:
        raise Fail(f"C2 找不到 paths 的最后一条（{last_key}）")
    items = []
    for i, t in enumerate(TRACKS):
        idx = uuids_len + i
        path = f'music/inGame/{folder(t)}/{t["name"]}'
        items.append(f'"{idx}":["{path}",5,1]')
    ins = "," + ",".join(items)
    text = text[:m2.end()] + ins + text[m2.end():]
    changes.append(("C2 paths",
                    f"追加 {len(TRACKS)} 条（下标 {uuids_len}..{uuids_len + len(TRACKS) - 1}）"))
    return text, changes, ["config.json"]


# --------------------------------------------------------------------------
# 0a278bb49.json 的 1 处补丁
# --------------------------------------------------------------------------
MUSICS_ANCHOR_SUFFIX = '"musicLength":28,"world":"All","type":["Always"]}'


def patch_music_json(text, dry=False):
    if '"RZ_Egypt"' in text:
        return text, [("M1 Musics 条目", "已存在，跳过")], []

    pat = re.compile(r'("path":"dialogue/Dialogue_Dave_LP",' + re.escape(MUSICS_ANCHOR_SUFFIX) + r')')
    m = pat.search(text)
    if not m:
        raise Fail("M1 找不到 Musics 数组的最后一条（Dialogue_Dave_LP）")
    # 确认其后紧跟数组结束
    after = text[m.end():m.end() + 2]
    if not after.startswith("]"):
        raise Fail(f"M1 锚点后不是数组结尾，而是 {after!r}")

    items = []
    for t in TRACKS:
        items.append(
            '{"name":"%s","path":"inGame/%s/%s","musicLength":%s,"world":"%s",'
            '"type":["%s"]}'
            % (t["name"], folder(t), t["name"],
               _num(t["music_len"]), t["world"], TYPE_TAG)
        )
    text = text[:m.end()] + "," + ",".join(items) + text[m.end():]
    return text, [("M1 Musics 条目", f"追加 {len(TRACKS)} 条")], ["0a278bb49.json"]


def _num(v):
    """整数就写成整数，否则保留小数。"""
    return str(int(v)) if float(v) == int(v) else repr(float(v))


# --------------------------------------------------------------------------
# import json 生成（Cocos AudioClip 描述）
# --------------------------------------------------------------------------
IMPORT_TEMPLATE = ('[1,0,0,[["cc.AudioClip",["_name","_native","_duration"],0]],'
                   '[[0,0,1,2,4]],[[0,"{name}",".mp3",{dur}],-1],0,0,[],[],[]]')


def gen_import_json(repo, dry=False):
    out = []
    for t in TRACKS:
        sub = t["uuid"][:2]
        p = os.path.join(repo, "docs", "assets", "resources", "import", sub,
                         t["uuid"] + ".json")
        body = IMPORT_TEMPLATE.format(name=t["name"], dur=_num(t["duration"]))
        if os.path.exists(p):
            cur = read_text(p)
            if cur == body:
                out.append((t["name"], "已一致，跳过"))
                continue
            if dry:
                out.append((t["name"], "内容不同（dry-run 未写）"))
                continue
            write_text(p, body)
            out.append((t["name"], "已重建"))
        else:
            if dry:
                out.append((t["name"], "缺失（dry-run 未建）"))
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            write_text(p, body)
            out.append((t["name"], "已新建"))
    return out


def check_mp3(repo):
    miss = []
    for t in TRACKS:
        sub = t["uuid"][:2]
        p = os.path.join(repo, "docs", "assets", "resources", "native", sub,
                         t["uuid"] + ".mp3")
        if not os.path.exists(p):
            miss.append((t["name"], os.path.relpath(p, repo)))
    return miss


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def verify(repo, verbose=True):
    problems = []
    js_p = os.path.join(repo, "docs", "assets", "main", "index.js")
    cfg_p = os.path.join(repo, "docs", "assets", "resources", "config.json")
    mj_p = os.path.join(repo, "docs", "assets", "resources", "import", "0a",
                        "0a278bb49.json")

    js = read_text(js_p)
    cfg = read_text(cfg_p)
    mj = read_text(mj_p)

    # index.js
    if f'.{SORT_MEMBER}=' not in js:
        problems.append("index.js: 缺 MusicSortEnum 成员")
    if '".RZ_Egypt="'.strip('"') not in js:
        problems.append("index.js: 缺 RZ_* 枚举")
    if f'"{TYPE_TAG}"==(null==' not in js:
        problems.append("index.js: 缺加载器三元链分支")
    if f'"KongfuBoss","{TYPE_TAG}"' not in js:
        problems.append("index.js: 缺沙盒类型列表项")
    if not re.search(r'"' + re.escape(TYPE_TAG) + r'"===[\w$]+\.', js):
        problems.append("index.js: 缺 levelController 判定")
    if not re.search(re.escape(SORT_MEMBER) + r'\)\{switch\(', js):
        problems.append("index.js: 缺 switchMusic 世界分支")
    if not re.search(r'currentMusicSort==[\w$]+\.' + re.escape(SORT_MEMBER)
                     + r'\)S=[\w$]+\.RZ_Victory', js):
        problems.append("index.js: 缺 Victory 结算曲")

    # 枚举值与 Musics 下标一致（铁律）
    try:
        o = json.loads(cfg)
        musics = None
        for el in json.loads(mj):
            if isinstance(el, dict) and "Musics" in el:
                musics = el["Musics"]
        g = find_alias(js, "MusicEnum")
        gp = enum_param(js, g, "MusicEnum")
        vals = {}
        for m in re.finditer(re.escape(gp) + r'\[' + re.escape(gp)
                            + r'\.(\w+)=(\d+)\]="', js):
            vals[m.group(1)] = int(m.group(2))
        if musics is not None:
            for i, t in enumerate(TRACKS):
                v = vals.get(t["name"])
                if v is None:
                    problems.append(f"枚举缺 {t['name']}")
                    continue
                expected = None
                for k, e in enumerate(musics):
                    if isinstance(e, dict) and e.get("name") == t["name"]:
                        expected = k
                        break
                if expected is None:
                    problems.append(f"Musics 缺 {t['name']}")
                elif expected != v:
                    problems.append(
                        f"{t['name']} 下标错位：枚举={v} Musics={expected}")
        # RZ 路径注册
        rz = {k: v for k, v in o["paths"].items() if "RZ_" in str(v)}
        if len(rz) != len(TRACKS):
            problems.append(f"config.json RZ 路径 {len(rz)} 条（应为 {len(TRACKS)}）")
        for t in TRACKS:
            hit = [v for v in o["paths"].values()
                   if v and v[0].endswith("/" + t["name"])]
            if not hit:
                problems.append(f"config.json 缺路径 {t['name']}")
        for t in TRACKS:
            if t["uuid"] not in o["uuids"]:
                problems.append(f"config.json uuids 缺 {t['uuid']}")
    except Exception as ex:
        problems.append(f"JSON 解析/一致性检查失败：{ex}")

    # 资源文件
    for t in TRACKS:
        sub = t["uuid"][:2]
        ip = os.path.join(repo, "docs", "assets", "resources", "import", sub,
                          t["uuid"] + ".json")
        op = os.path.join(repo, "docs", "assets", "resources", "native", sub,
                          t["uuid"] + ".mp3")
        if not os.path.exists(ip):
            problems.append(f"缺 import json：{t['uuid']}.json")
        if not os.path.exists(op):
            problems.append(f"缺 mp3：{t['uuid']}.mp3")

    if verbose:
        if problems:
            print("校验未通过：")
            for p in problems:
                print("  ✗", p)
        else:
            print("✅ 校验全部通过（8 处 index.js 改动 + 13 条枚举/下标/路径/资源）")
    return problems


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="重放 MiniGame_C 音乐定制")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--check", action="store_true", help="只看会改什么，不落盘")
    ap.add_argument("--verify", action="store_true", help="只校验当前状态")
    ap.add_argument("--gen-import", action="store_true", help="重建 import/*.json")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, "docs")):
        print(f"❌ 不是有效的仓库根目录（找不到 docs/）：{repo}")
        return 1
    print(f"仓库：{repo}")
    print()

    if args.verify:
        return 0 if not verify(repo) else 1

    js_p = os.path.join(repo, "docs", "assets", "main", "index.js")
    cfg_p = os.path.join(repo, "docs", "assets", "resources", "config.json")
    mj_p = os.path.join(repo, "docs", "assets", "resources", "import", "0a",
                        "0a278bb49.json")

    try:
        for path, fn, label in [(js_p, patch_index_js, "index.js"),
                                (cfg_p, patch_config_json, "config.json"),
                                (mj_p, patch_music_json, "0a278bb49.json")]:
            if not os.path.exists(path):
                raise Fail(f"文件不存在：{path}")
            src = read_text(path)
            dst, changes, touched = fn(src, dry=args.check)
            print(f"── {label} ──")
            for name, desc in changes:
                print(f"   {name:28s} {desc}")
            if touched and not args.check:
                write_text(path, dst)
                print(f"   → 已写入（{len(src):,} → {len(dst):,} 字符）")
            elif touched:
                print(f"   → dry-run，未写入（将 {len(src):,} → {len(dst):,} 字符）")
            print()

        if args.gen_import:
            print("── import/*.json ──")
            for name, desc in gen_import_json(repo, dry=args.check):
                print(f"   {name:28s} {desc}")
            print()

        miss = check_mp3(repo)
        if miss:
            print("⚠️  以下 mp3 不在位（需要从 git 历史恢复）：")
            for name, rel in miss:
                print(f"   {name:14s} {rel}")
            print("   恢复：git checkout <含音乐的提交> -- docs/assets/resources/native/")
            print()

    except Fail as ex:
        print(f"❌ {ex}")
        return 1

    if args.check:
        print("（dry-run 完成，没有改动任何文件）")
        return 0

    print("── 最终校验 ──")
    problems = verify(repo)
    print()
    if problems:
        return 1
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
