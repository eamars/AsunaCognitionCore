import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { packageManagerEnv } from '../../../tools/asuna-launch.mjs';

const pnpmName = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm';
const corepackName = process.platform === 'win32' ? 'corepack.cmd' : 'corepack';

test('a restart can install the selected candidate without a global pnpm: the DSH child gets corepack\'s', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-launch-'));
  try {
    const node = path.join(dir, 'node'), shim = path.join(dir, 'shim'), tools = path.join(dir, 'tools');
    await fs.mkdir(node); await fs.mkdir(tools);
    await fs.writeFile(path.join(node, corepackName), '');
    // The PATH key keeps its spelling (Windows uses "Path"); the shim goes first and corepack does not prompt.
    const env = await packageManagerEnv({ Path: tools, DSH_HOME: 'home' }, { nodeDir: node, shimDir: shim });
    assert.deepEqual(env.Path.split(path.delimiter), [shim, tools]);
    assert.equal(env.PATH, undefined);
    assert.equal(env.COREPACK_ENABLE_DOWNLOAD_PROMPT, '0');
    assert.equal(env.DSH_HOME, 'home');
    assert.match(await fs.readFile(path.join(shim, pnpmName), 'utf8'), new RegExp(corepackName.replace('.', '\\.') + '" pnpm'));

    // An installed pnpm is used as is, and without corepack nothing is invented.
    await fs.writeFile(path.join(tools, pnpmName), '');
    const own = { Path: tools };
    assert.equal(await packageManagerEnv(own, { nodeDir: node, shimDir: path.join(dir, 'unused') }), own);
    const bare = { Path: path.join(dir, 'empty') };
    assert.equal(await packageManagerEnv(bare, { nodeDir: path.join(dir, 'empty'), shimDir: path.join(dir, 'unused') }), bare);
    await assert.rejects(fs.access(path.join(dir, 'unused')));
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test('ADR-011 §6.4: a selection that never comes up returns to the previous running one; the source stays', async () => {
  const { advanceSelection, MAX_UNCONFIRMED_STARTS } = await import('../../../tools/asuna-launch.mjs');
  const previous = { candidate: 'old', artifact: 'old.tgz', sha256: 'aa', state: 'ACTIVE', packageRoot: 'old-root' };
  const selection = { projects: {
    core: { candidate: 'new', artifact: 'new.tgz', sha256: 'bb', state: 'APPLIED', published_at: 't', previous },
    persona: { candidate: 'p', artifact: 'p.tgz', state: 'ACTIVE' },
    first: { candidate: 'f', artifact: 'f.tgz', state: 'APPLIED' } } };
  for (let start = 1; start <= MAX_UNCONFIRMED_STARTS; start++) assert.deepEqual(advanceSelection(selection), []);
  assert.equal(selection.projects.core.boots, MAX_UNCONFIRMED_STARTS);
  const notes = advanceSelection(selection, 'now');
  assert.match(notes[0], /core: returned to the previous running selection/);
  assert.match(notes[1], /first: never started, and there is no earlier running selection/);
  assert.deepEqual(selection.projects.core, { ...previous, state: 'HOST_RESTART_REQUIRED', reverted_at: 'now',
    reverted_from: { candidate: 'new', sha256: 'bb', published_at: 't', starts: MAX_UNCONFIRMED_STARTS + 1 } },
    'the launcher installs the previous artifact again; nothing else changes');
  assert.equal(selection.projects.persona.boots, undefined, 'a running selection is left alone');
});

test('owner 2026-10-07: a start installs the checkout only when its packed digests changed', async () => {
  const { syncCheckout, changedPackages, checkoutPython } = await import('../../../tools/asuna-launch.mjs');
  assert.equal(checkoutPython('/repo', 'linux'), path.join('/repo', '.venv', 'bin', 'python'));
  assert.equal(changedPackages({}, []), null, 'nothing recorded: install everything');
  assert.deepEqual(changedPackages({ a: '1', b: '2' }, [{ name: 'a', sha256: '1' }, { name: 'b', sha256: '3' }]), ['b']);
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-sync-'));
  try {
    const python = path.join(dir, 'python'), manifest = path.join(dir, 'manifest.json');
    await fs.writeFile(python, '');
    const launch = { config: 'config/local.json', profile: 'asuna-native', sharedActionModel: true,
      setup: { persona_package: 'packages/personas/xiaoman', channel_packages: ['packages/channels/napcat-qq'] },
      installed: { '@asuna/cognition-core': 'aa', '@asuna/xiaoman': 'bb' } };
    const calls = [], notes = [];
    const exec = async (command, args) => { calls.push(args[0]); return 0; };
    await fs.writeFile(manifest, JSON.stringify([{ name: '@asuna/cognition-core', sha256: 'aa' }, { name: '@asuna/xiaoman', sha256: 'bb' }]));
    assert.equal(await syncCheckout(launch, exec, note => notes.push(note), { python, manifest }), 'UP_TO_DATE');
    assert.deepEqual(calls, ['tools/pack_plugins.py'], 'unchanged: packed and compared, nothing installed');
    await fs.writeFile(manifest, JSON.stringify([{ name: '@asuna/cognition-core', sha256: 'cc' }, { name: '@asuna/xiaoman', sha256: 'bb' }]));
    let installArgs;
    const record = async (command, args) => { if (args[0].includes('setup')) installArgs = args; return 0; };
    assert.equal(await syncCheckout(launch, record, note => notes.push(note), { python, manifest }), 'INSTALLED');
    assert.match(notes.at(-1), /installing the checkout \(@asuna\/cognition-core\)/);
    assert.deepEqual(installArgs, ['tools/setup_native_profile.py', '--config', 'config/local.json', '--profile', 'asuna-native',
      '--persona-package', 'packages/personas/xiaoman', '--channel-package', 'packages/channels/napcat-qq', '--shared-action-model']);
    assert.equal(await syncCheckout({ ...launch, setup: undefined }, exec, note => notes.push(note), { python, manifest }), 'UNKNOWN');
    assert.equal(await syncCheckout(launch, exec, note => notes.push(note), { python: path.join(dir, 'none'), manifest }), 'NO_PYTHON');
    await assert.rejects(syncCheckout(launch, async () => 1, () => {}, { python, manifest }), /--no-sync/);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});
