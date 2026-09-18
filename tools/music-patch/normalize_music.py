#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_music.py —— 把 RZ 音轨的**响度和峰值**对齐到同一把尺子。

为什么要有它（先看清事实再决定要不要用）
----------------------------------------
先把"不统一"这件事查清楚，结论和直觉相反：

* 13 条 RZ 音轨里，**只有 3 条是换过的**（RZ_Egypt / RZ_Pirate / RZ_Beach）；
* 其余 **10 条与官方 UB_* 原曲逐字节相同**（PCM md5 一一对上），
  它们本来就不是"没统一"，而是**原样保留了官方母带的响度**；
* 官方那套 UB_* 本身跨曲就差得很开（约 -10.5 ~ -17.7 LUFS），
  所以这 10 条的差异是**官方设计**，不是事故。

⇒ 真正要动的只有那 3 条换过的。它们在换入时已经对齐到
   **-14.5 LUFS / TP -0.5 dBFS**（口径见下），实测落在 -14.8，彼此一致。

**默认不要 `--apply` 全量**：那会把 10 条官方字节级一致的曲子重新编码，
既有代际损失，又偏离官方规格。要动请用 `--tracks` 点名。

对齐口径（沿用项目既有做法，参照官方 UB 集）
--------------------------------------------
    响度  -14.5 LUFS      峰值  ≤ -0.5 dBFS
    160 kbps / 48 kHz / 立体声

两种方式（`--method`）：

* `loudnorm`（**默认**）：两遍 loudnorm + `linear=true`，整轨只加一个线性增益，
  **完全不改动态** —— 与既有 3 条完全同法。代价是源峰值余量不足时会被 TP 上限
  压住、打不到 -14.5 就停在 -14.8 附近，属**刻意保留**的既有行为。
* `gain-limit`：线性增益 + 一级 `alimiter` 限幅，配闭环重测，
  能真正打到目标（±0.2 LU），代价是削掉几个越界峰。要"严格同一水平"时用。

用法
----
    python normalize_music.py --dry-run              # 只看计划，不动文件（默认）
    python normalize_music.py --apply --tracks RZ_Egypt,RZ_Pirate,RZ_Beach
    python normalize_music.py --apply --tracks RZ_Dark --method gain-limit
    python normalize_music.py --restore latest        # 从最近备份整批回滚

退出码：0 成功 / 1 有失败 / 2 环境缺 ffmpeg
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
import _console_utf8  # noqa: E402,F401

sys.path.insert(0, _HERE)
import _audio  # noqa: E402
import apply_music  # noqa: E402

# 收敛判据（两个容差用途不同，别混）
I_TOL = 0.2          # 闭环迭代的收敛阈值（LUFS）
SKIP_TOL = 0.5       # "是否算达标、能不能跳过"的阈值 —— 与 audio_report 的
                     # LUFS_TOLERANCE 保持一致。注意既有那 3 条自制轨落在 -14.8，
                     # 是 loudnorm-linear 被 TP 上限压住的**既定结果**，不是偏差，
                     # 所以这里不能用 0.2 去判它"需要修"。
PEAK_TOL = 0.15      # 峰值超上限多少以内算可接受（MP3 编解码过冲量级）
MAX_ITER = 3
DAMPING = 0.9        # 误差回灌时的阻尼，防止来回震荡

# 备份默认落在仓库**外面** —— 放仓库里会污染 git status
DEFAULT_BACKUP_ROOT = os.path.join(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(),
    "pvzge_web-audio-backup")


def track_path(repo, t):
    sub = t["uuid"][:2]
    return os.path.join(repo, "docs", "assets", "resources", "native", sub,
                        t["uuid"] + ".mp3")


# 官方初始 musicLength —— 与 rz_map_check.py / audio_report.py 同一套口径。
# 被替换过会被改成实际循环点（如 182.5），据此判定"自制 / 官方原声"。
ORIGINAL_LEN = {"RZ_Victory": 3}
DEFAULT_LEN = 181


def is_self(t):
    """True = 被替换过的自制轨（要统一的对象）；False = 官方原声（别动）。"""
    return t["music_len"] != ORIGINAL_LEN.get(t["name"], DEFAULT_LEN)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def needs_work(info, loud, target, ceiling, spec):
    """已经达标就不动 —— 重新编码是有代际损失的，能省一次就省一次。"""
    why = []
    if abs(loud["I"] - target) > SKIP_TOL:
        why.append(f"响度 {loud['I']:+.1f} LUFS（差 {loud['I'] - target:+.1f}）")
    if loud["peak"] > ceiling + PEAK_TOL:
        why.append(f"峰值 {loud['peak']:+.1f} dBFS 超上限")
    if info.get("br") and abs((info["br"] or 0) - int(spec["br"].rstrip("k")) * 1000) > 8000:
        why.append(f"码率 {(info['br'] or 0) // 1000}k")
    if info.get("sr") and info["sr"] != spec["sr"]:
        why.append(f"采样率 {info['sr']}")
    if info.get("ch") and info["ch"] != spec["ch"]:
        why.append(f"{info['ch']} 声道")
    return why


