#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
import_track.py —— 把一段视频（或音频）换成某条 RZ 音轨。

用途
----
「我发你一个视频，你替换到对应的 RZ 音频」——  这个脚本把那件事整套做掉：
从视频里抽音频 → 裁掉首尾静音 → 转成统一规格的 mp3 → **响度也对齐到同一把尺子**
（不然刚统一好的音量又被打乱）→ 写进正确的 uuid 文件 → 同步改掉 apply_music.py
里那两个必须跟着变的数字 → 重建 import json → 校验。

为什么不能只换 mp3 文件
-----------------------
换音频会让**时长**变，而仓库里有三个数字和时长绑死，少改一个就出 bug：

  1. `duration`      → 写进 import/*.json 的 `_duration`（Cocos 的资源元数据）
  2. `music_len`     → 写进 Musics 的 `musicLength`，是 index.js 里的**循环/切歌点**：
                       `currentTime >= musicLength && changeLoopPlayer()`。
                       新音频比它短 ⇒ 永远等不到切歌点；比它长 ⇒ 被提前切断。
  3. mp3 文件本体

本脚本三个一起改，然后跑 apply_music.py 重建 + 校验。

`music_len` 怎么定
------------------
默认**保留该音轨原有的尾长**（duration - music_len，现有集合是 3.4~4.5s）。
那段尾音在游戏里是播不到的（到点就切歌），所以保持尾长 = 保持原有手感。
可用 `--tail` 改尾长、`--music-length` 直接指定、`--full` 让整首都能放到。

用法
----
    python import_track.py --list
    python import_track.py --track RZ_Egypt --src "D:/videos/rz_egypt.mp4"
    python import_track.py --track RZ_Egypt --src xx.mp4 --apply
    python import_track.py --track RZ_Egypt --src xx.mp4 --start 12 --end 95 --apply
    python import_track.py --track RZ_Egypt --src xx.mp4 --no-trim --apply

退出码：0 成功 / 1 失败 / 2 环境缺 ffmpeg
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.dirname(_HERE))
import _console_utf8  # noqa: E402,F401

sys.path.insert(0, _HERE)
import _audio  # noqa: E402
import apply_music  # noqa: E402

SPEC = {"br": "160k", "sr": 48000, "ch": 2}
BACKUP_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
    "pvzge_web-audio-backup")

# 首尾静音低于这个长度就不值得裁（多半只是 MP3 编码器的 padding）
MIN_TRIM = 0.15


def track_path(repo, t):
    sub = t["uuid"][:2]
    return os.path.join(repo, "docs", "assets", "resources", "native", sub,
                        t["uuid"] + ".mp3")


def pick_track(name):
    for t in apply_music.TRACKS:
        if t["name"] == name:
            return t
    near = [t["name"] for t in apply_music.TRACKS
            if name.lower() in t["name"].lower()]
    raise SystemExit(f"[错] 没有音轨叫 {name!r}。"
                     + (f"你是不是想输：{', '.join(near)}？" if near
                        else "\n用 --list 看全部音轨名。"))


def fmt_sec(v):
    """秒数写成 apply_music.py 里的干净形式：0.2 精度够用，又去掉浮点尾巴。"""
    if v is None:
        return None
    return f"{round(float(v), 3):g}"


def patch_apply_music(path, name, duration, music_len):
    """只改 apply_music.py 里**目标音轨那一行**的两个数字。

    按行锚定（name="RZ_X"），不做全局替换 —— 免得改到别的音轨或别的地方。
    """
    with open(path, "rb") as f:
        raw = f.read()
    # 保住原文件的换行符（本仓库 core.autocrlf=true，检出是 CRLF）
    n_crlf = raw.count(b"\r\n")
    eol = "\r\n" if n_crlf > raw.count(b"\n") - n_crlf else "\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")

    pat = re.compile(r'(^\s*dict\(name="' + re.escape(name) + r'",[^\n]*)$', re.M)
    m = pat.search(text)
    if not m:
        raise SystemExit(f"[错] 在 apply_music.py 里找不到 {name} 的定义行")
    old_line = m.group(1)
    new_line = old_line
    for field, val in (("music_len", music_len), ("duration", duration)):
        fpat = re.compile(r"(?<![\w.])" + field + r"\s*=\s*[-+]?[\d.]+")
        if not fpat.search(new_line):
            raise SystemExit(f"[错] {name} 那一行里没有 {field}= 字段：{old_line}")
        new_line = fpat.sub(f"{field}={val}", new_line, count=1)
    if new_line == old_line:
        return None, old_line
    text = text[:m.start(1)] + new_line + text[m.end(1):]
    with open(path, "wb") as f:
        f.write(text.replace("\n", eol).encode("utf-8"))
    return new_line, old_line


def main():
    ap = argparse.ArgumentParser(description="把视频/音频换成某条 RZ 音轨")
    ap.add_argument("--repo", default=_ROOT)
    ap.add_argument("--track", help="目标音轨名，如 RZ_Egypt")
    ap.add_argument("--src", help="源文件（视频或音频）")
    ap.add_argument("--list", action="store_true", help="列出全部音轨")
    ap.add_argument("--apply", action="store_true", help="真的写回（默认只预览）")
    ap.add_argument("--target", type=float, default=_audio.TARGET_LUFS)
    ap.add_argument("--ceiling", type=float, default=_audio.TARGET_TP_DB)
    ap.add_argument("--method", choices=("loudnorm", "gain-limit"),
                    default="loudnorm",
                    help="响度对齐方式：loudnorm=两遍线性、不改动态（默认，"
                         "与既有 3 条一致）；gain-limit=增益+限幅、严格打到目标")
    ap.add_argument("--start", type=float, help="只取视频的这一秒之后")
    ap.add_argument("--end", type=float, help="只取到这一秒为止")
    ap.add_argument("--no-trim", action="store_true", help="不裁首尾静音")
    ap.add_argument("--tail", type=float, help="musicLength 到结尾的尾长（秒）")
    ap.add_argument("--music-length", type=float, help="直接指定 musicLength")
    ap.add_argument("--full", action="store_true",
                    help="musicLength = 整条时长（整首都放到）")
    ap.add_argument("--stream", help="指定音频流，如 0:a:1")
    args = ap.parse_args()

    try:
        _audio.require_tools()
    except _audio.AudioError as ex:
        print(f"❌ {ex}")
        return 2

    repo = os.path.abspath(args.repo)

    if args.list or not args.track:
        print(f"{'音轨':<13}{'world':<10}{'uuid':<10}{'时长':>9}{'循环点':>9}{'尾长':>8}")
        for t in apply_music.TRACKS:
            print(f"{t['name']:<13}{t['world']:<10}{t['uuid']:<10}"
                  f"{t['duration']:>9.3f}{t['music_len']:>9.3f}"
                  f"{t['duration'] - t['music_len']:>8.3f}")
        print()
        if not args.track:
            print("用法：python import_track.py --track RZ_Egypt --src <视频> [--apply]")
        return 0

    if not args.src:
        print("❌ 缺少 --src")
        return 1

    t = pick_track(args.track)
    src = os.path.abspath(args.src)
    if not os.path.exists(src):
        print(f"❌ 源文件不存在：{src}")
        return 1
    dst = track_path(repo, t)

    # ---------- 1. 看源文件 ----------
    print(f"音轨：{t['name']}（world={t['world']}, uuid={t['uuid']}）")
    print(f"目标：{os.path.relpath(dst, repo)}")
    print()
    print("── 源文件 ──")
    si = _audio.probe(src)
    print(f"容器 {os.path.basename(src)}")
    print(f"  格式 {si['format_name']}　时长 {si['dur']:.3f}s　"
          f"音轨 {si['n_audio']} 条" + (f"　视频 {si['video']}" if si["has_video"] else ""))
    if not si["has_audio"]:
        print("❌ 这个文件里没有音频流，没法抽音频。")
        return 1
    print(f"  音频编码 {si['codec']}　{si['sr']} Hz　{si['ch']}ch　"
          f"{(si['br'] or 0) // 1000}k")

    # ---------- 2. 决定裁切窗口 ----------
    dur = si["dur"] or 0.0
    start = args.start or 0.0
    end = args.end if args.end is not None else None
    leading, trailing = _audio.silence_bounds(src)
    print()
    print("── 静音检测（阈值 -50dB）──")
    print(f"  开头静音 {leading:.3f}s　结尾静音 {trailing:.3f}s")
    if not args.no_trim:
        if args.start is None:
            if leading >= MIN_TRIM:
                start = leading
                print(f"  开头静音 ≥{MIN_TRIM}s，自动裁掉（--no-trim 可关）")
            else:
                print(f"  开头静音 <{MIN_TRIM}s，不值得裁（多半是编码器 padding）")
        if args.end is None:
            if trailing >= MIN_TRIM:
                end = dur - trailing
                print(f"  结尾静音 ≥{MIN_TRIM}s，自动裁掉（--no-trim 可关）")
            else:
                print(f"  结尾静音 <{MIN_TRIM}s，不值得裁")
    if args.start is not None:
        print(f"  --start 指定：从 {start:.3f}s 开始，不自动裁头")
    if args.end is not None:
        print(f"  --end 指定：到 {end:.3f}s 为止，不自动裁尾")

    new_dur = (end if end is not None else dur) - start
    if new_dur <= 1.0:
        print(f"❌ 裁完之后只剩 {new_dur:.3f}s，太短了。检查 --start / --end。")
        return 1

    # ---------- 3. 决定 musicLength ----------
    old_tail = t["duration"] - t["music_len"]
    if args.music_length is not None:
        new_len = args.music_length
        how = "--music-length 直接指定"
    elif args.full:
        new_len = new_dur
        how = "--full：整首都放到"
    elif args.tail is not None:
        new_len = new_dur - args.tail
        how = f"--tail 指定尾长 {args.tail}s"
    else:
        new_len = new_dur - old_tail
        how = f"沿用原尾长 {old_tail:.3f}s"
    new_len = max(0.5, round(new_len, 3))

    print()
    print("── 时长与循环点 ──")
    print(f"  实测时长   {t['duration']:>9.3f}  →  {new_dur:>9.3f}s"
          f"（{new_dur - t['duration']:+.3f}）")
    print(f"  循环点     {t['music_len']:>9.3f}  →  {new_len:>9.3f}s"
          f"（{new_len - t['music_len']:+.3f}）　{how}")
    print(f"  尾音       {old_tail:>9.3f}  →  {new_dur - new_len:>9.3f}s"
          "（这段在游戏里播不到，到点就切歌）")

    # ---------- 4. 跑闭环 ----------
    tmpdir = tempfile.mkdtemp(prefix="rz-import-")
    out = os.path.join(tmpdir, t["name"] + ".mp3")
    try:
        print()
        print(f"── 抽音频 + 对齐响度（目标 {args.target:+.1f} LUFS，峰值 ≤ "
              f"{args.ceiling:+.1f} dBFS）──")
        trim = (start, end) if (start > 0.001 or (end is not None
                                                  and end < dur - 0.001)) else None
        res = _audio.fit_to_target(
            src, out, target=args.target, ceiling=args.ceiling, spec=SPEC,
            tag=_audio.tag_title(t["name"]), trim=trim, stream=args.stream,
            method=args.method, log=print)
        before, after, info = res["before"], res["after"], res["info"]

        print()
        print("── 结果 ──")
        print(f"  响度   {before['I']:+.1f}  →  {after['I']:+.2f} LUFS"
              f"（目标 {args.target:+.1f}，差 {after['I'] - args.target:+.2f}）")
        print(f"  峰值   {before['peak']:+.2f}  →  {after['peak']:+.2f} dBFS")
        print(f"  规格   {info['codec']} {(info['br'] or 0) // 1000}k / "
              f"{info['sr']} Hz / {info['ch']}ch / {info['dur']:.3f}s")
        if res["gain_db"] is None:
            print(f"  方式   两遍 loudnorm linear（未改动态），"
                  f"{'已达标' if res['converged'] else '未达标'}")
        else:
            print(f"  增益   {res['gain_db']:+.2f} dB　限幅 {res['limit_db']:.2f} dB　"
                  f"{res['iterations']} 轮"
                  f"{'（已收敛）' if res['converged'] else '（未收敛）'}")

        warn = []
        if not res["converged"]:
            warn.append(f"响度未收敛到目标（实得 {after['I']:+.2f}）")
        if after["peak"] > args.ceiling + 0.15:
            warn.append(f"真峰值 {after['peak']:+.2f} 高于上限 {args.ceiling:+.1f}")
        if abs(new_dur - info["dur"]) > 0.05:
            warn.append(f"裁后时长 {new_dur:.3f} 与实际产物 {info['dur']:.3f} 差 "
                        f"{info['dur'] - new_dur:+.3f}s")

        if warn:
            print()
            for w in warn:
                print(f"  ⚠️ {w}")

        if not args.apply:
            print()
            print("（预览模式，没有改动任何文件。加 --apply 才会写回。）")
            print(f"   产物试听：{out}")
            # 预览也把产物留下来，方便先听一耳朵
            keep = os.path.join(tempfile.gettempdir(),
                                f"rz-import-preview-{t['name']}.mp3")
            shutil.copy2(out, keep)
            print(f"   已另存一份便于试听：{keep}")
            return 1 if warn else 0

        # ---------- 5. 备份 + 写入 ----------
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bdir = os.path.join(BACKUP_ROOT, stamp + "-import-" + t["name"])
        os.makedirs(bdir, exist_ok=True)
        rel = os.path.relpath(dst, repo)
        bpath = os.path.join(bdir, rel)
        os.makedirs(os.path.dirname(bpath), exist_ok=True)
        shutil.copy2(dst, bpath)
        tmpdst = dst + ".new"
        shutil.copy2(out, tmpdst)
        os.replace(tmpdst, dst)
        print()
        print(f"✅ mp3 已替换（原文件备份在 {bpath}）")

        # ---------- 6. 同步 apply_music.py ----------
        am = os.path.join(_HERE, "apply_music.py")
        new_line, old_line = patch_apply_music(am, t["name"],
                                               fmt_sec(info["dur"]),
                                               fmt_sec(new_len))
        if new_line:
            print(f"✅ apply_music.py 已更新（{t['name']}）")
            print(f"   旧：{old_line.strip()}")
            print(f"   新：{new_line.strip()}")
        else:
            print("·  apply_music.py 无需改动")

        # ---------- 7. 重建 import json + 校验 ----------
        py = sys.executable
        print()
        print("── 重建 import/*.json ──")
        r = subprocess.run([py, am, "--repo", repo, "--gen-import"],
                           capture_output=True)
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if t["name"] in line or "import" in line.lower():
                print("   " + line.strip())
        if r.returncode != 0:
            print("   ⚠️ 重建失败：")
            print(r.stdout.decode("utf-8", "replace")[-600:])
            print(r.stderr.decode("utf-8", "replace")[-600:])

        print()
        print("── 最终校验 ──")
        r = subprocess.run([py, am, "--repo", repo, "--verify"],
                           capture_output=True)
        tail = r.stdout.decode("utf-8", "replace")
        print("   " + "\n   ".join(tail.strip().splitlines()[-8:]))

        print()
        if warn or r.returncode != 0:
            print("⚠️ 有告警，建议先跑 audio_report.py 复核再提交。")
            return 1
        print("完成。建议随后跑一次体检：")
        print("  python tools/music-patch/audio_report.py --repo D:/git/pvzge_web")
        return 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
