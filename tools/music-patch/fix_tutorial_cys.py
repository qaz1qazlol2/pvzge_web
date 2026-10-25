# -*- coding: utf-8 -*-
"""教程关的 CYS 要按家族选，而不是一律用主线 CYS_LP_Tutorial。

现状（case 96）
--------------
    t.t1===v.UltimateBattle       ? UB_Tutorial
  : t.t1===v.DemonstrateMinigame  ? MG_Tutorial
  : t.t1===v.RemadeZombotany      ? ZBT_Tutorial
  : t.t1===v.Loonboon             ? LB_Tutorial
  : t.t1===v.Victory              ? VIC_Tutorial
  : t.t1===v.CYS_Start||t.t1===v.CYS_LP ? CYS_LP_Tutorial   ← 问题在这
  : LP_Tutorial

所以 MiniGame_X 的教程关，选卡音乐播的是**主线**的 CYS_LP_Tutorial，
而不是 `UB_CYS_Tutorial` / `MG_CYS_Tutorial` / `ZBT_CYS_Tutorial` /
`LB_CYS_Tutorial`（这 4 条素材都在，也已经进了 `__CYS_TBL` 的 Tutorial 键）。

改法
----
照其他世界的写法（`__CYS_TBL[__cys_fam].Egypt` 那套），这里改成
`__CYS_TBL[__cys_fam].Tutorial`，并保留 `CYS_LP_Tutorial` 作兜底：

    CYS_Start → (家族 Tutorial CYS || CYS_LP_Tutorial)，L=CYS_LP，g=!1
    CYS_LP    → 同上，g=!0

⚠️ 两个分支要分开写：
   CYS_Start 是**前奏**（g=!1，播完切 CYS_LP），
   CYS_LP 是**循环**（g=!0）。
   原来把两者合并成 g=!0，等于让前奏直接循环，跳过了 L 的设定。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

# 家族 Tutorial CYS 的查表表达式（与其它世界同构）
FAM_CYS = ("((window.__cys_fam&&window.__CYS_TBL[window.__cys_fam]"
           "&&(window.__CYS_TBL[window.__cys_fam].Tutorial"
           "||window.__CYS_TBL[window.__cys_fam].Fallback))"
           "||A.CYS_LP_Tutorial)")

OLD = ('t.t1===v.CYS_Start||t.t1===v.CYS_LP'
       '?(u=A.CYS_LP_Tutorial,g=!0,t.abrupt("break",99))')

NEW = ('t.t1===v.CYS_Start'
       '?(u=' + FAM_CYS + ',L=v.CYS_LP,g=!1,t.abrupt("break",99))'
       ':t.t1===v.CYS_LP'
       '?(u=' + FAM_CYS + ',g=!0,t.abrupt("break",99))')


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    n = js.count(OLD)
    print("锚点次数:", n)
    if n != 1:
        raise SystemExit("锚点不唯一，中止")
    if "CYS_TBL[window.__cys_fam].Tutorial" in js:
        print("已是目标状态，跳过")
        return 0

    js2 = js.replace(OLD, NEW, 1)

    print()
    print("=== 改后 case 96 的 CYS 部分 ===")
    i = js2.find('t.t1===v.CYS_Start?')
    print(" ", js2[i:i + 330])
    print()
    print(f"字符数 {orig:,} → {len(js2):,}")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js2)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
