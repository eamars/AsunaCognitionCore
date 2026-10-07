import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import LocalSpillStore from '@deepseek-ai/dsh-spill-local';
import { PublicationFloor } from '../src/floor.js';
import { readSpill } from '../src/spill.js';

test('actual npm artifact freezes a bounded candidate; edits do not change active resources', async () => {
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
  assert.match(listing.stale_note, /publish refuses/);
  await assert.rejects(floor.call('development_publish', { reason: 'stale' }).then(r => { throw new Error(r.state); }),
    /EFFECTIVE_PROJECT_CHANGED: a\.md/);
});

test('native spilled output stays readable only by its own action, in bounded pages', async () => {
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
