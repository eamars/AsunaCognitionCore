/** Builds the worker's Python environment on first start: a venv in the profile's data folder, installed from the
 * package's `requirements.lock` with uv, or with any Python 3.12+ and pip.
 *
 * The lock is the exact dependency closure the worker was tested with; uv is used when it is on PATH (it can also
 * fetch a Python itself). A built environment is reused until the lock changes. Nothing is installed at
 * plugin-install time, so DSH's ban on install scripts is never in the way. */
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

const MARKER = 'asuna-environment.json';

function run(command, args, { cwd, timeout = 15 * 60_000 } = {}) {
  return new Promise(resolve => {
    let child;
    try {
      child = spawn(command, args, { cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONUTF8: '1', PIP_DISABLE_PIP_VERSION_CHECK: '1' } });
    } catch (error) { resolve({ code: -1, output: String(error) }); return; }
    let output = '';
    const keep = data => { output = (output + data).slice(-4000); };
    child.stdout.on('data', keep); child.stderr.on('data', keep);
    const timer = setTimeout(() => child.kill(), timeout);
    child.once('error', error => { clearTimeout(timer); resolve({ code: -1, output: String(error) }); });
    child.once('exit', code => { clearTimeout(timer); resolve({ code: code ?? -1, output }); });
  });
}

const venvPython = env => process.platform === 'win32' ? path.join(env, 'Scripts', 'python.exe') : path.join(env, 'bin', 'python');

/** A Python 3.12+ on this machine, as [command, ...args], or null. */
async function basePython() {
  const candidates = process.platform === 'win32'
    ? [['py', '-3.13'], ['py', '-3.12'], ['python'], ['python3']] : [['python3.13'], ['python3.12'], ['python3'], ['python']];
  for (const [command, ...args] of candidates) {
    const probe = await run(command, [...args, '-c', 'import sys; print(sys.version_info >= (3, 12))'], { timeout: 20_000 });
    if (probe.code === 0 && probe.output.trim().endsWith('True')) return [command, ...args];
  }
  return null;
}

/**
 * @param {{ dataRoot: string, workerPath: string, report?: (step: string) => void }} options
 * @returns {Promise<string>} the environment's python executable
 */
export async function ensurePythonEnvironment({ dataRoot, workerPath, report = () => {} }) {
  const lockFile = path.join(workerPath, 'requirements.lock');
  const lock = await fs.readFile(lockFile).catch(() => null);
  if (!lock) throw new Error('PYTHON_LOCK_MISSING: the installed package has no python/requirements.lock');
  const digest = createHash('sha256').update(lock).digest('hex');
  const env = path.join(dataRoot, 'python');
  const python = venvPython(env);
  const marker = await fs.readFile(path.join(env, MARKER), 'utf8').then(JSON.parse).catch(() => null);
  if (marker?.lock === digest && await fs.access(python).then(() => true, () => false)) return python;

  await fs.rm(env, { recursive: true, force: true });
  await fs.mkdir(dataRoot, { recursive: true });
  const uv = await run('uv', ['--version'], { timeout: 20_000 });
  let steps;
  if (uv.code === 0) {
    report('uv');                     // a step key: the settings card words it (settings.step.*)
    steps = [['uv', ['venv', '--python', '3.12', env]], ['uv', ['pip', 'install', '--python', python, '-r', lockFile]]];
  } else {
    const base = await basePython();
    if (!base) throw new Error('PYTHON_NOT_FOUND: install uv (https://docs.astral.sh/uv/) or Python 3.12+, then apply the settings again');
    report('python');
    const [command, ...args] = base;
    steps = [[command, [...args, '-m', 'venv', env]], [python, ['-m', 'pip', 'install', '--no-input', '-r', lockFile]]];
  }
  for (const [command, args] of steps) {
    const result = await run(command, args, { cwd: dataRoot });
    if (result.code !== 0) {
      await fs.rm(env, { recursive: true, force: true });
      throw new Error('PYTHON_ENVIRONMENT_FAILED: ' + [command, ...args.slice(0, 2)].join(' ') + ': ' + result.output.trim().slice(-600));
    }
  }
  await fs.writeFile(path.join(env, MARKER), JSON.stringify({ lock: digest, built_at: new Date().toISOString(),
    with: uv.code === 0 ? 'uv' : 'pip' }));
  report('ready');
  return python;
}
