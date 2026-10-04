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
// The installed persona package is whichever other package sits beside the core.
const installed = (await fs.readdir(path.join(repo, 'packages'))).find(name => name !== 'cognition-core');
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
    const floor = new PublicationFloor({ workspace: tmp, stateDir: 'state', defaultProject: 'demo', projects: [] });
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
