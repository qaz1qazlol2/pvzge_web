#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows + Git Bash 下让 Python 的中文输出别乱码。**导入即生效，且永远不打印任何东西。**

【症状】

    □汾□□Դ : docs/index.html □□□□: PvZ2 Gardendless Online | 0.14.0
    Ŀ□□□汾 : 0.14.0   (FileVersion 0.14.0.0)

注意乱码里夹着「汾」这种"看着像中文但不是"的字 —— 那是能对上号的线索，见下。

【根因】

Windows 上 Python 只在 stdout 是**真控制台**时才走 `WriteConsoleW`（编码无关）；
一旦 stdout 是管道 / 重定向，就退回系统 ANSI 代码页 —— 简体中文机器上是
**cp936(GBK)**。而这里两端都不是 UTF-8：

  * Git Bash / mintty **不是** Windows 控制台（它是个 pty 管道），所以 `isatty()` 为假；
  * `build.sh` 里还层层 `| sed 's/^/   /'`、`| tail -4`，stdout 必然是管道。

于是 Python 吐 GBK 字节、Git Bash 按 UTF-8 解：`版本真源` 的 GBK 是
`b0 e6 b1 be d5 e6 d4 b4`，其中 `b0` 不是合法 UTF-8 起始字节 → 显示 `�`（或豆腐块），
而后面的 `e6 b1 be` 又**恰好**凑成一个合法 UTF-8 三字节序列 = U+6C7E = 汾。
所以乱码是「豆腐块 + 一两个无辜的汉字」混着来，一眼看不出规律。

【为什么 build.sh 里 echo 的中文是好的】

`build.sh` 是 UTF-8 文件，`echo` 原样吐 UTF-8 字节，mintty 也按 UTF-8 解 → 正常。
**只有 Python 的输出会炸**。所以「有的行好、有的行坏」不是随机现象，是分工不同。

【用法】

脚本最前面、任何 print 之前导入（tools/ 下的脚本直接导入即可，
因为直接运行时 `sys.path[0]` 就是脚本所在目录）：

    import _console_utf8  # noqa: F401

tools/ 子目录里的脚本（launcher/ webserver/ music-patch/）先补一句再把 tools/ 塞进 sys.path：

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import _console_utf8  # noqa: E402,F401

【行为】

1. 已经设了 `PYTHONUTF8` / `PYTHONIOENCODING` → **尊重用户设置，什么都不做**；
2. stdout/stderr 是 tty（真控制台，比如 cmd.exe / PowerShell 里直接跑）→ **不动**，
   那里 Python 本来就写对了；
3. 其余情况（管道 / 重定向）→ 编码强制成 UTF-8，`errors="replace"`，
   **并把换行翻译关掉**（见下）。errors 用 replace 是刻意的：
   **输出编码这种事不该把整个构建打断**。

【顺带修掉的 `\r`】

Windows 上管道里的 stdout 是 `newline=None` 的 TextIOWrapper，会把 `\n` 翻译成
`os.linesep`（`\r\n`）。终端上看不出来，但 `$(...)` 捕获时**只剥尾部的 `\n`、不剥 `\r`**：

    APPVER="$("$PY" tools/sync_version.py --value)"    # -> "0.14.0\r"

这个 `\r` 会一路带进变量、带进 echo 的参数。所以这里同时 `newline="\n"`，
让 Python 的输出跟 bash 的 `echo` 一样是纯 LF —— 反正 Git Bash 两边都是 LF 的世界。

【不想改脚本时的手工等价办法】

    export PYTHONUTF8=1            # 最省事，一次管所有 Python 进程
    export PYTHONIOENCODING=utf-8  # 只改 stdout/stderr
    python -X utf8 tools/xxx.py    # 单次

【为什么不用 `chcp 65001`】

那只对 cmd.exe/Windows 控制台的代码页有效，对 mintty 的 pty 管道毫无作用。
"""
import os
import sys

__all__ = ["enable", "enabled"]


def _norm(enc):
    return (enc or "").lower().replace("-", "").replace("_", "")


def enable():
    """把「被管道/重定向」的 stdout/stderr 改成 UTF-8。返回真正改过的流名列表。

    真控制台和已显式配置过编码的情况一律跳过（见模块 docstring 的行为约定）。
    """
    if os.environ.get("PYTHONUTF8") or os.environ.get("PYTHONIOENCODING"):
        return []                       # 环境已经表态，别抢方向盘
    changed = []
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:              # pythonw / 被替换成 None
            continue
        try:
            if stream.isatty():         # 真控制台：走 WriteConsoleW，与编码无关
                continue
        except Exception:
            pass
        if _norm(getattr(stream, "encoding", "")) == "utf8":
            continue
        try:
            # newline="\n"：关掉 Windows 的 \n -> \r\n 翻译，别让 \r 混进 shell 变量
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
            changed.append(name)
        except Exception:
            pass                        # 不是 TextIOWrapper（被包装过）就算了，不值得为它报错
    return changed


# 注意：这里**绝对不能 print** —— sync_version.py --value 的输出会被 build.sh 捕获当版本号用。
enabled = enable()
