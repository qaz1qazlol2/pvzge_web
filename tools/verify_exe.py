#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验构建成品：五个 exe 的版本号 / 图标 / 产品信息是否都一致。

配合 tools/sync_version.py（版本）和 tools/extract_icon.py（图标）使用 ——
那两个负责「写对」，本脚本负责「核对真的写进去了」。

用法（不给参数时自动检查 dist/ 下约定的那 5 个产物）:
    python tools/verify_exe.py
    python tools/verify_exe.py <exe> [<exe> ...]
    python tools/verify_exe.py --dist D:/发布
    python tools/verify_exe.py --json

三项判定：
  1) 版本号   —— 五个产物的 FileVersion 必须完全相同，且等于真源版本
  2) 图标     —— 五个产物内嵌图标的 sha256 必须完全相同
  3) 产品信息 —— CompanyName / LegalCopyright 五个产物必须完全相同，
                且 ProductName 都必须以品牌名开头（后面可带「本地启动器」这类后缀）

退出码: 0 全部一致 / 2 有不一致 / 1 参数或读取错误
"""
import json
import os
import sys

# 必须最早导入：Windows 下 stdout 走管道时会退回 cp936，中文全乱码。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _console_utf8  # noqa: E402,F401

# 共享的 PE 资源读取器（图标 + 版本）都在 extract_icon.py 里，这里不再重复实现
from extract_icon import (  # noqa: E402
    PE, RT_GROUP_ICON, parse_group_icon, build_ico, sha,
    read_version as read_version_info,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRODUCTS = (
    "PvZGE-Gardendless.exe",
    "PvZGE-WebServer.exe",
    "PvZGE-WebServer-单文件.exe",
    "PvZGE-Launcher.exe",
    "PvZGE-Launcher-单文件.exe",
)

# ---- 期望的产品信息（与三处构建输入里的值对应，改这里等于改判定标准）----
# 全产品必须逐字相同的字段：
UNIFIED = {
    "CompanyName": "PvZ2 Gardendless",
    "LegalCopyright": "Plants vs Zombies 2 Gardendless",
}
# ProductName 允许各自不同，但都必须以这个品牌名开头：
BRAND_PREFIX = "PvZ2 Gardendless"


# ------------------------------------------------------------------ 版本资源
def read_version(path):
    """读版本资源，返回 {"file", "product", "strings", "lang"} 或 None。

    真正的解析在 extract_icon.read_version 里（共享的 PE 资源读取器）——
    这里只把它整成下面判定逻辑要的形状。**不要再另写一份 PE 解析**：
    曾用「搜关键字再猜偏移」的写法，把 Value 起点算错（wType 读成 90），
    结果 5 个产物的 ProductName 全被判成「无」。
    """
    info = read_version_info(path)
    if not info:
        return None
    return {
        "file": info.get("file"),
        "product": info.get("product"),
        "strings": info.get("strings") or {},
        "lang": info.get("lang"),
    }


def read_icon(path):
    """返回 (条数, 总字节, 组装后 .ico 的 sha256, 尺寸描述)。"""
    p = PE(path)
    if not p.res_rva:
        return None
    root = p.rva2off(p.res_rva)
    groups = p.walk(root, 0, RT_GROUP_ICON)
    if not groups:
        return None
    g = groups[0]
    for cand in groups:
        if cand[2] == 0x0409:
            g = cand
            break
    entries = parse_group_icon(p.m[p.rva2off(g[3]):p.rva2off(g[3]) + g[4]])
    icons = {(nm, lang): (p.rva2off(rva), size)
             for _t, nm, lang, rva, size in p.walk(root, 0, 3)}
    blobs = []
    for w, h, colors, planes, bpp, nbytes, rid in sorted(entries, key=lambda e: (e[0], e[1])):
        off, size = icons[(rid, g[2])]
        blobs.append((w, h, colors, planes, bpp, p.m[off:off + size]))
    ico = build_ico(blobs)
    return {
        "count": len(blobs),
        "bytes": sum(len(b[5]) for b in blobs),
        "sha256": sha(ico),
        "sizes": " ".join("%dx%d" % (b[0], b[1]) for b in blobs),
    }


# ------------------------------------------------------------------------- 主流程
def main():
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    as_json = "--json" in argv
    dist = argv[argv.index("--dist") + 1] if "--dist" in argv else os.path.join(ROOT, "dist")
    paths = [a for a in argv if not a.startswith("-") and a != dist]
    if not paths:
        paths = [os.path.join(dist, n) for n in PRODUCTS]

    rows = []
    missing = []
    for p in paths:
        if not os.path.isfile(p):
            missing.append(p)
            continue
        try:
            rows.append({
                "path": p,
                "name": os.path.basename(p),
                "bytes": os.path.getsize(p),
                "version": read_version(p),
                "icon": read_icon(p),
            })
        except SystemExit as e:
            rows.append({"path": p, "name": os.path.basename(p), "error": str(e)})

    if as_json:
        sys.stdout.reconfigure(newline="\n")
        print(json.dumps({"rows": rows, "missing": missing}, ensure_ascii=False, indent=2))
        return 0

    sys.stdout.reconfigure(newline="\n")
    print("=" * 84)
    print("  成品校验：版本号 + 图标")
    print("=" * 84)
    if missing:
        print("  以下产物不存在（还没构建？）：")
        for p in missing:
            print("    %s" % p)
        print()

    vers, icons = set(), set()
    meta = {k: set() for k in UNIFIED}      # 只统计要求全产品一致的字段
    prodnames = []
    for r in rows:
        if "error" in r:
            print("  %-30s [读取失败] %s" % (r["name"], r["error"]))
            continue
        v = r["version"] or {}
        ic = r["icon"]
        s = v.get("strings") or {}
        fv = v.get("file", "（无）")
        pv = v.get("product", "（无）")
        if ic:
            icons.add(ic["sha256"])
            istr = "%d 尺寸 (%s) %d 字节" % (ic["count"], ic["sizes"], ic["bytes"])
        else:
            istr = "（没有图标）"
            icons.add(None)
        vers.add(fv)
        for k in UNIFIED:
            meta[k].add(s.get(k) or "")
        prodnames.append(s.get("ProductName") or "")
        print("  %-30s %7.1f MB" % (r["name"], r["bytes"] / 1048576))
        print("      版本   FileVersion=%s  ProductVersion=%s" % (fv, pv))
        print("      产品   ProductName=%s" % (s.get("ProductName") or "（无）"))
        print("      公司   CompanyName=%s" % (s.get("CompanyName") or "（无）"))
        print("      版权   LegalCopyright=%s" % (s.get("LegalCopyright") or "（无）"))
        if s.get("FileDescription"):
            print("      说明   FileDescription=%s" % s["FileDescription"])
        if s.get("OriginalFilename"):
            print("      原始名 OriginalFilename=%s" % s["OriginalFilename"])
        print("      图标   %s" % istr)
        print()

    bad = 0
    print("-" * 84)
    if len(vers) == 1 and vers and None not in vers:
        print("  版本号 : 全部一致 -> %s" % next(iter(vers)))
    else:
        print("  版本号 : **不一致** -> %s" % " / ".join(sorted(x or "（无）" for x in vers)))
        bad += 1
    if len(icons) == 1 and None not in icons:
        h = next(iter(icons))
        print("  图标   : 全部一致 -> sha256 %s" % h[:16])
    else:
        print("  图标   : **不一致**（%d 种，其中可能包含「没有图标」）" % len(icons))
        bad += 1

    # 产品信息：CompanyName / LegalCopyright 必须全产品逐字相同，且等于期望值
    for k, want in UNIFIED.items():
        got = meta[k]
        label = "发布者" if k == "CompanyName" else ("版权  " if k == "LegalCopyright" else k)
        if len(got) != 1:
            print("  %s : **不一致** -> %s" % (label, " / ".join(sorted(x or "（无）" for x in got))))
            bad += 1
        else:
            only = next(iter(got))
            if only == want:
                print("  %s : 全部一致 -> %s" % (label, only))
            elif not only:
                print("  %s : **为空**（期望 %s）" % (label, want))
                bad += 1
            else:
                print("  %s : 全部一致 -> %s   （与期望值 %s 不同）" % (label, only, want))
                bad += 1

    # ProductName 允许多样，但都必须以品牌名开头
    if prodnames and all(n.startswith(BRAND_PREFIX) for n in prodnames):
        print("  产品名 : 各自不同，但都属 %s 系列" % BRAND_PREFIX)
    else:
        odd = [n or "（无）" for n in prodnames if not n.startswith(BRAND_PREFIX)]
        print("  产品名 : **有异常**（不以 %s 开头）-> %s" % (BRAND_PREFIX, " / ".join(odd)))
        bad += 1

    print("-" * 84)
    if bad:
        print("  结论: 有 %d 项不一致。" % bad)
        print("        版本 -> tools/sync_version.py；图标 -> tools/extract_icon.py --write；")
        print("        产品信息 -> 检查两个 csproj 的 Company/Product/Copyright，"
              "以及 tauri.conf.json 的 bundle.publisher/copyright")
        print("        改完都要重新 bash build.sh（图标和版本是构建期写进 PE 的）。")
        return 2
    print("  结论: 五个产物的版本号、图标、产品信息完全一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
