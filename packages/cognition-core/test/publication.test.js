import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { Context } from '@deepseek-ai/cordis';
import LocalSpillStore from '@deepseek-ai/dsh-spill-local';
import { PublicationFloor } from '../src/floor.js';
import { readSpill } from '../src/spill.js';

test('actual npm artifact freezes a bounded candidate; edits do not change active resources', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });     // a fresh checkout has no data folder yet
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/publication-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['README.md'], type: 'module' }));
  await fs.writeFile(path.join(source, 'README.md'), 'Before publication');
  await fs.mkdir(path.join(source, 'src'));
  await fs.writeFile(path.join(source, 'src/floor.js'), '// Stable floor can be inspected.');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  await floor.call('development_write', { path: 'README.md', text: 'Published resource', overwrite: true });
  const result = await floor.call('development_publish', { reason: 'native packaging probe' });
  assert.equal(result.state, 'APPLIED', JSON.stringify(result));
  assert.ok((await fs.stat(result.artifact)).size > 0);
  await floor.workerReady('persona');
  await floor.call('development_write', { path: 'README.md', text: 'Next candidate only', overwrite: true });
  assert.equal(await fs.readFile(path.join((await floor.effective('persona')).packageRoot, 'README.md'), 'utf8'), 'Published resource');
  assert.equal((await floor.call('development_files', { limit: 1 })).files.length, 1);
  await assert.rejects(floor.call('development_write', { path: '../outside', text: 'denied' }), /PATH_DENIED/);
  await assert.rejects(floor.call('development_write', { path: 'credentials.json', text: 'denied' }), /PATH_DENIED/);
  assert.match((await floor.call('development_read', { path: 'src/floor.js' })).text, /Stable floor/);
  await assert.rejects(floor.call('development_write', { path: 'src/floor.js', text: 'denied', overwrite: true }), /PATH_DENIED/);
});

test('a publication whose package is byte for byte the running one is active at once: nothing to load, no restart', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/same-package-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['README.md'], type: 'module' }));
  await fs.writeFile(path.join(source, 'README.md'), 'Running');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  await floor.call('development_write', { path: 'README.md', text: 'Published', overwrite: true });
  const first = await floor.call('development_publish', { reason: 'packed change' });
  assert.equal(first.state, 'APPLIED', JSON.stringify(first));
  await floor.workerReady('persona');
  await floor.call('development_write', { path: 'docs/notes.md', text: 'outside the package' });
  const second = await floor.call('development_publish', { reason: 'a document only' });
  assert.equal(second.state, 'ACTIVE', JSON.stringify(second));            // not APPLIED: the Host restarts for APPLIED
  assert.equal(second.activated, true);
  assert.equal(second.sha256, first.sha256);
  assert.deepEqual(second.changed_files, ['docs/notes.md']);
  assert.equal(await fs.readFile(path.join(source, 'docs/notes.md'), 'utf8'), 'outside the package');
  assert.equal((await floor.effective('persona')).sha256, first.sha256);
  await floor.call('development_write', { path: 'README.md', text: 'Changed again', overwrite: true });
  assert.equal((await floor.call('development_publish', { reason: 'packed again' })).state, 'APPLIED');
});

test('ADR-010 D9: a file she changed whose source moved after her baseline is marked stale before publish', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });     // a fresh checkout has no data folder yet
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/stale-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', type: 'module' }));
  for (const name of ['a.md', 'b.md', 'c.md']) await fs.writeFile(path.join(source, name), 'v1 ' + name);
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  await floor.call('development_write', { path: 'a.md', text: 'her edit', overwrite: true });   // source will move
  await floor.call('development_write', { path: 'b.md', text: 'her edit', overwrite: true });   // source stays
  await fs.writeFile(path.join(source, 'a.md'), 'v2 a.md');
  await fs.writeFile(path.join(source, 'c.md'), 'v2 c.md');                                    // untouched by her
  const listing = await floor.call('development_files', {});
  const byPath = Object.fromEntries(listing.files.map(row => [row.path, row]));
  assert.equal(byPath['a.md'].stale, true);
  assert.equal(byPath['b.md'].stale, undefined);
  assert.equal(byPath['c.md'].changed, false, 'an untouched file simply follows the source');
  assert.match(listing.stale_note, /EFFECTIVE_PROJECT_CHANGED/);
  await assert.rejects(floor.call('development_publish', { reason: 'stale' }).then(r => { throw new Error(r.state); }),
    /EFFECTIVE_PROJECT_CHANGED: a\.md/);
});

