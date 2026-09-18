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
  _console_utf8.py           ← 【全部 Python 脚本开头都 import 它】中文输出别乱码，见第八节
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
  music-patch/               ← MiniGame_C 音乐定制（详见第九节）
    apply_music.py           ← 把音乐改动重放到 docs/ 的三个压缩文件上（幂等）
    _audio.py                ← 音频共享库：ffmpeg 定位 / 探测 / 响度 / 闭环转码
    audio_report.py          ← 体检 13 条 RZ 音轨：规格 / 响度 / 时长一致性
    normalize_music.py       ← 把响度与峰值统一到同一把尺子（可回滚）
    import_track.py          ← 把一段视频/音频换成某条 RZ 音轨
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
5. **Python 打印的中文在 Git Bash 里变成 `□汾□□Դ`** —— 是 Windows 编码坑，不是文件坏了，
   所有 `tools/*.py` 开头都 `import _console_utf8` 兜住了。细节见第八节。

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
python tools/sync_version.py --from-upstream                  # ⚠️ 别用，见下
```

> ⚠️ **不要用 `--from-upstream`**。它取「upstream 远端最高的 `vX.Y.Z` tag」，
> 但**上游并不是每个版本都打 tag** —— 实测（2026-09-18）上游最新 tag 只到 `v0.12.1`，
> 而游戏本体已经是 `0.14.0`。照它写配置，5 处版本号会被**静默降级**成 `0.12.1`：
>
> ```
> $ python tools/sync_version.py --from-upstream --dry-run
>   将改 tools/tauri-app/src-tauri/tauri.conf.json            0.14.0 -> 0.12.1
>   ...（5 处全是 0.14.0 -> 0.12.1）
> ```
>
> 脚本已加保护：**结果低于 docs 真源就直接拒绝执行**（退出码 1），
> `--print` / `--value` / `--check` / `--dry-run` 这些只读模式下只打印警告（方便排查）。
> 确实要用旧版本覆盖，得显式加 `--force`。
>
> 想拿「当前版本」就**不加任何参数**；想拿「新版本」等上游发新版后更新 `docs/` 再跑默认，
> 或用 `--set` / `--from-exe` 明确指定。**这条路径唯一可靠的用法是不用。**

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

---

## 八、中文输出与 Windows 编码（`_console_utf8.py`）

**症状**：在 Git Bash 里跑 `bash build.sh`，`build.sh` 自己 `echo` 的中文是好的，
但 Python 脚本打印的中文全变成 `□汾□□Դ`、`Ŀ□□□汾` 这种。

**为什么一半好一半坏**：`build.sh` 是 UTF-8 文件，`echo` 原样吐 UTF-8 字节，mintty 也按 UTF-8 解 → 正常。
Python 则不然：Windows 上它只在 stdout 是**真控制台**时才走 `WriteConsoleW`（与编码无关）；
一旦是管道 / 重定向就退回**系统 ANSI 代码页**（简体中文 = `cp936`/GBK）。
而 Git Bash 的 pty **不是** Windows 控制台，`build.sh` 里还层层 `| sed` / `| tail` —— 所以必然是管道。

于是 Python 吐 GBK、终端按 UTF-8 解：`版本真源` 的 GBK 是 `b0 e6 b1 be d5 e6 d4 b4`，
`b0` 不是合法 UTF-8 起始字节 → 豆腐块；紧随的 `e6 b1 be` 又**恰好**拼成合法序列 U+6C7E → 「汾」。
**乱码里夹着一两个"看着像中文但根本不是"的字，就是它**。

**修法**：`tools/_console_utf8.py`，导入即生效，`tools/` 下所有 Python 脚本开头都 import 了它。
行为：

| 情况 | 动作 |
|---|---|
| 已设 `PYTHONUTF8` / `PYTHONIOENCODING` | 尊重用户设置，什么都不做 |
| stdout/stderr 是 tty（cmd/PowerShell 里直接跑） | 不动 —— 那里本来就是对 |
| 其余（管道 / 重定向） | 编码强制 UTF-8 + `errors="replace"`，并把 `\n`→`\r\n` 的翻译关掉 |

`errors="replace"` 和「关掉换行翻译」都是刻意的：

- 输出编码这种事**不该把整个构建打断**；
- Windows 上管道 stdout 默认会把 `\n` 翻成 `\r\n`，而 `$( )` 只剥尾部 `\n`、**不剥 `\r`** ——
  于是 `APPVER="$("$PY" tools/sync_version.py --value)"` 拿到的是 `"0.14.0\r"`。
  肉眼看不出来（`\r` 会把光标送回行首），但 `\r` 会一路带进变量和后续参数里。统一成 LF 最省心。

**不想改脚本时的手工等价办法**（临时排查可用）：

```bash
export PYTHONUTF8=1            # 最省事，一次管住所有 Python 进程
export PYTHONIOENCODING=utf-8  # 只改 stdout/stderr
python -X utf8 tools/xxx.py    # 单次
```

注意 `chcp 65001` **没用** —— 那只改 cmd.exe 的代码页，对 mintty 的 pty 管道毫无影响。

---

## 九、RZ 音轨：规格、响度统一、换音频

`music-patch/` 下五个文件：

| 文件 | 职责 |
|---|---|
| `apply_music.py` | 把音乐定制**重放到上游压缩文件**上（幂等，可反复跑） |
| `_audio.py` | 音频共享库：ffmpeg 定位 / 探测 / 响度测量 / 闭环转码 |
| `audio_report.py` | 体检 13 条 RZ 音轨：**来源** / 规格 / 响度 / 时长一致性（只读） |
| `normalize_music.py` | 把响度与峰值统一到同一把尺子（可回滚） |
| `import_track.py` | 把一段视频 / 音频换成某条 RZ 音轨 |

### 9.1 统一规格（house spec）

**先分清来源，再谈统一。** 13 条 RZ 音轨其实是两类东西：

| 来源 | 条数 | 判据 | 该怎么办 |
|---|---|---|---|
| **自制轨** | 3（Egypt / Pirate / Beach） | `musicLength` 被改成循环点（182.5） | **这才是要统一的对象** |
| **官方原声** | 10 | `musicLength` 仍是原值（181 / Victory 3） | **保持原样 = 忠实官方** |

官方那 10 条与官方 `UB_*` 同源，它们的响度差异是**官方母带本身就有的**
（官方 UB 集跨曲 −10.5 ~ −17.7 LUFS，极差 7.2 LU）。把它们"统一"了反而是偏离官方，
还白叠一代重编码损失。所以两个工具都**默认排除官方原声**，要动得显式加
`--include-official`。判据与工作区的 `rz_map_check.py` 同一套，保证口径一致。

自制轨对齐的口径：

| 项目 | 值 | 依据 |
|---|---|---|
| 编码 | MP3 `libmp3lame` CBR **160 kbps** | 那三条实测值 |
| 采样率 | **48000 Hz** | 同（官方集合里混了 44.1k / **32k**，那是官方的，不动） |
| 声道 | **2** | 全部一致 |
| 响度 I | **-14.5 LUFS** | 官方 UB 集均值 ≈ −14.2，同档 |
| 真峰值 | **≤ -0.5 dBFS** | 比官方更保守（官方普遍压在 0 附近甚至超过，本身在削波） |

> **`loudnorm linear=true` 打不到 -14.5 是正常的。** 整轨只施加一个线性增益、不改动态，
> 源峰值余量不够时增益会被 TP 上限压住 —— 既有那三条就停在 **-14.8 / -14.8 / -14.9**，
> 这是**刻意保留**的既有行为，不是偏差。要严格打到 -14.5 得用 `--method gain-limit`（削峰换准）。

> **限幅器要压得比目标更低**：`alimiter` 限的是**采样峰值**，而 `ebur128 peak=true`
> 量的是**真峰值**（含交织点）。实测编完再解码，真峰值比限值高 ~0.2~0.3 dB，
> 所以 `_audio.LIMIT_MARGIN_DB = 0.3` 是必需的补偿，不是保守。

### 9.2 换音频时必须**一起改三个数字**，少一个就出 bug

| # | 位置 | 为什么 |
|---|---|---|
| 1 | `native/<前两位>/<uuid>.mp3` | 音频本体 |
| 2 | `TRACKS[].duration` → import json 的 `_duration` | Cocos 的资源元数据 |
| 3 | `TRACKS[].music_len` → Musics 的 `musicLength` | **index.js 的循环/切歌点** |

第 3 条最容易漏，而它是硬约束。`index.js` 里是：

```js
this.leftRepeat>0 && this.currentPlayingComponent.currentTime >= this.currentMusic.musicLength
  && this.changeLoopPlayer()
