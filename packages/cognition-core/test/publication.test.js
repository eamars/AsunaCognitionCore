import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { Context } from '@deepseek-ai/cordis';
import LocalSpillStore from '@deepseek-ai/dsh-spill-local';
import { PublicationFloor } from '../src/floor.js';
import { CognitionCore } from '../src/index.js';
import { asunaLogExporter } from '../src/log-sink.js';
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
  await floor.call('development_write', { path: '.tmp/scratch.py', text: 'her temporary folder' });
  const second = await floor.call('development_publish', { reason: 'a document only' });
  assert.equal(second.state, 'ACTIVE', JSON.stringify(second));            // not APPLIED: the Host restarts for APPLIED
  assert.equal(second.activated, true, 'what runs now');
  assert.equal(second.unchanged, true, 'the running package: nothing swapped in');
  assert.equal(first.unchanged, undefined);
  assert.equal(second.sha256, first.sha256);
  assert.deepEqual(second.changed_files, ['docs/notes.md']);
  assert.equal(await fs.readFile(path.join(source, 'docs/notes.md'), 'utf8'), 'outside the package');
  await assert.rejects(fs.stat(path.join(source, '.tmp')));                 // the sandbox's temporary folder never reaches the source
  assert.equal((await floor.effective('persona')).sha256, first.sha256);
  await floor.call('development_write', { path: 'README.md', text: 'Changed again', overwrite: true });
  assert.equal((await floor.call('development_publish', { reason: 'packed again' })).state, 'APPLIED');
});

test('each publication has its own receipt: A, B, then A again (a revert) gives three', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/revert-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['README.md'], type: 'module' }));
  await fs.writeFile(path.join(source, 'README.md'), 'Running');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  const publish = async text => {
    await floor.call('development_write', { path: 'README.md', text, overwrite: true });
    return floor.call('development_publish', { reason: text });
  };
  const a = await publish('A');
  await floor.workerReady('persona');
  const b = await publish('B');
  const reverted = await publish('A');
  assert.equal(reverted.candidate, a.candidate, 'the same content');
  assert.equal(reverted.state, 'ACTIVE', 'A is still the running package');
  assert.equal(new Set([a.receipt_id, b.receipt_id, reverted.receipt_id]).size, 3, JSON.stringify([a, b, reverted].map(r => r.receipt_id)));
  for (const receipt of [a, b, reverted]) assert.ok(receipt.receipt_id.startsWith('self-publish-' + receipt.candidate.slice(0, 32) + '-'));
  assert.equal((await floor.selected()).projects.persona.receipt_id, reverted.receipt_id);
});

// A Core over a stand-in floor and worker: what the Host does around a publication.
const persona = model => ({ id: 'demo', resource_root: '/installed', model, seeds: [], jobs: [], skill_directories: [] });
function hostWith(floor, call, logged = []) {
  const core = new CognitionCore({ get: () => undefined, agents: { get: () => undefined }, llm: {}, asunaFloor: floor,
    logger: { info: line => logged.push(line) } }, { persona: 'demo', deployment: {}, routes: {} });
  core.personas.set('demo', persona('persona-model.json'));
  core.channelPlugins = async () => [];
  core.worker = { call };
  return core;
}

test('a persona publication applied in place: the receipt says what the worker took, one log line each time', async () => {
  const logged = [], readied = [];
  const record = { project: 'persona', state: 'APPLIED', sha256: 'abcdef0123456789', receipt_id: 'self-publish-x' };
  const floor = { persona: async persona => persona, skillPaths: async () => ['persona-skills'], effective: async () => undefined,
    workerReady: async id => { readied.push(id); return [{ ...record, state: 'ACTIVE', activated_at: '2026-10-21T09:00:00.000Z' }]; } };
  const lines = ['persona model swapped', 'skills swapped: new action scopes read them from this package', 'existing self heads preserved'];
  const core = hostWith(floor, async (method, args) => {
    assert.equal(method, 'persona.resources'); assert.ok(args.skill_directories.includes('persona-skills'));
    return { accepted: true, applied: lines };
  }, logged);
  const swapped = await core.applyInPlace({ ...record, activated: false, commit: 'c0ffee1' });
  assert.equal(swapped.state, 'ACTIVE');
  assert.equal(swapped.activated, true);
  assert.deepEqual(swapped.applied, lines, 'the worker\'s own lines');
  assert.equal(swapped.commit, 'c0ffee1', 'the commit survives the activation record');
  assert.deepEqual(readied, ['persona']);
  assert.deepEqual(logged, ['Asuna publication: persona abcdef012345 applied in place: ' + lines.join('; ')]);
  // The line reaches restart/host.log: the log sink keeps lines that start with Asuna.
  const written = [];
  asunaLogExporter(text => written.push(text)).export({ ts: 0, type: 'info', args: [logged[0]] });
  assert.equal(written.length, 1);
});