test('native spilled output stays readable only by its own action, in bounded pages', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const root = await fs.mkdtemp(path.resolve('.runtime/adr008/spill-probe-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const ctx = new Context(); const store = new LocalSpillStore(ctx, { root, cleanupPeriodDays: 0 });
  try {
    const value = await store.saveText({ owner: { sessionId: 'action-one' }, source: { kind: 'tool', toolName: 'read', callId: 'one', label: 'result' }, suggestedName: 'result', content: 'abcdefghijklmnop' });
    assert.equal((await readSpill(store, 'action-one', { path: value.locator, offset: 4, limit: 4 })).text, 'efgh');
    assert.equal(await readSpill(store, 'action-two', { path: value.locator }), undefined);
    assert.equal(await readSpill(store, 'action-one', { path: path.resolve('config/local.json') }), undefined);
    await assert.rejects(readSpill(store, 'action-one', { path: value.locator, limit: 999999 }), /INVALID_SPILL_PAGE/);
  } finally { await ctx.fiber.dispose(); }
});

test('ADR-011 §6.4: publication imports the plugin entry and reads its structure; the floor closure is protected', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });     // a fresh checkout has no data folder yet
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/import-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(path.join(source, 'src'), { recursive: true });
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe-persona', version: '0.0.0',
    type: 'module', exports: { '.': './src/index.js' }, files: ['src', 'persona-model.json', 'cordis.patch.yml'] }));
  await fs.writeFile(path.join(source, 'src/index.js'), "import { fileURLToPath } from 'node:url';\nexport const name = 'probe';\nexport function apply() { return fileURLToPath(import.meta.url); }\n");
  await fs.writeFile(path.join(source, 'persona-model.json'), JSON.stringify({ persona: { id: 'probe-persona' } }));
  await fs.writeFile(path.join(source, 'cordis.patch.yml'), '- id: probe\n  name: probe\n');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  // An entry that resolves a Host package (from this Host's own installation) and exports apply starts.
  await floor.call('development_write', { path: 'src/index.js', overwrite: true,
    text: "import { defineTool } from '@deepseek-ai/dsh-tools';\nexport const name = 'probe';\nexport function apply() { return defineTool; }\n" });
  const good = await floor.call('development_publish', { reason: 'entry imports' });
  assert.equal(good.state, 'HOST_RESTART_REQUIRED', JSON.stringify(good.boot_probe));
  assert.match(good.boot_probe.stdout, /Plugin entry imported; persona model, cordis patch, structure valid/);
  // An entry whose import throws, a model whose id changed, or a broken patch never get selected.
  for (const [file, text, problem] of [
    ['src/index.js', "import './missing.js';\nexport function apply() {}\n", /missing\.js|ERR_MODULE_NOT_FOUND/],
    ['src/index.js', "export const name = 'probe';\n", /PLUGIN_ENTRY_HAS_NO_APPLY/],
    ['persona-model.json', JSON.stringify({ persona: { id: 'someone-else' } }), /PERSONA_MODEL_ID_CHANGED/],
    ['cordis.patch.yml', '- id: [unclosed\n', /YAML|Flow sequence|Missing/i],
  ]) {
    const before = await floor.call('development_read', { path: file });
    await floor.call('development_write', { path: file, text, overwrite: true });
    const result = await floor.call('development_publish', { reason: 'should not start' });
    assert.equal(result.state, 'BOOT_FAILED', file + ': ' + JSON.stringify(result.state));
    assert.match(result.boot_probe.stderr, problem);
    await floor.call('development_write', { path: file, text: before.text, overwrite: true });
  }
  // The floor's own imports cannot be replaced by a publication.
  for (const name of ['src/persona.js', 'src/channel.js', 'src/settings.js'])
    await assert.rejects(floor.call('development_write', { path: name, text: '// replaced', overwrite: true }), /PATH_DENIED/);
  const selected = await floor.selected();
  assert.equal(selected.projects.persona.candidate, good.candidate, 'a failed probe never replaces the selection');
});

