#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_audio.py —— RZ 音轨的共享音频工具（ffmpeg 定位 / 探测 / 响度 / 转码）。

这是**库**，不是命令行工具：自己不打印任何东西，由调用方决定怎么呈现。

统一规格（HOUSE）
-----------------
对齐仓库里已经统一过的三条（Egypt / Pirate / Beach）：**160 kbps / 48 kHz / 立体声**。
响度目标 -14.8 LUFS、真峰值上限 -1.0 dBFS —— 也是从那三条量出来的。

两个关键量（改音频前必须先懂）
------------------------------
* `duration`   —— 音频真实时长，写进 import/*.json 的 `_duration`。
* `musicLength` —— **循环/切歌点**。index.js 里是
  `currentTime >= musicLength && changeLoopPlayer()`（钢琴曲更是直接 `currentTime=0`）。
  所以 (duration - musicLength) 是**永远播不到的尾音**（渐弱+静音）。
  ⇒ 换音频后这两个数必须一起改，否则音乐会提前切断、或者永远等不到切歌点。
"""

import os
import re
import shutil
import subprocess

# ---- 统一规格 -------------------------------------------------------------
SPEC = {
    "codec": "libmp3lame",
    "br": "160k",        # 参考 Egypt/Pirate/Beach（自制的那三条）
    "sr": 48000,         # 参考同上（现有集合里混了 44.1k / 32k）
    "ch": 2,
    "vp": 3,             # id3v2.3，兼容性最好
}

# ---- 响度基准 -------------------------------------------------------------
# ⚠️ 这两个数是**已固化的项目约定**，别按"测出来的中位数"自己改：
#   目标 I = -14.5 LUFS、TP = -0.5 dBFS，对齐的是**官方 UB_* 音轨**
#   （UB 均值 ≈ -14.2，UB_Egypt -14.6）。见 tools/README.md 第九节。
TARGET_LUFS = -14.5
TARGET_TP_DB = -0.5
TARGET_LRA = 11          # loudnorm 的 LRA 目标，沿用既有脚本

# 成品 MP3 的 ID3 标签约定（既有做法，便于回溯来源）
TAG_ALBUM = "PvZ2 GE Mod"


def tag_title(name):
    return f"{name} (MiniGame_C, loud-matched)"


# 限幅器的实际限值要比目标峰值再低一点 —— alimiter 管的是**采样峰值**，
# 而 ebur128 的 peak=true 量的是**真峰值**（含交织点）。实测编完再解码，
# 真峰值会比限值高出 ~0.2~0.3 dB，所以先把限值压下来补偿掉。
# 只对 gain-limit 方法有用；loudnorm 自己就是真峰值感知的，不需要额外余量。
LIMIT_MARGIN_DB = 0.3

# 判定"这个增益会不会顶破上限"的容差
TP_EPS = 0.05

RE_I = re.compile(r"^\s*I:\s*(-?[\d.]+)\s*LUFS", re.M)
RE_LRA = re.compile(r"^\s*LRA:\s*(-?[\d.]+)\s*LU", re.M)
RE_PEAK = re.compile(r"^\s*Peak:\s*(-?[\d.]+)\s*dBFS", re.M)
RE_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
RE_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")
# loudnorm 第一遍吐出的那坨 JSON（夹在 stderr 里）
RE_LN_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class AudioError(Exception):
    pass


# --------------------------------------------------------------------------
# 工具定位
# --------------------------------------------------------------------------
def find_tool(name):
    """找 ffmpeg / ffprobe：先 PATH，再 winget 的 Links 目录 —— winget 装的
    默认不在 PATH 里（或是 .EXE 大写后缀），这里一并兜住。"""
    p = shutil.which(name)
    if p:
        return p
    la = os.environ.get("LOCALAPPDATA", "")
    dirs = [os.path.join(la, "Microsoft", "WinGet", "Links") if la else None,
            r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"]
    for d in dirs:
        if not d:
            continue
        for ext in (".exe", ".EXE", ""):
            cand = os.path.join(d, name + ext)
            if os.path.exists(cand):
                return cand
    return None


def require_tools():
    """返回 (ffmpeg, ffprobe)；缺任何一个就抛 AudioError。"""
    ff, fp = find_tool("ffmpeg"), find_tool("ffprobe")
    if not ff or not fp:
        raise AudioError(
            "找不到 ffmpeg / ffprobe。安装：winget install Gyan.FFmpeg\n"
            "  （winget 装完可能不在 PATH，本模块会自动去 "
            "%LOCALAPPDATA%\\Microsoft\\WinGet\\Links 找）")
    return ff, fp


def run(cmd):
    """跑一条命令，返回 (返回码, stdout, stderr)，都按 utf-8 + replace 解。"""
    p = subprocess.run(cmd, capture_output=True)
    return (p.returncode,
            p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# 探测
# --------------------------------------------------------------------------
def probe(path):
    """ffprobe 拿编码参数 + 实际时长 + 是否含音频流 + 是否含视频流。"""
    ff, fp = require_tools()
    cmd = [fp, "-v", "error",
           "-show_entries",
           "stream=index,codec_type,codec_name,sample_rate,channels,bit_rate,"
           "width,height",
           "-show_entries", "format=duration,bit_rate,format_name",
           "-of", "json", path]
    rc, out, err = run(cmd)
    if rc != 0:
        raise AudioError(f"ffprobe 失败（{os.path.basename(path)}）：{(err or out).strip()[:300]}")
    try:
        import json as _json
        data = _json.loads(out)
    except Exception as ex:
        raise AudioError(f"ffprobe 输出无法解析：{ex}") from None

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    vstreams = [s for s in streams if s.get("codec_type") == "video"]
    a = astreams[0] if astreams else {}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "path": path,
        "format_name": fmt.get("format_name"),
        "dur": num(fmt.get("duration")),
        "br_fmt": num(fmt.get("bit_rate")),
        "has_audio": bool(astreams),
        "has_video": bool(vstreams),
        "n_audio": len(astreams),
        "codec": a.get("codec_name"),
        "sr": int(num(a.get("sample_rate")) or 0) or None,
        "ch": a.get("channels"),
        "br": int(num(a.get("bit_rate")) or 0) or None,
        "video": ("%sx%s" % (vstreams[0].get("width"), vstreams[0].get("height")))
                 if vstreams else None,
    }


# --------------------------------------------------------------------------
# 响度（EBU R128）
# --------------------------------------------------------------------------
def measure_loudness(path, prefilter=None):
    """用 ebur128 量完整响度：I（LUFS）/ LRA（LU）/ 真峰值（dBFS）。

    prefilter —— 先套一层滤镜再量（比如 atrim 掐掉静音段）。
                 视频开头几秒静音会被算进整轨平均，**必须先裁再量**，
                 否则测出来的响度偏低、后面的增益就白加了。

    ebur128 的报告打在 stderr，且只在默认日志级别（info）下输出 ——
    `-v error` 会把它吞掉，所以这里**不能**加 -v。
    """
    ff, _ = require_tools()
    chain = (prefilter + "," if prefilter else "") + "ebur128=peak=true"
    cmd = [ff, "-hide_banner", "-nostats", "-i", path, "-af", chain,
           "-f", "null", "-"]
    rc, out, err = run(cmd)
    if rc != 0:
        raise AudioError(f"ebur128 失败：{(err or out).strip()[-300:]}")
    mi, ml, mp = RE_I.search(err), RE_LRA.search(err), RE_PEAK.search(err)

    def g(m):
        return float(m.group(1)) if m else None

    res = {"I": g(mi), "lra": g(ml), "peak": g(mp)}
    if res["I"] is None:
        raise AudioError("ebur128 没输出 Integrated loudness（音频可能是纯静音）")
    return res


# --------------------------------------------------------------------------
# 静音边界
# --------------------------------------------------------------------------
def silence_bounds(path, noise="-50dB", min_dur=0.25):
    """找首尾静音长度。返回 (leading_sec, trailing_sec)。

    循环曲最怕开头有静音 —— 每次循环都听得见一次空白。
    silencedetect 的 silence_start/end 是**配对**出现的，但纯静音文件可能只有 start，
    所以这里按顺序扫、容忍缺尾巴。
    """
    ff, _ = require_tools()
    info = probe(path)
    dur = info["dur"] or 0.0
    cmd = [ff, "-hide_banner", "-nostats", "-i", path,
           "-af", f"silencedetect=noise={noise}:d={min_dur}", "-f", "null", "-"]
    rc, out, err = run(cmd)
    if rc != 0:
        raise AudioError(f"silencedetect 失败：{(err or out).strip()[-300:]}")

    leading = 0.0
    trailing = 0.0
    pending = None
    for line in err.splitlines():
        m = RE_SIL_START.search(line)
        if m:
            pending = float(m.group(1))
            continue
        m = RE_SIL_END.search(line)
        if m and pending is not None:
            s, e = pending, float(m.group(1))
            if s <= 0.05:                      # 从 0 开始的静音 = 开头静音
                leading = max(leading, e)
            pending = None
    # 末尾静音：最后一段没等到 silence_end，或者它的 end 贴着文件尾巴
    if pending is not None and dur and pending >= dur - 0.5:
        trailing = dur - pending
    elif dur:
        # 用最后一条 silence_end 反推：若它之后到结尾都很安静，则整段算尾静音
        last_end = None
        for m in RE_SIL_END.finditer(err):
            last_end = float(m.group(1))
        if last_end is not None and dur - last_end < 0.5 and last_end > 1.0:
            # 找到该 end 对应的 start
            starts = [float(x.group(1)) for x in RE_SIL_START.finditer(err)]
            cand = [s for s in starts if s < last_end]
            if cand:
                trailing = dur - cand[-1]
    return round(leading, 3), round(trailing, 3)


# --------------------------------------------------------------------------
# 响度对齐的增益计划
# --------------------------------------------------------------------------
def gain_plan(I, peak, target=TARGET_LUFS, ceiling=TARGET_TP_DB, limiter_budget=6.0):
    """算出对齐目标响度所需的增益，以及要不要限幅。

    纯增益是**线性**的，所以峰值也平移同样的 dB —— 数学上是精确的，
    不需要跑 loudnorm 两遍。只有当"平移后峰值会顶破上限"时才引入限幅，
    这样最大程度保留原曲动态（限幅只削掉那几个越界的峰）。

    返回 dict(gain_db, need_limit, limiter_db, mode)。
    """
    gain = round(target - I, 2)
    new_peak = peak + gain
    need = new_peak > ceiling + TP_EPS
    return {
        "gain_db": gain,
        "need_limit": need,
        "limiter_db": round(new_peak - ceiling, 2) if need else 0.0,
        "over_budget": need and (new_peak - ceiling) > limiter_budget,
        "new_peak_if_gain": round(new_peak, 2),
        "mode": "增益 + 限幅" if need else "纯增益",
    }


def db2lin(db):
    return 10.0 ** (db / 20.0)


# --------------------------------------------------------------------------
# 响度对齐：两条路线
# --------------------------------------------------------------------------
def ln_measure(src, target=TARGET_LUFS, ceiling=TARGET_TP_DB, lra=TARGET_LRA,
               prefilter=None):
    """loudnorm 的第一遍：量出 measured_* 与 target_offset。

    注意这是 **loudnorm 自己的**测量（和 ebur128 的 I 口径略有差别），
    第二遍必须原样回填这几个数，否则 results 对不上。
    """
    ff, _ = require_tools()
    chain = (prefilter + "," if prefilter else "") + \
        f"loudnorm=I={target}:TP={ceiling}:LRA={lra}:print_format=json"
    cmd = [ff, "-hide_banner", "-nostats", "-i", src, "-af", chain,
           "-f", "null", "-"]
    rc, out, err = run(cmd)
    if rc != 0:
        raise AudioError(f"loudnorm 第一遍失败：{(err or out).strip()[-300:]}")
    m = RE_LN_JSON.search(err)
    if not m:
        raise AudioError("loudnorm 第一遍没吐出 JSON（音频可能全是静音）")
    try:
        import json as _json
        d = _json.loads(m.group(0))
    except Exception as ex:
        raise AudioError(f"loudnorm JSON 解析失败：{ex}") from None
    need = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    for k in need:
        if k not in d:
            raise AudioError(f"loudnorm JSON 缺字段 {k}")
    return d


def ln_filter(meas, target=TARGET_LUFS, ceiling=TARGET_TP_DB, lra=TARGET_LRA):
    """拼出第二遍要用的 loudnorm 滤镜串（linear=true，即"整轨单增益"，不改动态）。"""
    return ("loudnorm=I={I}:TP={TP}:LRA={LRA}"
            ":measured_I={mi}:measured_TP={mt}:measured_LRA={ml}"
            ":measured_thresh={mth}:offset={off}:linear=true").format(
        I=target, TP=ceiling, LRA=lra,
        mi=meas["input_i"], mt=meas["input_tp"], ml=meas["input_lra"],
        mth=meas["input_thresh"], off=meas["target_offset"])


def fit_to_target(src, dst, target=TARGET_LUFS, ceiling=TARGET_TP_DB, spec=None,
                  tag=None, trim=None, method="loudnorm", max_iter=3, damping=0.9,
                  tol=0.2, log=None, stream=None, album=TAG_ALBUM):
    """把 src 处理成"响度对齐 target、真峰值不超 ceiling"的 mp3，写到 dst。

    两种方法：

    * `method="loudnorm"`（**默认，沿用项目既有做法**）
      两遍 loudnorm + `linear=true`：整轨只施加一个线性增益，**完全不改动态**。
      代价是：源本身的峰值余量不够时，增益会被 TP 上限压住，最后**打不到 target**
      （既有那三条 Egypt/Pirate/Beach 就是这样落在 -14.8 的）。这是刻意保留的行为。
    * `method="gain-limit"`
      线性增益 + 一级 `alimiter` 限幅。能真正打到 target，代价是要削掉几个越界的峰。
      想要"整套严格对齐到同一水平"时用这条。

    注意 `trim` 若生效，两者都会**先裁再量** —— 开头静音会把整轨平均拉低，
    不先裁就量出一个偏低的响度，增益加完还是不够响。

    返回：dict(method, gain_db, limit_db, iterations, converged, before, after,
               info, ln)
    """
    def say(s):
        if log:
            log(s)

    if method not in ("loudnorm", "gain-limit"):
        raise AudioError(f"未知 method：{method}")

    # 裁切时先造出 prefilter 串，供"裁完再量"用
    pre = None
    if trim:
        dur = probe(src)["dur"] or 0.0
        st = trim[0] or 0.0
        en = trim[1] if trim[1] is not None else dur
        if st > 0.001 or en < dur - 0.001:
            pre = f"atrim=start={st:.3f}:end={en:.3f},asetpts=PTS-STARTPTS"
            say(f"      裁切：{st:.3f}s → {en:.3f}s（去掉 {st:.3f}s 头 / "
                f"{max(0.0, dur - en):.3f}s 尾）")

    before = measure_loudness(src, prefilter=pre)

    # ---------------- 路线一：两遍 loudnorm（既有做法） ----------------
    if method == "loudnorm":
        meas = ln_measure(src, target, ceiling, TARGET_LRA, prefilter=pre)
        say(f"      loudnorm 测量：I={meas['input_i']} TP={meas['input_tp']} "
            f"LRA={meas['input_lra']} thresh={meas['input_thresh']} "
            f"offset={meas['target_offset']}")
        if abs(float(meas["target_offset"])) > 1.0:
            say(f"      ⚠️ target_offset 绝对值 >1（{meas['target_offset']}），"
                f"linear 模式很难打准目标")
        encode(src, dst, trim=trim, spec=spec, tag=tag, stream=stream,
               album=album, loudnorm=ln_filter(meas, target, ceiling, TARGET_LRA))
        after = measure_loudness(dst)
        err = target - after["I"]
        say(f"      编码后 → {after['I']:+.2f} LUFS / 峰值 {after['peak']:+.2f} "
            f"dBFS（与目标差 {err:+.2f}）")
        if after["peak"] > ceiling + 0.15:
            say(f"      ⚠️ 真峰值 {after['peak']:+.2f} 超过上限 {ceiling:+.2f}"
                "（MP3 编解码会产生 0.2~0.3 dB 过冲）")
        return {"method": method, "gain_db": None, "limit_db": None,
                "iterations": 1, "converged": abs(err) <= 0.5, "ln": meas,
                "before": before, "after": after, "info": probe(dst)}

    # ---------------- 路线二：增益 + 限幅（闭环） ----------------
    # 限幅器的限值：目标峰值再压掉一点，抵掉采样峰值→真峰值的那点差
    lim_ceiling = round(ceiling - LIMIT_MARGIN_DB, 3)
    gain = round(target - before["I"], 2)
    best = None
    it = 0

    for it in range(1, max_iter + 1):
        limit = max(0.0, round(before["peak"] + gain - lim_ceiling, 2))
        encode(src, dst, gain_db=gain, limit_db=limit, trim=trim, spec=spec,
               tag=tag, stream=stream, album=album, limit_ceiling=lim_ceiling)
        after = measure_loudness(dst)
        err = target - after["I"]
        say(f"      第{it}轮 增益{gain:+.2f}dB 限幅{limit:.2f}dB → "
            f"{after['I']:+.2f} LUFS / 峰值 {after['peak']:+.2f} dBFS"
            f"（差 {err:+.2f}）")
        if best is None or abs(err) < abs(best["err"]):
            best = {"gain_db": gain, "limit_db": limit, "err": err, "after": after}
        if abs(err) <= tol:
            return dict(best, method=method, iterations=it, converged=True,
                        ln=None, before=before, info=probe(dst))
        gain = round(gain + err * damping, 2)
    else:
        # 没收敛：退回误差最小的那一轮，按它的误差再修正一次增益
        gain = round(best["gain_db"] + best["err"], 2)
        limit = max(0.0, round(before["peak"] + gain - lim_ceiling, 2))
        encode(src, dst, gain_db=gain, limit_db=limit, trim=trim, spec=spec,
               tag=tag, stream=stream, album=album, limit_ceiling=lim_ceiling)
        after = measure_loudness(dst)
        say(f"      未收敛，取最佳增益 {gain:+.2f}dB 收尾 → {after['I']:+.2f} LUFS")
        return {"method": method, "gain_db": gain, "limit_db": limit,
                "err": target - after["I"], "after": after, "iterations": it,
                "converged": False, "ln": None, "before": before,
                "info": probe(dst)}


# --------------------------------------------------------------------------
# 转码
# --------------------------------------------------------------------------
def encode(src, dst, gain_db=0.0, limit_db=0.0, trim=None, spec=None,
           tag=None, extra_in=None, limit_ceiling=None, stream=None,
           loudnorm=None, album=None):
    """把 src 转成统一规格的 mp3 写到 dst。

    gain_db       —— 整轨线性增益（dB）
    limit_db      —— >0 时加一级真峰值限幅
    limit_ceiling —— 限幅器的实际限值（dBFS），默认 TARGET_TP_DB。
                     注意 alimiter 限的是**采样峰值**，要比目标真峰值再低一点，
                     调用方（fit_to_target）会传 ceiling - LIMIT_MARGIN_DB。
    loudnorm      —— 直接给一条 loudnorm 滤镜串（两遍法的第二遍）。
                     给了它就忽略 gain_db / limit_db —— 两条路线互斥。
    trim          —— (起始秒, 结束秒) **绝对秒**；None 表示不裁/到结尾。
                     用来去首尾静音，或从视频里截取某一段。
    tag / album   —— 写进 ID3（沿用既有约定，便于回溯来源）
    extra_in      —— 追加在 -i 之前的输入参数（如 -ss）
    stream        —— 指定音频流下标（视频里有多条音轨时用，如 `0:a:1`）
    """
    ff, _ = require_tools()
    sp = dict(SPEC)
    if spec:
        sp.update(spec)
    if limit_ceiling is None:
        limit_ceiling = TARGET_TP_DB

    # 信号链顺序有讲究：先掐头尾（不然响度测量和增益都被静音稀释），
    # 再做响度处理（loudnorm 或 增益+限幅，限幅必须最后一道）。
    chain = []
    if trim:
        dur = probe(src)["dur"] or 0.0
        st = trim[0] or 0.0
        en = trim[1] if trim[1] is not None else dur
        if st > 0.001 or en < dur - 0.001:
            # 用 atrim 而不是 -ss/-t：只动音频采样，不依赖容器时间戳，更稳。
            chain.append(f"atrim=start={st:.3f}:end={en:.3f}")
            chain.append("asetpts=PTS-STARTPTS")  # 重排时间戳，否则播放器时间轴错乱
    if loudnorm:
        chain.append(loudnorm)
    else:
        if abs(gain_db) > 0.001:
            chain.append(f"volume={gain_db}dB")
        if limit_db > 0.001:
            # level=disabled 很关键：默认 alimiter 会把输出自动抬到 0dB，毁掉我们的增益
            chain.append(f"alimiter=limit={db2lin(limit_ceiling):.6f}:level=disabled")

    cmd = [ff, "-y", "-hide_banner", "-nostats", "-loglevel", "error"]
    if extra_in:
        cmd += extra_in
    cmd += ["-i", src]
    if chain:
        cmd += ["-af", ",".join(chain)]
    if stream:
        cmd += ["-map", stream]
    cmd += ["-map_metadata", "-1", "-vn", "-ar", str(sp["sr"]), "-ac", str(sp["ch"]),
            "-c:a", sp["codec"], "-b:a", sp["br"],
            "-id3v2_version", str(sp["vp"])]
    if tag:
        cmd += ["-metadata", f"title={tag}"]
    if album:
        cmd += ["-metadata", f"album={album}"]
    cmd += [dst]
    rc, out, err = run(cmd)
    if rc != 0:
        raise AudioError(f"转码失败：{(err or out).strip()[-400:]}")
    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise AudioError("转码后产物不存在或为空")
    return dst