def fit(repo, t, src, target, ceiling, spec, tmpdir, log, method):
    """把一条轨对齐到 target。返回 (产物路径, 处理结果)。

    真正的对齐逻辑在 _audio.fit_to_target（import_track.py 也用它）。
    """
    out = os.path.join(tmpdir, t["name"] + ".mp3")
    res = _audio.fit_to_target(src, out, target=target, ceiling=ceiling,
                               spec=spec, tag=_audio.tag_title(t["name"]),
                               method=method, max_iter=MAX_ITER,
                               damping=DAMPING, tol=I_TOL, log=log)
    return out, res


def main():
    ap = argparse.ArgumentParser(description="RZ 音轨响度/规格统一")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(_HERE)))
    ap.add_argument("--apply", action="store_true", help="真的写回文件（默认只预览）")
    ap.add_argument("--dry-run", action="store_true", help="预览（默认行为，可显式写）")
    ap.add_argument("--tracks", help="逗号分隔的音轨名，默认只取自制轨")
    ap.add_argument("--include-official", action="store_true",
                    help="连官方原声一起处理（默认排除；官方差异是母带设计）")
    ap.add_argument("--target", type=float, default=_audio.TARGET_LUFS)
    ap.add_argument("--ceiling", type=float, default=_audio.TARGET_TP_DB)
    ap.add_argument("--method", choices=("loudnorm", "gain-limit"),
                    default="loudnorm",
                    help="loudnorm=两遍线性（既有做法，不改动态，可能打不到目标）；"
                         "gain-limit=增益+限幅（能打准，代价是削峰）")
    ap.add_argument("--backup-root", default=DEFAULT_BACKUP_ROOT)
    ap.add_argument("--restore", metavar="BACKUP_DIR",
                    help="从备份目录整批回滚（给 'latest' 用最近一次）")
    args = ap.parse_args()

    try:
        _audio.require_tools()
    except _audio.AudioError as ex:
        print(f"❌ {ex}")
        return 2

    repo = os.path.abspath(args.repo)
    spec = {"br": "160k", "sr": 48000, "ch": 2}

    # ---------------- 回滚 ----------------
    if args.restore:
        bdir = args.backup_root
        if args.restore != "latest":
            bdir = args.restore
        elif os.path.isdir(bdir):
            subs = sorted(d for d in os.listdir(bdir)
                          if os.path.isdir(os.path.join(bdir, d)))
            if not subs:
                print(f"❌ {bdir} 下没有备份")
                return 1
            bdir = os.path.join(bdir, subs[-1])
        mf = os.path.join(bdir, "manifest.json")
        if not os.path.exists(mf):
            print(f"❌ 找不到 {mf}")
            return 1
        with open(mf, encoding="utf-8") as f:
            man = json.load(f)
        print(f"从 {bdir} 回滚 {len(man['files'])} 个文件")
        for rec in man["files"]:
            src = os.path.join(bdir, rec["rel"])
            dst = os.path.join(repo, rec["rel"])
            if not os.path.exists(src):
                print(f"   ✗ 备份缺失 {rec['rel']}")
                continue
            shutil.copy2(src, dst)
            print(f"   ✓ {rec['rel']}")
        print("\n✅ 回滚完成")
        return 0

    # ---------------- 选轨 ----------------
    want = None
    if args.tracks:
        want = {s.strip() for s in args.tracks.split(",") if s.strip()}
    tracks = [t for t in apply_music.TRACKS if not want or t["name"] in want]
    if want:
        unknown = want - {t["name"] for t in apply_music.TRACKS}
        for u in sorted(unknown):
            print(f"⚠️  未知音轨名：{u}")

    # ---- 来源护栏：默认不碰官方原声 ----
    # 那 10 条与官方 UB 同源，它们的响度差是**官方母带设计**，重编码只会
    # 既偏离官方又叠一代损失。只有被替换过的"自制轨"才是要统一的对象。
    # 显式 --tracks 点名 = 用户自己决定；否则默认只取自制备份。
    offi = [t for t in tracks if not is_self(t)]
    if want:
        if offi:
            print(f"⚠️  你点名的轨道里有 {len(offi)} 条是官方原声："
                  f"{', '.join(t['name'] for t in offi)}")
            print("    （官方母带差异，重编码会偏离官方并叠加代际损失 —— 确认要动再加 --apply）")
    elif args.include_official:
        print(f"（含官方原声 {len(offi)} 条，因为指定了 --include-official）")
    elif offi:
        tracks = [t for t in tracks if is_self(t)]
        print(f"（已排除 {len(offi)} 条官方原声，只处理自制轨 {len(tracks)} 条；"
              f"要一并处理加 --include-official）")

    mode = "应用" if args.apply else "预览（不会改任何文件）"
    print(f"仓库：{repo}")
    print(f"目标：{args.target:+.1f} LUFS ｜ 峰值上限 {args.ceiling:+.1f} dBFS ｜ "
          f"{spec['br']} / {spec['sr']} Hz / {spec['ch']}ch")
    print(f"模式：{mode}　共 {len(tracks)} 条")
    print()

    lines = []
    todo = []

    def log(s):
        print(s)

    for t in tracks:
        p = track_path(repo, t)
        if not os.path.exists(p):
            print(f"✗ {t['name']:<13} 文件缺失：{os.path.relpath(p, repo)}")
            continue
        info = _audio.probe(p)
        loud = _audio.measure_loudness(p)
        why = needs_work(info, loud, args.target, args.ceiling, spec)
        cur = (f"I={loud['I']:+.1f} LUFS  峰值={loud['peak']:+.2f}  "
               f"{(info.get('br') or 0) // 1000}k/{info.get('sr')}Hz/{info.get('ch')}ch")
        if not why:
            print(f"✓ {t['name']:<13} {cur}   已达标")
            lines.append({"name": t["name"], "action": "skip"})
            continue
        print(f"· {t['name']:<13} {cur}")
        print(f"      原因：{'；'.join(why)}")
        lines.append({"name": t["name"], "action": "fit", "why": why,
                      "before": {"I": loud["I"], "peak": loud["peak"],
                                 "br": info.get("br"), "sr": info.get("sr")}})
        todo.append(t)

    print()
    if not todo:
        print("✅ 全部已达标，无需改动。")
        return 0

    if not args.apply:
        print(f"── 预览：{len(todo)} 条需要处理 ──")
        print("   加 --apply 才会真正写回（写回前会自动备份到仓库外）。")
        print(f"   例：python {os.path.basename(__file__)} --apply")
        return 0

    # ---------------- 备份 ----------------
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(args.backup_root, stamp)
    os.makedirs(bdir, exist_ok=True)
    man = {"repo": repo, "created": stamp, "target": args.target,
           "ceiling": args.ceiling, "spec": spec, "files": []}

    tmpdir = tempfile.mkdtemp(prefix="rz-norm-")
    ok, bad = [], []
    try:
        print(f"── 处理 {len(todo)} 条（备份 → {bdir}）──")
        # 先把所有产物都算出来，全部成功才动原文件 —— 避免改一半留下不一致状态
        for t in todo:
            p = track_path(repo, t)
            rel = os.path.relpath(p, repo)
            rec = {"rel": rel, "sha256": sha256(p)}
            bpath = os.path.join(bdir, rel)
            os.makedirs(os.path.dirname(bpath), exist_ok=True)
            shutil.copy2(p, bpath)
            man["files"].append(rec)

            print(f"· {t['name']}")
            out, res = fit(repo, t, p, args.target, args.ceiling, spec, tmpdir,
                           print, args.method)
            before, after = res["before"], res["after"]
            new_info = res["info"]
            rec.update({"before_I": before["I"], "before_peak": before["peak"],
                        "after_I": after["I"], "after_peak": after["peak"],
                        "gain_db": res["gain_db"], "limit_db": res["limit_db"],
                        "iterations": res["iterations"],
                        "converged": res["converged"]})
            if after["peak"] > args.ceiling + 0.15:
                print(f"      ⚠️ 峰值 {after['peak']:+.2f} 仍高于上限 {args.ceiling:+.1f}")
                bad.append(t["name"])
            elif not res["converged"]:
                print(f"      ⚠️ 响度未收敛到 {args.target:+.1f}（实得 {after['I']:+.2f}）")
                bad.append(t["name"])
            else:
                ok.append(t["name"])
            print(f"      ⇒ {after['I']:+.2f} LUFS / 峰值 {after['peak']:+.2f} dBFS ｜ "
                  f"{int((new_info['br'] or 0)) // 1000}k/{new_info['sr']}Hz/"
                  f"{new_info['ch']}ch ｜ 时长 {new_info['dur']:.3f}s")
            # 落盘（同目录临时名 + os.replace，避免半截文件）
            tmpdst = p + ".new"
            shutil.copy2(out, tmpdst)
            os.replace(tmpdst, p)

        with open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(man, f, ensure_ascii=False, indent=2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    print(f"✅ 完成 {len(ok)} 条" + (f"，{len(bad)} 条有告警：{', '.join(bad)}" if bad else ""))
    print(f"   备份：{bdir}")
    print(f"   回滚：python {os.path.basename(__file__)} --restore latest")
    print()
    print("   下一步：跑一次体检确认收敛 ——")
    print("   python tools/music-patch/audio_report.py --repo D:/git/pvzge_web")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
