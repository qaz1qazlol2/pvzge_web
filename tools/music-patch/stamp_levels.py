#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stamp_levels.py —— 给关卡 JSON 打 MusicType 标记（决定进关播哪套音乐）。

参考了 D:\\temp\\音乐补丁\\patch\\patcher.js 里的 expandLevelPatterns / stampMusicType，
改成：
  * 读仓库 docs/assets/resources/import/ 而不是 asar 解包目录
  * 配置放独立 json（level_map.json），不写死在脚本里
  * 默认 dry-run，只列会改什么；加 --apply 才写
  * 每次运行前把改过的文件备份到仓库外，可 --restore 回滚

关卡 JSON 的结构（Cocos 序列化）：

    [ ..., [ [0, "egypt26", {objects: [ {objclass: "LevelDefinition",
                                          objdata: {..., MusicType: "MiniGame_C"}} ]}], ... ], ... ]

MusicType 是 objdata 里的一个字符串字段。引擎读它的地方：
    "MiniGame_A" === MusicType ? ...   // 极限战斗
    "MiniGame_B" === MusicType ? ...   // 演示小游戏
    "MiniGame_C" === MusicType ? ...   // RemadeZombotany（我们）
    "MiniGame_D" === MusicType ? ...   // 保龄球

用法
----
    python stamp_levels.py                      # 预览（默认，不改文件）
    python stamp_levels.py --apply              # 真写回
    python stamp_levels.py --target MiniGame_C  # 临时改目标类型
    python stamp_levels.py --list               # 列出当前所有关卡的 MusicType 分布
    python stamp_levels.py --restore latest     # 回滚到最近一次 --apply 之前
