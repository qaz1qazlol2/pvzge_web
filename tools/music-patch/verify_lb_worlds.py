# -*- coding: utf-8 -*-
"""按 LawnProperties.Music 反查每个 StageModule 真正落到哪个世界曲。

引擎的解析链：
    StageModule (RTID(WestStage@LevelModules))
      → LawnType (aliases 里有 WestStage)  → Properties: RTID(WestStage@LawnProps)
      → LawnProperties (aliases 里有 WestStage) → Music: "Cowboy"
      → WorldMusic.Cowboy → switchMusic 的 case w.Cowboy

所以判断「LB 关卡能否找到专属曲」必须看 LawnProperties.Music，
不能看 StageModule 的名字。
"""
import glob
import json
import os
import re

REPO = r"D:\git\pvzge_web"
IMP = os.path.join(REPO, "docs", "assets", "resources", "import")

# 1) 建 LawnProperties 索引：alias → Music
props = {}
for p in glob.glob(os.path.join(IMP, "**", "*.json"), recursive=True):
    try:
        raw = open(p, "rb").read()
    except OSError:
        continue
    if b"LawnProperties" not in raw:
        continue
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception:
        continue

    def walk(o):
        if isinstance(o, dict):
            if o.get("objclass") == "LawnProperties":
                od = o.get("objdata") or {}
                for a in (o.get("aliases") or []):
                    props[a] = od.get("Music")
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(d)

# 2) 每个 LB 关卡的 StageModule → Music
worlds = {}
lb_files = []
for p in glob.glob(os.path.join(IMP, "**", "*.json"), recursive=True):
    try:
        raw = open(p, "rb").read()
    except OSError:
        continue
    if b'"MiniGame_D"' not in raw:
        continue
    lb_files.append(p)
    m = re.search(rb'"StageModule":"RTID\((\w+)@', raw)
    if not m:
        continue
    stage = m.group(1).decode()
    music = props.get(stage)
    worlds[music] = worlds.get(music, 0) + 1

print(f"LB 关卡 {len(lb_files)} 个")
print()
print("=== LawnProperties.Music 分布（这才是真正的世界曲键）===")
for w, n in sorted(worlds.items(), key=lambda x: (-x[1], str(x[0]))):
    print(f"  {str(w):<16} {n}")

# 3) 对照 LB 音轨库
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
have = {e["name"] for e in json.loads(raw[start:end])}

print()
print("=== 每个世界的 LB 曲是否就位 ===")
bad = []
for w in sorted(worlds, key=lambda x: -worlds[x]):
    if w is None:
        # 极少数关卡的 LawnProperties.Music 字段本身就是空的（游戏原版如此），
        # 走 switchMusic 的 default 兜底 → LB_Ballad，不是缺曲。
        print(f"  {'(null)':<16} {worlds[w]:>4}  → default 兜底 LB_Ballad（原版字段为空）")
        continue
    key = "LB_" + w
    if key in have:
        print(f"  {w:<16} {worlds[w]:>4}  {key:<20} OK")
    elif w == "Eighties":
        print(f"  {w:<16} {worlds[w]:>4}  → LB_Ballad（Jam 复用，switch 里已映射）")
    else:
        print(f"  {w:<16} {worlds[w]:>4}  {key:<20} 缺！会落 default")
        bad.append(w)

print()
print("未覆盖:", bad if bad else "无（(null) 已走 default 兜底）")