test('a persona model the next start would refuse is refused at publication, by the worker schema', async t => {
  const { checkoutPython } = await import('../../../tools/asuna-launch.mjs');
  const python = checkoutPython(path.resolve('.'), process.platform);
  try { await fs.access(python); } catch { t.skip('no checkout Python to run the worker schema'); return; }
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/model-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(path.join(source, 'src'), { recursive: true });
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe-persona', version: '0.0.0',
    type: 'module', exports: { '.': './src/index.js' }, files: ['src', 'persona-model.json'] }));
  await fs.writeFile(path.join(source, 'src/index.js'), "export const name = 'probe';\nexport function apply() {}\n");
  const model = { model_version: 1, persona: { id: 'probe-persona', display_name: 'Probe' } };
  await fs.writeFile(path.join(source, 'persona-model.json'), JSON.stringify(model));
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', python,
    projects: [{ id: 'persona', root: source, format: 'package' }] });
  floor.workerPath = async () => path.resolve('src');           // the checkout's worker, as an installed Core's
  await floor.call('development_write', { path: 'persona-model.json', overwrite: true,
    text: JSON.stringify({ ...model, self_review: { tag: '标签' } }) });
  const good = await floor.call('development_publish', { reason: 'a valid model, with her review tag' });
  assert.match(good.state, /^(APPLIED|HOST_RESTART_REQUIRED)$/, JSON.stringify(good.boot_probe));
  assert.match(good.boot_probe.stdout, /Persona model valid against the running Core/);
  await floor.call('development_write', { path: 'persona-model.json', overwrite: true,
    text: JSON.stringify({ ...model, not_a_key: { tag: 'x' } }) });
  const refused = await floor.call('development_publish', { reason: 'a key the schema does not have' });
  assert.equal(refused.state, 'BOOT_FAILED');
  assert.match(refused.boot_probe.stderr, /PERSONA_MODEL_INVALID: <root>: Additional properties.*not_a_key.*下次启动装不上/s);
});

