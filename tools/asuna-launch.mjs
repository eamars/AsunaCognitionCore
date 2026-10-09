/** Stable entry: native Web and repair tools boot without importing Python code. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import net from 'node:net';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = async (file, fallback) => {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT' && fallback !== undefined) return fallback; throw error; }
};
const usage = 'Usage: asuna-launch.mjs ui [--profile <name>] [--config <path>] [--port <port>] [--no-sync] [--once] [--dry-run] | --list';
const exists = file => fs.access(file).then(() => true, () => false);

// DSH installs plugins by running `pnpm` from PATH. Node ships pnpm through corepack, so a machine
// without its own pnpm still has one: the DSH child gets a one-line shim to it. Without this, every
// restart meant to activate a published candidate falls back to the repair floor.
export async function packageManagerEnv(env, { nodeDir = path.dirname(process.execPath),
  shimDir = path.join(root, '.runtime/bin') } = {}) {
  const key = Object.keys(env).find(name => name.toUpperCase() === 'PATH') ?? 'PATH';
  const dirs = (env[key] ?? '').split(path.delimiter).filter(Boolean);
  const names = process.platform === 'win32' ? ['pnpm.cmd', 'pnpm.exe'] : ['pnpm'];
  for (const dir of dirs) for (const name of names) if (await exists(path.join(dir, name))) return env;
  const corepack = path.join(nodeDir, process.platform === 'win32' ? 'corepack.cmd' : 'corepack');
  if (!await exists(corepack)) return env;
  await fs.mkdir(shimDir, { recursive: true });
  if (process.platform === 'win32') await fs.writeFile(path.join(shimDir, 'pnpm.cmd'), `@"${corepack}" pnpm %*\r\n`);
  else await fs.writeFile(path.join(shimDir, 'pnpm'), `#!/bin/sh\nexec "${corepack}" pnpm "$@"\n`, { mode: 0o755 });
  return { ...env, [key]: [shimDir, ...dirs].join(path.delimiter), COREPACK_ENABLE_DOWNLOAD_PROMPT: '0' };
}

// The checkout's own Python (uv sync), which runs the pack and install tools; the worker has its own (python-env.js).
export const checkoutPython = (base = root, platform = process.platform) =>
  platform === 'win32' ? path.join(base, '.venv', 'Scripts', 'python.exe') : path.join(base, '.venv', 'bin', 'python');

/** Which packed packages differ from the ones this profile last installed, or were never installed (a channel
 * package newly added to the profile), by name; all of them when nothing is recorded. */
export function changedPackages(installed, packed) {
  const wanted = Object.keys(installed ?? {});
  if (!wanted.length) return null;
  const now = Object.fromEntries((packed ?? []).map(artifact => [artifact.name, artifact.sha256]));
  return [...wanted.filter(name => now[name] !== installed[name]), ...Object.keys(now).filter(name => !(name in installed))];
}

/** Owner 2026-10-07: a start installs what the checkout holds now, so a change never waits on a manual install.
 * Packing is deterministic, so packing and comparing digests with the last install is the change check; only a
 * difference runs the installer, which records the previous running package so a start that never comes up returns
 * to it (advanceSelection below). Uncommitted edits are installed too: what is on disk is what runs. */
export async function syncCheckout(launch, exec, report = text => process.stderr.write(text + '\n'),
  { python = checkoutPython(), manifest = path.join(root, '.runtime/adr008/packages/manifest.json') } = {}) {
  const setup = launch.setup;
  if (!setup) { report('Asuna: this profile does not record its packages yet; run tools/setup_native_profile.py once.'); return 'UNKNOWN'; }
  if (!await exists(python)) { report('Asuna: no checkout environment (.venv); run `uv sync` to let starts install changes.'); return 'NO_PYTHON'; }
  const channels = (setup.channel_packages ?? []).flatMap(directory => ['--channel', directory]);
  if (await exec(python, ['tools/pack_plugins.py', '--persona', setup.persona_package, ...channels], { quiet: true }) !== 0)
    throw new Error('Packing the checkout failed; start with --no-sync to run what is installed');
  const packed = await read(manifest, []);
  const changed = changedPackages(launch.installed, packed);
  if (changed && !changed.length) return 'UP_TO_DATE';
  report('Asuna: installing the checkout (' + (changed ?? ['all packages']).join(', ') + ')');
  const install = ['tools/setup_native_profile.py', '--config', launch.config, '--profile', launch.profile,
    '--persona-package', setup.persona_package, ...(setup.channel_packages ?? []).flatMap(d => ['--channel-package', d]),
    ...(launch.sharedActionModel ? ['--shared-action-model'] : [])];
  if (await exec(python, install) !== 0) throw new Error('Installing the checkout failed; start with --no-sync to run what is installed');
  return 'INSTALLED';
}

