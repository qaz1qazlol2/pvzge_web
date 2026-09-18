// PvZ2 Gardendless —— Tauri 单文件启动器
//   资源以 PVZGEARC 归档形式追加在本 exe 尾部，Rust 侧按偏移直接读取（不解压到磁盘），
//   通过自定义协议 `pvzge` 提供给 WebView；Windows 上自动映射为 http://pvzge.localhost
//   （固定 origin、与端口无关，localStorage 存档稳定）。
//
// 归档格式（由 pack.py 生成）:
//   [exe 原始字节][所有文件数据块][index JSON(UTF-8)][u64 LE indexLength][8字节 "PVZGEARC"]
//   index: {"v":1,"e":[["相对路径", offset, storedLen, rawLen, method], ...]}  method: 0=store 1=deflate(裸)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use flate2::read::DeflateDecoder;
use tauri::http::{Request, Response, StatusCode};
use tauri::{WebviewUrl, WebviewWindowBuilder};

const MAGIC: &[u8; 8] = b"PVZGEARC";
const SCHEME: &str = "pvzge"; // Windows 上映射为 http://pvzge.localhost

#[derive(Clone, Copy)]
struct Entry {
    offset: u64,
    stored: u64,
    rawlen: u64,
    method: u8,
}

enum Source {
    /// exe 尾部内嵌归档
    Archive { exe: PathBuf, entries: HashMap<String, Entry> },
    /// 磁盘目录（回退 / 调试）
    Dir(PathBuf),
}

// ---------------------------------------------------------------- 归档读取

fn open_source() -> Source {
    // 1) 优先内嵌归档
    if let Some(s) = try_open_archive() {
        return s;
    }
    // 2) 环境变量 / 命令行 / exe 相对位置（全部相对 exe，不写死机器路径）
    for cand in candidate_roots() {
        if cand.join("index.html").is_file() {
            return Source::Dir(cand);
        }
    }
    Source::Dir(default_fallback())
}

/// 找不到任何游戏目录时的兜底：exe 同级的 docs\（不写死盘符）
fn default_fallback() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|e| e.parent().map(|d| d.join("docs")))
        .unwrap_or_else(|| PathBuf::from("docs"))
}

fn candidate_roots() -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = Vec::new();
    if let Ok(p) = std::env::var("PVZGE_WEB") {
        if !p.is_empty() {
            v.push(PathBuf::from(p));
        }
    }
    let args: Vec<String> = std::env::args().collect();
    for i in 0..args.len() {
        if (args[i] == "--web" || args[i] == "--root") && i + 1 < args.len() {
            v.push(PathBuf::from(&args[i + 1]));
        }
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            v.push(dir.to_path_buf()); // exe 所在目录本身
            v.push(dir.join("web")); // exe 同级 web\
            v.push(dir.join("docs")); // exe 同级 docs\
            v.push(dir.join("..").join("docs")); // exe 上级 docs\（开发态 dist\ → 仓库\docs）
        }
    }
    v
}

fn try_open_archive() -> Option<Source> {
    let exe = std::env::current_exe().ok()?;
    let mut f = File::open(&exe).ok()?;
    let len = f.metadata().ok()?.len();
    if len < 32 {
        return None;
    }
    let mut foot = [0u8; 16];
    f.seek(SeekFrom::Start(len - 16)).ok()?;
    f.read_exact(&mut foot).ok()?;
    if &foot[8..16] != MAGIC {
        return None;
    }
    let idx_len = u64::from_le_bytes(foot[0..8].try_into().ok()?);
    if idx_len == 0 || idx_len > 64 * 1024 * 1024 || idx_len > len - 16 {
        return None;
    }
    let mut idx = vec![0u8; idx_len as usize];
    f.seek(SeekFrom::Start(len - 16 - idx_len)).ok()?;
    f.read_exact(&mut idx).ok()?;

    let v: serde_json::Value = serde_json::from_slice(&idx).ok()?;
    let arr = v.get("e")?.as_array()?;
    let mut entries = HashMap::with_capacity(arr.len());
    for item in arr {
        let a = item.as_array()?;
        let name = a.first()?.as_str()?.replace('\\', "/");
        entries.insert(
            name,
            Entry {
                offset: a.get(1)?.as_u64()?,
                stored: a.get(2)?.as_u64()?,
                rawlen: a.get(3)?.as_u64()?,
                method: (a.get(4)?.as_u64()? & 0xff) as u8,
            },
        );
    }
    if entries.is_empty() {
        return None;
    }
    println!("[pvzge] 内嵌归档: {} 个文件", entries.len());
    Some(Source::Archive { exe, entries })
}

