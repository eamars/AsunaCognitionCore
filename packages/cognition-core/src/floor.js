/** Minimal publication floor, deliberately independent of the business worker.
 * Immutable artifacts run; authorized source candidates remain writable.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolvePersona } from './persona.js';
import { resolveChannel } from './channel.js';
import { dataRoot, floorState } from './paths.js';

export const name = 'asuna-publication-floor';
const packageRoot = fileURLToPath(new URL('../', import.meta.url));
const hash = data => createHash('sha256').update(data).digest('hex');
const excluded = new Set(['.runtime', '.venv', '.git', 'node_modules', '__pycache__', '.pytest_cache', 'reports']);
// The floor and everything it imports (ADR-011 §6.4): persona.js and channel.js for floor.js,
// settings.js for recovery.js. A publication can never replace what keeps the Host bootable.
const FLOOR_FILES = ['floor.js', 'recovery.js', 'persistence.js', 'persona.js', 'channel.js', 'settings.js', 'paths.js'];
// The launcher runs the packer and installer on every start (owner 2026-10-07), so they are the floor too.
const protectedPaths = new Set(['start-asuna.cmd', 'start-asuna.sh', 'tools/asuna-launch.mjs',
  'tools/pack_plugins.py', 'tools/setup_native_profile.py',
  ...FLOOR_FILES.map(name => 'packages/cognition-core/src/' + name), 'packages/cognition-core/runtime-manifest.json',
  ...FLOOR_FILES.map(name => 'src/' + name), 'runtime-manifest.json']);
// A child process that really imports a plugin entry, resolving bare packages from this Host's own
// installation when the frozen artifact has none of its own, and reads the package's structured files.
const PROBE_LOADER = `let fallback;
export async function initialize(data) { fallback = data; }
export async function resolve(specifier, context, next) {
  try { return await next(specifier, context); }
  catch (error) {
    if (/^[./]|^[a-z][a-z0-9+.-]*:/i.test(specifier)) throw error;
    return next(specifier, { ...context, parentURL: fallback });
  }
}`;
const PROBE = `import { register } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
const [entry, fallback, model, patch, persona] = process.argv.slice(1);
register('data:text/javascript,' + encodeURIComponent(process.env.ASUNA_PROBE_LOADER), import.meta.url, { data: fallback });
const loaded = await import(pathToFileURL(entry).href);
const relative = path.relative(process.cwd(), entry).split(path.sep).join('/');
if (typeof loaded.apply !== 'function') throw new Error('PLUGIN_ENTRY_HAS_NO_APPLY: 入口 ' + relative
  + ' 没有导出 apply 函数，Host 装不上这个插件；导出 export function apply(ctx, config) 再发布');
if (model !== '-') {
  const value = JSON.parse(await fs.readFile(model, 'utf8'));
  if (typeof value?.persona?.id !== 'string' || !value.persona.id) throw new Error('PERSONA_MODEL_HAS_NO_ID: '
    + 'persona-model.json 里没有 persona.id（要非空字符串）；补回原来的 id 再发布');
  if (persona !== '-' && value.persona.id !== persona) throw new Error('PERSONA_MODEL_ID_CHANGED: '
    + 'persona-model.json 的 persona.id 改成了 ' + JSON.stringify(value.persona.id) + '，原来是 ' + JSON.stringify(persona)
    + '；id 是这个人格存档的身份，不能改：改回 ' + JSON.stringify(persona) + ' 再发布');
}
if (patch !== '-') {
  const { parse } = await import('yaml');
  const value = parse(await fs.readFile(patch, 'utf8'));
  if (value !== null && typeof value !== 'object') throw new Error('CORDIS_PATCH_NOT_A_DOCUMENT: '
    + 'cordis.patch.yml 解析出来是 ' + JSON.stringify(value).slice(0, 80) + '，不是列表或映射；改成 YAML 列表或映射再发布');
}
console.log('Plugin entry imported; ' + (model !== '-' ? 'persona model, ' : '') + (patch !== '-' ? 'cordis patch, ' : '') + 'structure valid.');`;
const privateName = name => /(^|\/)(\.env(?:\..*)?|.*\.local\.json(?:\..*)?|local\.json(?:\..*)?|credentials\.json|secrets\.json|.*\.(?:key|pem|p12|pfx))$/i.test(name);
const inside = (root, value) => { const relative = path.relative(root, value); return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative); };
async function exists(file) { try { await fs.access(file); return true; } catch { return false; } }
// Her own argument, quoted back short (it may be anything a model wrote).
const given = value => value === undefined ? '（没写）' : typeof value === 'string' ? `'${value.slice(0, 200)}'`
  : String(JSON.stringify(value) ?? value).slice(0, 80);
// A filesystem refusal on a path she named, as a coded error: the raw one names host folders and no fix.
// EEXIST from writing the file stays as it is: the worker turns it into DEVELOPMENT_FILE_EXISTS.
function pathFault(error, project, relative, writing) {
  const name = given(relative);
  // Making its folders: some folder on the way is a file.
  if (writing === 'mkdir' && (error?.code === 'EEXIST' || error?.code === 'ENOTDIR'))
    return new Error(`DEVELOPMENT_PARENT_NOT_DIRECTORY: ${name} 的上级里有一级是文件，不能在它下面建目录；换一条路径写`);
  if (error?.code === 'ENOENT' || error?.code === 'ENOTDIR') return new Error(`DEVELOPMENT_FILE_NOT_FOUND: 项目 ${project.id} `
    + `的候选里没有 ${name}；路径照 development_files 列出的 path 写（prefix 可缩小范围）`);
  if (error?.code === 'EISDIR') return new Error(`DEVELOPMENT_NOT_A_FILE: ${name} 是目录，不是文件；`
    + (writing ? '写到它下面的文件路径' : `用 development_files 加 prefix '${String(relative).replace(/\/$/, '')}/' 列出它下面的文件`));
  return error;
}
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
const PYTHONS = new Set(['python3', 'python', 'python3.exe', 'python.exe']);
/** What a sandboxed command inherits: enough for Windows and Python to start, no credentials (as sandbox_backend.py). */
function commandEnvironment() {
  const keep = ['SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'TEMP', 'TMP', 'SYSTEMDRIVE', 'PROGRAMDATA',
    'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'HOME', 'USERPROFILE'];
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => keep.includes(key.toUpperCase())));
  return { ...env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1' };
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
  constructor(config, root = dataRoot(null, config)) {
    this.config = config;
    this.dataRoot = root;
    // Each profile has its own data folder, so it can never select or publish another profile's artifacts.
    // Candidates (work/) and their baselines (state) are always in the same folder: a candidate found without
    // its baseline would read as every file deleted, and publishing that would delete them from the source.
    this.base = floorState(root, config);
    this.workRoot = path.join(root, 'work');
    this.activationFile = path.join(this.base, 'activation.json');
    this.projects = new Map((config.projects ?? []).map(project => [project.id, project]));
    this.serial = Promise.resolve();
    this.coreProbe = null;
  }

  /** Core lends the floor a settings check for a core candidate's worker (see prepare). Returns the release. */
  setCoreProbe(probe) {
    this.coreProbe = probe;
    return () => { if (this.coreProbe === probe) this.coreProbe = null; };
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
    return (await this.persona(persona)).skill_directories;
  }

  /** Every persona path resolves against the published package artifact when one is selected. */
  async persona(persona) {
    const root = (await this.effective(this.config.defaultProject))?.packageRoot;
    return resolvePersona(persona, root ?? persona.resource_root);
  }

  /** A channel plugin's paths, against its own published artifact when one is selected. */
  async channel(channel) {
    const root = (await this.effective(channel.project))?.packageRoot;
    return resolveChannel(channel, root ?? channel.resource_root);
  }

  async workerReady(projectId) {
    const selected = await this.selected(); selected.active ??= {};
    const activated = [];
    for (const [id, value] of Object.entries(selected.projects)) {
      if (projectId && id !== projectId) continue;
      if (value.state !== 'APPLIED' && value.state !== 'ACTIVE') continue;
      value.state = 'ACTIVE'; value.activated_at ??= new Date().toISOString(); delete value.boots;
      selected.active[id] = value; activated.push(value);
    }
    await atomic(this.activationFile, selected); return activated;
  }

  /** The writable development copy of a channel plugin's adapter: her integration_* tools work there. */
  async integrationProject(channel) {
    // A profile that has not made the channel a development project (a fresh install) has no integration copy.
    if (!channel?.integration_directory || !this.projects.has(channel.project)) return null;
    const project = await this.ensure(channel.project);
    const directory = path.resolve(project.candidate, channel.integration_directory);
    if (!inside(project.candidate, directory)) throw new Error('CHANNEL_INTEGRATION_PATH_INVALID');
    return directory;
  }

  async ensure(id = this.config.defaultProject) {
    const project = this.projects.get(id);
    if (!project || !/^[a-z][a-z0-9-]{0,50}$/.test(id)) {
      const ids = [...this.projects.keys()];
      throw new Error('DEVELOPMENT_PROJECT_NOT_AUTHORIZED: ' + (!ids.length
        ? '这个 Host 没有配置任何开发项目——不是参数的问题；重试也一样：不改代码能做的先做，要改的写进报告'
        : (id === undefined ? '没写 project，这个 Host 也没有默认项目' : `没有项目 ${given(id)}`)
          + `；有的是 ${ids.join('、')}，project 写其中一个`
          + (this.config.defaultProject ? `（不写就是 ${this.config.defaultProject}）` : '')));
    }
    const source = path.resolve(project.root);
    if (!await exists(source)) throw new Error(`DEVELOPMENT_PROJECT_ROOT_MISSING: 项目 ${id} 配置的源目录不存在或读不了——`
      + '这是 Host 的配置问题，不是参数的问题；重试也一样：换个项目做，或把要改的写进报告，请 owner 修好配置');
    const candidate = path.join(this.workRoot, 'self-development', id);
    const baselineFile = path.join(this.base, 'development', id, 'baseline.json');
    const baseline = await json(baselineFile, {});
    const sourceFiles = await files(source);
    for (const [relative, prior] of Object.entries(baseline)) {
      if (sourceFiles.has(relative)) continue;
      const target = path.resolve(candidate, relative);
      if (!inside(candidate, target)) throw new Error(`DEVELOPMENT_BASELINE_PATH_INVALID: 项目 ${id} 的基线记录里有一条路径 `
        + `${given(relative)} 落在候选目录外——这是程序的状态坏了，不是参数的问题；重试也一样：把这件事写进报告，请 owner 检查`);
      if (await exists(target) && hash(await fs.readFile(target)) === prior) {
        await fs.unlink(target); delete baseline[relative];
      }
    }
    for (const [relative, file] of sourceFiles) {
      if (project.format === 'repository' && !/^(src\/|packages\/cognition-core\/|docs\/|tests\/|tools\/|(?:pyproject.toml|uv.lock|package.json|package-lock.json|README.md|AGENTS.md|INSTALL.md|RUN_ASUNA.md|NATIVE_PLUGIN.md|RUNTIME_API.md)$)/.test(relative)) continue;
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
        const denied = why => new Error('DEVELOPMENT_PATH_DENIED: ' + why);
        if (typeof relative !== 'string' || !relative)
          throw denied(`path 要是非空字符串（给的是 ${given(relative)}）；写项目里的相对路径，如 development_files 列出的 path`);
        if (relative.includes('\\')) throw denied(`${given(relative)} 用了反斜杠；路径分隔用正斜杠 /，如 src/a.py`);
        if (path.isAbsolute(relative)) throw denied(`${given(relative)} 是绝对路径；写相对于项目根的路径，如 development_files `
          + '列出的 path（/task 只在 development_run 的 argv 里指候选目录）');
        const result = path.resolve(project.candidate, relative);
        const normalized = path.relative(project.candidate, result).split(path.sep).join('/');
        if (!inside(project.candidate, result)) throw denied(`${given(relative)} 落在项目候选外面（或就是项目根）；写项目里的文件路径，不要用 ..`);
        if (privateName(normalized)) throw denied(`${given(relative)} 是私密文件（.env、local.json、*.local.json、credentials.json、`
          + 'secrets.json、*.key、*.pem、*.p12、*.pfx），development_* 不读也不写；重试也一样：不用它继续');
        if (writing && protectedPaths.has(normalized)) throw denied(`${normalized} 是发布底座的文件（启动器、打包和安装脚本、floor 和它导入的模块），`
          + 'development_write 不能改；重试也一样：不改它，需要改就写进报告，请 owner 改');
        let parent = result;
        while (!await exists(parent)) parent = path.dirname(parent);
        const real = await fs.realpath(parent), root = await fs.realpath(project.candidate);
        if (real !== root && !inside(root, real)) throw new Error(`DEVELOPMENT_SYMLINK_DENIED: ${given(relative)} `
          + '经过一个指向候选目录外的链接；重试也一样：换一条不经过这个链接的路径');
        return result;
      };
      if (tool === 'development_files') {
        const current = await files(project.candidate);
        const offset = args.offset ?? 0, limit = args.limit ?? 100, prefix = args.prefix ?? '';
        if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100 || typeof prefix !== 'string')
          throw new Error('DEVELOPMENT_PAGE_INVALID: ' + [
            !Number.isSafeInteger(offset) || offset < 0 ? `offset 是 ${given(offset)}，只能是 0 或更大的整数` : '',
            !Number.isSafeInteger(limit) || limit < 1 || limit > 100 ? `limit 是 ${given(limit)}，只能 1..100` : '',
            typeof prefix !== 'string' ? `prefix 是 ${given(prefix)}，要是字符串` : ''].filter(Boolean).join('，')
            + '；改了再列，下一页用上次结果里的 next_offset');
        const rows = [...current].filter(([name]) => name.startsWith(prefix)).sort(([a], [b]) => a.localeCompare(b));
        // A file she changed whose source also moved after her baseline: publishing it would be refused
        // (EFFECTIVE_PROJECT_CHANGED), so say so before she builds on it (ADR-010 D9).
        const moved = async name => {
          const source = path.join(project.source, name);
          return (await exists(source) ? hash(await fs.readFile(source)) : undefined) !== project.baseline[name];
        };
        const listed = await Promise.all(rows.slice(offset, offset + limit).map(async ([name, file]) => {
          const digest = hash(await fs.readFile(file)), changed = digest !== project.baseline[name];
          return { path: name, sha256: digest, changed, ...(changed && await moved(name) ? { stale: true } : {}) };
        }));
        const deleted = Object.keys(project.baseline).filter(name => !current.has(name));
        const staleDeleted = (await Promise.all(deleted.map(async name => await moved(name) ? name : null))).filter(Boolean);
        return { project: project.id, candidate: project.candidate, projects: [...this.projects.keys()],
          total: rows.length, next_offset: offset + limit < rows.length ? offset + limit : null,
          files: listed, deleted, ...(staleDeleted.length ? { stale_deleted: staleDeleted } : {}),
          ...(listed.some(row => row.stale) || staleDeleted.length ? { stale_note: 'stale：你改过这个文件，'
            + '而它的源在你的基线之后也变了，照现在这样发布会被拒绝（EFFECTIVE_PROJECT_CHANGED）。先把它恢复成你最初读到的原样，'
            + '下一次 development_* 调用会换上新的源版本，再在新版本上重做你的改动' } : {}),
          selected: await this.selected() };
      }
      if (tool === 'development_read') {
        const file = await safePath(args.path);
        try {
          const size = (await fs.stat(file)).size;
          if (size > 262144) throw new Error(`DEVELOPMENT_READ_LIMIT: ${given(args.path)} 有 ${size} 字节（约 `
            + `${Math.ceil(size / 1024)} KiB），development_read 一次最多 256 KiB；重试也一样：用 development_run 跑 python3 只读需要的那一段`);
          const bytes = await fs.readFile(file); return { path: args.path, text: bytes.toString('utf8'), sha256: hash(bytes) };
        } catch (error) { throw pathFault(error, project, args.path, false); }
      }
      if (tool === 'development_write') {
        const file = await safePath(args.path, true);
        if (typeof args.text !== 'string') throw new Error(`DEVELOPMENT_WRITE_LIMIT: text 要是字符串（给的是 ${given(args.text)}）；`
          + '把文件的全部内容作为一个字符串传');
        if (Buffer.byteLength(args.text) > 1048576) throw new Error(`DEVELOPMENT_WRITE_LIMIT: text 有 ${Buffer.byteLength(args.text)} `
          + '字节，一次最多 1 MiB（1048576 字节）；拆成几个文件写，或删掉用不着的部分');
        try { await fs.mkdir(path.dirname(file), { recursive: true }); }
        catch (error) { throw pathFault(error, project, args.path, 'mkdir'); }
        try { await fs.writeFile(file, args.text, { flag: args.overwrite ? 'w' : 'wx' }); }
        catch (error) { throw pathFault(error, project, args.path, true); }
        return { path: args.path, written: true, sha256: hash(args.text) };
      }
      if (tool === 'development_run') {
        const argvInvalid = why => new Error('DEVELOPMENT_ARGV_INVALID: ' + why);
        if (!Array.isArray(args.argv) || !args.argv.length)
          throw argvInvalid(`argv 要是非空的字符串数组（给的是 ${given(args.argv)}）；如 ["python3", "/task/check.py"]`);
        if (args.argv.length > 40) throw argvInvalid(`argv 有 ${args.argv.length} 项，最多 40 项；把长参数写进脚本（development_write）再运行它`);
        const bad = args.argv.findIndex(a => typeof a !== 'string' || a.includes('\0'));
        if (bad >= 0) throw argvInvalid(`argv[${bad}] 不是字符串，或含有空字符（\\0）；每一项都写成普通字符串`);
        if (args.argv.join('').length > 16000) throw argvInvalid(`argv 合起来 ${args.argv.join('').length} 个字符，最多 16000；`
          + '把长内容写进文件（development_write），让命令去读它');
        // DSH's own sandbox (owner 2026-10-06): the command may write only its candidate. It runs natively on this
        // machine: python3 is the worker's Python, and /task names the candidate folder (as her tools say).
        const sandbox = this.sandbox?.();
        if (!sandbox) throw new Error('SANDBOX_UNAVAILABLE: 这个 Host 没装沙箱提供者，development_run 跑不了命令——不是参数的问题；'
          + '重试也一样：不跑命令能做的先做，要跑命令的那一步写进报告');
        const root = project.candidate.replaceAll('\\', '/');
        const argv = args.argv.map((arg, index) => index === 0 && PYTHONS.has(arg) ? this.config.python ?? this.workerPython
          : arg === '/task' || arg.startsWith('/task/') ? root + arg.slice(5) : arg);
        const confined = await sandbox.confine(argv, { mode: 'workspace-write', workspaceRoot: project.candidate });
        const result = await run(confined.argv[0], confined.argv.slice(1), { cwd: project.candidate, timeout: 35000,
          env: commandEnvironment() });
        return { ...result, argv: args.argv, sandbox: 'dsh', writes: 'candidate only' };
      }
      if (tool === 'development_publish') return this.publish(project, args.reason ?? '', origin);
      throw new Error(`UNKNOWN_DEVELOPMENT_TOOL: 发布底座不认识 ${given(tool)}——程序两边对不上，不是参数的问题；`
        + '重试也一样：不用它能做的先做，没做成的写进报告');
    };
    const pending = this.serial.then(execute); this.serial = pending.catch(() => {}); return pending;
  }

  async publish(project, reason, origin = {}) {
    // An unattended self-improvement turn never stacks a change on one that has not run yet (ADR-021 D4).
    if (origin.unattended && (await this.selected()).projects?.[project.id]?.state === 'HOST_RESTART_REQUIRED')
      throw new Error(`DEVELOPMENT_PUBLISH_WAITING_RESTART: 项目 ${project.id} 上一次发布的改动还在等宿主重启，`
        + '重启前没人在场的自我开发回合不能再往它发布，免得没验过的改动叠上去；重试也一样：这次改动留在候选里，'
        + '这一段做别的项目或只读检查，重启生效、验过以后再发布');
    const current = await files(project.candidate), hashes = {};
    for (const [name, file] of current) hashes[name] = hash(await fs.readFile(file));
    const changed = Object.keys(hashes).filter(name => hashes[name] !== project.baseline[name]);
    const deleted = Object.keys(project.baseline).filter(name => !(name in hashes));
    if (!changed.length && !deleted.length) return { state: 'NO_CHANGES', project: project.id };
    for (const name of [...changed, ...deleted]) {
      if (protectedPaths.has(name)) throw new Error(`DEVELOPMENT_FLOOR_PROTECTED: ${name} 是发布底座的文件，候选里它被改了或删了，`
        + '发布不能替换它；撤销对它的改动（删了的恢复原样）再发布，做不到就写进报告，请 owner 处理');
      const source = path.join(project.source, name);
      const actual = await exists(source) ? hash(await fs.readFile(source)) : undefined;
      if (actual !== project.baseline[name]) throw new Error(`EFFECTIVE_PROJECT_CHANGED: ${name} 你改过（或删了），而它的源在你的基线`
        + '之后也变了，发布会盖掉那次变化；重试也一样：把它恢复成你最初读到的原样，下一次 development_* 调用会换上新的源版本，'
        + '在新版本上重做你的改动再发布；做不到就写进报告，请 owner 合并');
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
    // A channel plugin's python/ is imported once by the worker, like the plugin's own JavaScript.
    const restartRequired = [...changed, ...deleted].some(name => /(^|\/)(package(?:-lock)?\.json|cordis\.patch\.yml|uv\.lock|pyproject\.toml)$/.test(name)
      || /\.(?:js|mjs|ts|tsx|jsx)$/.test(name) || project.format === 'package' && name.startsWith('python/'));
    const selected = await this.selected();
    const value = { candidate: identity, packageRoot: prepared.packageRoot, workerPath: prepared.workerPath,
      artifact: addressed, sha256: hash(bytes), state: restartRequired ? 'HOST_RESTART_REQUIRED' : 'APPLIED',
      project: project.id, changed_files: changed, deleted_files: deleted, reason,
      receipt_id: 'self-publish-' + identity.slice(0, 32), origin,
      published_at: new Date().toISOString(), boot_probe: prepared.boot_probe };
    // No rollback pointer. The next successful publication advances this record.
    // The last selection that actually ran: the launcher returns to it when this one never starts (§6.4).
    const previous = selected.active?.[project.id];
    if (previous) { const { previous: _older, boots: _boots, ...kept } = previous; value.previous = kept; }
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
    // A file of the package as her development tools name it (relative to the project).
    const at = name => path.relative(frozen, path.join(target, name)).split(path.sep).join('/');
    const packageJson = async () => {
      try { return await json(path.join(target, 'package.json'), null); }
      catch (error) { throw new Error(`PACKAGE_JSON_MISSING_OR_INVALID: ${at('package.json')} 不是合法的 JSON（${String(error.message).slice(0, 200)}）；改好再发布`); }
    };
    if (project.id === 'core' && project.format === 'repository') {
      const manifest = await json(path.join(packageRoot, 'runtime-manifest.json'));
      for (const [source, destination] of manifest.files) {
        const output = path.join(target, destination);
        if (!await exists(path.join(frozen, source))) throw new Error(`DEVELOPMENT_RUNTIME_FILE_MISSING: 候选里没有 ${source}，`
          + 'runtime-manifest.json 要把它打进运行时；恢复这个文件再发布');
        await fs.mkdir(path.dirname(output), { recursive: true }); await fs.copyFile(path.join(frozen, source), output);
      }
      if (!await exists(path.join(frozen, 'src/asuna'))) throw new Error('DEVELOPMENT_RUNTIME_FILE_MISSING: 候选里没有 src/asuna，'
        + 'worker 的模块都在那里；恢复它再发布');
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
      const proposed = await packageJson();
      if (!proposed) throw new Error(`PACKAGE_JSON_MISSING_OR_INVALID: 候选里没有 ${at('package.json')}（或它是空的）；恢复它再发布`);
      if (proposed.type !== 'module') throw new Error(`DEVELOPMENT_FLOOR_MODULE_TYPE_PROTECTED: ${at('package.json')} 的 type 是 `
        + `${given(proposed.type)}，必须是 "module"（发布底座靠它加载）；改回 "module" 再发布`);
      for (const key of ['./floor', './recovery', './persistence']) {
        if (proposed.exports?.[key] !== trusted.exports[key]) throw new Error(`DEVELOPMENT_FLOOR_EXPORT_PROTECTED: ${at('package.json')} `
          + `的 exports["${key}"] 是 ${given(proposed.exports?.[key])}，必须保持 ${given(trusted.exports[key])}（发布底座的入口）；改回再发布`);
      }
      const composition = path.join(target, 'cordis.patch.yml');
      if (!await exists(composition) || !(await fs.readFile(composition)).equals(await fs.readFile(path.join(packageRoot, 'cordis.patch.yml'))))
        throw new Error(`DEVELOPMENT_FLOOR_COMPOSITION_PROTECTED: ${at('cordis.patch.yml')} 和正在运行的不一样（或缺了）；它决定 Host `
          + '装哪些插件，只能由 owner 改：撤销你对它的改动再发布，做不到就写进报告，请 owner 处理');
    }
    const workerPath = project.id === 'core' ? path.join(target, 'python') : null;
    let probe = { exit_code: 0, stdout: 'Persona resources packaged; existing live self heads preserved.', stderr: '' };
    for (const [name, file] of await files(target)) {
      if (name.endsWith('.js') || name.endsWith('.mjs')) {
        probe = await run(process.execPath, ['--check', file]); if (probe.exit_code !== 0) return { packageRoot: target, workerPath, boot_probe: probe };
      }
    }
    // Syntax alone is not a start: import the plugin entry as the Host would, and read its structure.
    const manifest = await packageJson();
    if (!manifest) return { packageRoot: target, workerPath, boot_probe: { exit_code: 1, stdout: '',
      stderr: `PACKAGE_JSON_MISSING_OR_INVALID: 候选里没有 ${at('package.json')}（或它是空的），Host 装不上这个包；补上再发布` } };
    const main = typeof manifest.exports === 'string' ? manifest.exports : manifest.exports?.['.'] ?? manifest.main;
    if (typeof main === 'string') {
      const optional = async name => await exists(path.join(target, name)) ? path.join(target, name) : '-';
      // A persona's id is her state's identity: a candidate keeps the id its source already has.
      const persona = (await json(path.join(project.source, 'persona-model.json'), null))?.persona?.id ?? '-';
      const imported = await run(process.execPath, ['--input-type=module', '-e', PROBE, path.resolve(target, main),
        new URL('../package.json', import.meta.url).href, await optional('persona-model.json'), await optional('cordis.patch.yml'),
        persona], { cwd: target, env: { ...process.env, ASUNA_PROBE_LOADER: PROBE_LOADER } });
      if (imported.exit_code !== 0) return { packageRoot: target, workerPath, boot_probe: imported };
      probe = { ...imported, stdout: imported.stdout + probe.stdout };
    }
    if (!workerPath && await exists(path.join(target, 'python'))) {
      // A channel plugin's Python must at least parse before it can be published.
      probe = await run(this.config.python ?? this.workerPython, ['-c', 'import ast, pathlib, sys\n'
        + 'for f in pathlib.Path(sys.argv[1]).rglob("*.py"): ast.parse(f.read_text(encoding="utf-8"), str(f))',
        path.join(target, 'python')]);
      if (probe.exit_code !== 0) return { packageRoot: target, workerPath, boot_probe: probe };
    }
    if (workerPath) {
      probe = await run(this.config.python ?? this.workerPython, ['-c', 'import asuna.native_worker; print("Worker imports.")'],
        { cwd: frozen, env: { ...process.env, ASUNA_DATA_ROOT: this.dataRoot, PYTHONPATH: workerPath, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' } });
      // With Core running, the candidate's worker also validates this profile's settings against the existing
      // database (validate_settings: no consumers, no model): Core holds the settings, the floor never reads them.
      if (probe.exit_code === 0 && this.coreProbe) {
        const validated = await this.coreProbe(workerPath);
        probe = { ...validated, stdout: probe.stdout + validated.stdout };
      }
    }
    return { packageRoot: target, workerPath, boot_probe: probe };
  }
}

export function apply(ctx, config = {}) {
  const floor = new PublicationFloor(config, dataRoot(ctx, config));
  // DSH's own sandbox, when the Host mounts one (development_run).
  floor.sandbox = () => { try { return ctx.get('sandbox'); } catch { return undefined; } };
  ctx.provide('asunaFloor', floor);
}