// A selection installed but never confirmed running (ACTIVE) counts each start; past this many the
// launcher returns to the previous ACTIVE selection (ADR-011 §6.4). Only which package runs changes;
// the published source is never rolled back.
export const MAX_UNCONFIRMED_STARTS = 2;

/** Advance one start: count unconfirmed selections and revert those that never came up. Returns notes. */
export function advanceSelection(selection, now = new Date().toISOString()) {
  const notes = [];
  for (const [id, selected] of Object.entries(selection.projects ?? {})) {
    if (selected.state !== 'APPLIED') continue;
    selected.boots = (selected.boots ?? 0) + 1;
    if (selected.boots <= MAX_UNCONFIRMED_STARTS) continue;
    if (!selected.previous?.artifact) { notes.push(id + ': never started, and there is no earlier running selection'); continue; }
    const { previous, boots, ...failed } = selected;
    selection.projects[id] = { ...previous, state: 'HOST_RESTART_REQUIRED', reverted_at: now,
      reverted_from: { candidate: failed.candidate, sha256: failed.sha256, published_at: failed.published_at, starts: boots } };
    notes.push(id + ': returned to the previous running selection after ' + boots + ' starts that never came up');
  }
  return notes;
}

// The owner's original profile keeps its location; any other profile (e.g. the
// demo) has its own DSH home, activation state and launch record.
export function profileBase(profile) {
  const base = path.join(root, '.runtime/adr008');
  return profile === 'asuna-native' ? base : path.join(base, 'profiles', profile);
}

export async function resolveLaunch(argv, env = process.env) {
  const args = argv.filter(arg => !['ui', '--native'].includes(arg));
  const options = { profile: env.ASUNA_PROFILE || 'asuna-native', config: env.ASUNA_CONFIG || null, port: null, dryRun: false,
    sync: true, once: false };
  for (let index = 0; index < args.length; index++) {
    const flag = args[index], value = args[index + 1];
    if (flag === '--dry-run') { options.dryRun = true; continue; }
    if (flag === '--no-sync') { options.sync = false; continue; }
    if (flag === '--once') { options.once = true; continue; }       // run DSH once, without the supervisor (ADR-034)
    if (!['--port', '--profile', '--config'].includes(flag) || value === undefined) throw new Error(usage);
    index++;
    if (flag === '--port') {
      if (!/^\d{2,5}$/.test(value)) throw new Error(usage);
      options.port = Number(value);
    } else options[flag.slice(2)] = value;
  }
  if (!/^[a-z][a-z0-9-]{0,50}$/.test(options.profile)) throw new Error('Invalid profile name');
  if (options.port !== null && (options.port < 1024 || options.port > 65535)) throw new Error('Invalid local Web port');
  const base = profileBase(options.profile);
  const launch = await read(path.join(base, 'launch.json'), options.dryRun ? {} : undefined);
  const config = path.resolve(root, options.config ?? launch.config ?? 'config/local.json');
  if (launch.config && path.resolve(launch.config) !== config)
    throw new Error('Profile ' + options.profile + ' was installed for a different local configuration');
  // Native settings own the credentials once imported; the local file is then only a migration source.
  const local = await read(config, launch.native_credentials ? {} : undefined);
  return { profile: options.profile, base, home: path.join(base, 'home'), config, database: local.database,
    // The profile's own port (ADR-020): this start's --port, else the one its install recorded, else 8780.
    port: options.port ?? launch.port ?? 8780, dryRun: options.dryRun, sync: options.sync, once: options.once,
    setup: launch.setup, installed: launch.installed,
    sharedActionModel: Boolean(launch.shared_action_model),
    nativeCredentials: Boolean(launch.native_credentials), local };
}

/** Every installed profile of this checkout: its persona, Web port, database and whether something answers there. */
export async function listProfiles() {
  const base = path.join(root, '.runtime/adr008');
  const names = ['asuna-native', ...await fs.readdir(path.join(base, 'profiles')).catch(() => [])];
  const rows = [];
  for (const profile of names) {
    const launch = await read(path.join(profileBase(profile), 'launch.json'), null);
    if (!launch) continue;
    const local = launch.config ? await read(launch.config, {}) : {};
    const port = launch.port ?? 8780;
    const running = await new Promise(resolve => {
      const socket = net.connect({ host: '127.0.0.1', port }, () => { socket.destroy(); resolve(true); });
      socket.setTimeout(300, () => { socket.destroy(); resolve(false); });
      socket.once('error', () => resolve(false));
    });
    rows.push({ profile, persona: launch.setup ? path.basename(launch.setup.persona_package) : local.chat?.persona ?? '?', port,
      database: local.database ?? '?', running });
  }
  return rows;
}

