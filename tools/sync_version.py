#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本号单一真源 + 分发同步。

为什么需要它：五个 exe 的版本号来自 **4 个彼此独立的配置点**，
手改必然漂移（历史上就是这么漂的：Tauri 是 0.14.0，两个 .NET 项目是 1.0.0）：

    tools/tauri-app/src-tauri/tauri.conf.json      "version"
    tools/tauri-app/src-tauri/Cargo.toml           [package] version
    tools/tauri-app/src-tauri/Cargo.lock           本包条目（免得构建后变脏）
    tools/launcher/src/PvZGE-Launcher.csproj       Version/FileVersion/...
    tools/webserver/src/PvZGE-WebServer.csproj     Version/FileVersion/...

本脚本把「上游版本」当唯一真源，其余全部由它派生 —— 所以每次构建前跑一次，
就等于版本永远跟着上游走（上游发 0.15，下次构建出来的 5 个 exe 就都是 0.15）。

用法（默认 = 从 docs/index.html 探测并写入，可直接跑）:
    python tools/sync_version.py                 # 自动探测 + 写入（构建时的默认行为）
    python tools/sync_version.py --print         # 只打印各处当前值
    python tools/sync_version.py --value         # 只输出解析到的版本号本身（脚本用）
    python tools/sync_version.py --check         # 只校验是否一致，不一致退出码 2
    python tools/sync_version.py --dry-run       # 只显示会改什么，不落盘
    python tools/sync_version.py --set 0.15.0    # 手工指定
    python tools/sync_version.py --from-exe D:/pvzge-0.15.0.exe
    python tools/sync_version.py --from-upstream # 网络：读 upstream 远端最高版本 tag
    python tools/sync_version.py --force         # 配合 --from-upstream：明知版本更旧也要写

唯一真源的优先级：
    --set  >  --from-exe  >  --from-upstream  >  docs/index.html 标题（默认，离线）

⚠️ 关于 --from-upstream：**这条路径不可靠，通常不要用**。
   上游并不是每个版本都打 tag —— 实测上游最新 tag 只到 v0.12.1，而游戏本体已经是 0.14.0。
   于是它会算出比实际游戏更旧的版本，照它写配置就把 5 处版本号静默降级了。
   为此本脚本加了保护：**只要 --from-upstream 的结果低于 docs 真源，就直接拒绝执行**
   （只读模式 --print/--value/--check/--dry-run 下改为打印警告，方便排查）。
   确实要用这个旧版本覆盖，请显式加 --force。

   要拿"当前版本"，正确做法就是**不加任何参数**（默认真源 = docs/index.html）。
   要拿"新版本"，等上游发新版后更新 docs/ 再跑默认，或用 --set / --from-exe 明确指定。
