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
| `PvZGE-WebServer.exe` | 独立 Web 服务器，`--root <游戏目录>` 起 HTTP 服务 | ~36 MB |
| `PvZGE-WebServer-单文件.exe` | 上面那个 + 内嵌游戏 | ~1.35 GB |
| `PvZGE-Launcher.exe` | .NET/WinForms + WebView2 启动器（早于 Tauri 的实现） | ~47 MB |
| `PvZGE-Launcher-单文件.exe` | 上面那个 + 内嵌游戏 | ~1.36 GB |

> 前两个是「**本体**」：只有程序，运行时从磁盘上的游戏目录读资源，
> 所以必须把 `dist\` 里的 exe 和 `docs\` 放一起（或用 `--root` 指过去）。
> 带「**-单文件**」后缀的三个把资源内嵌进 exe，**单个文件即可分发**。

> **版本号 / 图标**：五个产物的版本号统一跟随游戏本体（当前 `0.14.0`），
> 图标统一取上游发布 exe 里的那一份。两者都由脚本自动同步、不手工改，
> 见下面「七、版本号与图标」。

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
  extract_icon.py            ← 从上游发布的 exe 里提取图标 → 写入三处构建输入（可复现/可校验）
  sync_version.py            ← 版本号唯一真源（docs/index.html）→ 分发到 5 处配置
  verify_exe.py              ← 校验成品：五个 exe 的版本号 / 图标是否真的都一致
  launcher/                  ← .NET/WinForms + WebView2 启动器 + 打包/校验/本地服务器
    src/Program.cs           ← 启动器主体（内含 HttpMime / PayloadArchive / MiniHttpServer 三个内核类）
    src/PvZGE-Launcher.csproj
    src/icon.ico             ← 图标（由 extract_icon.py 生成，勿手改）
    pack.py                  ← 把资源目录追加到 exe 尾部
    verify_pack.py           ← 校验归档：索引可读 + 解压内容与磁盘逐字节一致
    server.py                ← 纯 Python 本地服务器（不想编译时的替代方案）
    启动游戏.cmd / 打包单文件exe.cmd
  webserver/                 ← 独立 HTTP 服务器（从 launcher 里抽内核而来）
    src/Program.cs
    src/Shared.cs            ← 自动生成（勿手改），见下
    src/PvZGE-WebServer.csproj
    src/icon.ico             ← 图标（由 extract_icon.py 生成，勿手改）
    extract_shared.py        ← 从 launcher/src/Program.cs 抽取三个内核类 → src/Shared.cs
    test_ws.sh               ← 起服务并实测：首页/mp3字节/wasm MIME/Range/目录穿越
  tauri-app/                 ← Tauri 桌面壳（Rust）
    src-tauri/src/main.rs    ← 归档读取 + 协议 handler + 窗口
    src-tauri/{Cargo.toml,Cargo.lock,build.rs,tauri.conf.json,capabilities/,icons/}
    src-tauri/icons/icon.ico ← 图标（由 extract_icon.py 生成，勿手改）
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
- 找游戏目录的顺序（**全部相对 exe 推导，源码里没有任何机器路径**）：
  `--root <目录>` → `PVZGE_WEB` 环境变量 → **exe 所在目录本身** → exe 同级 `web\` →
  exe 同级 `launcher.config`（`root=...`）→ exe 同级 `docs\` → exe 上级 `docs\`。
  目标是「目录里有 `index.html`」即命中
- **禁缓存**（`Cache-Control: no-store`）：改了 `docs/` 里的文件，刷新页面就生效
- **正确 MIME**：`.wasm` → `application/wasm`、`.mp3` → `audio/mpeg` 等（缺了会导致 wasm 编译失败或音频不播）
- **支持 Range**：音频/大文件分段加载更稳
- `--info` 打印资源来源与条目数；`--disk` 强制忽略内嵌资源（调试用）

> 三种放置方式任选一种即可跑起来：
> ① exe 与游戏目录同级（叫 `docs\` 或 `web\`）；
> ② 把 exe 直接丢进游戏目录里（命中「exe 所在目录」）；
> ③ 仓库开发态：exe 留在 `dist\`，自动取上级的 `docs\`。

---

## 六、常见坑

1. **别用 `file://` 打开游戏** —— Cocos 加载不了资源，必须 HTTP。
2. 下载管理器（IDM 等）如果把 `127.0.0.1` 也纳入抓取，会把 `effect.bin`、`*.mp3` 截走，
   表现为页面全白或音频 `204 (no response)`。让它排除本地地址。
3. 换了音频后浏览器媒体缓存顽固，**Ctrl+Shift+R** 强刷。
4. 单文件 exe 打完先跑一次 `verify_pack.py`，比启动起来看白屏快得多。

---

## 七、版本号与图标

五个产物都必须**同一个版本号**、**同一个图标**，而且两件事都不能手改 ——
手改必然漂移（历史上就漂过：Tauri 是 `0.14.0`，两个 .NET 项目是 `1.0.0`；
图标也不一致：Tauri 那份是单尺寸 BMP，另外三个干脆没有图标）。

### 7.1 版本号：真源是游戏本体

