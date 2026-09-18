#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 PE 文件（官方 exe）里提取 Windows 图标，写成标准 .ico —— 可复现、只读源码。

本模块同时是**共用的 PE 资源读取器**（`PE` / `read_icon` / `read_version`），
tools/verify_exe.py 直接复用这里，不要再写第二份 PE 解析。

为什么需要它：仓库里三处构建输入都要带同一个图标（Tauri 壳 + 两个 .NET 项目），
而图标的唯一权威来源是**游戏上游发布的 exe**（例如 pvzge-0.14.0.exe）。
本脚本把这个提取过程固化下来，既能重新生成，也能校验三处是否已经同步。

用法（<exe> 必须显式给出，脚本里没有任何机器路径）:
    python extract_icon.py <exe>                  # 只打印该 exe 的图标信息
    python extract_icon.py <exe> -o out.ico       # 提取到指定文件
    python extract_icon.py <exe> --write          # 提取并写入下面三处约定位置
    python extract_icon.py <exe> --check          # 只比对三处是否与该 exe 一致（不写）

三处约定位置（--write 的目标 / --check 的对象）:
    tools/tauri-app/src-tauri/icons/icon.ico   Tauri 壳（tauri.conf.json 的 bundle.icon）
    tools/launcher/src/icon.ico                .NET 启动器（csproj 的 ApplicationIcon）
    tools/webserver/src/icon.ico               .NET Web 服务器（csproj 的 ApplicationIcon）

改图标的标准流程：
    1) 拿到新版上游 exe
    2) python tools/extract_icon.py <新版exe> --write
    3) 重新构建（bash build.sh）—— 图标是在编译期嵌进 PE 资源的，
       事后改已编译 exe 的资源段会破坏「-单文件」版尾部归档的偏移，必须重编译。