async function main() {
  if (process.argv.includes('--list')) {
    for (const row of await listProfiles())
      process.stdout.write([row.profile, row.persona, 'port ' + row.port, 'database ' + row.database,
        row.running ? 'answering' : 'not running'].join('  ') + '\n');
    return 0;
  }
  const launch = await resolveLaunch(process.argv.slice(2));
  if (launch.dryRun) {
    const { local, ...visible } = launch;
    process.stdout.write(JSON.stringify(visible) + '\n'); return 0;
  }
  const models = await read(launch.config.replace(/\.json$/, '.models.local.json'), {});
  const env = await packageManagerEnv({ ...process.env, DSH_HOME: launch.home, DSH_TELEMETRY_DISABLED: '1' });
  if (!launch.nativeCredentials)
    for (const [lane, source] of [['character', launch.sharedActionModel ? 'executor' : 'character'], ['action', 'executor']])
      env['ASUNA_NATIVE_' + lane.toUpperCase() + '_KEY'] = (models[source] || launch.local[source]).api_key || 'local-no-auth';
  const dsh = path.join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js');
  const run = args => new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [dsh, ...args], { cwd: root, env, windowsHide: true, stdio: 'inherit' });
    child.once('error', reject); child.once('exit', code => resolve(code ?? 1));
    const stop = () => child.kill(); process.once('SIGINT', stop); process.once('SIGTERM', stop);
    child.once('exit', () => { process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop); });
  });

  const exec = (command, args, { quiet = false } = {}) => new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: root, windowsHide: true, stdio: quiet ? ['ignore', 'ignore', 'inherit'] : 'inherit',
      env: { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' } });
    child.once('error', reject); child.once('exit', code => resolve(code ?? 1));
  });
  const host = ['--profile', launch.profile, '--no-open', '--host', '127.0.0.1', '--port', String(launch.port)];
  if (launch.once) {
    if (launch.sync) await syncCheckout(launch, exec);
    await applySelection(launch, run, advanceSelection);
    return run(host);
  }
  // ADR-034: the launcher stays as DSH's parent and brings it back.
  let stopped = false;
  const stops = [];
  const stop = () => { stopped = true; for (const fn of stops.splice(0)) fn(); };
  process.on('SIGINT', stop); process.on('SIGTERM', stop);
  const supervisor = await import('./asuna-supervisor.mjs');
  const launchFile = path.join(launch.base, 'launch.json');
  await supervisor.supervise({
    prepare: async rung => {
      if (rung === 0) {
        const fresh = await resolveLaunch(process.argv.slice(2));      // the install of a previous start rewrote launch.json
        if (fresh.sync) await syncCheckout(fresh, exec);
        // advanceSelection reverts only a selection that never came up in two starts: that is a fallback too.
        return (await applySelection(launch, run, advanceSelection)).filter(note => note.includes('returned to'));
      } else if (rung === 1) return applySelection(launch, run, supervisor.revertSelections);
    },
    spawnHost: () => spawn(process.execPath, [dsh, ...host], { cwd: root, env: { ...env, ASUNA_SUPERVISED: '1' },
      windowsHide: true, stdio: 'inherit', detached: process.platform !== 'win32' }),
    ready: since => supervisor.readySince(path.join(supervisor.dataRoot(env), 'reports'), since),
    takeRequest: () => supervisor.takeRequest(env),
    loaded: () => supervisor.loaded(launch.base, launchFile),
    writeRecord: record => supervisor.writeRecord(env, record),
    note: text => process.stderr.write(text + '\n'),
    now: () => Date.now(),
    sleep: ms => new Promise(resolve => { const timer = setTimeout(resolve, ms); stops.push(() => { clearTimeout(timer); resolve(); }); }),
    stopped: () => stopped,
    onStop: fn => stops.push(fn),
  });
  return 0;
}

/** Install selected publications waiting for a Host start; `step` decides first (advance or revert). */
async function applySelection(launch, run, step) {
  const selectionPath = path.join(launch.base, 'activation.json');
  const selection = await read(selectionPath, { projects: {} });
  const notes = step(selection);
  for (const note of notes) process.stderr.write('Asuna selection: ' + note + '\n');
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
  if (Object.keys(selection.projects ?? {}).length) {
    await fs.writeFile(selectionPath + '.tmp', JSON.stringify(selection, null, 2));
    await fs.rename(selectionPath + '.tmp', selectionPath);
  }
  return notes;
}

if (path.resolve(process.argv[1] ?? '') === fileURLToPath(import.meta.url)) process.exitCode = await main();
