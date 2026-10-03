/** Stable entry: native Web and repair tools boot without importing Python code. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const base = path.join(root, '.runtime/adr008');
const read = async (file, fallback) => {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT' && fallback !== undefined) return fallback; throw error; }
};
const launch = await read(path.join(base, 'launch.json'));
const env = { ...process.env, DSH_HOME: path.join(base, 'home'), DSH_TELEMETRY_DISABLED: '1' };
if (!launch.native_credentials) {
  const config = await read(launch.config);
  const models = await read(launch.config.replace(/\.json$/, '.models.local.json'), {});
  for (const [lane, source] of [['character', launch.shared_action_model ? 'executor' : 'character'], ['action', 'executor']])
    env['ASUNA_NATIVE_' + lane.toUpperCase() + '_KEY'] = (models[source] || config[source]).api_key || 'local-no-auth';
}
const dsh = path.join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js');
async function run(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [dsh, ...args], { cwd: root, env, windowsHide: true, stdio: 'inherit' });
    child.once('error', reject); child.once('exit', code => resolve(code ?? 1));
    const stop = () => child.kill(); process.once('SIGINT', stop); process.once('SIGTERM', stop);
    child.once('exit', () => { process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop); });
  });
}

const selectionPath = path.join(base, 'activation.json');
const selection = await read(selectionPath, { projects: {} });
for (const selected of Object.values(selection.projects)) {
  if (selected.state !== 'HOST_RESTART_REQUIRED') continue;
  try {
    const bytes = await fs.readFile(selected.artifact);
    if (createHash('sha256').update(bytes).digest('hex') !== selected.sha256) throw new Error('Selected artifact digest changed');
    const code = await run(['plugin', '--profile', 'asuna-native', 'add', selected.artifact]);
    if (code !== 0) throw new Error('Native plugin install failed');
    selected.state = 'APPLIED'; selected.installed_at = new Date().toISOString();
    delete selected.install_error;
  } catch (error) {
    selected.install_error = String(error);
    process.stderr.write('Selected plugin could not be installed. Opening native Web with the installed repair floor; the pending candidate is retained.\n');
  }
  await fs.writeFile(selectionPath + '.tmp', JSON.stringify(selection, null, 2));
  await fs.rename(selectionPath + '.tmp', selectionPath);
}
const args = process.argv.slice(2).filter(arg => !['ui', '--native'].includes(arg));
let port = 8780;
for (let index = 0; index < args.length; index++) {
  if (args[index] !== '--port' || !/^\d{2,5}$/.test(args[index + 1] ?? '')) throw new Error('Usage: asuna-launch.mjs ui [--port 8780]');
  port = Number(args[++index]);
}
if (port < 1024 || port > 65535) throw new Error('Invalid local Web port');
process.exitCode = await run(['--profile', 'asuna-native', '--no-open', '--host', '127.0.0.1', '--port', String(port)]);
