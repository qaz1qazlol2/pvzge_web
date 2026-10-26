# -*- coding: utf-8 -*-
"""修 Tauri EXE 的存档导出/导入。

问题
----
1. **导出不弹框，直接落到 Downloads**
   游戏的 `createExportElement`（内部名 `zi`）本来有两条路：

       if (window.__TAURI__) { dialog.save -> fs.writeTextFile }
       else                  { <a download> 回退 }

   但 `tauri.conf.json` 里没有 `withGlobalTauri`，Tauri 2 默认**不注入**
   `window.__TAURI__` ⇒ 永远走回退分支 ⇒ 浏览器式下载 ⇒ 进 Downloads。

2. **导入选了文件没反应**
   导入用的是纯 `document.createElement("input")` + FileReader，
   在 WebView2 + 自定义协议下不可靠。

修法
----
Rust 侧新增两个命令（`save_text_file` / `open_text_file`），
用 `tauri-plugin-dialog` 弹**原生**对话框，再直接 std::fs 读写 ——
绕开 `<a download>`、FileReader，也不受 fs 插件 scope 限制。

JS 侧：
- 导出：`a.dialog.save(...)` 那段改成 `a.core.invoke("save_text_file", ...)`
- 导入：`Ui` 返回的 input 在 Tauri 下把 `click()` 换成走原生对话框，
  调用方（`importPP` / `importKeyBinds` / `importLevel`）一行都不用动

前置（已改）
------------
- `tauri.conf.json`  → `app.withGlobalTauri = true`
- `Cargo.toml`       → `tauri-plugin-dialog = "2"`
- `main.rs`          → `.plugin(...)` + `invoke_handler![]` + 两个命令
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _console_utf8  # noqa: E402,F401

JS = r"D:\git\pvzge_web\docs\assets\main\index.js"

# ---- 导出：把 dialog.save + fs.writeTextFile 换成 invoke ----
EXP_OLD = ('return e.next=5,a.dialog.save({defaultPath:t+".json",'
           'filters:[{name:"JSON",extensions:["json"]}]});'
           'case 5:if(o=e.sent){e.next=8;break}return e.abrupt("return");'
           'case 8:return e.next=10,a.fs.writeTextFile(o,n);'
           'case 10:return e.abrupt("return");case 11:')
EXP_NEW = ('return e.next=5,a.core.invoke("save_text_file",'
           '{defaultName:t+".json",content:n});'
           'case 5:return e.abrupt("return");case 11:')

# ---- 导入：Tauri 下把 input.click() 改成原生对话框 ----
# ⚠️ `document.body.appendChild(i),i}` 在 importMP3 里也出现（同样结尾），
#    必须带上前面「无法解析JSON文件」那句才唯一。
IMP_OLD = ('catch(e){console.error("无法解析JSON文件",e)}'
           'null==(r=K.cp)||r.scheduleOnce((function(){K.loadCursor(Xi.cursor,!1)}),.1)},'
           'a.readAsText(n)}i.value=""},document.body.appendChild(i),i}')
IMP_NEW = ('catch(e){console.error("无法解析JSON文件",e)}'
           'null==(r=K.cp)||r.scheduleOnce((function(){K.loadCursor(Xi.cursor,!1)}),.1)},'
           'a.readAsText(n)}i.value=""},document.body.appendChild(i),'
           'window.__TAURI__&&window.__TAURI__.core&&(i.click=function(){'
           'window.__TAURI__.core.invoke("open_text_file").then((function(t){'
           'if(null!=t)try{e(V.parse(t))}'
           'catch(e){console.error("无法解析JSON文件",e)}}))}),i}')


def main(apply=False):
    js = io.open(JS, encoding="utf-8", errors="replace").read()
    orig = len(js)

    if "save_text_file" in js:
        print("已修过，跳过")
        return 0

    pairs = [
        ("导出 → invoke", EXP_OLD, EXP_NEW),
        ("导入 → 原生对话框", IMP_OLD, IMP_NEW),
    ]
    for tag, old, _ in pairs:
        n = js.count(old)
        print(f"  锚点 {tag:<20} {n} 次")
        if n != 1:
            raise SystemExit(f"!! {tag} 锚点不唯一，中止")

    for _, old, new in pairs:
        js = js.replace(old, new, 1)

    print()
    print(f"字符数 {orig:,} -> {len(js):,}")
    print(f"save_text_file 出现 {js.count('save_text_file')} 处（应为 1）")
    print(f"open_text_file 出现 {js.count('open_text_file')} 处（应为 1）")

    if apply:
        io.open(JS, "w", encoding="utf-8", newline="").write(js)
        print("已写入")
    else:
        print("[dry-run] 加 --apply 落盘")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
