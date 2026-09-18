# PvZ2 Gardendless 本地启动器

两种用法，任选其一。共同点：**都是本地起一个小 HTTP 服务器**，再用浏览器内核打开游戏
（必须走 HTTP，`file://` 协议下 Cocos 加载不了资源）。

---

## 方案 A：一键启动脚本（需要 Python）

双击 **`启动游戏.cmd`** 即可。它会：

1. 自动找游戏目录（优先脚本同级的 `web\`，否则用脚本里配置的绝对路径）
2. 用 Python 起本地服务器（自动找可用端口）
3. 用默认浏览器打开游戏

关闭那个最小化的命令行窗口即可停止服务器。

### 改游戏目录

编辑 `启动游戏.cmd` 顶部：

```bat
set "PORT=8123"
set "DEFAULT_ROOT=%HERE%..\..\docs"
```

`DEFAULT_ROOT` 默认就指向仓库的 `docs\`（相对脚本推导，不写死盘符）。
或者把游戏文件放到脚本同级的 `web\` / `docs\` 文件夹里（这样最省事、可整体拷走）。

### 手动跑（等价）

```bat
python server.py --root "..\..\docs" --port 8123 --open
```

`server.py` 支持 `--root` / `--port` / `--open` / `--quiet` / `--logfile`。

---

## 方案 B：独立 exe（WebView2，不需要 Python）

**`PvZGE-Launcher.exe`** —— 单文件、自包含 .NET 运行时，内嵌 HTTP 服务器 + WebView2 窗口。
双击即用，不弹命令行窗口。

### 依赖

只需要系统装有 **Microsoft Edge WebView2 Runtime**（Win10/11 基本都自带，
本机已装 153.0.4234.32）。没装的话从
<https://developer.microsoft.com/microsoft-edge/webview2/> 下载安装即可。

### 指定游戏目录（按优先级，全部相对 exe 推导）

1. 命令行：`PvZGE-Launcher.exe --root "D:\其他\路径"`
2. 环境变量 `PVZGE_WEB`
3. **exe 所在目录本身**（把 exe 丢进游戏目录）
4. exe 同级的 **`web\`** 文件夹（放 `index.html` 那一层）
5. exe 同级的 **`launcher.config`**，写一行 `root=<游戏目录>`
6. exe 同级的 **`docs\`**
7. exe 上级的 **`docs\`**（仓库开发态：`dist\` 里的 exe → 仓库 `docs\`）

> 源码里不写死任何机器路径，换机器把 exe 和游戏目录放对位置即可。

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--root <目录>` | 指定游戏目录 |
| `--port 8123` | 起始端口（占用会自动往后试 10 个） |
| `--host 0.0.0.0` | 允许局域网访问（默认只监听 `127.0.0.1`，更安全） |
| `--serve-only` | 只跑服务器、不开窗口（便于脚本调用或自测） |
| `--help` | 帮助 |

### 快捷键

- **F11** 切换全屏（游戏内请求全屏时也会自动跟随）
- **Esc** 退出全屏

---

## 自己重新编译 exe

```bat
cd src
dotnet publish PvZGE-Launcher.csproj -c Release -o ..\publish
```

发布参数已写进 `csproj`（`win-x64` + 自包含 + 单文件 + 压缩），产物就是
`publish\PvZGE-Launcher.exe` 一个文件。

> 注意：`src\NuGet.config` 里把包源清空后只指向 nuget.org。
> 如果你的机器只能访问内网源，改这个文件即可。

---

## 两个方案共有的行为

- **禁缓存**（`Cache-Control: no-store`）：改了游戏文件、换了音频，**刷新页面就生效**，不用重启服务器
- **正确的 MIME**：`.wasm` → `application/wasm`、`.mp3` → `audio/mpeg` 等（缺了会导致 wasm 编译失败或音频不播）
- **支持 Range 请求**（exe 版）：音频/大文件分段加载更稳
- **端口自动避让**：8123 被占用时自动往后试

## 方案 C：单文件 exe（把全部资源打进 exe，像原版发布那样）

双击 **`打包单文件exe.cmd`** 即可，它会：

1. （可选）用 .NET SDK 重新编译启动器主程序
2. 把 `GAMEDIR` 里的**全部资源**压缩打包，追加到启动器 exe 尾部
3. 生成一个**单文件 exe**（内置 WebView2 窗口 + 内嵌 HTTP 服务器 + 内嵌全部资源）

产物不需要 `web\` 目录、也不需要 `--root`，**双击即玩**。

### 改配置

编辑 `打包单文件exe.cmd` 顶部：

```bat
set "GAMEDIR=%HERE%..\..\docs"                       rem 游戏目录（相对脚本推导）
set "OUTEXE=%~dp0PvZGE-Gardendless-单文件.exe"        rem 输出路径
set "REBUILD=1"                                       rem 1=重新编译(需 .NET SDK) 0=用现成的
```

产物实测：游戏资源 1.39 GB / 8418 个文件 → **单文件 1.36 GB**（文本类走 deflate 压缩，mp3/png 原样存储）。

### 也可以直接命令行打包

```bat
python pack.py publish\PvZGE-Launcher.exe "..\..\docs" "D:\输出.exe"
python verify_pack.py "D:\输出.exe" "..\..\docs"    rem 校验归档与磁盘一致
```

### 单文件版的运行时行为

- 启动时自动检测 exe 尾部有没有内嵌归档：**有就用内嵌的**，没有才回落到磁盘目录
- 资源**不落地解包**：HTTP 服务直接从 exe 内部按偏移读取（store 条目 = 本地随机读，零解压）
- `PvZGE-Launcher.exe --info` 可查看是否内嵌及条目数
- `--disk` 可强制忽略内嵌资源、改用磁盘目录（调试用）

### 归档格式（自己实现，无需 zip 库）

```
[exe 原始字节][所有文件数据块][index JSON (UTF-8)][uint64 indexLength][8字节 "PVZGEARC"]
index: {"v":1,"e":[["相对路径", offset, storedLen, rawLen, method], ...]}   method: 0=store 1=deflate
```

> ⚠️ 压缩用的是**裸 deflate**（Python `zlib.compressobj(9, zlib.DEFLATED, -15)`），
> 因为 .NET 的 `DeflateStream` 只认裸 deflate；用默认 zlib 格式（带 2 字节头 + adler32）会解压失败。

---

## 常见坑

1. **别用 `file://` 打开游戏** —— Cocos 会加载失败。
2. **下载管理器（IDM 等）** 如果把 `127.0.0.1` 也纳入抓取范围，会把 `effect.bin`、`*.mp3` 截走，
   表现为页面全白或音频报 `204 (no response)`。请让它排除本地地址。
3. 换了音频后浏览器媒体缓存顽固，**Ctrl+Shift+R** 强刷。
