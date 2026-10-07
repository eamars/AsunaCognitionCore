import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import LocalSpillStore from '@deepseek-ai/dsh-spill-local';
import { PublicationFloor } from '../src/floor.js';
import { readSpill } from '../src/spill.js';

test('actual npm artifact freezes a bounded candidate; edits do not change active resources', async () => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });     // a fresh checkout has no data folder yet
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/publication-probe-'));
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
  console.log('Publication artifact evidence:', result.artifact);
});

test('ADR-010 D9: a file she changed whose source moved after her baseline is marked stale before publish', async () => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });     // a fresh checkout has no data folder yet
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/stale-probe-'));
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

test('native spilled output stays readable only by its own action, in bounded pages', async () => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const root = await fs.mkdtemp(path.resolve('.runtime/adr008/spill-probe-'));
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
});

test('ADR-021 D4: an unattended turn does not publish onto a change still waiting for a Host restart', async () => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/publication-wait-'));
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