```

钢琴曲那条更直接：`audioSourcePiano.currentTime > this.pianoLength && (currentTime=0)` —— 硬循环回 0。

⇒ `(duration - music_len)` 那段是**永远播不到的尾音**（现有集合 3.4~4.5s，是渐弱+静音）。
换了音频不改这两个数：新的比它短 → 永远等不到切歌点；比它长 → 被提前切断。

**`music_len` 怎么定**：`import_track.py` 默认**沿用该轨原有尾长**（保持手感），
也可 `--tail` / `--music-length` / `--full` 覆盖。

### 9.3 把一段视频换成某条音轨

```bash
# 先看有哪些音轨和它们当前的时长/循环点
python tools/music-patch/import_track.py --list

# 预览（不动任何文件，产物留一份到 %TEMP% 便于试听）
python tools/music-patch/import_track.py --track RZ_Egypt --src "D:/videos/xxx.mp4"

# 真写回
python tools/music-patch/import_track.py --track RZ_Egypt --src "D:/videos/xxx.mp4" --apply

# 只要视频中间一段
python tools/music-patch/import_track.py --track RZ_Egypt --src xx.mp4 --start 12 --end 95 --apply
```

`--apply` 会按顺序做：备份原 mp3（仓库**外**）→ 写新 mp3 → 改 `apply_music.py` 那一行
→ 重跑 `apply_music.py --gen-import` → 重跑 `--verify`。

响度对齐方式（`--method`，两处脚本通用）：

| 方法 | 做法 | 特点 |
|---|---|---|
| `loudnorm`（**默认**） | 两遍 `loudnorm linear=true` | 只加一个线性增益，**完全不改动态**；被 TP 上限压住时停在 -14.8 附近 |
| `gain-limit` | 线性增益 + 一级 `alimiter` + 闭环重测 | 能真正打到 -14.5（±0.2 LU），代价是削掉几个越界峰 |

> 项目既有的换音频流程还有一份**仓库外**的脚本 `replace_rz_audio.sh`
> （唯一入口文档 `RZ_AUDIO_REPLACEMENT.md`，在本机会话工作区），
> 功能与本文这套 Python 工具重叠：它是 5 步流程 + 服务器字节复测 + 操作日志。
> 两套都可用；`audio_report.py` / `normalize_music.py` 是 Python 侧独有的（体检 / 统一）。

流程要点：

1. **从视频抽音频**（`-vn`，可 `--stream 0:a:1` 选轨）。
2. **裁首尾静音**（`silencedetect`, -50dB）。默认只裁 ≥0.15s 的 —— 更短的多半只是
   MP3 编码器 padding，裁了没意义。视频开头几秒静音**必须裁**，否则循环时每次都听见空白。
3. **统一规格 + 响度闭环**（见 9.4）。这一步不能省 —— 不然刚统一好的音量又被新音频打乱。
4. **改数字 + 重建 + 校验**。

### 9.4 响度闭环：为什么不能"一次算准"

```bash
# 体检（默认只读）：来源 / 规格 / 响度 / 时长一致性
python tools/music-patch/audio_report.py --repo D:/git/pvzge_web
python tools/music-patch/audio_report.py --repo D:/git/pvzge_web --track RZ_Egypt
python tools/music-patch/audio_report.py --repo D:/git/pvzge_web --include-official

