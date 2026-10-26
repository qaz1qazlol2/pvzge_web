// 用无头 Edge + CDP 检查游戏是否真正启动（canvas / audioEngine / 场景）。
const http = require('http');
const net = require('net');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const EDGE = fs.existsSync('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe')
  ? 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
  : 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9337;
const PROFILE = path.join(os.tmpdir(), '_edge_boot2');
// 用法: node check_boot.js [url]
// 默认连本地静态服务器（serve_pvzge.py 8199）
const TARGET = process.argv[2] || 'http://127.0.0.1:8199/index.html';

const sleep = ms => new Promise(r => setTimeout(r, ms));

function req(method, p) {
  return new Promise((res, rej) => {
    const r = http.request({ host: '127.0.0.1', port: PORT, path: p, method }, s => {
      let b = '';
      s.on('data', d => (b += d));
      s.on('end', () => { try { res(JSON.parse(b)); } catch (e) { res(b); } });
    });
    r.on('error', rej);
    r.end();
  });
}

function wsConnect(u) {
  return new Promise((res, rej) => {
    const url = new URL(u);
    const key = crypto.randomBytes(16).toString('base64');
    const sock = net.connect(Number(url.port || 80), url.hostname, () => {
      sock.write(`GET ${url.pathname}${url.search} HTTP/1.1\r\nHost: ${url.host}\r\n` +
        `Upgrade: websocket\r\nConnection: Upgrade\r\n` +
        `Sec-WebSocket-Key: ${key}\r\nSec-WebSocket-Version: 13\r\n\r\n`);
    });
    let buf = Buffer.alloc(0), up = false;
    const msgs = [];
    sock.on('data', c => {
      buf = Buffer.concat([buf, c]);
      if (!up) {
        const i = buf.indexOf('\r\n\r\n');
        if (i < 0) return;
        buf = buf.slice(i + 4);
        up = true;
        res({
          send: o => sendFrame(sock, JSON.stringify(o)),
          on: f => msgs.push(f),
          close: () => sock.destroy(),
        });
      }
      while (buf.length >= 2) {
        const b0 = buf[0], b1 = buf[1], op = b0 & 0x0f;
        let len = b1 & 0x7f, off = 2;
        if (len === 126) { if (buf.length < 4) return; len = buf.readUInt16BE(2); off = 4; }
        else if (len === 127) { if (buf.length < 10) return; len = Number(buf.readBigUInt64BE(2)); off = 10; }
        if (buf.length < off + len) return;
        const p = buf.slice(off, off + len);
        buf = buf.slice(off + len);
        if (op === 1) { try { const j = JSON.parse(p.toString()); msgs.forEach(f => f(j)); } catch (e) { } }
      }
    });
    sock.on('error', rej);
  });
}

function sendFrame(sock, str) {
  const pl = Buffer.from(str, 'utf8');
  const n = pl.length;
  let h;
  if (n < 126) h = Buffer.from([0x81, 0x80 | n]);
  else { h = Buffer.alloc(4); h[0] = 0x81; h[1] = 0x80 | 126; h.writeUInt16BE(n, 2); }
  const m = crypto.randomBytes(4);
  const out = Buffer.alloc(n);
  for (let i = 0; i < n; i++) out[i] = pl[i] ^ m[i % 4];
  sock.write(Buffer.concat([h, m, out]));
}

(async () => {
  const edge = spawn(EDGE, ['--headless=new', '--disable-gpu',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--no-first-run', '--no-default-browser-check',
    '--autoplay-policy=no-user-gesture-required', '--mute-audio', 'about:blank'],
    { stdio: 'ignore' });

  let v = null;
  for (let i = 0; i < 40; i++) { await sleep(500); try { v = await req('GET', '/json/version'); break; } catch (e) { } }
  if (!v) { console.log('DevTools 未就绪'); edge.kill(); process.exit(1); }

  const tab = await req('PUT', '/json/new?' + encodeURIComponent(TARGET));
  const ws = await wsConnect(tab.webSocketDebuggerUrl);

  const errs = [];
  ws.on(m => {
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errs.push('EXC: ' + (d.exception && (d.exception.description || d.exception.value) || d.text));
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      errs.push('CONSOLE: ' + m.params.args.map(a => a.value || a.description || '').join(' '));
    }
  });

  let id = 0;
  const send = (method, params) => ws.send({ id: ++id, method, params: params || {} });
  send('Runtime.enable'); send('Page.enable');
  await sleep(1000);
  send('Page.navigate', { url: TARGET });

  console.log('等待 22s …');
  await sleep(22000);

  const expr = `(function(){
    var o={};
    o.url=location.href;
    o.title=document.title;
    var cv=document.getElementById('GameCanvas');
    o.canvas=cv?cv.width+'x'+cv.height:'none';
    o.cc=typeof cc;
    o.engine=!!window.audioEngine;
    o.clips=window.audioEngine?Object.keys(window.audioEngine.manifest).length:-1;
    o.rz=window.audioEngine?Object.keys(window.audioEngine.manifest).filter(function(k){return k.indexOf('rk_ZBT_')===0}).length:-1;
    o.cysTbl=!!window.__CYS_TBL;
    o.cysFams=window.__CYS_TBL?Object.keys(window.__CYS_TBL).join(','):'-';
    o.cysLbKeys=window.__CYS_TBL&&window.__CYS_TBL.LB?Object.keys(window.__CYS_TBL.LB).length:-1;
    try{
      var _sm=window.__CYS_TBL;
      o.lbBallad=_sm&&_sm.LB?_sm.LB.Eighties:-1;
      o.lbPunk=_sm&&_sm.LB?_sm.LB.Punk:-1;
    }catch(e){o.lbBallad='ERR'}
    o.lb=window.audioEngine?Object.keys(window.audioEngine.manifest).filter(function(k){return k.indexOf('rk_LB_')===0}).length:-1;
    o.resume=typeof window.__cys_resume;
    try{o.scene=cc.director.getScene()?cc.director.getScene().name:'null'}catch(e){o.scene='ERR'}
    return JSON.stringify(o);
  })()`;

  const r = await new Promise(res => {
    const my = ++id;
    ws.on(m => { if (m.id === my) res(m); });
    ws.send({ id: my, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true } });
    setTimeout(() => res({ timeout: true }), 15000);
  });

  console.log('\n=== 运行时状态 ===');
  if (r.timeout) console.log('评估超时');
  else if (r.result && r.result.exceptionDetails) console.log('异常:', JSON.stringify(r.result.exceptionDetails).slice(0, 300));
  else console.log(r.result.result.value);

  console.log('\n=== 启动期错误 (' + errs.length + ') ===');
  errs.slice(0, 8).forEach(e => console.log('  ' + e.slice(0, 260)));
  if (!errs.length) console.log('  无');

  ws.close(); edge.kill(); await sleep(400); process.exit(0);
})().catch(e => { console.log('FATAL', e && e.message); process.exit(1); });