"""
import json
import os
import re
import struct
import subprocess
import sys

# 必须最早导入：Windows 下 stdout 走管道时会退回 cp936，中文全乱码。
# 这里【绝对不能】有任何输出 —— --value 的结果会被 build.sh 当版本号捕获。
import _console_utf8  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TAURI_CONF = "tools/tauri-app/src-tauri/tauri.conf.json"
CARGO_TOML = "tools/tauri-app/src-tauri/Cargo.toml"
CARGO_LOCK = "tools/tauri-app/src-tauri/Cargo.lock"
LAUNCHER_CSPROJ = "tools/launcher/src/PvZGE-Launcher.csproj"
WEBSERVER_CSPROJ = "tools/webserver/src/PvZGE-WebServer.csproj"
GAME_INDEX = "docs/index.html"

BEGIN = "<!-- @version 由 tools/sync_version.py 自动写入，勿手改；真源见 tools/README.md -->"
END = "<!-- /@version -->"

VERSION_PROPS = ("Version", "FileVersion", "AssemblyVersion", "InformationalVersion",
                 "IncludeSourceRevisionInInformationalVersion")


# ------------------------------------------------------------------ 版本解析/规范化
def norm(semver):
    """把 0.15 / 0.15.0 / v0.15.0 / 0.15.0-beta.1 规范成 (semver, fileversion)。"""
    s = semver.strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", s)
    if not m:
        raise SystemExit("认不出这是版本号: %r" % semver)
    nums = [int(x) for x in m.group(1).split(".")]
    suffix = m.group(2) or ""
    while len(nums) < 3:
        nums.append(0)
    sem = ".".join(str(n) for n in nums[:3]) + suffix
    quad = nums[:4] + [0] * max(0, 4 - len(nums))
    return sem, "%d.%d.%d.%d" % tuple(quad[:4])


def from_docs():
    """从 docs/index.html 的 <title> 里取游戏版本（离线、始终反映我们实际打包的游戏）。"""
    p = os.path.join(ROOT, GAME_INDEX)
    if not os.path.isfile(p):
        raise SystemExit("找不到 %s" % GAME_INDEX)
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        html = f.read()
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not m:
        raise SystemExit("docs/index.html 里没有 <title>")
    title = m.group(1).strip()
    hits = re.findall(r"\d+(?:\.\d+)+", title)
    if not hits:
        raise SystemExit("docs/index.html 标题里没有版本号: %r\n"
                         "（上游改了标题格式？用 --set X.Y.Z 手工指定）" % title)
    return hits[-1], "docs/index.html 标题: %s" % title


def vt(sem):
    """把版本号拍成可比较的元组：0.14.0 -> (0, 14, 0)。用于判断「谁更旧」。"""
    m = re.match(r"^(\d+(?:\.\d+)*)", str(sem).strip().lstrip("vV"))
    return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)


def docs_or_none():
    """取 docs 真源；取不到就返回 (None, None)。

    保护逻辑拿它当对照基准，不该因为读不到 docs/index.html 就把整条命令弄失败。
    """
    try:
        return from_docs()
    except SystemExit:
        return None, None


def from_exe(path):
    """读 PE 的 VS_VERSIONINFO → dwFileVersion。"""
    import mmap
    with open(path, "rb") as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    if data[:2] != b"MZ":
        raise SystemExit("不是 PE 文件: %s" % path)
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec, = struct.unpack_from("<H", data, pe + 6)
    optsz, = struct.unpack_from("<H", data, pe + 20)
    opt = pe + 24
    magic, = struct.unpack_from("<H", data, opt)
    plus = magic == 0x20B
    ddoff = opt + (112 if plus else 96)
    rva, _sz = struct.unpack_from("<II", data, ddoff + 2 * 8)     # 资源目录
    sections = []
    sec = opt + optsz
    for i in range(nsec):
        b = sec + i * 40
        vsz, va, rsz, raw = struct.unpack_from("<IIII", data, b + 8)
        sections.append((va, max(vsz, rsz), raw))

    def rva2off(r):
        for va, sz, raw in sections:
            if va <= r < va + sz:
                return raw + (r - va)
        return None

    root = rva2off(rva)
    nnamed, nid = struct.unpack_from("<HH", data, root + 12)
    for i in range(nnamed + nid):
        nameid, off = struct.unpack_from("<II", data, root + 16 + i * 8)
        if nameid & 0xFFFF != 16 or not (off & 0x80000000):       # 16 = RT_VERSION
            continue
        sub = off & 0x7FFFFFFF
        n2, i2 = struct.unpack_from("<HH", data, root + sub + 12)
        for j in range(n2 + i2):
            _nm, off2 = struct.unpack_from("<II", data, root + sub + 16 + j * 8)
            if not (off2 & 0x80000000):
                continue
            sub2 = off2 & 0x7FFFFFFF
            n3, i3 = struct.unpack_from("<HH", data, root + sub2 + 12)
            for k in range(n3 + i3):
                _lg, off3 = struct.unpack_from("<II", data, root + sub2 + 16 + k * 8)
                if off3 & 0x80000000:
                    continue
                drva, dsize = struct.unpack_from("<II", data, root + off3)
                doff = rva2off(drva)
                blob = data[doff:doff + dsize]
                p = blob.find(b"\xbd\x04\xef\xfe")                # VS_FIXEDFILEINFO
                if p < 0:
                    continue
                ms, ls = struct.unpack_from("<II", blob, p + 8)    # dwFileVersionMS/LS
                return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF), \
                    "%s 的资源版本" % os.path.basename(path)
    raise SystemExit("%s 里没找到版本资源（RT_VERSION）" % path)


def from_upstream():
    """读 upstream 远端最高版本 tag。"""
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", "upstream"],
                             cwd=ROOT, capture_output=True, text=True, timeout=90)
    except Exception as e:
        raise SystemExit("git ls-remote upstream 失败: %s" % e)
    if out.returncode != 0:
        raise SystemExit("git ls-remote upstream 失败: %s" % (out.stderr.strip() or "未知错误"))
    best = None
    for line in out.stdout.splitlines():
        ref = line.split("\t")[-1].strip()
        if not ref.startswith("refs/tags/") or ref.endswith("^{}"):
            continue
        m = re.match(r"^v?(\d+(?:\.\d+)*)$", ref[len("refs/tags/"):])
        if m:
            t = tuple(int(x) for x in m.group(1).split("."))
            if best is None or t > best[0]:
                best = (t, m.group(1))
    if best is None:
        raise SystemExit("upstream 远端没有形如 vX.Y.Z 的 tag")
    return best[1], "upstream 远端最高 tag: v%s" % best[1]


# ------------------------------------------------------------------------ 各写入点
def read(p):
    """读文本，同时记住它原来的换行符 —— 写回去时要还原。

    本仓库 core.autocrlf=true，未显式声明 eol 的文件在 Windows 上会检出成 CRLF；
    如果这里统一按 LF 写回，就会把 CRLF 文件悄悄刷成 LF（diff 看不出来，但和
    别人 clone 出来的工作区不一致）。
    """
    with open(os.path.join(ROOT, p), "rb") as f:
        raw = f.read()
    n_crlf = raw.count(b"\r\n")
    n_lf = raw.count(b"\n") - n_crlf
    eol = "\r\n" if n_crlf > n_lf else "\n"
    return raw.decode("utf-8").replace("\r\n", "\n"), eol


def write(p, text, eol):
    data = text.replace("\n", eol) if eol != "\n" else text
    with open(os.path.join(ROOT, p), "wb") as f:
        f.write(data.encode("utf-8"))


def cur_json_version(text):
    m = re.search(r'"version"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else None


def set_json_version(text, sem):
    new, n = re.subn(r'("version"\s*:\s*")[^"]*(")', r"\g<1>%s\g<2>" % sem, text, count=1)
    if n != 1:
        raise SystemExit("tauri.conf.json 里没找到 version 字段")
    return new


def cur_toml_version(text):
    m = re.search(r'(?ms)^\[package\]\s*$.*?^version\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def set_toml_version(text, sem):
    head, sep, tail = text.partition("[package]")
    if not sep:
        raise SystemExit("Cargo.toml 里没有 [package] 段")
    body, n = re.subn(r'(?m)^(version\s*=\s*")[^"]*(")', r"\g<1>%s\g<2>" % sem, tail, count=1)
    if n != 1:
        raise SystemExit("Cargo.toml [package] 里没找到 version")
    return head + sep + body


def cur_lock_version(text, pkg="pvzge"):
    m = re.search(r'(?ms)^\[\[package\]\]\s*\nname\s*=\s*"%s"\s*\nversion\s*=\s*"([^"]*)"' % re.escape(pkg), text)
    return m.group(1) if m else None


def set_lock_version(text, sem, pkg="pvzge"):
    new, n = re.subn(r'(?ms)(^\[\[package\]\]\s*\nname\s*=\s*"%s"\s*\nversion\s*=\s*")[^"]*(")'
                     % re.escape(pkg), r"\g<1>%s\g<2>" % sem, text, count=1)
    if n != 1:
        raise SystemExit("Cargo.lock 里没找到 package %s 的 version" % pkg)
    return new


def csproj_block(sem, quad):
    return "\n".join([
        "    " + BEGIN,
        "    <Version>%s</Version>" % sem,
        "    <FileVersion>%s</FileVersion>" % quad,
        "    <AssemblyVersion>%s</AssemblyVersion>" % quad,
        "    <InformationalVersion>%s</InformationalVersion>" % sem,
        "    <!-- .NET 默认会把 git 提交哈希拼到 ProductVersion 后面（1.0.0+abc123）——关掉 -->",
        "    <IncludeSourceRevisionInInformationalVersion>false</IncludeSourceRevisionInInformationalVersion>",
        "    " + END,
    ])


def cur_csproj_version(text):
    m = re.search(r"<Version>([^<]*)</Version>", text)
    return m.group(1) if m else None


def set_csproj_version(text, sem, quad, anchor):
    """把带标记的版本块整块换掉；没有标记就先清掉旧属性再插入。"""
    block = csproj_block(sem, quad)
    if BEGIN in text and END in text:
        return re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), block.strip(), text,
                      count=1, flags=re.S)
    lines = text.split("\n")
    kept = [ln for ln in lines
            if not any(re.match(r"\s*<%s\s*>" % p, ln) for p in VERSION_PROPS)
            and BEGIN not in ln and END not in ln]
    out = []
    inserted = False
    for ln in kept:
        out.append(ln)
        if not inserted and re.match(r"\s*<%s\s*>" % anchor, ln):
            out.append(block)
            inserted = True
    if not inserted:
        # 兜底：插到第一个 </PropertyGroup> 之前
        idx = next((i for i, ln in enumerate(out) if "</PropertyGroup>" in ln), None)
        if idx is None:
            raise SystemExit("csproj 里既没有 <%s> 也没有 </PropertyGroup>" % anchor)
        out.insert(idx, block)
    return "\n".join(out)


# -------------------------------------------------------------------------- 主流程
def main():
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0

    do_check = "--check" in argv
    do_print = "--print" in argv
    do_value = "--value" in argv
    dry = "--dry-run" in argv

    def opt(name):
        return argv[argv.index(name) + 1] if name in argv else None

    # ---- 1) 定版本 ----
    if opt("--set"):
        raw, why = opt("--set"), "--set 手工指定"
    elif opt("--from-exe"):
        raw, why = from_exe(opt("--from-exe"))
    elif "--from-upstream" in argv:
        raw, why = from_upstream()
        # 上游**并不是每个版本都打 tag** —— 实测上游最新 tag 只到 v0.12.1，
        # 而游戏本体（docs/index.html 标题）已经是 0.14.0。
        # 所以这条路径算出来的版本可能比我们实际打包的游戏还旧；一旦照它写配置，
        # 5 处版本号会被**静默降级**。低于 docs 真源就拒绝执行。
        raw_docs, why_docs = docs_or_none()
        if raw_docs and vt(raw) < vt(raw_docs):
            detail = ("--from-upstream 算出 %s，比 docs 真源还旧：\n"
                      "    上游 tag : %s\n"
                      "    文档真源 : %s\n"
                      "  原因：上游不是每个版本都打 tag，这条路径不可靠。"
                      % (raw, why, why_docs))
            readonly = do_print or do_value or do_check or dry
            if readonly:
                # 只读模式（--print/--value/--check/--dry-run）不改文件，给警告就好，方便排查
                sys.stderr.write("[警告] %s\n" % detail)
            elif "--force" not in argv:
                raise SystemExit(
                    "[拒绝] %s\n"
                    "  想用这个旧版本覆盖 5 处配置，请显式加 --force；\n"
                    "  想拿当前版本，直接跑默认（不加任何参数，真源走 docs/index.html）。"
                    % detail)
    else:
        raw, why = from_docs()
    sem, quad = norm(raw)

    if do_value:
        # 只输出解析到的版本号本身，方便脚本捕获（build.sh 用）
        print(sem)
        return 0

    files = {
        TAURI_CONF: (cur_json_version, lambda t: set_json_version(t, sem)),
        CARGO_TOML: (cur_toml_version, lambda t: set_toml_version(t, sem)),
        CARGO_LOCK: (cur_lock_version, lambda t: set_lock_version(t, sem)),
        LAUNCHER_CSPROJ: (cur_csproj_version,
                          lambda t: set_csproj_version(t, sem, quad, "AssemblyTitle")),
        WEBSERVER_CSPROJ: (cur_csproj_version,
                           lambda t: set_csproj_version(t, sem, quad, "RootNamespace")),
    }

    if do_print:
        print("真源: %s  ->  %s" % (why, sem))
        print()
        for p, (get, _set) in files.items():
            print("  %-52s %s" % (p, get(read(p)[0])))
        return 0

    if do_check:
        bad = []
        print("版本真源 : %s" % why)
        print("目标版本 : %s   (FileVersion %s)" % (sem, quad))
        print()
        for p, (get, _set) in files.items():
            v = get(read(p)[0])
            ok = (v == sem)
            print("  %s %-52s %s" % ("OK  " if ok else "差异", p, v))
            if not ok:
                bad.append(p)
        print()
        if bad:
            print("  结论: %d 处与真源不一致（跑一次 tools/sync_version.py 即可修好）" % len(bad))
            return 2
        print("  结论: 五处版本全部一致")
        return 0

    # ---- 2) 写入 ----
    print("版本真源 : %s" % why)
    print("目标版本 : %s   (FileVersion %s)" % (sem, quad))
    print()
    changed = []
    for p, (get, setter) in files.items():
        text, eol = read(p)
        old = get(text)
        new = setter(text)
        if new == text:
            print("  未变 %-52s %s" % (p, old))
            continue
        changed.append((p, old, sem))
        if not dry:
            write(p, new, eol)
        print("  %s %-52s %s -> %s" % ("将改" if dry else "已改", p, old, sem))
    print()
    print("  小计: %d 处%s" % (len(changed), "（dry-run，未落盘）" if dry else "已更新"))
    if not changed:
        print("  五处版本已经全部一致，无需改动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
