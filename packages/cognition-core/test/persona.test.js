// ADR-009 P1: persona contract v2 registration and published-artifact resolution.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Context } from '@deepseek-ai/cordis';
import { CognitionCore } from '../src/index.js';
import { PublicationFloor } from '../src/floor.js';

const repo = fileURLToPath(new URL('../../../', import.meta.url));
// The installed persona package is the other package beside the core that carries a persona model;
// a channel package (e.g. napcat-qq) registers a channel instead.
const siblings = (await fs.readdir(path.join(repo, 'packages'))).filter(name => name !== 'cognition-core');
const hasModel = async name => fs.access(path.join(repo, 'packages', name, 'persona-model.json')).then(() => true, () => false);
const installed = (await Promise.all(siblings.map(async name => await hasModel(name) && name))).find(Boolean);
const channelPackages = (await Promise.all(siblings.map(async name => !await hasModel(name) && name))).filter(Boolean);
const packages = { demo: path.join(repo, 'tests/fixtures/personas/demo'), installed: path.join(repo, 'packages', installed) };

function core(persona = 'demo') {
  return new CognitionCore(new Context(), { persona });
}

async function install(core, directory) {
  const plugin = await import(pathToFileURL(path.join(directory, 'src/index.js')).href);
  const disposers = [];
  plugin.apply({ asuna: core, on: (_event, dispose) => disposers.push(dispose) });
  return JSON.parse(await fs.readFile(path.join(directory, 'package.json'), 'utf8'));
}

test('T1.1 the synthetic and the installed persona package both register; no persona leaves Core inert', async () => {
  const withDemo = core('demo');
  await install(withDemo, packages.demo);
  const demo = withDemo.personas.get('demo');
  assert.equal(demo.model, 'persona-model.json');
  assert.deepEqual(demo.seeds.map(seed => seed.kind), ['persona', 'voice', 'ledger']);
  assert.equal(demo.seeds.find(seed => seed.kind === 'persona').path, 'seeds/persona.md');
  const withInstalled = core('other');
  const manifest = await install(withInstalled, packages.installed);
  assert.equal(withInstalled.personas.size, 1);
  assert.equal(manifest.peerDependencies['@asuna/cognition-core'], '0.2.x');
  const empty = core('demo');
  await assert.rejects(empty.ready(), /Select an installed Asuna persona/);
  assert.equal(empty.lifecycle.state, 'failed');
});

test('a channel package registers its kind; its paths stay inside the package and resolve to the published artifact', async () => {
  for (const name of channelPackages) {
    const value = core('demo'), directory = path.join(repo, 'packages', name);
    await install(value, directory);
    assert.equal(value.channels.size, 1);
    const [channel] = value.channels.values();
    assert.match(channel.kind, /^[a-z][a-z0-9_]*$/);
    assert.equal(value.channelOf(channel.kind + ':bot:group:1'), channel);
    assert.equal(value.channelOf('local-dm'), null);
    await fs.access(path.join(directory, channel.python, channel.module, '__init__.py'));
    if (channel.integration_directory) await fs.access(path.join(directory, channel.integration_directory));
    const floor = new PublicationFloor({ dataRoot: os.tmpdir(), stateDir: 'x', defaultProject: 'demo', projects: [] });
    floor.effective = async () => ({ packageRoot: '/published' });
    const resolved = await floor.channel(channel);
    assert.equal(resolved.python, path.join('/published', channel.python));
    assert.throws(() => value.registerChannel({ ...channel, resource_root: directory }), /Duplicate Asuna channel kind/);
  }
  assert.throws(() => core('demo').registerChannel({ kind: 'x', project: 'x', title: 'X', module: 'x',
    resource_root: '/tmp/x', python: '../escape' }), /CHANNEL_CONTRACT_INVALID: python/);
});

test('T1.6 model, seeds, jobs and skills resolve against the published artifact, not the candidate', async () => {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-floor-'));
  try {
    const candidate = path.join(tmp, 'candidate'), published = path.join(tmp, 'published');
    for (const [root, marker] of [[candidate, 'candidate'], [published, 'published']]) {
      await fs.mkdir(path.join(root, 'seeds'), { recursive: true });
      await fs.mkdir(path.join(root, 'jobs/migrate'), { recursive: true });
      await fs.writeFile(path.join(root, 'model.json'), JSON.stringify({ model_version: 1, persona: { id: 'demo', display_name: marker } }));
      await fs.writeFile(path.join(root, 'seeds/persona.md'), '# ' + marker + '\n');
      await fs.writeFile(path.join(root, 'jobs/migrate/main.py'), '# ' + marker + '\n');
    }
    const value = core('demo');
    value.registerPersona({ id: 'demo', character_id: 'demo', display_name: 'x', version: '0', resource_root: candidate,
      model: 'model.json', seeds: [{ slug: 'persona', kind: 'persona', path: 'seeds/persona.md' }],
      jobs: [{ id: 'migrate', entry: 'jobs/migrate/main.py', runtime: 'python', grants: ['probe'], sources: [], timeout_s: 60 }],
      skill_directories: ['skills'], preset: 'x' });
    const floor = new PublicationFloor({ dataRoot: tmp, stateDir: 'state', defaultProject: 'demo', projects: [] });
    const unpublished = await floor.persona(value.personas.get('demo'));
    assert.equal(unpublished.model, path.join(candidate, 'model.json'));
    await fs.mkdir(path.join(tmp, 'state'), { recursive: true });
    await fs.writeFile(path.join(tmp, 'state/activation.json'), JSON.stringify({ projects: {},
      active: { demo: { state: 'ACTIVE', packageRoot: published } } }));
    const resolved = await floor.persona(value.personas.get('demo'));
    assert.equal(JSON.parse(await fs.readFile(resolved.model, 'utf8')).persona.display_name, 'published');
    assert.equal(await fs.readFile(resolved.seeds[0].path, 'utf8'), '# published\n');
    assert.equal(await fs.readFile(resolved.jobs[0].entry, 'utf8'), '# published\n');
    assert.equal(resolved.seeds.find(seed => seed.kind === 'persona').path, path.join(published, 'seeds/persona.md'));
    assert.deepEqual(await floor.skillPaths(value.personas.get('demo')), [path.join(published, 'skills')]);
  } finally { await fs.rm(tmp, { recursive: true, force: true }); }
});
