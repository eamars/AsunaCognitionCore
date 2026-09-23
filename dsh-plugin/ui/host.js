import { readFile } from 'node:fs/promises';

export const inject = ['webServer'];

// DSH owns page delivery; this plugin only adds an embedded view and forwards
// small display and interaction API operations to the existing Python Chat controller.
export function apply(ctx) {
  if (ctx.webServer.host !== '127.0.0.1') throw new Error('ASUNA_UI_LOOPBACK_REQUIRED');
  const origin = `http://127.0.0.1:${ctx.webServer.port}`;
  const assets = {'/asuna/': ['index.html', 'text/html'], '/asuna/workbench.js': ['workbench.js', 'text/javascript'], '/asuna/style.css': ['style.css', 'text/css']};
  ctx.effect(() => ctx.webServer.register({kind: 'prefix', path: '/asuna', async handler(req, res) {
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'self'");
    const reply = (status, data) => { res.writeHead(status, {'Content-Type': 'application/json; charset=utf-8'}); res.end(JSON.stringify(data)); };
    if (req.headers.host !== new URL(origin).host || (req.headers.origin && req.headers.origin !== origin)) return reply(403, {error: '仅允许本机同源访问'});
    const path = new URL(req.url, origin).pathname;
    const asset = assets[path === '/asuna' ? '/asuna/' : path];
    if (asset && req.method === 'GET') {
      res.writeHead(200, {'Content-Type': `${asset[1]}; charset=utf-8`});
      res.end(await readFile(new URL(`./static/${asset[0]}`, import.meta.url)));
      return;
    }
    if (!['/asuna/api/state', '/asuna/api/provider-response', '/asuna/api/send', '/asuna/api/new', '/asuna/api/models', '/asuna/api/models/discover', '/asuna/api/stop', '/asuna/api/integration/stop'].includes(path)) return reply(404, {error: '未知接口'});
    const readOnly = path.endsWith('/state') || path.endsWith('/provider-response');
    if ((readOnly ? req.method !== 'GET' : req.method !== 'POST') || (req.method === 'POST' && req.headers['x-asuna-ui'] !== '1')) return reply(405, {error: '不支持的请求'});
    if (!process.env.ASUNA_UI_BRIDGE || !process.env.ASUNA_UI_TOKEN) return reply(503, {error: 'Asuna 交互进程未连接，请通过 asuna ui 启动。'});
    try {
      let body = '';
      for await (const chunk of req) { body += chunk; if (Buffer.byteLength(body) > 65536) return reply(413, {error: '消息过长'}); }
      const upstream = await fetch(process.env.ASUNA_UI_BRIDGE + path.slice('/asuna/api'.length) + new URL(req.url, origin).search, {
        method: req.method, headers: {'Authorization': `Bearer ${process.env.ASUNA_UI_TOKEN}`, 'Content-Type': 'application/json'},
        body: req.method === 'POST' ? body : undefined, signal: AbortSignal.timeout(25000),
      });
      res.writeHead(upstream.status, {'Content-Type': 'application/json; charset=utf-8'});
      res.end(await upstream.text());
    } catch { reply(503, {error: 'Asuna 连接中断，未自动重发。请检查启动终端。'}); }
  }}), 'Asuna UI route');
}
