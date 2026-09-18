#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_report.py —— 体检 13 条 RZ 音轨：来源、编码规格、响度、时长一致性。

先搞清楚"来源"，再谈"统不统一"
------------------------------
这 13 条轨分两类，**不能一锅端**：

* **自制轨** —— 用户喂进来的替换音频（`musicLength` 被改成循环点，如 182.5）。
  它们是"手工塞进来"的，母带响度取决于当时怎么处理的 ⇒ **这才是要统一的对象**。
* **官方原声** —— 从未被替换流程碰过（`musicLength` 仍是原值 181 / Victory 3）。
  它们的响度差异是**官方母带本身就有的**（官方 UB 集跨曲 −10.5 ~ −17.7 LUFS），
  保持原样 = 忠实官方。把它们"统一"了反而是偏离官方。

所以本脚本默认**只把自制轨的响度离散算作问题**；官方轨的差异单独列出来当情报看。
想连官方轨一起纳入判定，加 `--include-official`。

判据来自项目既有工具 `rz_map_check.py` 的同一套规则（`musicLength` vs 原生长度），
保证两个工具口径一致。

响度用 EBU R128（ffmpeg 的 ebur128 滤镜），广播级标准：
  I    —— Integrated loudness，整轨平均响度（LUFS）。**决定"听起来谁更响"的是它**。
  LRA  —— Loudness range，响度动态范围（LU）。
  Peak —— True peak，真峰值（dBFS），超过 0 会削波。

用法
----
    python audio_report.py                     # 全量报告
    python audio_report.py --loudness-only     # 跳过格式探测，只测响度
    python audio_report.py --track RZ_Egypt    # 只看一条
    python audio_report.py --json out.json     # 顺便导出机器可读结果
    python audio_report.py --target -14.5      # 指定参考 LUFS（默认 -14.5）
    python audio_report.py --include-official   # 官方原声也纳入统一判定

