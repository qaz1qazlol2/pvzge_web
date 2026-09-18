// 本文件由工具自动生成（tools/webserver/extract_shared.py 从 tools/launcher/src/Program.cs 抽取），请勿手改。
// 内容：HttpMime（MIME 表）/ PayloadArchive（尾部归档读取）/ MiniHttpServer（HTTP 服务器）
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace PvzgeWeb
{

    // ============================================================ MIME 表（HTTP 与 WebView2 拦截共用）
    internal static class HttpMime
    {
        private static readonly Dictionary<string, string> Map =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { ".html", "text/html; charset=utf-8" }, { ".htm", "text/html; charset=utf-8" },
            { ".js",   "text/javascript; charset=utf-8" }, { ".mjs", "text/javascript; charset=utf-8" },
            { ".json", "application/json; charset=utf-8" }, { ".css", "text/css; charset=utf-8" },
            { ".wasm", "application/wasm" },
            { ".mp3",  "audio/mpeg" }, { ".ogg", "audio/ogg" }, { ".wav", "audio/wav" },
            { ".png",  "image/png" }, { ".jpg", "image/jpeg" }, { ".jpeg", "image/jpeg" },
            { ".webp", "image/webp" }, { ".gif", "image/gif" }, { ".svg", "image/svg+xml" },
            { ".ico",  "image/x-icon" },
            { ".ttf",  "font/ttf" }, { ".otf", "font/otf" },
            { ".woff", "font/woff" }, { ".woff2", "font/woff2" },
            { ".bin",  "application/octet-stream" }, { ".pvr", "application/octet-stream" },
            { ".astc", "application/octet-stream" }, { ".pkm", "application/octet-stream" },
            { ".txt",  "text/plain; charset=utf-8" }, { ".xml", "application/xml" },
            { ".zip",  "application/zip" },
        };

        public static string Get(string path)
        {
            string ext = Path.GetExtension(path);
            string v;
            if (ext != null && Map.TryGetValue(ext, out v)) return v;
            return "application/octet-stream";
        }
    }

    // ============================================================ 内嵌资源归档读取
    // 归档布局（追加在 exe 末尾）:
    //   [exe 原始字节][所有文件的数据块][index JSON (UTF-8)][uint64 indexLength][8字节 magic "PVZGEARC"]
    // index JSON: {"v":1,"e":[["相对路径", offset, storedLen, rawLen, method], ...]}   method: 0=store 1=deflate
    internal sealed class PayloadArchive : IDisposable
    {
        private static readonly byte[] Magic = Encoding.ASCII.GetBytes("PVZGEARC");
        private const int FooterSize = 16;

        public struct Entry
        {
            public long Offset;      // 数据块在 exe 中的绝对偏移
            public long StoredLen;   // 存储长度
            public long RawLen;      // 原始长度
            public int Method;       // 0=store 1=deflate
        }

        private readonly FileStream _fs;
        private readonly SafeFileHandle _handle;
        private readonly Dictionary<string, Entry> _map;
        public string SourcePath { get; private set; }
        public long ExeLength { get; private set; }
        public int Count { get { return _map.Count; } }
        public long PayloadBytes { get; private set; }

        private PayloadArchive(FileStream fs, Dictionary<string, Entry> map, string path, long exeLen, long payloadBytes)
        {
            _fs = fs;
            _handle = fs.SafeFileHandle;
            _map = map; SourcePath = path; ExeLength = exeLen; PayloadBytes = payloadBytes;
        }

        public static PayloadArchive TryOpen(string exePath)
        {
            FileStream fs = null;
            try
            {
                fs = new FileStream(exePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
                long len = fs.Length;
                if (len < FooterSize + 2) { fs.Dispose(); return null; }

                byte[] footer = new byte[FooterSize];
                fs.Seek(len - FooterSize, SeekOrigin.Begin);
                if (ReadExact(fs, footer, FooterSize) != FooterSize) { fs.Dispose(); return null; }
                for (int i = 0; i < Magic.Length; i++)
                    if (footer[8 + i] != Magic[i]) { fs.Dispose(); return null; }

                long indexLen = BitConverter.ToInt64(footer, 0);
                if (indexLen <= 0 || indexLen > 64L * 1024 * 1024 || indexLen > len - FooterSize) { fs.Dispose(); return null; }
                long indexPos = len - FooterSize - indexLen;

                byte[] idx = new byte[indexLen];
                fs.Seek(indexPos, SeekOrigin.Begin);
                if (ReadExact(fs, idx, idx.Length) != idx.Length) { fs.Dispose(); return null; }

                var map = ParseIndex(Encoding.UTF8.GetString(idx));
                if (map == null || map.Count == 0) { fs.Dispose(); return null; }

                long payloadBytes = indexPos - 0;   // 数据块从 exe 原始末尾开始，这里仅作展示
                return new PayloadArchive(fs, map, exePath, len, payloadBytes);
            }
            catch
            {
                if (fs != null) { try { fs.Dispose(); } catch { } }
                return null;
            }
        }

        private static int ReadExact(Stream s, byte[] buf, int count)
        {
            int got = 0;
            while (got < count)
            {
                int n = s.Read(buf, got, count - got);
                if (n <= 0) break;
                got += n;
            }
            return got;
        }

        private static Dictionary<string, Entry> ParseIndex(string json)
        {
            // 极简 JSON 解析（避免依赖 JsonSerializer 的反射裁剪问题）
            var map = new Dictionary<string, Entry>(StringComparer.OrdinalIgnoreCase);
            int i = json.IndexOf("\"e\"", StringComparison.Ordinal);
            if (i < 0) return null;
            int arr = json.IndexOf('[', i);
            if (arr < 0) return null;
            int p = arr + 1;
            while (p < json.Length)
            {
                while (p < json.Length && (json[p] == ',' || char.IsWhiteSpace(json[p]))) p++;
                if (p >= json.Length || json[p] == ']') break;
                if (json[p] != '[') break;
                p++;
                var vals = new List<string>(5);
                var sb = new StringBuilder();
                bool inStr = false;
                while (p < json.Length)
                {
                    char c = json[p];
                    if (inStr)
                    {
                        if (c == '\\' && p + 1 < json.Length) { sb.Append(json[p + 1]); p += 2; continue; }
                        if (c == '"') { inStr = false; p++; continue; }
                        sb.Append(c); p++;
                    }
                    else
                    {
                        if (c == '"') { inStr = true; sb.Length = 0; p++; continue; }
                        if (c == ',' || c == ']') { vals.Add(sb.ToString().Trim()); sb.Length = 0; p++; if (c == ']') break; continue; }
                        if (c == '[') { p++; continue; }
                        if (char.IsWhiteSpace(c)) { p++; continue; }
                        sb.Append(c); p++;
                    }
                }
                if (vals.Count >= 5)
                {
                    var e = new Entry();
                    e.Offset = long.Parse(vals[1], CultureInfo.InvariantCulture);
                    e.StoredLen = long.Parse(vals[2], CultureInfo.InvariantCulture);
                    e.RawLen = long.Parse(vals[3], CultureInfo.InvariantCulture);
                    e.Method = int.Parse(vals[4], CultureInfo.InvariantCulture);
                    map[vals[0].Replace('\\', '/').TrimStart('/')] = e;
                }
            }
            return map;
        }

        private byte[] ReadRaw(Entry e, long skip, int count)
        {
            var buf = new byte[count];
            int got = 0;
            while (got < count)
            {
                int n = RandomAccess.Read(_handle, buf.AsSpan(got, count - got), e.Offset + skip + got);
                if (n <= 0) break;
                got += n;
            }
            if (got != count) throw new EndOfStreamException();
            return buf;
        }

        public Entry? Lookup(string relPath)
        {
            string k = relPath.Replace('\\', '/').TrimStart('/');
            Entry e;
            if (_map.TryGetValue(k, out e)) return e;
            return null;
        }

        /// 读出完整内容（自动解压）
        public byte[] ReadAll(Entry e)
        {
            if (e.Method == 0) return ReadRaw(e, 0, (int)e.StoredLen);
            byte[] comp = ReadRaw(e, 0, (int)e.StoredLen);
            using (var ms = new MemoryStream(comp))
            using (var ds = new DeflateStream(ms, CompressionMode.Decompress))
            {
                var outBuf = new byte[e.RawLen];
                int got = 0;
                while (got < outBuf.Length)
                {
                    int n = ds.Read(outBuf, got, outBuf.Length - got);
                    if (n <= 0) break;
                    got += n;
                }
                return outBuf;
            }
        }

        /// 仅对 store 条目做区间读（用于 Range 请求）
        public byte[] ReadStoredRange(Entry e, long skip, int count)
        {
            return ReadRaw(e, skip, count);
        }

        public void Dispose()
        {
            try { if (_fs != null) _fs.Dispose(); } catch { }
        }
    }


    // ============================================================ HTTP 服务器
    internal sealed class MiniHttpServer
    {
        private readonly string _root;          // 磁盘模式根目录（可为 null）
        private readonly PayloadArchive _arc;   // 归档模式
        private readonly int _port;
        private readonly string _host;
        private TcpListener _listener;
        public int Port { get; private set; }

        // MIME 表见 HttpMime（HTTP 与 WebView2 拦截共用）

        public MiniHttpServer(string root, PayloadArchive arc, int port, string host)
        {
            _root = string.IsNullOrEmpty(root) ? null : Path.GetFullPath(root);
            _arc = arc;
            _port = port;
            _host = string.IsNullOrEmpty(host) ? "127.0.0.1" : host;
        }

        public void Start()
        {
            IPAddress addr = _host == "0.0.0.0"
                ? IPAddress.Any
                : (_host == "localhost" ? IPAddress.Loopback : IPAddress.Parse(_host));

            for (int p = _port; p < _port + 10; p++)
            {
                try { _listener = new TcpListener(addr, p); _listener.Start(); Port = p; break; }
                catch (SocketException) { _listener = null; }
            }
            if (_listener == null) throw new IOException("找不到可用端口（从 " + _port + " 试了 10 个）");
            new Thread(AcceptLoop) { IsBackground = true, Name = "http-accept" }.Start();
        }

        private void AcceptLoop()
        {
            while (true)
            {
                TcpClient c;
                try { c = _listener.AcceptTcpClient(); }
                catch { return; }
                ThreadPool.QueueUserWorkItem(_ => { try { Handle(c); } catch { } finally { try { c.Close(); } catch { } } });
            }
        }

        private static string Reason(int code)
        {
            switch (code)
            {
                case 200: return "OK";
                case 206: return "Partial Content";
                case 403: return "Forbidden";
                case 404: return "Not Found";
                case 405: return "Method Not Allowed";
                default: return "Error";
            }
        }

        private void Handle(TcpClient client)
        {
            client.NoDelay = true;
            using (var ns = client.GetStream())
            {
                ns.ReadTimeout = 15000; ns.WriteTimeout = 60000;

                var buf = new byte[8192];
                var sb = new StringBuilder();
                int total = 0;
                while (total < 65536)
                {
                    int n = ns.Read(buf, 0, buf.Length);
                    if (n <= 0) return;
                    total += n;
                    sb.Append(Encoding.ASCII.GetString(buf, 0, n));
                    if (sb.ToString().IndexOf("\r\n\r\n", StringComparison.Ordinal) >= 0) break;
                }
                string head = sb.ToString();
                int hEnd = head.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                if (hEnd < 0) return;
                string[] lines = head.Substring(0, hEnd).Split(new[] { "\r\n" }, StringSplitOptions.None);
                if (lines.Length == 0) return;
                string[] req = lines[0].Split(' ');
                if (req.Length < 2) return;

                string method = req[0].ToUpperInvariant();
                string rawPath = req[1];
                var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                for (int i = 1; i < lines.Length; i++)
                {
                    int c = lines[i].IndexOf(':');
                    if (c > 0) headers[lines[i].Substring(0, c).Trim()] = lines[i].Substring(c + 1).Trim();
                }
                if (method != "GET" && method != "HEAD")
                {
                    WriteSimple(ns, 405, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes("Method Not Allowed"), false);
                    return;
                }

                int q = rawPath.IndexOf('?');
                if (q >= 0) rawPath = rawPath.Substring(0, q);
                string rel;
                try { rel = Uri.UnescapeDataString(rawPath); } catch { rel = rawPath; }
                rel = rel.Replace('\\', '/').TrimStart('/');
                if (rel.Length == 0 || rel.EndsWith("/")) rel += "index.html";

                string rangeHdr;
                headers.TryGetValue("Range", out rangeHdr);

                if (_arc != null)
                    ServeFromArchive(ns, method, rel, rangeHdr);
                else
                    ServeFromDisk(ns, method, rel, rangeHdr);
            }
        }

        // ---------------- 归档模式 ----------------
        private void ServeFromArchive(NetworkStream ns, string method, string rel, string rangeHdr)
        {
            if (rel.Contains("..")) { WriteSimple(ns, 403, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes("Forbidden"), method == "HEAD"); return; }
            var maybe = _arc.Lookup(rel);
            if (maybe == null)
            {
                if (rel.EndsWith("/index.html"))
                {
                    WriteSimple(ns, 404, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes("Not Found: " + rel), method == "HEAD");
                    return;
                }
                WriteSimple(ns, 404, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes("Not Found: " + rel), method == "HEAD");
                return;
            }
            var e = maybe.Value;
            string ctype = GetMime(rel);

            // deflate 条目内容小，直接整块给
            if (e.Method != 0)
            {
                byte[] body = _arc.ReadAll(e);
                WriteSimple(ns, 200, ctype, body, method == "HEAD");
                return;
            }

            long start = 0, end = e.RawLen - 1;
            bool partial = false;
            if (!string.IsNullOrEmpty(rangeHdr) && rangeHdr.StartsWith("bytes=", StringComparison.OrdinalIgnoreCase))
            {
                string spec = rangeHdr.Substring(6).Split(',')[0].Trim();
                int dash = spec.IndexOf('-');
                if (dash >= 0)
                {
                    string a = spec.Substring(0, dash).Trim();
                    string b = spec.Substring(dash + 1).Trim();
                    if (a.Length == 0)
                    {
                        long suffix;
                        if (long.TryParse(b, NumberStyles.Integer, CultureInfo.InvariantCulture, out suffix) && suffix > 0)
                        { start = Math.Max(0, e.RawLen - suffix); end = e.RawLen - 1; partial = true; }
                    }
                    else
                    {
                        long s0, e0;
                        if (long.TryParse(a, NumberStyles.Integer, CultureInfo.InvariantCulture, out s0))
                        {
                            start = s0;
                            end = b.Length == 0 ? e.RawLen - 1
                                  : (long.TryParse(b, NumberStyles.Integer, CultureInfo.InvariantCulture, out e0) ? e0 : e.RawLen - 1);
                            if (end > e.RawLen - 1) end = e.RawLen - 1;
                            if (start <= end) partial = true;
                        }
                    }
                }
            }
            if (start < 0 || start > e.RawLen - 1) { start = 0; end = e.RawLen - 1; partial = false; }
            long len = end - start + 1;

            var hs = new StringBuilder();
            hs.Append("HTTP/1.1 ").Append(partial ? 206 : 200).Append(' ').Append(Reason(partial ? 206 : 200)).Append("\r\n");
            hs.Append("Content-Type: ").Append(ctype).Append("\r\n");
            hs.Append("Content-Length: ").Append(len).Append("\r\n");
            hs.Append("Accept-Ranges: bytes\r\n");
            if (partial) hs.Append("Content-Range: bytes ").Append(start).Append('-').Append(end).Append('/').Append(e.RawLen).Append("\r\n");
            hs.Append("Cache-Control: no-store, no-cache, must-revalidate\r\n");
            hs.Append("Pragma: no-cache\r\n");
            hs.Append("Access-Control-Allow-Origin: *\r\n");
            hs.Append("Connection: close\r\n\r\n");
            byte[] hb = Encoding.ASCII.GetBytes(hs.ToString());
            ns.Write(hb, 0, hb.Length);

            if (method == "GET")
            {
                const int CHUNK = 256 * 1024;
                long pos = start;
                while (pos <= end)
                {
                    int n = (int)Math.Min(CHUNK, end - pos + 1);
                    byte[] chunk = _arc.ReadStoredRange(e, pos, n);
                    ns.Write(chunk, 0, chunk.Length);
                    pos += n;
                }
            }
            ns.Flush();
        }

        // ---------------- 磁盘模式 ----------------
        private void ServeFromDisk(NetworkStream ns, string method, string rel, string rangeHdr)
        {
            string full = Path.GetFullPath(Path.Combine(_root, rel.Replace('/', Path.DirectorySeparatorChar)));
            if (!full.StartsWith(_root, StringComparison.OrdinalIgnoreCase))
            {
                WriteSimple(ns, 403, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes("Forbidden"), method == "HEAD");
                return;
            }
            if (Directory.Exists(full)) full = Path.Combine(full, "index.html");
            if (!File.Exists(full))
            {
                WriteSimple(ns, 404, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes("Not Found: " + rel), method == "HEAD");
                return;
            }
            using (var fs = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            {
                long fileLen = fs.Length;
                long start = 0, end = fileLen - 1;
                bool partial = false;
                if (!string.IsNullOrEmpty(rangeHdr) && rangeHdr.StartsWith("bytes=", StringComparison.OrdinalIgnoreCase))
                {
                    string spec = rangeHdr.Substring(6).Split(',')[0].Trim();
                    int dash = spec.IndexOf('-');
                    if (dash >= 0)
                    {
                        string a = spec.Substring(0, dash).Trim();
                        string b = spec.Substring(dash + 1).Trim();
                        if (a.Length == 0)
                        {
                            long suffix;
                            if (long.TryParse(b, out suffix) && suffix > 0) { start = Math.Max(0, fileLen - suffix); end = fileLen - 1; partial = true; }
                        }
                        else
                        {
                            long s0, e0;
                            if (long.TryParse(a, out s0))
                            {
                                start = s0;
                                end = b.Length == 0 ? fileLen - 1 : (long.TryParse(b, out e0) ? e0 : fileLen - 1);
                                if (end > fileLen - 1) end = fileLen - 1;
                                if (start <= end) partial = true;
                            }
                        }
                    }
                }
                if (start < 0 || start > fileLen - 1) { start = 0; end = fileLen - 1; partial = false; }
                long len = end - start + 1;

                var hs = new StringBuilder();
                hs.Append("HTTP/1.1 ").Append(partial ? 206 : 200).Append(' ').Append(Reason(partial ? 206 : 200)).Append("\r\n");
                hs.Append("Content-Type: ").Append(GetMime(full)).Append("\r\n");
                hs.Append("Content-Length: ").Append(len).Append("\r\n");
                hs.Append("Accept-Ranges: bytes\r\n");
                if (partial) hs.Append("Content-Range: bytes ").Append(start).Append('-').Append(end).Append('/').Append(fileLen).Append("\r\n");
                hs.Append("Cache-Control: no-store, no-cache, must-revalidate\r\n");
                hs.Append("Pragma: no-cache\r\n");
                hs.Append("Access-Control-Allow-Origin: *\r\n");
                hs.Append("Connection: close\r\n\r\n");
                byte[] hb = Encoding.ASCII.GetBytes(hs.ToString());
                ns.Write(hb, 0, hb.Length);

                if (method == "GET")
                {
                    fs.Seek(start, SeekOrigin.Begin);
                    var chunk = new byte[256 * 1024];
                    long left = len;
                    while (left > 0)
                    {
                        int n = fs.Read(chunk, 0, (int)Math.Min(chunk.Length, left));
                        if (n <= 0) break;
                        ns.Write(chunk, 0, n);
                        left -= n;
                    }
                }
                ns.Flush();
            }
        }

        private static string GetMime(string path)
        {
            return HttpMime.Get(path);
        }

        private static void WriteSimple(NetworkStream ns, int code, string ctype, byte[] body, bool headOnly)
        {
            var hs = new StringBuilder();
            hs.Append("HTTP/1.1 ").Append(code).Append(' ').Append(Reason(code)).Append("\r\n");
            hs.Append("Content-Type: ").Append(ctype).Append("\r\n");
            hs.Append("Content-Length: ").Append(body.Length).Append("\r\n");
            hs.Append("Cache-Control: no-store\r\n");
            hs.Append("Connection: close\r\n\r\n");
            byte[] hb = Encoding.ASCII.GetBytes(hs.ToString());
            ns.Write(hb, 0, hb.Length);
            if (!headOnly) ns.Write(body, 0, body.Length);
            ns.Flush();
        }
    }
}