test('a refused development call says what was wrong, with the values, and what to do', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/refusal-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(path.join(source, 'docs'), { recursive: true });
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', type: 'module' }));
  await fs.writeFile(path.join(source, 'big.txt'), 'x'.repeat(262145));
  await fs.writeFile(path.join(source, 'docs/a.md'), 'a');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [
    { id: 'persona', root: source, format: 'package' }, { id: 'adapter', root: path.join(workspace, 'missing'), format: 'package' }] });
  await assert.rejects(floor.call('development_files', { project: 'qq-adapter' }),
    /^Error: DEVELOPMENT_PROJECT_NOT_AUTHORIZED: 没有项目 'qq-adapter'；有的是 persona、adapter，project 写其中一个（不写就是 persona）$/);
  await assert.rejects(floor.call('development_files', { project: 'adapter' }), /^Error: DEVELOPMENT_PROJECT_ROOT_MISSING: 项目 adapter .*不是参数的问题/);
  await assert.rejects(floor.call('development_files', { offset: -1, limit: 200 }),
    /DEVELOPMENT_PAGE_INVALID: offset 是 -1，只能是 0 或更大的整数，limit 是 200，只能 1\.\.100；/);
  await assert.rejects(floor.call('development_read', { path: 'big.txt' }), /DEVELOPMENT_READ_LIMIT: 'big\.txt' 有 262145 字节.*256 KiB/);
  await assert.rejects(floor.call('development_read', { path: 'nope.md' }), /^Error: DEVELOPMENT_FILE_NOT_FOUND: 项目 persona 的候选里没有 'nope\.md'；/);
  await assert.rejects(floor.call('development_read', { path: 'docs' }), /^Error: DEVELOPMENT_NOT_A_FILE: 'docs' 是目录.*prefix 'docs\/'/);
  await assert.rejects(floor.call('development_write', { path: 'docs/a.md/b.md', text: 'x' }), /^Error: DEVELOPMENT_PARENT_NOT_DIRECTORY: /);
  await assert.rejects(floor.call('development_write', { path: 'docs', text: 'x', overwrite: true }), /^Error: DEVELOPMENT_NOT_A_FILE: 'docs' 是目录.*写到它下面/);
  await assert.rejects(floor.call('development_write', { path: 'docs/a.md', text: 'x' }), /EEXIST/, 'the worker names an existing file');
  await assert.rejects(floor.call('development_read', { path: 'docs\\a.md' }), /DEVELOPMENT_PATH_DENIED: 'docs\\a\.md' 用了反斜杠/);
  await assert.rejects(floor.call('development_read', { path: '../x' }), /DEVELOPMENT_PATH_DENIED: '\.\.\/x' 落在项目候选外面/);
  await assert.rejects(floor.call('development_read', { path: '.env' }), /DEVELOPMENT_PATH_DENIED: '\.env' 是私密文件/);
  await assert.rejects(floor.call('development_run', { argv: Array(41).fill('a') }), /DEVELOPMENT_ARGV_INVALID: argv 有 41 项，最多 40 项/);
  await assert.rejects(floor.call('development_run', { argv: ['python3', '-c', '1'], timeout: 601 }),
    /DEVELOPMENT_TIMEOUT_INVALID: timeout 是 1 到 600 的整数秒（给的是 601）/);
  // A command may ask for longer; one stopped by its time hands back what it printed so far.
  floor.sandbox = () => ({ confine: async argv => ({ argv }) });
  const stopped = await floor.call('development_run', { argv: [process.execPath, '-e',
    'console.log("half done"); setTimeout(() => {}, 30000)'], timeout: 2 });
  assert.equal(stopped.timed_out, true);
  assert.match(stopped.stdout, /half done/); assert.match(stopped.stopped, /2 秒/);
  const quick = await floor.call('development_run', { argv: [process.execPath, '-e', 'console.log(1)'] });
  assert.equal(quick.timed_out, false); assert.equal(quick.stopped, undefined);
  // On Windows git in a confined command uses OpenSSL: Schannel has no credentials under the restricted token.
  const tls = await floor.call('development_run', { argv: [process.execPath, '-e',
    'console.log(process.env.GIT_CONFIG_KEY_0 + "=" + process.env.GIT_CONFIG_VALUE_0)'] });
  assert.equal(tls.stdout.trim(), process.platform === 'win32' ? 'http.sslBackend=openssl' : 'undefined=undefined');
});

