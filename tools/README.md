# 构建工具链

把 `docs/`（游戏本体，也是 GitHub Pages 发布目录）打包成**可独立分发的 Windows 组件**。

入口是仓库根目录的 **`build.sh`**，本目录下是它用到的全部源码。

```bash
bash build.sh check      # 只看环境探测结果（不构建）
bash build.sh web        # 只做 Web 服务器
bash build.sh tauri      # 只做 Tauri 桌面版
bash build.sh            # 全做
```

产物默认输出到 `dist/`（已 gitignore）。

---

## 一、产物一览

| 产物 | 是什么 | 体积 |
|---|---|---|
| `PvZGE-Gardendless.exe` | Tauri 桌面壳（Rust + WebView2），内嵌游戏，**双击即玩** | ~1.32 GB |
| `PvZGE-WebServer.exe` | 独立 Web 服务器，`--root <游戏目录>` 起 HTTP 服务 | ~37 MB |
| `PvZGE-WebServer-单文件.exe` | 上面那个 + 内嵌游戏 | ~1.35 GB |
| `PvZGE-Launcher.exe` | .NET/WinForms + WebView2 启动器（早于 Tauri 的实现） | ~37 MB |
| `PvZGE-Launcher-单文件.exe` | 上面那个 + 内嵌游戏 | ~1.36 GB |

> 体积大是因为游戏资源本身 1.39 GB / 8418 个文件。
> 文本类（`.js/.json/.html/.wasm`…）走 deflate 压缩，mp3/png 原样存储。

**为什么单文件版能用**：把资源以「追加归档」的形式塞进 exe 尾部，运行时按偏移直接从 exe 内部读，
**不落地解包**。游戏里必须走 HTTP（`file://` 下 Cocos 加载不了资源），所以每个壳内部都带一个小型
HTTP 服务器，把 `http://pvzge.localhost/`（Tauri 自定义协议）或 `127.0.0.1:<port>` 映射到归档/目录。

---

## 二、目录结构

```
build.sh                     ← 一键入口（仓库根）
tools/
  launcher/                  ← .NET/WinForms + WebView2 启动器 + 打包/校验/本地服务器
    src/Program.cs           ← 启动器主体（内含 HttpMime / PayloadArchive / MiniHttpServer 三个内核类）
    src/PvZGE-Launcher.csproj
    pack.py                  ← 把资源目录追加到 exe 尾部
    verify_pack.py           ← 校验归档：索引可读 + 解压内容与磁盘逐字节一致
    server.py                ← 纯 Python 本地服务器（不想编译时的替代方案）
    启动游戏.cmd / 打包单文件exe.cmd
  webserver/                 ← 独立 HTTP 服务器（从 launcher 里抽内核而来）
    src/Program.cs
    src/Shared.cs            ← 自动生成（勿手改），见下
    src/PvZGE-WebServer.csproj
    extract_shared.py        ← 从 launcher/src/Program.cs 抽取三个内核类 → src/Shared.cs
    test_ws.sh               ← 起服务并实测：首页/mp3字节/wasm MIME/Range/目录穿越
  tauri-app/                 ← Tauri 桌面壳（Rust）
    src-tauri/src/main.rs    ← 归档读取 + 协议 handler + 窗口
    src-tauri/{Cargo.toml,Cargo.lock,build.rs,tauri.conf.json,capabilities/,icons/}
    boot/index.html          ← 加载中占位页（frontendDist）
    build_tauri.sh           ← 手工注入 MSVC/SDK 环境后 cargo build（不用 vcvars64.bat）
    build_singlefile.sh      ← 构建 + 打包成单文件
    verify_tauri_app.sh      ← 增量重建计时 + 用 --log 证明实际加载了哪些文件
    test_singlefile.sh       ← 跑起来查 WebView2 用户目录/缓存/origin
```

**三处共用同一套内核**：`HttpMime`（MIME 表）/ `PayloadArchive`（尾部归档读取）/ `MiniHttpServer`（HTTP 服务器）
只在 `launcher/src/Program.cs` 里维护一份，webserver 的 `Shared.cs` 由 `extract_shared.py` 按大括号配对**自动抽取**。
改完 launcher 的内核记得重跑一次抽取（`build.sh web` 会自动跑），否则 webserver 会停在旧版本。

