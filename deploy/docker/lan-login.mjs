// LAN access without a login token, as the owner's existing DSH container has it (ADR-019 §6.1 Q6, owner 2026-10-07).
// The LAN and the host's firewall are the access boundary. Patches the checkout's installed DSH client connection:
// - the browser reports a loopback authority, so DSH's loopback-only settings (Settings > Models) work through the
//   HTTPS proxy, which already presents a loopback Host and Origin to DSH's server-side fence;
// - page and RPC authentication accept every request, and the printed URL carries no token.
// Idempotent; fails loudly when DSH's code no longer matches, so an upgrade cannot silently keep or drop the patch.
import fs from 'node:fs';
import path from 'node:path';

const checkout = process.argv[2] ?? process.cwd();
const folder = path.join(checkout, 'node_modules', '@deepseek-ai', 'dsh-client-connection', 'lib');
const MARK = '/* asuna-lan-login */';

function patch(file, change) {
  const target = path.join(folder, file);
  const source = fs.readFileSync(target, 'utf8');
  if (source.includes(MARK)) return false;
  fs.writeFileSync(target, change(source) + '\n' + MARK + '\n');
  return true;
}

const client = patch('client.js', source => {
  const pattern = /isLoopback:\s*(?:transport\?\.ownsHost === true \|\| )?pageLocation === void 0 \|\| isLoopbackHostname\(pageLocation\.hostname\),/;
  if (!pattern.test(source)) throw new Error('lan-login: the client loopback expression changed in this DSH; update the patch');
  return source.replace(pattern, 'isLoopback: true,');
});

const server = patch('index.js', source => {
  let out = source;
  const replaceMethod = (name, params, body) => {
    const start = out.indexOf('\n\t' + name + '(' + params + ') {');
    const end = start < 0 ? -1 : out.indexOf('\n\t}', start);
    if (start < 0 || end < 0) throw new Error('lan-login: ' + name + ' changed in this DSH; update the patch');
    out = out.slice(0, start) + '\n\t' + name + '(' + params + ') {\n\t\t' + body + '\n\t}' + out.slice(end + 3);
  };
  replaceMethod('authenticatedUrl', 'baseUrl', 'const url = new URL(baseUrl); url.search = ""; url.hash = ""; return url.href;');
  replaceMethod('authorizeIndex', 'req, res', 'return true;');
  replaceMethod('isAuthenticated', 'request', 'return true;');
  return out;
});

process.stdout.write('Asuna: LAN login ' + (client || server ? 'patched' : 'already patched') + '\n');
