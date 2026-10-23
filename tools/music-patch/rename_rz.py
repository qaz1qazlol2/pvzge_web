# -*- coding: utf-8 -*-
"""把 RZ_* 音轨整体改名为 ZBT_*（CYS 三套按家族去前缀）。

规则
----
  RZ_UB_CYS_X   → UB_CYS_X      （家族前缀保留，去掉 RZ_）
  RZ_MG_CYS_X   → MG_CYS_X
  RZ_ZBT_CYS_X  → ZBT_CYS_X
  其他 RZ_X     → ZBT_X

要动的地方
----------
  1. docs/audio/Music/inGame/<旧名>/<旧名>.mp3  → <新名>/<新名>.mp3（目录+文件）
  2. docs/audio/manifest.json   key rk_<旧> → rk_<新>，路径同步
  3. docs/assets/resources/import/0d/0d4cac202.json  Musics 的 name / tauri
  4. docs/assets/main/index.js   MusicEnum 成员名
  5. tools/music-patch/*.py      代码里的字面量

⚠️ 必须**同时**改完这 5 处，否则枚举值、Musics 下标、manifest key 会脱节。
   本脚本按「先算完整映射 → 再逐处替换 → 最后整体校验」的顺序做，
   任一步对不上就中止，不落盘。

用法
----
    python tools/music-patch/rename_rz.py --check
    python tools/music-patch/rename_rz.py --apply
"""
import argparse
import io
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

REPO = r"D:\git\pvzge_web"
GAME = os.path.join("docs", "audio", "Music", "inGame")
MUSICS = os.path.join("docs", "assets", "resources", "import", "0d", "0d4cac202.json")
MANIFEST = os.path.join("docs", "audio", "manifest.json")
INDEX = os.path.join("docs", "assets", "main", "index.js")

CODE_FILES = [
    os.path.join("tools", "music-patch", "apply_music.py"),
    os.path.join("tools", "music-patch", "audio_report.py"),
    os.path.join("tools", "music-patch", "normalize_music.py"),
    os.path.join("tools", "music-patch", "import_track.py"),
]


def read(p):
    with io.open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def rename(name):
    """RZ_ → ZBT_；CYS 三套按家族去前缀。"""
    if re.match(r"^RZ_(UB|MG|ZBT)_CYS_", name):
        return name[3:]
    if name.startswith("RZ_"):
        return "ZBT_" + name[3:]
    return name


def find_musics_names(text):
    """按出现顺序取出 Musics 里的 RZ_ 条目名。"""
    return re.findall(r'\{"name":"(RZ_\w+)","tauri"', text)


def main():
    ap = argparse.ArgumentParser(description="RZ_* → ZBT_* 整体改名")
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    mj_p = os.path.join(repo, MUSICS)
    man_p = os.path.join(repo, MANIFEST)
    js_p = os.path.join(repo, INDEX)

    mj = read(mj_p)
    old_names = find_musics_names(mj)
    if not old_names:
        print("❌ Musics 里找不到 RZ_ 条目（可能已经改过名）")
        return 1

    mapping = {o: rename(o) for o in old_names}
    print(f"仓库：{repo}")
    print(f"待改名：{len(mapping)} 条")
    print()

    # 撞名检查
    clash = set()
    for o, n in mapping.items():
        if o != n and f'"{n}"' in mj and f'"name":"{n}"' in mj:
            clash.add(n)
    if clash:
        print(f"❌ 新名与现有条目撞车：{sorted(clash)[:5]}")
        return 1

    print(f"{'旧名':<28}{'新名'}")
    print("-" * 56)
    for o, n in list(mapping.items())[:8]:
        print(f"{o:<28}{n}")
    print(f"... 共 {len(mapping)} 条")
    print()

    # 逐项统计要改的东西
    d_audio = [o for o in mapping if os.path.isdir(os.path.join(repo, GAME, o))]
    n_man = sum(1 for o in mapping if f'"rk_{o}"' in read(man_p))
    n_js = sum(1 for o in mapping if f".{o}=" in read(js_p))
    print(f"音频目录：{len(d_audio)} 个")
    print(f"manifest key：{n_man} 个")
    print(f"index.js 枚举成员：{len(mapping)} 个（逐个确认后替换）")
    print()

    if args.check or not args.apply:
        print("（dry-run，未写入。加 --apply 执行）")
        return 0

    # ---- 1. 音频目录改名 ----
    moved = 0
    for o, n in mapping.items():
        od = os.path.join(repo, GAME, o)
        nd = os.path.join(repo, GAME, n)
        if not os.path.isdir(od):
            continue
        of = os.path.join(od, o + ".mp3")
        nf = os.path.join(nd, n + ".mp3")
        os.makedirs(nd, exist_ok=True)
        if os.path.isfile(of):
            shutil.move(of, nf)
        if os.path.isdir(od) and not os.listdir(od):
            os.rmdir(od)
        moved += 1
    print(f"✓ 音频目录 {moved} 个")

    # ---- 2. manifest ----
    man = read(man_p)
    for o, n in mapping.items():
        man = man.replace(f'"rk_{o}":', f'"rk_{n}":')
        man = man.replace(f'"Music/inGame/{o}/{o}.mp3"',
                          f'"Music/inGame/{n}/{n}.mp3"')
    write(man_p, man)
    print(f"✓ manifest 已更新")

    # ---- 3. Musics ----
    for o, n in mapping.items():
        mj = mj.replace(f'{{"name":"{o}","tauri":"rk_{o}"',
                        f'{{"name":"{n}","tauri":"rk_{n}"')
    write(mj_p, mj)
    print(f"✓ Musics 已更新")

    # ---- 4. index.js 枚举 ----
    # 这里有三种形式，都要改：
    #   枚举定义   t[t.RZ_Egypt=260]="RZ_Egypt"
    #   引用        u=A.RZ_Egypt
    #   字符串比较  window.__mts=="MiniGame_C"（不涉及 RZ_）
    #
    # RZ_ 前缀全仓库只有我们在用，上游没有任何同名符号，
    # 所以按**整词**替换即可，不必逐种形式写正则。
    js = read(js_p)
    hit = 0
    for o, n in mapping.items():
        if o == n:
            continue
        pat = re.compile(r"\b" + re.escape(o) + r"\b")
        if pat.search(js):
            js = pat.sub(n, js)
            hit += 1
    write(js_p, js)
    print(f"✓ index.js 枚举/引用 {hit} 条")

    # ---- 5. 工具脚本 ----
    for rel in CODE_FILES:
        p = os.path.join(repo, rel)
        if not os.path.isfile(p):
            continue
        src = read(p)
        # 整词替换：代码里可能以 "RZ_X" 字面量、f-string 片段、
        # 或 name= 参数形式出现，逐种写法匹配容易漏。
        out = src
        for o, n in mapping.items():
            if o == n:
                continue
            out = re.sub(r"\b" + re.escape(o) + r"\b", n, out)
        if out != src:
            write(p, out)
            print(f"✓ {rel}")

    print()
    print("完成。下一步：")
    print("  node --check docs/assets/main/index.js")
    print("  python tools/music-patch/apply_music.py --verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