唯一真源 = **`docs/index.html` 的 `<title>`**（当前是 `PvZ2 Gardendless Online | 0.14.0`）。
`docs/` 整块是上游发布的游戏本体，我们不动它；它升到 `0.15`，我们构建出来的包就自动是 `0.15`。

```bash
python tools/sync_version.py             # 探测 + 写入 5 处（构建时的默认行为）
python tools/sync_version.py --print     # 看 5 处当前值
python tools/sync_version.py --value     # 只输出解析到的版本号（给脚本用）
python tools/sync_version.py --check     # 只校验，不一致退出码 2（CI 用）
python tools/sync_version.py --dry-run   # 只显示会改什么，不落盘
```

真源优先级：`--set` > `--from-exe` > `--from-upstream` > `docs/index.html`（默认，离线）。

```bash
python tools/sync_version.py --set 0.15.0                     # 上游改了标题格式 → 手工指定
python tools/sync_version.py --from-exe D:/pvzge-0.15.0.exe   # 直接读发布 exe 的版本资源
python tools/sync_version.py --from-upstream                  # 读 upstream 远端最高 tag（需网络）
```

`--check` 校验的就是这 5 处：

| 文件 | 字段 | 影响到 |
|---|---|---|
| `tools/tauri-app/src-tauri/tauri.conf.json` | `version` | Tauri 壳的 FileVersion / ProductVersion |
| `tools/tauri-app/src-tauri/Cargo.toml` | `[package] version` | crate 版本 |
| `tools/tauri-app/src-tauri/Cargo.lock` | 本包条目 | 免得构建完 lock 变脏 / `--locked` 失败 |
| `tools/launcher/src/PvZGE-Launcher.csproj` | `@version` 标记块 | 启动器本体 + 它的「-单文件」版 |
| `tools/webserver/src/PvZGE-WebServer.csproj` | `@version` 标记块 | Web 服务器本体 + 它的「-单文件」版 |

`bash build.sh` 每次构建前都会自动跑一次同步并把结果打出来；
`bash build.sh check` 里也会顺带给出一致性检查。所以**不需要手工改任何版本号**。

两个 .NET 项目里额外关掉了 `IncludeSourceRevisionInInformationalVersion`：
.NET 默认会把 git 提交哈希拼在 `ProductVersion` 后面（`1.0.0+19254fe5ad…`），
在资源管理器「属性 → 详细信息」里看着就像版本不一致。

### 7.2 图标：从上游发布的 exe 里提取

唯一真源 = **上游发布 exe 的资源段**。例如 `pvzge-0.14.0.exe` 里是 6 个尺寸
（16 / 24 / 32 / 48 / 64 / 256，全部 32bpp、PNG 编码，合计 138 998 字节）——
按尺寸补齐，任务栏、资源管理器各视图、Alt+Tab 才都是清晰的。

```bash
python tools/extract_icon.py D:/pvzge-0.14.0.exe           # 只看图标信息（不写文件）
python tools/extract_icon.py D:/pvzge-0.14.0.exe --check   # 校验三处是否与它一致
python tools/extract_icon.py D:/pvzge-0.14.0.exe --write   # 提取并写入三处
python tools/extract_icon.py D:/pvzge-0.14.0.exe -o my.ico # 只导出成单个 .ico 文件
```

| 文件 | 谁用 |
|---|---|
| `tools/tauri-app/src-tauri/icons/icon.ico` | Tauri 壳（`tauri.conf.json` 的 `bundle.icon`） |
| `tools/launcher/src/icon.ico` | .NET 启动器（csproj 的 `<ApplicationIcon>`） |
| `tools/webserver/src/icon.ico` | .NET Web 服务器（同上） |

> **图标必须构建期嵌进去，不能事后往成品 exe 里塞。**
> 两个「-单文件」版本是 `pack.py` 把基础 exe 整段复制、再往尾部追加 1.4 GB 归档，
> PE 头和资源段都是从基础 exe 继承的；事后改资源段会让尾部归档的偏移全部失效，
> **整个包直接报废**。所以「换图标」= 改上面三处 + 重新 `bash build.sh`。

> Tauri 的图标是 `build.rs` 生成 `.rc` 再编译进 PE 的，属于该 crate 的构建产物。
> 万一换了图标但产物没跟着变，清掉该 crate 的构建缓存再编：
> `rm -rf tools/tauri-app/src-tauri/target/release/build/pvzge-*`

### 7.3 构建完怎么确认两件事都对了

`bash build.sh` 跑完会自动调一次校验，也可以随时单独跑：

```bash
python tools/verify_exe.py                 # 默认检查 dist/ 下那 5 个产物
python tools/verify_exe.py --dist D:/发布   # 指定产物目录
python tools/verify_exe.py a.exe b.exe     # 指定具体文件
```

它逐个读出真实的 PE 资源（不看配置文件），对比 **FileVersion** 和**图标内容的 sha256**，
全部一致返回 0、有不一致返回 2，可直接挂 CI。

### 7.4 上游升版本时的完整流程

```bash
git fetch upstream && git merge upstream/master   # 拿到新版游戏本体（含新的 docs/index.html）
python tools/sync_version.py --print              # 确认版本号已经跟着变
# 如果新版上游 exe 换了图标：
python tools/extract_icon.py <新版exe> --write
bash build.sh                                     # 版本号自动同步，5 个产物一次成型 + 自动校验
```