fn read_entry(f: &mut File, e: &Entry) -> std::io::Result<Vec<u8>> {
    f.seek(SeekFrom::Start(e.offset))?;
    let mut buf = vec![0u8; e.stored as usize];
    f.read_exact(&mut buf)?;
    if e.method == 0 {
        Ok(buf)
    } else {
        let mut d = DeflateDecoder::new(&buf[..]);
        let mut out = Vec::with_capacity(e.rawlen as usize);
        d.read_to_end(&mut out)?;
        Ok(out)
    }
}

// ---------------------------------------------------------------- MIME / 路径

fn mime_of(p: &str) -> &'static str {
    let ext = Path::new(p)
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    match ext.as_str() {
        "html" | "htm" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "json" => "application/json; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "wasm" => "application/wasm",
        "mp3" => "audio/mpeg",
        "ogg" => "audio/ogg",
        "wav" => "audio/wav",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "txt" => "text/plain; charset=utf-8",
        "xml" => "application/xml",
        "zip" => "application/zip",
        _ => "application/octet-stream",
    }
}

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            let h = (b[i + 1] as char).to_digit(16);
            let l = (b[i + 2] as char).to_digit(16);
            if let (Some(h), Some(l)) = (h, l) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn parse_range(h: &str, total: u64) -> Option<(u64, u64)> {
    let h = h.trim();
    if !h.to_ascii_lowercase().starts_with("bytes=") {
        return None;
    }
    let spec = h[6..].split(',').next().unwrap_or("").trim();
    let (a, b) = spec.split_once('-')?;
    if a.is_empty() {
        let n: u64 = b.trim().parse().ok()?;
        if n == 0 || total == 0 {
            return None;
        }
        let start = total.saturating_sub(n);
        Some((start, total - 1))
    } else {
        let start: u64 = a.trim().parse().ok()?;
        let end: u64 = if b.trim().is_empty() {
            total.saturating_sub(1)
        } else {
            b.trim().parse().ok()?
        };
        if start > end || start >= total {
            return None;
        }
        Some((start, end.min(total.saturating_sub(1))))
    }
}

/// 可选：把每个请求记到 %LOCALAPPDATA%\com.pvzge.launcher\requests.log
/// 默认关闭；带 `--log` 参数或设 PVZGE_LOG=1 打开。用于排查"游戏到底加载了哪些文件"。
fn log_req(path: &str, status: u16, len: usize) {
    let on = std::env::var("PVZGE_LOG").is_ok()
        || std::env::args().any(|a| a == "--log");
    if !on {
        return;
    }
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| ".".to_string());
    let dir = PathBuf::from(base).join("com.pvzge.launcher");
    let _ = std::fs::create_dir_all(&dir);
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("requests.log"))
    {
        let _ = writeln!(f, "{} {} {}", status, len, path);
    }
}

fn serve_logged(src: &Source, request: &Request<Vec<u8>>) -> Response<Vec<u8>> {
    let resp = serve(src, request);
    log_req(request.uri().path(), resp.status().as_u16(), resp.body().len());
    resp
}