test('the running worker reads a persona candidate as it would take it, before anything is selected', async () => {
  const calls = [];
  const floor = { config: { defaultProject: 'persona' } };
  const core = hostWith(floor, async (method, args) => {
    calls.push([method, args.persona.model]);
    return { refused: args.persona.model.includes('bad') ? 'PERSONA_ID_MISMATCH: …：正在跑的这个工作进程装不上这个人格包' : null };
  });
  core.lifecycle.state = 'ready';
  assert.equal((await core.personaProbe('persona', path.resolve('/candidate'))).exit_code, 0);
  assert.deepEqual(calls, [['persona.check', path.join(path.resolve('/candidate'), 'persona-model.json')]], 'read at the candidate');
  core.personas.set('demo', persona('bad-model.json'));
  const refused = await core.personaProbe('persona', path.resolve('/candidate'));
  assert.equal(refused.exit_code, 1);
  assert.match(refused.stderr, /PERSONA_ID_MISMATCH.*装不上/);
  // Another project has no persona model; a worker not running cannot say (recovery): the probe passes both.
  assert.equal((await core.personaProbe('napcat-qq', '/candidate')).exit_code, 0);
  core.lifecycle.state = 'failed';
  assert.equal((await core.personaProbe('persona', '/candidate')).exit_code, 0);
  assert.equal(calls.length, 2);
});

test('a persona package the worker would refuse is refused at publication: nothing selected, nothing written back', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/persona-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(source);
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe', version: '0.0.0', files: ['README.md'], type: 'module' }));
  await fs.writeFile(path.join(source, 'README.md'), 'Running');
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
  const read = [];
  floor.setPersonaProbe(async (project, root) => { read.push([project, root]);
    return { exit_code: 1, stdout: '', stderr: 'PERSONA_STATE_ID_MISMATCH：正在跑的这个工作进程装不上这个人格包' }; });
  await floor.call('development_write', { path: 'README.md', text: 'Refused', overwrite: true });
  const refused = await floor.call('development_publish', { reason: 'refused by the worker' });
  assert.equal(refused.state, 'BOOT_FAILED');
  assert.equal(refused.activated, false);
  assert.match(refused.boot_probe.stderr, /PERSONA_STATE_ID_MISMATCH/);
  assert.equal(read[0][0], 'persona');
  assert.equal((await floor.selected()).projects.persona, undefined, 'nothing selected');
  assert.equal(await fs.readFile(path.join(source, 'README.md'), 'utf8'), 'Running', 'nothing copied to the source');
  // Released, the probe no longer runs; the same candidate then publishes.
  const release = floor.setPersonaProbe(async () => ({ exit_code: 0, stdout: ' The running worker takes this persona package.\n', stderr: '' }));
  const taken = await floor.call('development_publish', { reason: 'taken' });
  assert.equal(taken.state, 'APPLIED', JSON.stringify(taken.boot_probe));
  assert.match(taken.boot_probe.stdout, /The running worker takes this persona package/);
  release();
  assert.equal(floor.personaProbe, null);
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

test('ADR-078: a skill header the program would refuse is refused at publication, never read as home only', async t => {
  const { checkoutPython } = await import('../../../tools/asuna-launch.mjs');
  const python = checkoutPython(path.resolve('.'), process.platform);
  try { await fs.access(python); } catch { t.skip('no checkout Python to read skill headers'); return; }
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/skill-probe-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const source = path.join(workspace, 'source'); await fs.mkdir(path.join(source, 'src'), { recursive: true });
  await fs.mkdir(path.join(source, 'skills/probe-skill'), { recursive: true });
  await fs.writeFile(path.join(source, 'package.json'), JSON.stringify({ name: '@asuna/probe-skills', version: '0.0.0',
    type: 'module', exports: { '.': './src/index.js' }, files: ['src', 'skills'] }));
  await fs.writeFile(path.join(source, 'src/index.js'), "export const name = 'probe';\nexport function apply() {}\n");
  const header = extra => `---\nname: probe-skill\ndescription: a skill to probe\n${extra}---\n\nbody\n`;
  await fs.writeFile(path.join(source, 'skills/probe-skill/SKILL.md'), header(''));
  const floor = new PublicationFloor({ dataRoot: workspace, defaultProject: 'persona', python,
    projects: [{ id: 'persona', root: source, format: 'package' }] });
  floor.workerPath = async () => path.resolve('src');
  await floor.call('development_write', { path: 'skills/probe-skill/SKILL.md', overwrite: true,
    text: header('scene_kinds: [home, group]\n') });
  const good = await floor.call('development_publish', { reason: 'a skill that may be used in groups' });
  assert.match(good.state, /^(APPLIED|HOST_RESTART_REQUIRED)$/, JSON.stringify(good.boot_probe));
  assert.match(good.boot_probe.stdout, /Skill headers valid/);
  await floor.call('development_write', { path: 'skills/probe-skill/SKILL.md', overwrite: true,
    text: header('scene_kind: [group]\n') });
  const refused = await floor.call('development_publish', { reason: 'a misspelt key' });
  assert.equal(refused.state, 'BOOT_FAILED');
  assert.match(refused.boot_probe.stderr, /技能 probe-skill：头里有不认识的键 scene_kind.*照这个改 SKILL.md 的头再发布/s);
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
