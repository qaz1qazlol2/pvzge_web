// PvZGE Web 服务器组件 —— 只做一件事：把游戏通过 HTTP 提供给浏览器
//   · 支持两种资源来源：① 本 exe 尾部内嵌的 PVZGEARC 归档（发布用） ② 磁盘目录（开发/调试用）
//   · 正确 MIME（.wasm→application/wasm、.mp3→audio/mpeg）+ no-store + Range + 目录穿越防护
//   · 端口被占自动往后试 10 个
//
// 用法:
//   PvZGE-WebServer.exe                          有内嵌资源就用内嵌，否则找磁盘目录
//   PvZGE-WebServer.exe --root <目录>            指定游戏目录
//   PvZGE-WebServer.exe --port 8123 --host 0.0.0.0
//   PvZGE-WebServer.exe --open                   启动后自动打开浏览器
//   PvZGE-WebServer.exe --info                   只看资源来源，不起服务
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

namespace PvzgeWeb
{
    internal static class Program
    {
        private const string DefaultRoot = @"D:\git\pvzge_web\docs";

        private static int Main(string[] args)
        {
            string cliRoot = null;
            string host = "127.0.0.1";
            int port = 8123;
            bool open = false, infoOnly = false;

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a == "--root" && i + 1 < args.Length) cliRoot = args[++i];
                else if (a == "--port" && i + 1 < args.Length) int.TryParse(args[++i], out port);
                else if (a == "--host" && i + 1 < args.Length) host = args[++i];
                else if (a == "--open") open = true;
                else if (a == "--info") infoOnly = true;
                else if (a == "--help" || a == "-h") { Help(); return 0; }
                else if (!a.StartsWith("-") && cliRoot == null) cliRoot = a;
            }

            // ---- 资源来源：优先内嵌归档 ----
            PayloadArchive arc = null;
            if (cliRoot == null)
            {
                try
                {
                    string self = Process.GetCurrentProcess().MainModule.FileName;
                    arc = PayloadArchive.TryOpen(self);
                }
                catch { arc = null; }
            }

            string src = null, root = null;
            if (arc == null)
            {
                root = ResolveRoot(cliRoot, out src);
                if (root == null)
                {
                    Console.Error.WriteLine("找不到游戏目录（需要目录里有 index.html）。");
                    Console.Error.WriteLine("已尝试：--root / exe 同级 web\\ / exe 同级 launcher.config / 默认 " + DefaultRoot);
                    return 1;
                }
            }

            string origin = arc != null
                ? ("内嵌归档（" + arc.Count + " 个文件）")
                : (root + "   [" + src + "]");

            if (infoOnly)
            {
                Console.WriteLine("资源来源: " + origin);
                return 0;
            }

            MiniHttpServer server;
            try
            {
                server = new MiniHttpServer(root, arc, port, host);
                server.Start();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("启动失败: " + ex.Message);
                return 1;
            }

            string url = "http://" + (host == "0.0.0.0" ? "127.0.0.1" : host) + ":" + server.Port + "/";
            Console.OutputEncoding = Encoding.UTF8;
            Console.WriteLine("======================================================");
            Console.WriteLine("  PvZ2 Gardendless —— 本地 Web 服务器");
            Console.WriteLine("  资源来源: " + origin);
            Console.WriteLine("  游戏地址: " + url);
            if (host == "0.0.0.0")
                Console.WriteLine("  （已监听 0.0.0.0，局域网内其它设备可用本机 IP 访问）");
            Console.WriteLine("  按 Ctrl+C 停止");
            Console.WriteLine("======================================================");

            if (open)
            {
                TryOpenBrowser(url);
            }

            var wait = new ManualResetEvent(false);
            Console.CancelKeyPress += (s, e) => { e.Cancel = true; wait.Set(); };
            wait.WaitOne();
            Console.WriteLine("已停止。");
            return 0;
        }

        private static void Help()
        {
            Console.WriteLine("用法: PvZGE-WebServer.exe [选项]");
            Console.WriteLine("  --root <目录>     指定游戏目录（含 index.html）");
            Console.WriteLine("  --port 8123       起始端口（占用则自动往后试 10 个）");
            Console.WriteLine("  --host 0.0.0.0    允许局域网访问（默认仅本机 127.0.0.1）");
            Console.WriteLine("  --open            启动后自动打开默认浏览器");
            Console.WriteLine("  --info            只打印资源来源后退出");
            Console.WriteLine("不指定 --root 时：优先用 exe 尾部内嵌归档，其次 exe 同级 web\\，最后默认路径。");
        }

        private static string ResolveRoot(string cliRoot, out string source)
        {
            if (!string.IsNullOrWhiteSpace(cliRoot))
            {
                if (File.Exists(Path.Combine(cliRoot, "index.html"))) { source = "命令行参数"; return Path.GetFullPath(cliRoot); }
            }
            string exeDir = AppContext.BaseDirectory;
            string web = Path.Combine(exeDir, "web");
            if (File.Exists(Path.Combine(web, "index.html"))) { source = "exe 同级 web\\"; return Path.GetFullPath(web); }

            try
            {
                string cfg = Path.Combine(exeDir, "launcher.config");
                if (File.Exists(cfg))
                {
                    foreach (string raw in File.ReadAllLines(cfg))
                    {
                        string line = raw.Trim();
                        if (line.Length == 0 || line.StartsWith("#")) continue;
                        if (line.StartsWith("root", StringComparison.OrdinalIgnoreCase))
                        {
                            int eq = line.IndexOf('=');
                            if (eq > 0)
                            {
                                string p = line.Substring(eq + 1).Trim().Trim('"');
                                if (File.Exists(Path.Combine(p, "index.html"))) { source = "launcher.config"; return Path.GetFullPath(p); }
                            }
                        }
                    }
                }
            }
            catch { }

            if (File.Exists(Path.Combine(DefaultRoot, "index.html"))) { source = "默认路径"; return Path.GetFullPath(DefaultRoot); }
            source = null;
            return null;
        }

        private static void TryOpenBrowser(string url)
        {
            try
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch (Exception ex)
            {
                Console.WriteLine("（自动打开浏览器失败：" + ex.Message + "，请手动访问上面的地址）");
            }
        }
    }
}