"""
import hashlib
import mmap
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 三处构建输入（相对仓库根）
TARGETS = (
    "tools/tauri-app/src-tauri/icons/icon.ico",
    "tools/launcher/src/icon.ico",
    "tools/webserver/src/icon.ico",
)

RT_ICON = 3
RT_GROUP_ICON = 14
RT_VERSION = 16
IMAGE_RESOURCE_DIRECTORY = 16
PNG_SIG = b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------- PE
class PE:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        if self.m[:2] != b"MZ":
            raise SystemExit("不是 PE 文件（缺 MZ 头）: %s" % path)
        self.pe = struct.unpack_from("<I", self.m, 0x3C)[0]
        if self.m[self.pe:self.pe + 4] != b"PE\0\0":
            raise SystemExit("不是 PE 文件（缺 PE\\0\\0）: %s" % path)
        coff = self.pe + 4
        self.nsec, = struct.unpack_from("<H", self.m, coff + 2)
        optsz, = struct.unpack_from("<H", self.m, coff + 16)
        opt = coff + 20
        magic, = struct.unpack_from("<H", self.m, opt)
        self.pe32plus = (magic == 0x20B)
        ddoff = opt + (112 if self.pe32plus else 96)
        nrva, = struct.unpack_from("<I", self.m, opt + (108 if self.pe32plus else 92))
        self.dirs = [struct.unpack_from("<II", self.m, ddoff + i * 8) for i in range(nrva)]
        sec = opt + optsz
        self.sections = []
        for i in range(self.nsec):
            b = sec + i * 40
            name = self.m[b:b + 8].rstrip(b"\0").decode("latin1")
            vsz, va, rsz, raw = struct.unpack_from("<IIII", self.m, b + 8)
            self.sections.append((name, va, vsz, raw, rsz))
        self.res_rva, self.res_size = self.dirs[2] if len(self.dirs) > 2 else (0, 0)

    def rva2off(self, rva):
        for _name, va, vsz, raw, rsz in self.sections:
            if va <= rva < va + max(vsz, rsz):
                return raw + (rva - va)
        return None

    def _entries(self, root, dir_off):
        nnamed, nid = struct.unpack_from("<HH", self.m, root + dir_off + 12)
        out = []
        for i in range(nnamed + nid):
            e = root + dir_off + IMAGE_RESOURCE_DIRECTORY + i * 8
            nameid, off = struct.unpack_from("<II", self.m, e)
            out.append((nameid & 0xFFFF, off))
        return out

    def walk(self, root, dir_off, want_type):
        """返回 [(type_id, name_id, lang_id, data_rva, data_size)]。

        坑：IMAGE_RESOURCE_DIRECTORY_ENTRY 的 OffsetToData 一律相对**资源根目录**，
        不是相对当前子目录；按子目录算会读到文件尾部之后。
        """
        found = []
        for tid, off in self._entries(root, dir_off):
            if tid != want_type or not (off & 0x80000000):
                continue
            for nm, off2 in self._entries(root, off & 0x7FFFFFFF):
                if not (off2 & 0x80000000):
                    continue
                for lang, off3 in self._entries(root, off2 & 0x7FFFFFFF):
                    if off3 & 0x80000000:
                        continue
                    rva, size = struct.unpack_from("<II", self.m, root + off3)
                    found.append((tid, nm, lang, rva, size))
        return found


def parse_group_icon(blob):
    """解析 GRPICONDIR → [(w, h, colors, planes, bpp, nbytes, res_id)]"""
    count, = struct.unpack_from("<H", blob, 4)
    out = []
    for i in range(count):
        w, h, colors, _r, planes, bpp, nbytes, rid = struct.unpack_from(
            "<BBBBHHIH", blob, 6 + i * 14)
        out.append((w or 256, h or 256, colors, planes, bpp, nbytes, rid))
    return out


# ------------------------------------------------------------------- 版本资源
# VS_VERSIONINFO 是**嵌套块结构**（根块 → StringFileInfo → StringTable → String），
# 每个块都是: WORD wLength; WORD wValueLength; WORD wType; WCHAR szKey[];
#             padding; Value[wValueLength]; padding; [子块...]
# 必须老老实实按 wLength/wValueLength 递归走，不能拿「搜关键字再猜偏移」的
# 办法去捞 —— 那样会算错 Value 起点，把 wType 读成 'Z'(90) 这种鬼值。
def _block_key(blob, p):
    """读块的 szKey（UTF-16LE，双字节对齐的 \\0\\0 结尾）→ (key, 终止符之后的偏移)"""
    q = p + 6
    while q + 1 < len(blob):
        if blob[q] == 0 and blob[q + 1] == 0:
            try:
                return blob[p + 6:q].decode("utf-16-le"), q + 2
            except UnicodeDecodeError:
                return "", q + 2
        q += 2
    return "", q


def parse_version_block(blob, p=0, limit=None):
    """递归解析一个 VS_VERSIONINFO 块，返回 dict(key/wValueLength/wType/value/children)"""
    if limit is None:
        limit = len(blob)
    if p + 6 > limit:
        return None
    wlen, vlen, wtype = struct.unpack_from("<HHH", blob, p)
    key, after_key = _block_key(blob, p)
    voff = (after_key + 3) & ~3
    vbytes = vlen * 2 if wtype == 1 else vlen          # 文本按字符数，二进制按字节数
    node = {"key": key, "wLength": wlen, "wValueLength": vlen,
            "wType": wtype, "value": None, "children": []}
    if wtype == 1 and vlen:
        try:
            node["value"] = blob[voff:voff + vbytes].decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            pass
    if wlen == 0:
        return node
    end = min(p + wlen, limit, len(blob))
    q = (voff + vbytes + 3) & ~3
    while q + 6 <= end:
        cl = struct.unpack_from("<H", blob, q)[0]
        if cl == 0:
            break
        child = parse_version_block(blob, q, end)
        if child is None:
            break
        node["children"].append(child)
        nxt = (q + cl + 3) & ~3
        if nxt <= q:
            break
        q = nxt
    return node


def _flatten(node):
    yield node
    for c in node["children"]:
        yield from _flatten(c)


# 这些是结构节点，不是我们要的属性
_NOT_ATTR = ("VS_VERSION_INFO", "StringFileInfo", "VarFileInfo", "Translation")


def read_version(path):
    """读 PE 的 VS_VERSIONINFO。

    返回 {"lang": int, "file": "a.b.c.d", "product": "a.b.c.d",
          "strings": {属性名: 值}, "tree": 解析树}；没有版本资源时返回 None。
    """
    p = PE(path)
    if not p.res_rva:
        return None
    root = p.rva2off(p.res_rva)
    for _t, _nm, lang, rva, size in p.walk(root, 0, RT_VERSION):
        off = p.rva2off(rva)
        blob = p.m[off:off + size]
        tree = parse_version_block(blob)
        if tree is None:
            continue

        out = {"lang": lang, "file": None, "product": None, "strings": {}, "tree": tree}

        # 根块的 Value 就是 VS_FIXEDFILEINFO（44 字节），拿它的签名定位
        after_key = _block_key(blob, 0)[1]
        voff = (after_key + 3) & ~3
        sig = blob.find(b"\xbd\x04\xef\xfe", voff)      # 0xFEEF04BD 小端
        if 0 <= sig and sig + 52 <= len(blob):
            fms, fls, pms, pls = struct.unpack_from("<IIII", blob, sig + 8)

            def dv(ms, ls):
                return "%d.%d.%d.%d" % (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)

            out["file"] = dv(fms, fls)
            out["product"] = dv(pms, pls)

        for n in _flatten(tree):
            if n["key"] in _NOT_ATTR or not n["value"]:
                continue
            out["strings"].setdefault(n["key"], n["value"])
        return out
    return None


# ------------------------------------------------------------------- 提取 / 组装
def read_icon(path):
    """读取 PE 里的图标，返回 (entries, group_info)。

    entries: [(w, h, colors, planes, bpp, data)]，按尺寸升序
    """
    p = PE(path)
    if not p.res_rva:
        raise SystemExit("该文件没有资源目录: %s" % path)
    root = p.rva2off(p.res_rva)
    groups = p.walk(root, 0, RT_GROUP_ICON)
    if not groups:
        raise SystemExit("该文件没有图标（RT_GROUP_ICON）: %s" % path)
    icons = p.walk(root, 0, RT_ICON)

    # 优先简体英文(0x0409)语言组，否则取第一个
    g = groups[0]
    for cand in groups:
        if cand[2] == 0x0409:
            g = cand
            break
    _t, res_id, lang, grva, gsize = g
    dir_entries = parse_group_icon(p.m[p.rva2off(grva):p.rva2off(grva) + gsize])

    by_id = {}
    for _t, nm, l, rva, size in icons:
        by_id[(nm, l)] = (p.rva2off(rva), size)

    out = []
    for w, h, colors, planes, bpp, nbytes, rid in dir_entries:
        key = (rid, lang)
        if key not in by_id:
            raise SystemExit("RT_GROUP_ICON 引用了不存在的 RT_ICON id=%d lang=0x%04X" % key)
        off, size = by_id[key]
        if size != nbytes:
            raise SystemExit("图标 id=%d 尺寸不一致：资源目录 %d vs GROUP 记录 %d"
                             % (rid, size, nbytes))
        out.append((w, h, colors, planes, bpp, p.m[off:off + size]))
    out.sort(key=lambda e: (e[0], e[1]))
    info = {"res_id": res_id, "lang": lang, "count": len(out),
            "total": sum(len(e[5]) for e in out)}
    return out, info


def build_ico(entries):
    """按 ICONDIR 规范组装 .ico（PNG 条目的数据原样保留）。"""
    hdr = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    dirent = b""
    payload = b""
    for w, h, colors, planes, bpp, data in entries:
        dirent += struct.pack("<BBBBHHII", w if w < 256 else 0, h if h < 256 else 0,
                              colors, 0, planes, bpp, len(data), offset)
        offset += len(data)
        payload += data
    return hdr + dirent + payload


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fmt_bpp(bpp):
    return {1: "1bpp", 4: "4bpp", 8: "8bpp", 24: "24bpp", 32: "32bpp"}.get(bpp, "%dbpp" % bpp)


# ------------------------------------------------------------------------ 主流程
def describe(path, entries, info):
    print("源文件  : %s  (%d 字节)" % (path, os.path.getsize(path)))
    print("图标组  : 资源ID=%s  语言=0x%04X  共 %d 个尺寸  合计 %d 字节"
          % (info["res_id"], info["lang"], info["count"], info["total"]))
    print("  %-9s %-8s %-9s %s" % ("尺寸", "位深", "编码", "字节"))
    for w, h, _c, _p, bpp, data in entries:
        print("  %-9s %-8s %-9s %d"
              % ("%dx%d" % (w, h), fmt_bpp(bpp),
                 "PNG" if data.startswith(PNG_SIG) else "BMP/DIB", len(data)))


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 1

    src = argv[0]
    out = None
    if "-o" in argv:
        out = argv[argv.index("-o") + 1]
    do_write = "--write" in argv
    do_check = "--check" in argv

    if not os.path.isfile(src):
        raise SystemExit("找不到文件: %s" % src)

    entries, info = read_icon(src)
    ico = build_ico(entries)
    describe(src, entries, info)
    print("组装 .ico: %d 字节  sha256=%s" % (len(ico), sha(ico)[:16]))
    print()

    if do_write:
        targets = list(TARGETS)
        if out:
            targets.insert(0, out)
        for rel in targets:
            dst = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
            old = None
            if os.path.isfile(dst):
                with open(dst, "rb") as f:
                    old = f.read()
            if old == ico:
                print("  未变   %s" % dst)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(ico)
            print("  %s %s  (%s)"
                  % ("覆盖" if old is not None else "新建", dst,
                     "%d -> %d 字节" % (len(old), len(ico)) if old is not None
                     else "%d 字节" % len(ico)))
        return 0

    if do_check:
        bad = 0
        for rel in TARGETS:
            dst = os.path.join(ROOT, rel)
            if not os.path.isfile(dst):
                print("  缺失   %s" % rel)
                bad += 1
                continue
            with open(dst, "rb") as f:
                cur = f.read()
            if cur == ico:
                print("  一致   %s" % rel)
            else:
                print("  不一致 %s  (磁盘 %d 字节 sha256=%s)"
                      % (rel, len(cur), sha(cur)[:16]))
                bad += 1
        print()
        print("  结论: %s" % ("三处图标都与上游 exe 一致" if not bad
                              else "%d 处需要同步（跑 --write）" % bad))
        return 0 if not bad else 2

    if out:
        with open(out, "wb") as f:
            f.write(ico)
        print("已写出: %s  (%d 字节)" % (out, len(ico)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
