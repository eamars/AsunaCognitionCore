/** Stable entry: native Web and repair tools boot without importing Python code. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = async (file, fallback) => {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT' && fallback !== undefined) return fallback; throw error; }
};
const usage = 'Usage: asuna-launch.mjs ui [--profile <name>] [--config <path>] [--port 8780] [--dry-run]';

// The owner's original profile keeps its location; any other profile (e.g. the
// demo) has its own DSH home, activation state and launch record.
export function profileBase(profile) {
  const base = path.join(root, '.runtime/adr008');
  return profile === 'asuna-native' ? base : path.join(base, 'profiles', profile);
}

export async function resolveLaunch(argv, env = process.env) {
  const args = argv.filter(arg => !['ui', '--native'].includes(arg));
  const options = { profile: env.ASUNA_PROFILE || 'asuna-native', config: env.ASUNA_CONFIG || null, port: 8780, dryRun: false };
  for (let index = 0; index < args.length; index++) {
    const flag = args[index], value = args[index + 1];
    if (flag === '--dry-run') { options.dryRun = true; continue; }
    if (!['--port', '--profile', '--config'].includes(flag) || value === undefined) throw new Error(usage);
    index++;
    if (flag === '--port') {
      if (!/^\d{2,5}$/.test(value)) throw new Error(usage);
      options.port = Number(value);
    } else options[flag.slice(2)] = value;
  }
  if (!/^[a-z][a-z0-9-]{0,50}$/.test(options.profile)) throw new Error('Invalid profile name');
  if (options.port < 1024 || options.port > 65535) throw new Error('Invalid local Web port');
  const base = profileBase(options.profile);
  const launch = await read(path.join(base, 'launch.json'), options.dryRun ? {} : undefined);
  const config = path.resolve(root, options.config ?? launch.config ?? 'config/local.json');
  if (launch.config && path.resolve(launch.config) !== config)
    throw new Error('Profile ' + options.profile + ' was installed for a different local configuration');
  const local = await read(config);
  return { profile: options.profile, base, home: path.join(base, 'home'), config, database: local.database,
    port: options.port, dryRun: options.dryRun, sharedActionModel: Boolean(launch.shared_action_model), local };
}

async function main() {
  const launch = await resolveLaunch(process.argv.slice(2));
  if (launch.dryRun) {
    const { local, ...visible } = launch;
    process.stdout.write(JSON.stringify(visible) + '\n'); return 0;
  }
  const models = await read(launch.config.replace(/\.json$/, '.models.local.json'), {});
  const env = { ...process.env, DSH_HOME: launch.home, DSH_TELEMETRY_DISABLED: '1' };
  for (const [lane, source] of [['character', launch.sharedActionModel ? 'executor' : 'character'], ['action', 'executor']]) {
    env['ASUNA_NATIVE_' + lane.toUpperCase() + '_KEY'] = (models[source] || launch.local[source]).api_key || 'local-no-auth';
  }
  const dsh = path.join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js');
  const run = args => new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [dsh, ...args], { cwd: root, env, windowsHide: true, stdio: 'inherit' });
    child.once('error', reject); child.once('exit', code => resolve(code ?? 1));
    const stop = () => child.kill(); process.once('SIGINT', stop); process.once('SIGTERM', stop);
    child.once('exit', () => { process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop); });
  });

  const selectionPath = path.join(launch.base, 'activation.json');
  const selection = await read(selectionPath, { projects: {} });
  for (const selected of Object.values(selection.projects)) {
    if (selected.state !== 'HOST_RESTART_REQUIRED') continue;
    try {
      const bytes = await fs.readFile(selected.artifact);
      if (createHash('sha256').update(bytes).digest('hex') !== selected.sha256) throw new Error('Selected artifact digest changed');
      const code = await run(['plugin', '--profile', launch.profile, 'add', selected.artifact]);
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
  return run(['--profile', launch.profile, '--no-open', '--host', '127.0.0.1', '--port', String(launch.port)]);
}

if (path.resolve(process.argv[1] ?? '') === fileURLToPath(import.meta.url)) process.exitCode = await main();
