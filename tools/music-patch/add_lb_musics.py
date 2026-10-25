# -*- coding: utf-8 -*-
"""给 Musics 数组追加 LB 条目（照 ZBT 的顺序与位置）。

铁律 #1：Musics 下标 == MusicEnum 值。
所以 LB 条目必须**紧接着 ZBT 组之后**追加，
LB 在 MusicEnum 里的值也从 ZBT 最后一成员 +1 开始。

这个脚本只改 Musics，Enum 由 patch_lb_index.py 改。
两边顺序必须来自同一个清单 —— 所以清单定义在 add_lb_data.py 里，
这里 import 它。
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_lb_data import build_tracks, dur, SRC  # noqa: E402

REPO = r"D:\git\pvzge_web"
MUSICS_JSON = os.path.join(REPO, "docs", "assets", "resources", "import",
                           "0d", "0d4cac202.json")


def find_musics_span(s):
    """定位 Musics 数组的 [start, end) 字节区间（在 JSON 文本里）。"""
    i = s.find('{"name":"WorldMap"')
    if i < 0:
        raise SystemExit("找不到 Musics 起点")
    start = s.rfind("[", 0, i)
    depth = 0
    for k in range(start, len(s)):
        c = s[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return start, k + 1
    raise SystemExit("Musics 数组未闭合")


def main(apply=False):
    tracks = build_tracks()
    rows = []
    for name, src, fixed, formula in tracks:
        p = os.path.join(SRC, src)
        d = dur(p)
        ml = fixed if fixed is not None else round(d - 0.05, 2)
        rows.append((name, ml))

    raw = io.open(MUSICS_JSON, encoding="utf-8", errors="replace").read()

    # 现有 Musics 的条目名（按顺序）
    start, end = find_musics_span(raw)
    seg = raw[start:end]
    obj = json.loads(seg)
    exist = [e["name"] for e in obj]

    print("现有 Musics:", len(exist), "条")
    print("  尾部 3 条:", exist[-3:])

    present = [n for n in exist if n.startswith("LB_")]
    if present:
        print(f"  LB 已有 {len(present)} 条")

    absent = [(n, ml) for n, ml in rows if n not in exist]
    print(f"待追加: {len(absent)} 条")

    if not absent:
        print("无需改动")
        return 0

    def num(v):
        return str(int(v)) if float(v) == int(v) else repr(float(v))

    items = ",".join(
        '{"name":"%s","tauri":"rk_%s","musicLength":%s}' % (n, n, num(ml))
        for n, ml in absent)

    new_seg = seg[:-1] + "," + items + "]"
    out = raw[:start] + new_seg + raw[end:]

    # 校验
    arr = json.loads(new_seg)
    print("新 Musics:", len(arr), "条")

    # 铁律校验：ZBT 组之后的顺序必须与 rows 一致
    tail = [e["name"] for e in arr[len(exist):]]
    expect = [n for n, _ in absent]
    if tail != expect:
        raise SystemExit("追加顺序与清单不一致！")

    print("  LB 段顺序正确，前 3:", tail[:3])
    print("  末 3:", tail[-3:])

    if apply:
        io.open(MUSICS_JSON, "w", encoding="utf-8", newline="").write(out)
        # 二次校验
        chk = io.open(MUSICS_JSON, encoding="utf-8", errors="replace").read()
        s2, e2 = find_musics_span(chk)
        a2 = json.loads(chk[s2:e2])
        print("  已写入，文件内 Musics:", len(a2), "条")
    else:
        print("  [dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