---

## 三、依赖

| 组件 | 需要什么 |
|---|---|
| 打包/校验（所有产物） | **Python 3**（只用标准库） |
| `web` / `launcher` | **.NET 10 SDK**（`dotnet` 在 PATH 里） |
| `tauri` | **Rust**（rustup）+ **Visual Studio 的「使用 C++ 的桌面开发」**（MSVC + Windows SDK） |
| 运行产物 | **Microsoft Edge WebView2 Runtime**（Win10/11 基本自带） |

全部路径都会自动探测；探测逻辑与可覆盖的环境变量：

| 变量 | 作用 |
|---|---|
| `GAMEDIR` | 游戏目录，默认 `<仓库>/docs` |
| `DIST` | 产物目录，默认 `<仓库>/dist`。**刻意不叫 `OUTDIR`** —— 见下方坑 5 |
| `PYTHON` / `DOTNET` / `CARGO` | 指定解释器/编译器命令 |
| `SKIP_BUILD=1` | 跳过编译，只重新打包 |
| `MSVC_DIR` / `SDK_BASE` / `SDKVER` | 手工指定 MSVC / Windows SDK |
| `PVZGE_PROXY` | 需要走代理时设置（例如 `http://127.0.0.1:19132`）；**不设置就不会用代理** |
| `CHECK_ONLY=1` | 配合 `bash tools/tauri-app/build_tauri.sh`，只检查 MSVC/SDK/Rust 探测结果，不编译 |

`build_tauri.sh` 会自动找 MSVC（优先 `vswhere`，退路是扫 `Program Files`）和
`Windows Kits\10\Include` 下最高的 SDK 版本，然后手工注入 `PATH`/`INCLUDE`/`LIB`。

---

## 四、归档格式（自己实现，不依赖 zip 库）

```
[exe 原始字节][所有文件的数据块][index JSON (UTF-8)][uint64 indexLength][8 字节 "PVZGEARC"]
index: {"v":1,"e":[["相对路径", offset, storedLen, rawLen, method], ...]}
       method: 0 = store（原样）  1 = deflate（压缩）
```

两个坑：

1. 压缩必须用**裸 deflate**（Python `zlib.compressobj(9, zlib.DEFLATED, -15)`）。
   .NET 的 `DeflateStream` 只认裸 deflate，用默认 zlib 格式（2 字节头 + adler32 尾）会解压失败。
2. `pack.py` 会自动排除 `.bak` / `.orig_bak` 等我们自己产生的备份文件，别把备份留在 `docs/` 之外又指望它们进包。

---

## 五、运行时行为（各壳一致）

- 启动时先看 exe 尾部有没有 `PVZGEARC` 归档：**有就用内嵌的**，没有才回落到磁盘目录
- 找游戏目录的顺序：`--root <目录>` / `PVZGE_WEB` 环境变量 → exe 同级 `web\` → exe 同级 `launcher.config`（`root=...`）→ 源码里的默认路径
- **禁缓存**（`Cache-Control: no-store`）：改了 `docs/` 里的文件，刷新页面就生效
- **正确 MIME**：`.wasm` → `application/wasm`、`.mp3` → `audio/mpeg` 等（缺了会导致 wasm 编译失败或音频不播）
- **支持 Range**：音频/大文件分段加载更稳
- `--info` 打印资源来源与条目数；`--disk` 强制忽略内嵌资源（调试用）

> 源码里 `DefaultRoot` 还是 `D:\git\pvzge_web\docs` —— 它只是**最后**一道兜底，
> 正常走 `--root` 或 exe 同级 `web\`。换机器跑不用改代码，把游戏目录放对位置即可。

---

## 六、常见坑

1. **别用 `file://` 打开游戏** —— Cocos 加载不了资源，必须 HTTP。
2. 下载管理器（IDM 等）如果把 `127.0.0.1` 也纳入抓取，会把 `effect.bin`、`*.mp3` 截走，
   表现为页面全白或音频 `204 (no response)`。让它排除本地地址。
3. 换了音频后浏览器媒体缓存顽固，**Ctrl+Shift+R** 强刷。
4. 单文件 exe 打完先跑一次 `verify_pack.py`，比启动起来看白屏快得多。
