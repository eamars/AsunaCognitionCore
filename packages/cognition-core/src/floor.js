/** Minimal publication floor, deliberately independent of the business worker.
 * Immutable artifacts run; authorized source candidates remain writable.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export const name = 'asuna-publication-floor';
const packageRoot = fileURLToPath(new URL('../', import.meta.url));
const hash = data => createHash('sha256').update(data).digest('hex');
const excluded = new Set(['.runtime', '.venv', '.git', 'node_modules', '__pycache__', '.pytest_cache', 'reports']);
const protectedPaths = new Set(['start-asuna.cmd', 'tools/asuna-launch.mjs',
  'packages/cognition-core/src/floor.js', 'packages/cognition-core/src/recovery.js',
  'packages/cognition-core/src/persistence.js', 'packages/cognition-core/runtime-manifest.json',
  'src/floor.js', 'src/recovery.js', 'src/persistence.js', 'runtime-manifest.json']);
const privateName = name => /(^|\/)(\.env(?:\..*)?|.*\.local\.json(?:\..*)?|local\.json(?:\..*)?|credentials\.json|secrets\.json|.*\.(?:key|pem|p12|pfx))$/i.test(name);
const inside = (root, value) => { const relative = path.relative(root, value); return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative); };
async function exists(file) { try { await fs.access(file); return true; } catch { return false; } }
async function json(file, fallback) { return await exists(file) ? JSON.parse(await fs.readFile(file, 'utf8')) : fallback; }
async function atomic(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = file + '.' + randomUUID() + '.tmp';
  await fs.writeFile(temporary, JSON.stringify(value, null, 2)); await fs.rename(temporary, file);
}
async function files(root) {
  const result = new Map();
  async function visit(directory) {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      if (excluded.has(entry.name) || entry.isSymbolicLink()) continue;
      const file = path.join(directory, entry.name), relative = path.relative(root, file).split(path.sep).join('/');
      if (privateName(relative) || /\.(?:pyc|tgz)$/.test(relative)) continue;
      if (entry.isDirectory()) await visit(file);
      else if (entry.isFile()) result.set(relative, file);
    }
  }
  await visit(root); return result;
}
async function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true, ...options, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', limited = false;
    const collect = (key, data) => {
      if (stdout.length + stderr.length + data.length > 262144) { limited = true; child.kill(); return; }
      if (key === 'stdout') stdout += data; else stderr += data;
    };
    child.stdout.on('data', data => collect('stdout', data)); child.stderr.on('data', data => collect('stderr', data));
    const timer = setTimeout(() => { limited = true; child.kill(); }, 90000);
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('exit', code => { clearTimeout(timer); resolve({ exit_code: code, stdout, stderr, limited }); });
  });
}

export class PublicationFloor {
  constructor(config) {
    this.config = config;
    this.base = path.join(config.workspace ?? packageRoot, '.runtime/adr008');
    this.activationFile = path.join(this.base, 'activation.json');
    this.projects = new Map((config.projects ?? []).map(project => [project.id, project]));
    this.serial = Promise.resolve();
  }

  async selected() { return json(this.activationFile, { projects: {}, active: {} }); }

  async effective(id) {
    const selected = await this.selected(), pending = selected.projects[id];
    return pending && pending.state !== 'HOST_RESTART_REQUIRED' ? pending : selected.active?.[id];
  }

  async workerPath() {
    return (await this.effective('core'))?.workerPath ?? path.join(packageRoot, 'python');
  }

  async skillPaths(persona) {
    const root = (await this.effective(this.config.defaultProject))?.packageRoot;
    return root ? [path.join(root, 'skills')] : persona.skill_directories;
  }

  async persona(persona) {
    const root = (await this.effective(this.config.defaultProject))?.packageRoot;
    if (!root) return persona;
    return { ...persona, persona_file: path.join(root, 'persona/core.md'),
      skill_directories: [path.join(root, 'skills')] };
  }

  async workerReady(projectId) {
    const selected = await this.selected(); selected.active ??= {};
    const activated = [];
    for (const [id, value] of Object.entries(selected.projects)) {
      if (projectId && id !== projectId) continue;
      if (value.state !== 'APPLIED' && value.state !== 'ACTIVE') continue;
      value.state = 'ACTIVE'; value.activated_at ??= new Date().toISOString();
      selected.active[id] = value; activated.push(value);
    }
    await atomic(this.activationFile, selected); return activated;
  }

  async integrationProject(persona) {
    if (!persona.integration_directory) return null;
    const project = await this.ensure();
    const directory = path.resolve(project.candidate, persona.integration_directory);
    if (!inside(project.candidate, directory)) throw new Error('PERSONA_INTEGRATION_PATH_INVALID');
    return directory;
  }

  async skillWorkspace() {
    return path.join((await this.ensure()).candidate, 'skills');
  }

  async ensure(id = this.config.defaultProject) {
    const project = this.projects.get(id);
    if (!project || !/^[a-z][a-z0-9-]{0,50}$/.test(id)) throw new Error('DEVELOPMENT_PROJECT_NOT_AUTHORIZED');
    const source = path.resolve(project.root);
    const candidate = path.join(this.config.workspace, '.runtime/work/self-development', id);
    const baselineFile = path.join(this.base, 'development', id, 'baseline.json');
    const baseline = await json(baselineFile, {});
    const sourceFiles = await files(source);
    for (const [relative, prior] of Object.entries(baseline)) {
      if (sourceFiles.has(relative)) continue;
      const target = path.resolve(candidate, relative);
      if (!inside(candidate, target)) throw new Error('DEVELOPMENT_BASELINE_PATH_INVALID');
      if (await exists(target) && hash(await fs.readFile(target)) === prior) {
        await fs.unlink(target); delete baseline[relative];
      }
    }
    for (const [relative, file] of sourceFiles) {
      if (project.format === 'repository' && !/^(src\/|packages\/cognition-core\/|config\/prompts\/|docs\/|tests\/|tools\/|migrations\/|examples\/|(?:pyproject.toml|uv.lock|package.json|package-lock.json|README.md|RUN_ASUNA.md|RUNTIME_API.md)$)/.test(relative)) continue;
      const target = path.join(candidate, relative), prior = baseline[relative];
      const present = await exists(target), current = present ? hash(await fs.readFile(target)) : null;
      if (present && current !== prior || !present && prior) continue;
      await fs.mkdir(path.dirname(target), { recursive: true }); await fs.copyFile(file, target);
      baseline[relative] = hash(await fs.readFile(file));
    }
    await atomic(baselineFile, baseline);
    return { ...project, source, candidate, baselineFile, baseline };
  }

  async call(tool, args = {}, origin = {}) {
    const execute = async () => {
      const project = await this.ensure(args.project);
      const safePath = async (relative, writing = false) => {
        if (typeof relative !== 'string' || !relative || relative.includes('\\') || path.isAbsolute(relative)) throw new Error('DEVELOPMENT_PATH_DENIED');
        const result = path.resolve(project.candidate, relative);
        const normalized = path.relative(project.candidate, result).split(path.sep).join('/');
        if (!inside(project.candidate, result) || privateName(normalized) || writing && protectedPaths.has(normalized)) throw new Error('DEVELOPMENT_PATH_DENIED');
        let parent = result;
        while (!await exists(parent)) parent = path.dirname(parent);
        const real = await fs.realpath(parent), root = await fs.realpath(project.candidate);
        if (real !== root && !inside(root, real)) throw new Error('DEVELOPMENT_SYMLINK_DENIED');
        return result;
      };
      if (tool === 'development_files') {
        const current = await files(project.candidate);
        const offset = args.offset ?? 0, limit = args.limit ?? 100, prefix = args.prefix ?? '';
        if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100 || typeof prefix !== 'string')
          throw new Error('DEVELOPMENT_PAGE_INVALID');
        const rows = [...current].filter(([name]) => name.startsWith(prefix)).sort(([a], [b]) => a.localeCompare(b));
        return { project: project.id, candidate: project.candidate, projects: [...this.projects.keys()],
          total: rows.length, next_offset: offset + limit < rows.length ? offset + limit : null,
          files: await Promise.all(rows.slice(offset, offset + limit).map(async ([name, file]) => {
            const digest = hash(await fs.readFile(file)); return { path: name, sha256: digest, changed: digest !== project.baseline[name] };
          })), deleted: Object.keys(project.baseline).filter(name => !current.has(name)), selected: await this.selected() };
      }
      if (tool === 'development_read') {
        const file = await safePath(args.path);
        if ((await fs.stat(file)).size > 262144) throw new Error('DEVELOPMENT_READ_LIMIT');
        const bytes = await fs.readFile(file); return { path: args.path, text: bytes.toString('utf8'), sha256: hash(bytes) };
      }
      if (tool === 'development_write') {
        const file = await safePath(args.path, true);
        if (typeof args.text !== 'string' || Buffer.byteLength(args.text) > 1048576) throw new Error('DEVELOPMENT_WRITE_LIMIT');
        await fs.mkdir(path.dirname(file), { recursive: true });
        await fs.writeFile(file, args.text, { flag: args.overwrite ? 'w' : 'wx' });
        return { path: args.path, written: true, sha256: hash(args.text) };
      }
      if (tool === 'development_run') {
        if (!Array.isArray(args.argv) || !args.argv.length || args.argv.length > 40
          || args.argv.some(a => typeof a !== 'string' || a.includes('\0')) || args.argv.join('').length > 16000) throw new Error('DEVELOPMENT_ARGV_INVALID');
        const linux = '/mnt/' + project.candidate[0].toLowerCase() + project.candidate.slice(2).replaceAll('\\', '/');
        const result = await run('wsl', ['-d', 'Ubuntu', '--exec', 'timeout', '--kill-after=2', '35',
          'bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--ro-bind', '/usr', '/usr',
          '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
          '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--bind', linux, '/task', '--chdir', '/task',
          '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', 'prlimit', '--cpu=20', '--as=1073741824',
          '--fsize=8388608', '--nofile=128', '--', ...args.argv]);
        return { ...result, argv: args.argv, sandbox: 'wsl-bubblewrap-unshare-all', network: 'isolated' };
      }
      if (tool === 'development_publish') return this.publish(project, args.reason ?? '', origin);
      throw new Error('UNKNOWN_DEVELOPMENT_TOOL');
    };
    const pending = this.serial.then(execute); this.serial = pending.catch(() => {}); return pending;
  }

  async publish(project, reason, origin = {}) {
    const current = await files(project.candidate), hashes = {};
    for (const [name, file] of current) hashes[name] = hash(await fs.readFile(file));
    const changed = Object.keys(hashes).filter(name => hashes[name] !== project.baseline[name]);
    const deleted = Object.keys(project.baseline).filter(name => !(name in hashes));
    if (!changed.length && !deleted.length) return { state: 'NO_CHANGES', project: project.id };
    for (const name of [...changed, ...deleted]) {
      if (protectedPaths.has(name)) throw new Error('DEVELOPMENT_FLOOR_PROTECTED');
      const source = path.join(project.source, name);
      const actual = await exists(source) ? hash(await fs.readFile(source)) : undefined;
      if (actual !== project.baseline[name]) throw new Error('EFFECTIVE_PROJECT_CHANGED: ' + name);
    }
    const identity = hash(JSON.stringify(Object.entries(hashes).sort()));
    const frozen = path.join(this.base, 'development', project.id, 'frozen', identity);
    if (!await exists(frozen)) {
      for (const [name, file] of current) { const target = path.join(frozen, name);
        await fs.mkdir(path.dirname(target), { recursive: true }); await fs.copyFile(file, target); }
    }
    const prepared = await this.prepare(project, frozen);
    if (prepared.boot_probe.exit_code !== 0) return { state: 'BOOT_FAILED', candidate: identity,
      project: project.id, changed_files: changed, activated: false, ...prepared };
    const destination = path.join(prepared.packageRoot, '.runtime/packages'); await fs.mkdir(destination, { recursive: true });
    const packed = process.platform === 'win32'
      ? await run('cmd.exe', ['/d', '/s', '/c', 'npm.cmd pack --ignore-scripts --json --pack-destination .runtime/packages'], { cwd: prepared.packageRoot })
      : await run('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', '.runtime/packages'], { cwd: prepared.packageRoot });
    if (packed.exit_code !== 0) return { state: 'PACK_FAILED', project: project.id, boot_probe: packed, activated: false };
    const packageInfo = JSON.parse(packed.stdout)[0];
    const artifact = path.join(destination, packageInfo.filename), bytes = await fs.readFile(artifact);
    const addressed = path.join(destination, packageInfo.filename.replace('.tgz', '-' + hash(bytes).slice(0, 12) + '.tgz'));
    await fs.copyFile(artifact, addressed);
    const restartRequired = [...changed, ...deleted].some(name => /(^|\/)(package(?:-lock)?\.json|cordis\.patch\.yml|uv\.lock|pyproject\.toml)$/.test(name)
      || /\.(?:js|mjs|ts|tsx|jsx)$/.test(name));
    const selected = await this.selected();
    const value = { candidate: identity, packageRoot: prepared.packageRoot, workerPath: prepared.workerPath,
      artifact: addressed, sha256: hash(bytes), state: restartRequired ? 'HOST_RESTART_REQUIRED' : 'APPLIED',
      project: project.id, changed_files: changed, deleted_files: deleted, reason,
      receipt_id: 'self-publish-' + identity.slice(0, 32), origin,
      published_at: new Date().toISOString(), boot_probe: prepared.boot_probe };
    // No rollback pointer. The next successful publication advances this record.
    selected.projects[project.id] = value; await atomic(this.activationFile, selected);
    // Updating authorized source does not alter the already loaded artifact.
    for (const name of deleted) await fs.unlink(path.join(project.source, name));
    for (const name of changed) { const target = path.join(project.source, name);
      await fs.mkdir(path.dirname(target), { recursive: true }); await fs.copyFile(current.get(name), target); }
    await atomic(project.baselineFile, hashes);
    return { ...value, activated: false };
  }

  async prepare(project, frozen) {
    const target = project.format === 'repository' ? path.join(frozen, 'packages/cognition-core') : frozen;
    if (project.id === 'core' && project.format === 'repository') {
      const manifest = await json(path.join(packageRoot, 'runtime-manifest.json'));
      for (const [source, destination] of manifest.files) {
        const output = path.join(target, destination);
        await fs.mkdir(path.dirname(output), { recursive: true }); await fs.copyFile(path.join(frozen, source), output);
      }
      const bundled = new Set(manifest.files.map(([source]) => source));
      const excludedModule = /^(?:ui(?:_.*)?|dsh_lane|provider_proxy|cli|native_ui|doctor|.*_trials?|review.*|reporting|experiments|behavior_trials)\.py$/;
      for (const [name, file] of await files(path.join(frozen, 'src/asuna'))) {
        if (name.endsWith('.py') && !excludedModule.test(name) && !bundled.has('src/asuna/' + name)) {
          const output = path.join(target, 'python/asuna', name);
          await fs.mkdir(path.dirname(output), { recursive: true }); await fs.copyFile(file, output);
        }
      }
      await fs.copyFile(path.join(packageRoot, 'python/pyproject.toml'), path.join(target, 'python/pyproject.toml'));
    }
    if (project.id === 'core') {
      const trusted = await json(path.join(packageRoot, 'package.json'));
      const proposed = await json(path.join(target, 'package.json'));
      if (proposed.type !== 'module') throw new Error('DEVELOPMENT_FLOOR_MODULE_TYPE_PROTECTED');
      for (const key of ['./floor', './recovery', './persistence']) {
        if (proposed.exports?.[key] !== trusted.exports[key]) throw new Error('DEVELOPMENT_FLOOR_EXPORT_PROTECTED');
      }
      if (!(await fs.readFile(path.join(target, 'cordis.patch.yml'))).equals(await fs.readFile(path.join(packageRoot, 'cordis.patch.yml'))))
        throw new Error('DEVELOPMENT_FLOOR_COMPOSITION_PROTECTED');
    }
    const workerPath = project.id === 'core' ? path.join(target, 'python') : null;
    let probe = { exit_code: 0, stdout: 'Persona resources packaged; existing live self heads preserved.', stderr: '' };
    for (const [name, file] of await files(target)) {
      if (name.endsWith('.js') || name.endsWith('.mjs')) {
        probe = await run(process.execPath, ['--check', file]); if (probe.exit_code !== 0) return { packageRoot: target, workerPath, boot_probe: probe };
      }
    }
    if (workerPath) probe = await run(this.config.python, ['-c',
      'import asuna.native_worker; from asuna.config import load; from asuna.state import Store; s=Store(load(__import__("sys").argv[1])); s.db.command("ping"); s.authorize(s.config["chat"]["scene_id"],s.config["chat"]["person_id"]); s.client.close(); print("Worker imports and existing database authorization passed; no live consumers started.")',
      this.config.configPath], { cwd: frozen, env: { ...process.env, ASUNA_DATA_ROOT: this.config.workspace, PYTHONPATH: workerPath, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' } });
    return { packageRoot: target, workerPath, boot_probe: probe };
  }
}

export function apply(ctx, config = {}) {
  ctx.provide('asunaFloor', new PublicationFloor(config));
}