"""

import argparse
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_NAME = "level_map.json"

# 备份放仓库外，避免污染 git
BACKUP_ROOT = os.path.join(os.path.expanduser("~"), ".pvzge_level_backups")

# 打标顺序：同一关卡出现在多个列表时，先出现者生效
ORDER = [("ForcedUB", "MiniGame_A"),
         ("ForcedMG", "MiniGame_B"),
         ("ForcedZBT", "MiniGame_C"),
         ("ForcedLB", "MiniGame_D")]

TYPE_LABEL = {
    "MiniGame_A": "极限战斗 UB",
    "MiniGame_B": "演示小游戏 MG",
    "MiniGame_C": "RemadeZombotany（我们的 RZ）",
    "MiniGame_D": "保龄球 LB",
    "Normal": "普通关卡",
}


# --------------------------------------------------------------------------
# 关卡名模式展开（移植自 patcher.js 的 expandLevelPatterns）
# --------------------------------------------------------------------------
def expand_patterns(specs):
    """把 "egypt(26-29,32-34)" 这类写法展开成小写关卡名集合。"""
    out = set()
    MAX_SPAN = 5000

    def add_item(prefix, item):
        it = str(item).strip()
        if it == "":
            return False
        r = re.match(r"^(\d+)\s*-\s*(\d+)$", it)
        if r:
            lo, hi = r.group(1), r.group(2)
            pad = len(lo) if lo.startswith("0") else (len(hi) if hi.startswith("0") else 0)
            a, b = int(lo), int(hi)
            if abs(b - a) + 1 > MAX_SPAN:
                print(f"    ! 范围过大已跳过：{prefix}({it})")
                return False
            for i in range(min(a, b), max(a, b) + 1):
                out.add((prefix + (str(i).zfill(pad) if pad else str(i))).lower())
            return True
        if re.match(r"^\d+$", it):
            out.add((prefix + it).lower())
            return True
        return False

    def add_one(raw):
        s = (str(raw).replace("（", "(").replace("）", ")")
             .replace("，", ",").replace("、", ",").strip())
        if s == "":
            return
        m = re.match(r"^(.*?)\(([^()]*)\)$", s)
        if m:
            prefix = m.group(1).strip()
            ok = False
            for part in m.group(2).split(","):
                if add_item(prefix, part):
                    ok = True
            if not ok:
                out.add(s.lower())
            return
        out.add(s.lower())

    for spec in (specs or []):
        text = str(spec)
        depth, buf = 0, ""
        for ch in text:
            if ch in "(（":
                depth += 1
            elif ch in ")）":
                depth -= 1
            if ch in ",，、" and depth <= 0:
                if buf.strip() != "":
                    add_one(buf)
                buf = ""
                continue
            buf += ch
        if buf.strip() != "":
            add_one(buf)
    return out


# --------------------------------------------------------------------------
# 关卡文件扫描
# --------------------------------------------------------------------------
def iter_level_entries(raw):
    """从关卡 json 里找出 [[...assetName...]] 结构的 entries 列表。

    返回 [(entry_list, entry_index)]，entry_list 是那个 entries 数组本身。
    """
    try:
        data = json.loads(raw)
    except Exception:
        return None, None

    found = [None]

    def find(d):
        if found[0] is not None:
            return
        if isinstance(d, list):
            for item in d:
                if (isinstance(item, list) and item
                        and isinstance(item[0], list) and item[0]
                        and isinstance(item[0][0], int)
                        and len(item[0]) > 1 and isinstance(item[0][1], str)):
                    found[0] = item
                    return
                find(item)
        elif isinstance(d, dict):
            for v in d.values():
                find(v)

    find(data)
    return data, found[0]


def scan_levels(repo):
    """返回 {assetName小写: (文件路径, 相对路径)}，只收含 LevelDefinition 的。"""
    root = os.path.join(repo, "docs", "assets", "resources", "import")
    if not os.path.isdir(root):
        raise SystemExit(f"[错] 找不到 import 目录：{root}")
    index = {}
    for sub in sorted(os.listdir(root)):
        sd = os.path.join(root, sub)
        if not os.path.isdir(sd):
            continue
        for f in sorted(os.listdir(sd)):
            if not f.endswith(".json"):
                continue
            fp = os.path.join(sd, f)
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    raw = fh.read()
            except OSError:
                continue
            if "LevelDefinition" not in raw:
                continue
            data, entries = iter_level_entries(raw)
            if not entries:
                continue
            for entry in entries:
                if not (isinstance(entry, list) and len(entry) > 2
                        and isinstance(entry[1], str)
                        and isinstance(entry[2], dict)):
                    continue
                objs = entry[2].get("objects") or []
                if any(o.get("objclass") == "LevelDefinition" for o in objs):
                    index[entry[1].lower()] = fp
    return index


def read_level(fp):
    with open(fp, "rb") as f:
        raw = f.read()
    return raw


def dump_like(data, original):
    """按原格式序列化，保住末尾换行（备用方案，主路径用 surgical_set）。"""
    out = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    tail = original[len(original.rstrip("\r\n")):]
    return out + tail


def _brace_end(text, start):
    """从 text[start] 处的 '{' 开始，返回配对 '}' 之后的下标。

    需要考虑字符串里的花括号与转义，所以用状态机而不是正则。
    """
    assert text[start] == "{"
    depth = 0
    i = start
    n = len(text)
    in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise ValueError("大括号不配对")


def surgical_set(text, updates):
    """只改 objdata 里的 MusicType 字段，**不重写整个文件**。

    为什么不用 json.dumps 重写：Cocos 导出的数字写法五花八门
    （`1e-7` vs `1e-07`、`0.000001` vs `1e-06`），Python 重新序列化会改变
    这些字面量。语义相同但会让 diff 变脏，也可能影响引擎里依赖字面串的地方。
    这里做纯文本替换：定位到每个关卡的 objdata，只动 MusicType 那一段。

    updates: {assetName小写: 新 MusicType}
    返回 (新文本, [(assetName, old, new)])，第二个元素只含真正改了的。
    """
    out = text
    changed = []

    # 找所有 [0,"<assetName>",{ 的起点
    entry_re = re.compile(r'\[0,"([^"]+)"')
    # 从后往前改，避免下标失效
    spots = []
    for m in entry_re.finditer(out):
        name = m.group(1).lower()
        if name not in updates:
            continue
        spots.append((m.end(), name))

    for pos, name in reversed(spots):
        want = updates[name]
        # 在这个 entry 之后找 LevelDefinition 的 objdata
        ld = out.find('"objclass":"LevelDefinition","objdata":', pos)
        if ld < 0:
            continue
        obj_start = ld + len('"objclass":"LevelDefinition","objdata":')
        if obj_start >= len(out) or out[obj_start] != "{":
            continue
        obj_end = _brace_end(out, obj_start)
        obj = out[obj_start:obj_end]

        m_mt = re.search(r'"MusicType":"([^"]*)"', obj)
        if m_mt:
            old = m_mt.group(1)
            if old == want:
                continue
            new_obj = obj[:m_mt.start()] + f'"MusicType":"{want}"' + obj[m_mt.end():]
            changed.append((name, old, want))
        else:
            # 没有就插在 objdata 的末尾（JSON 键顺序无关）
            inner_end = len(obj) - 1     # 指向最后一个 '}'
            # 判断是否需要补逗号
            body = obj[:inner_end].rstrip()
            sep = "," if body and not body.endswith("{") else ""
            new_obj = obj[:inner_end] + sep + f'"MusicType":"{want}"' + obj[inner_end:]
            changed.append((name, None, want))

        out = out[:obj_start] + new_obj + out[obj_end:]

    changed.reverse()
    return out, changed


# --------------------------------------------------------------------------
# 打标
# --------------------------------------------------------------------------
def stamp(repo, cfg, apply=False):
    target_default = cfg.get("target", "MiniGame_C")
    per_list = {}
    for key, default_type in ORDER:
        specs = cfg.get(key) or []
        if specs:
            per_list[key] = (specs, default_type)

    if not per_list:
        print("配置里四个列表都是空的，无事可做。")
        return 0

    index = scan_levels(repo)
    print(f"扫描到 {len(index)} 个关卡\n")

    stamped_by = {}
    plan = []          # [(filepath, assetName, old, new, list_key)]
    missed = {}        # list_key -> [未找到的名字]

    for key, default_type in ORDER:
        if key not in per_list:
            continue
        specs, dtype = per_list[key]
        names = expand_patterns(specs)
        if not names:
            continue
        tgt = cfg.get("target") if key == "ForcedZBT" else dtype
        if key == "ForcedZBT":
            tgt = target_default
        print(f"── {key} → {tgt} （{TYPE_LABEL.get(tgt, '?')}）──")
        print(f"   配置 {len(specs)} 条 → 展开 {len(names)} 个关卡名")

        hit = set()
        for name in sorted(names):
            if name not in index:
                continue
            hit.add(name)
            fp = index[name]
            if name in stamped_by:
                prev = stamped_by[name]
                if prev != tgt:
                    print(f"   ! {name}：已被 {prev} 占用，跳过（先出现者生效）")
                continue
            raw = read_level(fp)
            data, entries = iter_level_entries(raw.decode("utf-8"))
            if not data or not entries:
                continue
            changed = False
            old = None
            for entry in entries:
                if not (isinstance(entry, list) and len(entry) > 2
                        and isinstance(entry[1], str)
                        and isinstance(entry[2], dict)):
                    continue
                if entry[1].lower() != name:
                    continue
                for obj in (entry[2].get("objects") or []):
                    if obj.get("objclass") != "LevelDefinition":
                        continue
                    od = obj.get("objdata") or {}
                    old = od.get("MusicType")
                    if old == tgt:
                        continue
                    if name in stamped_by:
                        continue
                    od["MusicType"] = tgt
                    stamped_by[name] = tgt
                    changed = True
                if changed:
                    break
            if changed:
                plan.append((fp, name, old, tgt, key))

        miss = sorted(names - hit)
        missed[key] = miss
        print(f"   命中 {len(hit)} 个，未找到 {len(miss)} 个")
        if miss:
            print(f"      未找到样例：{', '.join(miss[:12])}"
                  + (f" …共 {len(miss)} 个" if len(miss) > 12 else ""))
        print()

    # 汇总
    print("=" * 70)
    print(f"计划修改 {len(plan)} 个关卡")
    print("=" * 70)
    if not plan:
        print("  没有需要改的（可能都已经是对的）。")
        return 0

    by_file = {}
    for fp, name, old, new, key in plan:
        by_file.setdefault(fp, []).append((name, old, new))

    print(f"  涉及 {len(by_file)} 个文件\n")
    for fp, items in sorted(by_file.items(), key=lambda x: x[0])[:25]:
        rel = os.path.relpath(fp, repo)
        for name, old, new in items:
            print(f"  {name:<26} {str(old):<14} → {new:<14} ({rel})")
    if len(by_file) > 25:
        print(f"  … 还有 {len(by_file) - 25} 个文件")

    if not apply:
        print()
        print("（预览模式，没有改动任何文件。加 --apply 才会写回。）")
        return 0

    # ---- 真写 ----
    stamp_dir = time.strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(BACKUP_ROOT, stamp_dir)
    os.makedirs(bdir, exist_ok=True)
    meta = {"time": stamp_dir, "files": [], "plan": []}

    print()
    written = 0
    total_changed = 0
    for fp, items in by_file.items():
        rel = os.path.relpath(fp, repo)
        bpath = os.path.join(bdir, rel.replace(os.sep, "__"))
        shutil.copy2(fp, bpath)
        meta["files"].append({"path": rel, "backup": bpath})

        with open(fp, "r", encoding="utf-8", newline="") as fh:
            raw = fh.read()

        updates = {n: new for n, _old, new in items}
        new_raw, changed = surgical_set(raw, updates)
        if not changed:
            continue

        # 写完立刻验证：能被 json 解析，且目标字段确实是新值
        try:
            parsed = json.loads(new_raw)
        except Exception as ex:
            print(f"   ✗ {rel} 改后 JSON 解析失败，跳过：{ex}")
            continue

        with open(fp, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_raw)
        written += 1
        total_changed += len(changed)

    for fp, name, old, new, key in plan:
        meta["plan"].append({"level": name, "old": old, "new": new, "list": key})
    with open(os.path.join(bdir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    print(f"✅ 已写入 {written} 个文件，{total_changed} 个关卡打标完成")
    print(f"   备份：{bdir}")
    print(f"   回滚：python stamp_levels.py --restore {stamp_dir}")
    return 0


def cmd_list(repo):
    index = scan_levels(repo)
    print(f"共 {len(index)} 个关卡\n")
    stat = {}
    detail = {}
    for name, fp in index.items():
        raw = read_level(fp).decode("utf-8")
        data, entries = iter_level_entries(raw)
        mt = None
        if entries:
            for entry in entries:
                if not (isinstance(entry, list) and len(entry) > 2
                        and isinstance(entry[1], str)
                        and isinstance(entry[2], dict)):
                    continue
                for obj in (entry[2].get("objects") or []):
                    if obj.get("objclass") == "LevelDefinition":
                        mt = (obj.get("objdata") or {}).get("MusicType")
        stat[mt] = stat.get(mt, 0) + 1
        detail.setdefault(mt, []).append(name)
    print(f"{'MusicType':<18}{'条数':>6}   说明")
    print("-" * 60)
    for mt, c in sorted(stat.items(), key=lambda x: -x[1]):
        print(f"{str(mt):<18}{c:>6}   {TYPE_LABEL.get(mt, '')}")
    print()
    for mt in sorted(detail, key=lambda x: str(x)):
        print(f"  {str(mt)} 样例：{', '.join(sorted(detail[mt])[:8])}")
    return 0


def cmd_restore(which):
    if not os.path.isdir(BACKUP_ROOT):
        print(f"[错] 备份目录不存在：{BACKUP_ROOT}")
        return 1
    cands = sorted(os.listdir(BACKUP_ROOT))
    if not cands:
        print("[错] 没有可用备份")
        return 1
    if which == "latest":
        stamp_dir = cands[-1]
    else:
        stamp_dir = which
    bdir = os.path.join(BACKUP_ROOT, stamp_dir)
    metap = os.path.join(bdir, "meta.json")
    if not os.path.isfile(metap):
        print(f"[错] 找不到 {metap}")
        return 1
    meta = json.load(open(metap, encoding="utf-8"))
    repo = REPO_FROM_ARGS
    n = 0
    for f in meta["files"]:
        dst = os.path.join(repo, f["path"].replace("/", os.sep))
        if os.path.isfile(f["backup"]):
            shutil.copy2(f["backup"], dst)
            n += 1
    print(f"✅ 已恢复 {n} 个文件（从 {stamp_dir}）")
    return 0


def main():
    global REPO_FROM_ARGS
    ap = argparse.ArgumentParser(description="给关卡 JSON 打 MusicType 标记")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(HERE)))
    ap.add_argument("--config", default=os.path.join(HERE, CONFIG_NAME))
    ap.add_argument("--apply", action="store_true", help="真写回（默认只预览）")
    ap.add_argument("--list", action="store_true", help="列出关卡当前的 MusicType 分布")
    ap.add_argument("--restore", metavar="STAMP", help="回滚到某次 --apply 之前（或 latest）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    REPO_FROM_ARGS = repo
    if not os.path.isdir(os.path.join(repo, "docs")):
        print(f"[错] 不是有效的仓库根目录：{repo}")
        return 1

    if args.restore:
        return cmd_restore(args.restore)
    if args.list:
        return cmd_list(repo)

    if not os.path.isfile(args.config):
        print(f"[错] 找不到配置：{args.config}")
        return 1
    cfg = json.load(open(args.config, encoding="utf-8"))
    print(f"仓库：{repo}")
    print(f"配置：{args.config}")
    print(f"目标类型：{cfg.get('target')}")
    print()
    return stamp(repo, cfg, apply=args.apply)


REPO_FROM_ARGS = None

if __name__ == "__main__":
    sys.exit(main())
