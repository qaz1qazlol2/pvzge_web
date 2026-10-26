# -*- coding: utf-8 -*-
"""Tauri 存档导入/导出 + 自动播放策略 修复验证。

四项
----
1. JS 导出走 invoke（不再走 <a download>）
2. JS 导入在 Tauri 下改走原生对话框
3. Tauri 侧开启 withGlobalTauri（否则 window.__TAURI__ 不存在）
4. 两个壳都关掉自动播放限制
"""
import io
import json
import os
import sys

REPO = r"D:\git\pvzge_web"
JS = os.path.join(REPO, "docs", "assets", "main", "index.js")
CONF = os.path.join(REPO, "tools", "tauri-app", "src-tauri", "tauri.conf.json")
CARGO = os.path.join(REPO, "tools", "tauri-app", "src-tauri", "Cargo.toml")
MAIN_RS = os.path.join(REPO, "tools", "tauri-app", "src-tauri", "src", "main.rs")
PROG_CS = os.path.join(REPO, "tools", "launcher", "src", "Program.cs")

fails = []


def ck(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


js = io.open(JS, encoding="utf-8", errors="replace").read()

print("=== 1. JS 导出 ===")
ck('a.core.invoke("save_text_file"' in js, "导出改走 invoke")
ck("a.dialog.save(" not in js, "旧的 dialog.save 已移除")
ck("a.fs.writeTextFile(" not in js, "旧的 fs.writeTextFile 已移除")
ck('(s=document.createElement("a")).download=t+".json"' in js,
   "非 Tauri 环境下保留 <a download> 回退")

print()
print("=== 2. JS 导入 ===")
ck('core.invoke("open_text_file")' in js, "导入改走原生对话框")
ck("i.click=function()" in js, "拦截 input.click()")
# 三个调用方共用 Ui，所以只需改一处
ck(js.count("open_text_file") == 1, "只改一处（Ui），三个调用方共用")

print()
print("=== 3. Tauri 配置 ===")
conf = json.loads(io.open(CONF, encoding="utf-8").read())
ck(conf.get("app", {}).get("withGlobalTauri") is True,
   "withGlobalTauri = true（否则 window.__TAURI__ 不存在）")

cargo = io.open(CARGO, encoding="utf-8").read()
ck("tauri-plugin-dialog" in cargo, "Cargo.toml 引入 tauri-plugin-dialog")

rs = io.open(MAIN_RS, encoding="utf-8").read()
ck("tauri_plugin_dialog::init()" in rs, "main.rs 注册 dialog 插件")
ck("save_text_file" in rs and "open_text_file" in rs, "main.rs 定义两个命令")
ck("generate_handler![save_text_file, open_text_file]" in rs, "命令已注册")

print()
print("=== 4. 自动播放策略 ===")
ck("--autoplay-policy=no-user-gesture-required" in rs, "Tauri 壳放开自动播放")
ck("msWebOOUI,msPdfOOUI,msSmartScreenProtection" in rs,
   "Tauri 保留默认 disable-features（additional_browser_args 会整体替换）")

cs = io.open(PROG_CS, encoding="utf-8").read()
ck("CoreWebView2EnvironmentOptions" in cs, ".NET Launcher 用环境选项")
ck("--autoplay-policy=no-user-gesture-required" in cs, ".NET Launcher 放开自动播放")
ck("CreateAsync(null, _userDataFolder, envOptions)" in cs, "选项已传给 CreateAsync")

print()
if fails:
    print(f"❌ {len(fails)} 项失败")
    sys.exit(1)
print("✅ 存档对话框 + 自动播放 修复验证通过")