fn build(
    status: u16,
    ctype: &str,
    body: Vec<u8>,
    extra: Vec<(&'static str, String)>,
) -> Response<Vec<u8>> {
    let mut b = Response::builder()
        .status(StatusCode::from_u16(status).unwrap_or(StatusCode::OK))
        .header("Content-Type", ctype)
        .header("Cache-Control", "no-store, no-cache, must-revalidate")
        .header("Pragma", "no-cache")
        .header("Access-Control-Allow-Origin", "*")
        .header("Accept-Ranges", "bytes");
    for (k, v) in extra {
        b = b.header(k, v);
    }
    b.body(body)
        .unwrap_or_else(|_| Response::new(Vec::new()))
}

fn serve(src: &Source, request: &Request<Vec<u8>>) -> Response<Vec<u8>> {
    let raw = request.uri().path().to_string();
    let mut rel = percent_decode(raw.trim_start_matches('/'));
    if rel.is_empty() || rel.ends_with('/') {
        rel.push_str("index.html");
    }
    if rel.contains("..") {
        return build(403, "text/plain; charset=utf-8", b"Forbidden".to_vec(), vec![]);
    }
    let ctype = mime_of(&rel);
    let range_hdr = request
        .headers()
        .get("range")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.to_string());

    match src {
        Source::Archive { exe, entries } => {
            let e = match entries.get(&rel) {
                Some(e) => *e,
                None => {
                    return build(
                        404,
                        "text/plain; charset=utf-8",
                        format!("Not Found: {}", rel).into_bytes(),
                        vec![],
                    )
                }
            };
            let mut f = match File::open(exe) {
                Ok(f) => f,
                Err(err) => {
                    return build(
                        500,
                        "text/plain; charset=utf-8",
                        format!("open exe failed: {}", err).into_bytes(),
                        vec![],
                    )
                }
            };
            let body = match read_entry(&mut f, &e) {
                Ok(b) => b,
                Err(err) => {
                    return build(
                        500,
                        "text/plain; charset=utf-8",
                        format!("read failed: {}", err).into_bytes(),
                        vec![],
                    )
                }
            };
            let total = body.len() as u64;
            if e.method == 0 {
                if let Some((s, en)) = range_hdr.as_deref().and_then(|h| parse_range(h, total)) {
                    let slice = body[s as usize..=(en as usize)].to_vec();
                    return build(
                        206,
                        ctype,
                        slice,
                        vec![("Content-Range", format!("bytes {}-{}/{}", s, en, total))],
                    );
                }
            }
            build(200, ctype, body, vec![])
        }
        Source::Dir(root) => {
            let full = root.join(rel.replace('/', std::path::MAIN_SEPARATOR_STR));
            if !full.is_file() {
                return build(
                    404,
                    "text/plain; charset=utf-8",
                    format!("Not Found: {}", rel).into_bytes(),
                    vec![],
                );
            }
            let body = match std::fs::read(&full) {
                Ok(b) => b,
                Err(err) => {
                    return build(
                        500,
                        "text/plain; charset=utf-8",
                        format!("read failed: {}", err).into_bytes(),
                        vec![],
                    )
                }
            };
            let total = body.len() as u64;
            if let Some((s, en)) = range_hdr.as_deref().and_then(|h| parse_range(h, total)) {
                let slice = body[s as usize..=(en as usize)].to_vec();
                return build(
                    206,
                    ctype,
                    slice,
                    vec![("Content-Range", format!("bytes {}-{}/{}", s, en, total))],
                );
            }
            build(200, ctype, body, vec![])
        }
    }
}

// ---------------------------------------------------------------- main

fn main() {
    let source = Arc::new(open_source());
    match &*source {
        Source::Archive { entries, .. } => println!("[pvzge] 资源来源: 内嵌归档 {} 个文件", entries.len()),
        Source::Dir(p) => println!("[pvzge] 资源来源: 磁盘目录 {}", p.display()),
    }

    let src_for_handler = source.clone();
    tauri::Builder::default()
        .register_asynchronous_uri_scheme_protocol(SCHEME, move |_ctx, request, responder| {
            let s = src_for_handler.clone();
            std::thread::spawn(move || {
                let resp = serve_logged(&s, &request);
                responder.respond(resp);
            });
        })
        .setup(move |app| {
            let url = WebviewUrl::External(
                format!("http://{}.localhost/", SCHEME)
                    .parse()
                    .expect("url"),
            );
            WebviewWindowBuilder::new(app, "main", url)
                .title("PvZ2 Gardendless")
                .inner_size(1280.0, 760.0)
                .min_inner_size(800.0, 600.0)
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("运行 Tauri 应用失败");
}