test('a repository candidate publishes only the project paths, not what a command left beside them', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/publication-scope-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'), core = path.join(source, 'packages/cognition-core');
  await fs.mkdir(path.join(core, 'src'), { recursive: true }); await fs.mkdir(path.join(source, 'src'));
  await fs.writeFile(path.join(core, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', type: 'module', exports: './src/index.js' }));
  await fs.writeFile(path.join(core, 'src/index.js'), 'export const name = "probe"; export function apply() {}');
  await fs.writeFile(path.join(source, 'src/x.py'), 'x = 1\n');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'probe', projects: [{ id: 'probe', root: source, format: 'repository' }] });
  await floor.call('development_write', { path: 'src/x.py', text: 'x = 2\n', overwrite: true });
  // A nested command once installed a whole Python (docs with .js files) into the candidate's top folder.
  const candidate = path.join(workspace, 'work/self-development/probe');
  await fs.mkdir(path.join(candidate, 'Python/Doc'), { recursive: true });
  await fs.writeFile(path.join(candidate, 'Python/Doc/searchindex.js'), 'var x;');
  const published = await floor.call('development_publish', { reason: 'one Python change' });
  assert.equal(published.state, 'APPLIED', JSON.stringify(published));
  assert.deepEqual(published.changed_files, ['src/x.py']);
  assert.equal(await fs.readFile(path.join(source, 'src/x.py'), 'utf8'), 'x = 2\n');
  await assert.rejects(fs.stat(path.join(source, 'Python')), { code: 'ENOENT' });
});

test('a repository candidate keeps the other packages its tests import as the source has them, read-only', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/publication-references-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'), channel = path.join(source, 'packages/channels/chat/python');
  const core = path.join(source, 'packages/cognition-core');
  await fs.mkdir(path.join(core, 'src'), { recursive: true }); await fs.mkdir(path.join(source, 'src'));
  await fs.mkdir(channel, { recursive: true });
  await fs.writeFile(path.join(core, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', type: 'module', exports: './src/index.js' }));
  await fs.writeFile(path.join(core, 'src/index.js'), 'export const name = "probe"; export function apply() {}');
  await fs.writeFile(path.join(source, 'src/x.py'), 'x = 1\n');
  await fs.writeFile(path.join(channel, 'kind.py'), 'PARTS = 1\n');
  await fs.writeFile(path.join(channel, 'old.py'), 'gone soon\n');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'probe', projects: [{ id: 'probe', root: source, format: 'repository' }] });
  const candidate = path.join(workspace, 'work/self-development/probe');
  const listed = await floor.call('development_files', { prefix: 'packages/channels/' });
  assert.deepEqual(listed.files.map(row => [row.path, row.reference]), [['packages/channels/chat/python/kind.py', true],
    ['packages/channels/chat/python/old.py', true]]);
  // The source moves on: the next call brings the candidate's copy along, and a file gone from the source goes.
  await fs.writeFile(path.join(channel, 'kind.py'), 'PARTS = 2\n'); await fs.rm(path.join(channel, 'old.py'));
  await floor.call('development_files', {});
  assert.equal(await fs.readFile(path.join(candidate, 'packages/channels/chat/python/kind.py'), 'utf8'), 'PARTS = 2\n');
  await assert.rejects(fs.stat(path.join(candidate, 'packages/channels/chat/python/old.py')), { code: 'ENOENT' });
  await assert.rejects(floor.call('development_write', { path: 'packages/channels/chat/python/kind.py', text: 'PARTS = 3\n', overwrite: true }),
    /DEVELOPMENT_PATH_DENIED: .*别的包/);
  // A copy changed by a command is put back, and none of it publishes.
  await fs.writeFile(path.join(candidate, 'packages/channels/chat/python/kind.py'), 'PARTS = 9\n');
  await floor.call('development_write', { path: 'src/x.py', text: 'x = 2\n', overwrite: true });
  assert.equal(await fs.readFile(path.join(candidate, 'packages/channels/chat/python/kind.py'), 'utf8'), 'PARTS = 2\n');
  const published = await floor.call('development_publish', { reason: 'one Python change' });
  assert.deepEqual(published.changed_files, ['src/x.py']);
});