# 统一响度（默认预览 + 只取自制轨，--apply 才写）
python tools/music-patch/normalize_music.py --repo D:/git/pvzge_web
python tools/music-patch/normalize_music.py --repo D:/git/pvzge_web --apply --tracks RZ_Egypt
python tools/music-patch/normalize_music.py --repo D:/git/pvzge_web --restore latest   # 整批回滚
```

`audio_report.py` 把"自制轨彼此是否一致"和"官方原声的跨世界差异"分开判：
前者才是**音量统一**要解决的问题，后者是官方设计、只当情报看。所以官方轨的
削波（Iceage +0.6 等）和低码率**不会**被算成问题。

增益是**线性**的，理论上 `增益 = 目标 - 实测` 一步到位。但实测有两个偏差：

1. **动了限幅就必偏**：限幅削掉峰值的同时会把整轨响度一起拉低。
2. **就算不限幅，第一轮也稳定低约 0.4 LU**（重采样 + MP3 编解码 + ebur128 相对门限
   共同造成）。换 4 条不同的轨试，全都是 0.4，所以别去"修公式"，直接量了再修。

⇒ `_audio.fit_to_target()` 做成闭环：每轮重新量 ebur128，拿误差回灌增益（阻尼 0.9），
最多 3 轮。**实测 2 轮收敛到 ±0.1 LU**。每轮都**从原始文件重新编码**，不叠加代际损失。

已经达标的轨会被跳过（阈值 0.5 LU，与体检脚本一致；不是闭环那个 0.2）——
重新编码是有代际损失的，能省一次就省一次。**当前状态下 3 条自制轨全部已达标，
什么都不用做。**

### 9.5 依赖

`ffmpeg` / `ffprobe`：`winget install Gyan.FFmpeg`。
winget 装的**可能不在 PATH**（或在 `%LOCALAPPDATA%\Microsoft\WinGet\Links`），
`_audio.find_tool()` 会自动去那儿找，并兼容 `.EXE` 大写后缀。

