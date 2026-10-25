# -*- coding: utf-8 -*-
"""校验 LB 打标结果：抽查若干关卡确实是 MiniGame_D，且 LB 音轨能对上。"""
import glob
import json
import os
import re

REPO = r"D:\git\pvzge_web"
IMP = os.path.join(REPO, "docs", "assets", "resources", "import")

# 收集所有 MusicType 分布
dist = {}
lb_levels = []

for p in glob.glob(os.path.join(IMP, "**", "*.json"), recursive=True):
    try:
        raw = open(p, "rb").read()
    except OSError:
        continue
    if b"MusicType" not in raw:
        continue
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception:
        continue

    def walk(o, name=None):
        if isinstance(o, dict):
            if o.get("objclass") == "LevelDefinition":
                od = o.get("objdata") or {}
                t = od.get("MusicType")
                dist[t] = dist.get(t, 0) + 1
                if t == "MiniGame_D":
                    lb_levels.append((name, os.path.basename(p)))
                return
            for v in o.values():
                walk(v, name)
        elif isinstance(o, list):
            if len(o) > 2 and isinstance(o[1], str) and isinstance(o[2], dict):
                walk(o[2], o[1])
            else:
                for v in o:
                    walk(v, name)

    walk(d)

print("=== MusicType 分布 ===")
for k in sorted(dist, key=lambda x: (x is None, x or "")):
    print(f"  {str(k):<12} {dist[k]}")

print()
print("=== LB 关卡的 StageModule 抽样（应覆盖多世界）===")
worlds = {}
for p in glob.glob(os.path.join(IMP, "**", "*.json"), recursive=True):
    try:
        raw = open(p, "rb").read()
    except OSError:
        continue
    if b'"MiniGame_D"' not in raw:
        continue
    m = re.search(rb'"StageModule":"RTID\((\w+?)Stage', raw)
    if m:
        w = m.group(1).decode()
        worlds[w] = worlds.get(w, 0) + 1

for w, n in sorted(worlds.items(), key=lambda x: -x[1]):
    print(f"  {w:<16} {n}")

print()
print("=== 与 LB 主音轨对照（音轨库里有 LB_<世界> 吗）===")
musics = None
raw = open(os.path.join(IMP, "0d", "0d4cac202.json"), encoding="utf-8",
           errors="replace").read()
i = raw.find('{"name":"WorldMap"')
start = raw.rfind("[", 0, i)
depth = 0
for k in range(start, len(raw)):
    if raw[k] == "[":
        depth += 1
    elif raw[k] == "]":
        depth -= 1
        if depth == 0:
            end = k + 1
            break
arr = json.loads(raw[start:end])
have = {e["name"] for e in arr}

# ⚠️ 这里只能给出「提示」，不能当判据。
#    worlds 的键是 StageModule 名（WestStage/PaddysStage...），
#    而音轨键来自 LawnProperties.Music（Cowboy/Tutorial...）。
#    两者不是一回事 —— 真正的校验在 verify_lb_worlds.py。
print()
print("（下表仅供参考：StageModule 名 ≠ 音轨键，正式校验见 verify_lb_worlds.py）")
ALIAS = {"Ice": "Iceage", "Iceage": "Iceage"}
unknown = []
for w in sorted(worlds):
    key = "LB_" + ALIAS.get(w, w)
    if key in have:
        mark = "OK"
    elif w == "Eighties":
        mark = "→ Ballad"
    else:
        mark = "? (按 StageModule 猜的名字，可能不对)"
        unknown.append(w)
    print(f"  {w:<16} {key:<18} {mark}")

if unknown:
    print()
    print(f"  {len(unknown)} 个世界的名字未直接命中，这不代表缺曲 ——")
    print("  请以 verify_lb_worlds.py 的结果为准。")