test('ADR-021 D4: an unattended turn does not publish onto a change still waiting for a Host restart', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/publication-wait-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['src'], type: 'module' }));
  await fs.mkdir(path.join(source, 'src'));
  await fs.writeFile(path.join(source, 'src/index.js'), 'export const name = "probe"; export function apply() {}');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  await floor.call('development_write', { path: 'src/index.js', text: 'export const name = "probe-2"; export function apply() {}', overwrite: true });
  const first = await floor.call('development_publish', { reason: 'a JS change' }, { unattended: true });
  assert.equal(first.state, 'HOST_RESTART_REQUIRED', JSON.stringify(first));
  await floor.call('development_write', { path: 'src/index.js', text: 'export const name = "probe-3"; export function apply() {}', overwrite: true });
  await assert.rejects(floor.call('development_publish', { reason: 'on top' }, { unattended: true }),
    /DEVELOPMENT_PUBLISH_WAITING_RESTART: 项目 persona .*重试也一样/);
  const attended = await floor.call('development_publish', { reason: 'the owner is here' }, {});
  assert.equal(attended.state, 'HOST_RESTART_REQUIRED');                    // with someone present it may replace it
});

test('a text file she changed is published with LF line endings; a binary one keeps its bytes', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });     // a fresh checkout has no data folder yet
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/line-endings-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['skills'], type: 'module' }));
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  await floor.call('development_write', { path: 'skills/probe/SKILL.md', text: 'line one\r\nline two\r\n' });
  await floor.call('development_write', { path: 'skills/probe/data.bin', text: 'a\u0000b\r\n' });
  const result = await floor.call('development_publish', { reason: 'line endings probe' });
  assert.equal(result.state, 'APPLIED', JSON.stringify(result));
  assert.equal(await fs.readFile(path.join(source, 'skills/probe/SKILL.md'), 'utf8'), 'line one\nline two\n');
  assert.equal(await fs.readFile(path.join(source, 'skills/probe/data.bin'), 'utf8'), 'a\u0000b\r\n');
  assert.equal(await fs.readFile(path.join(result.packageRoot, 'skills/probe/SKILL.md'), 'utf8'), 'line one\nline two\n');
  // Nothing more to publish: the candidate holds what was published.
  assert.equal((await floor.call('development_publish', { reason: 'again' })).state, 'NO_CHANGES');
});

test('her publication is committed where it lands, under her name, and only its own paths', async t => {
  // A git repository of its own: the floor's probes under .runtime/ are ignored by the checkout and never committed.
  const workspace = await fs.mkdtemp(path.join((await import('node:os')).tmpdir(), 'asuna-commit-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const repo = path.join(workspace, 'repo'), source = path.join(repo, 'packages/persona');
  await fs.mkdir(source, { recursive: true });
  const git = (...args) => execFileSync('git', ['-c', 'user.name=Owner', '-c', 'user.email=owner@example.com', ...args], { cwd: repo, encoding: 'utf8' });
  git('init', '-q', '-b', 'main');
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['skills'], type: 'module' }));
  await fs.writeFile(path.join(repo, 'other.txt'), 'before');
  git('add', '-A'); git('commit', '-q', '-m', 'start');
  const floor = new PublicationFloor({ dataRoot: path.join(workspace, 'data'), defaultProject: 'persona',
    projects: [{ id: 'persona', root: source, format: 'package' }] });
  await fs.writeFile(path.join(repo, 'other.txt'), 'staged by someone else'); git('add', 'other.txt');
  await floor.call('development_write', { path: 'skills/probe/SKILL.md', text: 'mine\n' });
  const result = await floor.call('development_publish', { reason: '加一份技能' }, {}, { name: 'Character', email: 'character@example.com' });
  assert.equal(result.state, 'APPLIED', JSON.stringify(result));
  assert.ok(result.commit, JSON.stringify(result));
  assert.equal(git('log', '-1', '--format=%an <%ae>|%s').trim(),'Character <character@example.com>|加一份技能');
  assert.equal(git('show', '--name-only', '--format=', 'HEAD').trim(), 'packages/persona/skills/probe/SKILL.md');
  assert.equal(git('diff', '--cached', '--name-only').trim(), 'other.txt');        // someone else's staged work, untouched
  assert.equal(git('status', '--porcelain', '--', 'packages').trim(), '');
});