退出码：0 正常 / 1 有告警（自制轨响度离散 / 削波 / 时长不符）/ 2 环境缺 ffmpeg
"""

import argparse
import json
import os
import statistics
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import _console_utf8  # noqa: E402,F401

sys.path.insert(0, _HERE)
import _audio  # noqa: E402
import apply_music  # noqa: E402

LUFS_TOLERANCE = 0.5     # 自制轨彼此的响度差超过这么多 LU 就告警
DUR_TOLERANCE = 0.15     # 声明的 duration 和实测差超过这么多秒就告警

# 官方初始 musicLength —— 与 rz_map_check.py 保持一致。
# 被替换过会被改成实际循环点（如 182.5），据此判定"自制 / 官方原声"。
ORIGINAL_LEN = {"RZ_Victory": 3}
DEFAULT_LEN = 181

HOME_SPEC = {"br": 160000, "sr": 48000, "ch": 2}   # 房子标准（自制轨应对齐的规格）


def track_path(repo, t):
    sub = t["uuid"][:2]
    return os.path.join(repo, "docs", "assets", "resources", "native", sub,
                        t["uuid"] + ".mp3")


def provenance(t):
    """这条是自制替换轨还是官方原声？"""
    return "官方" if t["music_len"] == ORIGINAL_LEN.get(t["name"], DEFAULT_LEN) \
        else "自制"


def collect(repo, only=None, loudness_only=False):
    rows = []
    for t in apply_music.TRACKS:
        if only and t["name"] != only:
            continue
        p = track_path(repo, t)
        row = {"name": t["name"], "world": t["world"], "uuid": t["uuid"],
               "path": p, "exists": os.path.exists(p),
               "prov": provenance(t),
               "declared_dur": t["duration"], "declared_len": t["music_len"]}
        if not row["exists"]:
            rows.append(row)
            continue
        if not loudness_only:
            row.update(_audio.probe(p))
        row.update(_audio.measure_loudness(p))
        if row.get("dur"):
            row["dur_delta"] = round(row["dur"] - t["duration"], 3)
            # musicLength 之后的尾音是**永远播不到**的（index.js 到点就切歌）
            row["tail"] = round(row["dur"] - t["music_len"], 3)
        rows.append(row)
    return rows


def spec_off(r):
    """偏离房子标准的地方（160k/48k/立体声）。"""
    off = []
    if r.get("br") and abs(r["br"] - HOME_SPEC["br"]) > 8000:
        off.append(f"码率{r['br'] // 1000}k")
    if r.get("sr") and r["sr"] != HOME_SPEC["sr"]:
        off.append(f"{r['sr'] / 1000:g}k采样")
    if r.get("ch") and r["ch"] != HOME_SPEC["ch"]:
        off.append(f"{r['ch']}ch")
    return off


def main():
    ap = argparse.ArgumentParser(description="RZ 音轨体检：来源 / 规格 / 响度 / 时长")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(_HERE)))
    ap.add_argument("--track", help="只测一条（音轨名，如 RZ_Egypt）")
    ap.add_argument("--loudness-only", action="store_true")
    ap.add_argument("--json", dest="json_out", help="导出 JSON 到指定路径")
    ap.add_argument("--target", type=float, default=_audio.TARGET_LUFS,
                    help="参考 LUFS（默认 -14.5，即房子目标）")
    ap.add_argument("--include-official", action="store_true",
                    help="把官方原声也纳入响度统一判定（默认只判自制轨）")
    args = ap.parse_args()

    try:
        _audio.require_tools()
    except _audio.AudioError as ex:
        print(f"❌ {ex}")
        return 2

    repo = os.path.abspath(args.repo)
    rows = collect(repo, only=args.track, loudness_only=args.loudness_only)

    print(f"仓库：{repo}")
    print(f"ffmpeg：{_audio.find_tool('ffmpeg')}")
    n_self = sum(1 for r in rows if r["prov"] == "自制")
    print(f"其中 自制轨 {n_self} 条（要统一的对象）｜"
          f"官方原声 {len(rows) - n_self} 条（母带差异，保持原样=忠实官方）")
    print()

    problems = []

    # ---- 规格与时长 ----
    if not args.loudness_only:
        print("── 编码规格与时长 ──")
        print(f"{'音轨':<13}{'来源':<5}{'码率':>7}{'采样率':>8}{'声':>3}"
              f"{'实测时长':>11}{'声明':>11}{'差':>8}{'尾音':>8}")
        for r in rows:
            if not r["exists"]:
                print(f"{r['name']:<13}{'—— 文件缺失 ——':>40}")
                continue
            br = f"{(r['br'] or 0) // 1000}k" if r.get("br") else "?"
            sr = f"{r['sr'] / 1000:g}k" if r.get("sr") else "?"
            d = r.get("dur") or 0
            dd = r.get("dur_delta")
            mark = ""
            if dd is not None and abs(dd) > DUR_TOLERANCE:
                mark = " ⚠️"
                problems.append(f"{r['name']} duration 差 {dd:+.3f}s")
            off = spec_off(r)
            if off:
                # 官方原声的规格是官方给的，只当情报；自制轨才算问题
                if r["prov"] == "自制":
                    mark += " 规格≠房子标准:" + "/".join(off)
                    problems.append(f"{r['name']} 规格偏离：" + "/".join(off))
                else:
                    mark += " （官方规格：" + "/".join(off) + "）"
            print(f"{r['name']:<13}{r['prov']:<5}{br:>7}{sr:>8}{r.get('ch', '?'):>3}"
                  f"{d:>11.3f}{r['declared_dur']:>11.3f}"
                  f"{(f'{dd:+.3f}' if dd is not None else '?'):>8}"
                  f"{(r.get('tail') if r.get('tail') is not None else 0):>8.3f}{mark}")
        print()

    # ---- 响度 ----
    print("── 响度（EBU R128）──")
    print(f"{'音轨':<13}{'来源':<5}{'I (LUFS)':>10}{'LRA (LU)':>10}"
          f"{'真峰值':>10}{'到0dB余量':>11}")
    clip_self, clip_off = [], []
    for r in rows:
        if not r["exists"] or r.get("I") is None:
            print(f"{r['name']:<13}{r['prov']:<5}{'—— 测不到 ——':>41}")
            continue
        p = r.get("peak")
        room = -p if p is not None else None
        flag = ""
        if p is not None and p > 0:
            flag = "  ⚠️ 削波"
            (clip_self if r["prov"] == "自制" else clip_off).append(
                f"{r['name']} 真峰值 {p:+.2f} dBFS")
        elif p is not None and p > _audio.TARGET_TP_DB + 0.15:
            flag = f"  ⚠️ 峰值超上限 {_audio.TARGET_TP_DB:+.1f}"
            if r["prov"] == "自制":
                problems.append(f"{r['name']} 真峰值 {p:+.2f} 超上限")
        elif p is not None and p > -1.0:
            flag = "  余量偏紧"
        print(f"{r['name']:<13}{r['prov']:<5}{r['I']:>10.1f}"
              f"{(r['lra'] if r['lra'] is not None else 0):>10.1f}"
              f"{(p if p is not None else 0):>10.2f}"
              f"{(room if room is not None else 0):>11.2f}{flag}")
    print()

    if clip_self:
        print("── 自制轨削波（解码后真峰值 > 0 dBFS）──")
        for c in clip_self:
            print(f"   {c}")
            problems.append(c)
        print()
    if clip_off:
        print("── 官方原声削波（官方母带本就在 0 dBFS 边缘，属原样）──")
        for c in clip_off:
            print(f"   {c}")
        print()

    # ---- 自制轨：彼此是否统一 ----
    self_rows = [r for r in rows if r.get("I") is not None and r["prov"] == "自制"]
    off_rows = [r for r in rows if r.get("I") is not None and r["prov"] == "官方"]

    if self_rows:
        sv = [r["I"] for r in self_rows]
        med = statistics.median(sv)
        print("── 自制轨响度一致性（这才是「音量统一」要解决的问题）──")
        print(f"   {len(sv)} 条 ｜ 中位 {med:+.1f} LUFS ｜ 极差 {max(sv) - min(sv):.1f} LU ｜ "
              f"房子目标 {args.target:+.1f} LUFS")
        bad = [r for r in self_rows if abs(r["I"] - args.target) > LUFS_TOLERANCE]
        if bad:
            for r in sorted(bad, key=lambda x: -abs(x["I"] - args.target)):
                d = r["I"] - args.target
                print(f"   ⚠️ {r['name']:<13}{r['I']:>7.1f} LUFS  {d:+.1f} LU  "
                      f"{'偏响' if d > 0 else '偏轻'}   → 需 {-d:+.1f} dB")
                problems.append(f"{r['name']} 响度 {r['I']:.1f}（{d:+.1f} LU）")
        else:
            print(f"   ✅ 全部落在 ±{LUFS_TOLERANCE:g} LU 内，彼此一致")
        print()

    # ---- 官方原声：跨世界差异（情报，不是问题）----
    if off_rows:
        ov = [r["I"] for r in off_rows]
        print("── 官方原声跨世界差异（官方母带设计，保持原样=忠实官方）──")
        print(f"   {len(ov)} 条 ｜ {min(ov):+.1f} ~ {max(ov):+.1f} LUFS ｜ "
              f"极差 {max(ov) - min(ov):.1f} LU")
        if args.include_official:
            bad_o = [r for r in off_rows if abs(r["I"] - args.target) > LUFS_TOLERANCE]
            for r in sorted(bad_o, key=lambda x: -abs(x["I"] - args.target)):
                d = r["I"] - args.target
                print(f"   ⚠️ {r['name']:<13}{r['I']:>7.1f} LUFS  {d:+.1f} LU  "
                      f"→ 需 {-d:+.1f} dB")
                problems.append(f"{r['name']}（官方）响度 {r['I']:.1f}（{d:+.1f} LU）")
        else:
            print("   （已排除在判定之外；要一并统一加 --include-official）")
        print()

    bad_dur = [r for r in rows if r.get("dur_delta") is not None
               and abs(r["dur_delta"]) > DUR_TOLERANCE]
    if bad_dur:
        print("── 声明 duration 与实测不符（会让 Cocos 的 _duration 失真）──")
        for r in bad_dur:
            print(f"   {r['name']:<13}声明 {r['declared_dur']}  "
                  f"实测 {r['dur']:.3f}  差 {r['dur_delta']:+.3f}s")
        print()

    miss = [r for r in rows if not r["exists"]]
    if miss:
        print("── mp3 缺失 ──")
        for r in miss:
            print(f"   {r['name']:<13}{os.path.relpath(r['path'], repo)}")
            problems.append(f"{r['name']} 缺 mp3")
        print()

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"JSON 已写到 {args.json_out}")
        print()

    if problems:
        print(f"⚠️  {len(problems)} 项需要处理。"
              f"（统一响度：python tools/music-patch/normalize_music.py "
              f"--apply --tracks <名字,逗号分隔>）")
        return 1
    print("✅ 全部在容差内。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
