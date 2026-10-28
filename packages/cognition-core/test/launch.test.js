import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import fsSync from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { fastForwardCheckout, packageManagerEnv, prepareFresh, prepareLog, pruneLogs, pruneProjectionCache,
  retireOneShotSessions } from '../../../tools/asuna-launch.mjs';

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
  assert.deepEqual(changedPackages({ a: '1' }, [{ name: 'a', sha256: '1' }, { name: 'c', sha256: '4' }]), ['c'],
    'a package newly added to the profile is installed');
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-sync-'));
  try {
    const python = path.join(dir, 'python'), manifest = path.join(dir, 'manifest.json');
    await fs.writeFile(python, '');
    const launch = { config: 'config/local.json', profile: 'asuna-native',
      setup: { persona_package: 'tests/fixtures/personas/demo', channel_packages: ['packages/channels/napcat-qq'] },
      installed: { '@asuna/cognition-core': 'aa', '@asuna/demo': 'bb' } };
    const calls = [], notes = [];
    const exec = async (command, args) => { calls.push(args[0]); return 0; };
    await fs.writeFile(manifest, JSON.stringify([{ name: '@asuna/cognition-core', sha256: 'aa' }, { name: '@asuna/demo', sha256: 'bb' }]));
    assert.equal(await syncCheckout(launch, exec, note => notes.push(note), { python, manifest }), 'UP_TO_DATE');
    assert.deepEqual(calls, ['tools/pack_plugins.py'], 'unchanged: packed and compared, nothing installed');
    // A package a failed start set aside is installed again, although launch.json records it as installed.
    const selection = path.join(dir, 'activation.json');
    await fs.writeFile(selection, JSON.stringify({ projects: { core: { sha256: 'old', reverted_from: { sha256: 'aa', starts: 1 } } } }));
    let again;
    const watch = async (command, args) => { if (args[0].includes('setup')) again = true; return 0; };
    assert.equal(await syncCheckout(launch, watch, note => notes.push(note), { python, manifest, selection }), 'INSTALLED');
    assert.ok(again);
    assert.match(notes.at(-1), /installing the checkout \(@asuna\/cognition-core\)/);
    assert.deepEqual(changedPackages({ a: '1', b: '2' }, [{ name: 'a', sha256: '1' }, { name: 'b', sha256: '2' }], ['2']), ['b']);
    await fs.writeFile(manifest, JSON.stringify([{ name: '@asuna/cognition-core', sha256: 'cc' }, { name: '@asuna/demo', sha256: 'bb' }]));
    let installArgs;
    const record = async (command, args) => { if (args[0].includes('setup')) installArgs = args; return 0; };
    assert.equal(await syncCheckout(launch, record, note => notes.push(note), { python, manifest }), 'INSTALLED');
    assert.match(notes.at(-1), /installing the checkout \(@asuna\/cognition-core\)/);
    assert.deepEqual(installArgs, ['tools/setup_native_profile.py', '--config', 'config/local.json', '--profile', 'asuna-native',
      '--persona-package', 'tests/fixtures/personas/demo', '--channel-package', 'packages/channels/napcat-qq']);
    assert.equal(await syncCheckout({ ...launch, setup: undefined }, exec, note => notes.push(note), { python, manifest }), 'UNKNOWN');
    assert.equal(await syncCheckout(launch, exec, note => notes.push(note), { python: path.join(dir, 'none'), manifest }), 'NO_PYTHON');
    await assert.rejects(syncCheckout(launch, async () => 1, () => {}, { python, manifest }), /--no-sync/);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test('ADR-020: a profile starts on its own recorded Web port unless this start names one', async () => {
  const { resolveLaunch, profileBase, listProfiles } = await import('../../../tools/asuna-launch.mjs');
  const profile = 'port-probe-' + process.pid;
  const base = profileBase(profile);
  const config = path.join(base, 'config.json');
  await fs.mkdir(base, { recursive: true });
  try {
    await fs.writeFile(config, JSON.stringify({ database: 'asuna_v2_test_port_probe', chat: { persona: 'demo' } }));
    await fs.writeFile(path.join(base, 'launch.json'), JSON.stringify({ config, port: 8799 }));
    assert.equal((await resolveLaunch(['ui', '--profile', profile, '--dry-run'], {})).port, 8799);
    assert.equal((await resolveLaunch(['ui', '--profile', profile, '--port', '8801', '--dry-run'], {})).port, 8801);
    const row = (await listProfiles()).find(item => item.profile === profile);
    assert.deepEqual({ ...row, running: undefined }, { profile, persona: 'demo', port: 8799,
      database: 'asuna_v2_test_port_probe', running: undefined });
    await fs.writeFile(path.join(base, 'launch.json'), JSON.stringify({ config }));
    assert.equal((await resolveLaunch(['ui', '--profile', profile, '--dry-run'], {})).port, 8780);   // as before
  } finally {
    await fs.rm(base, { recursive: true, force: true });
  }
});

test('the supervisor waits on the profile data folder its worker writes to (setup_native_profile.data_folder)', async () => {
  const { dataFolder, profileBase } = await import('../../../tools/asuna-launch.mjs');
  const root = fileURLToPath(new URL('../../../', import.meta.url));
  assert.equal(dataFolder('asuna-native'), path.join(root, '.runtime'));
  assert.equal(dataFolder('kazusa'), profileBase('kazusa'));
  assert.equal(dataFolder('kazusa'), path.join(root, '.runtime', 'adr008', 'profiles', 'kazusa'));
});

// A child of the launcher script, as prepareFresh spawns it: writes some lines, then exits with `code`.
function fakeChild(lines, code, seen) {
  return argv => {
    seen.push(argv);
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough();
    setImmediate(() => {
      for (const [stream, text] of lines) child[stream].write(text);
      child.stdout.end(); child.stderr.end();
      setImmediate(() => child.emit('close', code));
    });
    return child;
  };
}

test('ADR-034: each start is prepared by a fresh process from the code on disk; its output is kept in a log', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-prepare-'));
  try {
    const logFile = path.join(dir, 'restart', 'prepare.log'), seen = [], shown = [];
    const quiet = { out: text => shown.push(text), err: text => shown.push(text) };
    const notes = await prepareFresh(0, ['ui', '--profile', 'asuna-native'], { logFile, ...quiet,
      spawnChild: fakeChild([['stdout', 'Asuna: installing the checkout (@asuna/cognition-core)\n'],
        ['stdout', 'ASUNA_PREPARE_CHECKOUT {"state":"up_to_date","detail":"abc1234"}\n'],
        ['stdout', 'ASUNA_PREPARE_NOTES ["core: returned to the previous running selection"]\n']], 0, seen) });
    assert.deepEqual(notes, { notes: ['core: returned to the previous running selection'],
      checkout: { state: 'up_to_date', detail: 'abc1234' } });
    assert.match(seen[0][0], /asuna-launch\.mjs$/);
    assert.deepEqual(seen[0].slice(1), ['ui', '--profile', 'asuna-native', '--prepare', '0'], 'its own arguments, then the rung');
    assert.match(await fs.readFile(logFile, 'utf8'), /rung 0\n.*installing the checkout/s);
    assert.ok(shown.join('').includes('installing the checkout'), 'the console still sees it');
    await assert.rejects(prepareFresh(0, [], { logFile, ...quiet, spawnChild: fakeChild([['stderr',
      'setup_native_profile.py: error: unrecognized arguments: --shared-action-model\n']], 2, seen) }),
      /preparing failed \(exit 2\): setup_native_profile\.py: error: unrecognized arguments: --shared-action-model .*prepare\.log/);
    assert.match(await fs.readFile(logFile, 'utf8'), /unrecognized arguments/, 'rewritten for this start');
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test('finished one-shot sessions (summaries, gate looks) leave the session store before a start, and the archive keeps them two weeks', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-retire-'));
  try {
    const home = path.join(dir, 'home'), archive = path.join(dir, 'archive'), project = path.join(home, 'sessions', 'p');
    const day = 24 * 3600 * 1000, now = Date.now();
    const make = async (folder, id, age) => {
      await fs.mkdir(path.join(folder, id), { recursive: true });
      await fs.writeFile(path.join(folder, id, 'session.v4.jsonl.zstd'), '');
      const at = new Date(now - age); await fs.utimes(path.join(folder, id), at, at);
    };
    await make(project, 'asuna-summary-old', 2 * day);
    await make(project, 'asuna-summary-fresh', 3600 * 1000);           // may still be asked again (a retry)
    await make(project, 'asuna-attend-old', 2 * day);                    // a gate look keeps nothing for later
    await make(project, 'asuna-errand-old', 2 * day);                    // an errand's copy of a conversation (ADR-066)
    await make(project, 'asuna-role-old', 30 * day);                     // her conversations are never touched
    await make(path.join(archive, 'p'), 'asuna-summary-gone', 15 * day);
    assert.deepEqual(await retireOneShotSessions(home, archive, now), { moved: 3, dropped: 1 });
    assert.deepEqual((await fs.readdir(project)).sort(), ['asuna-role-old', 'asuna-summary-fresh']);
    assert.deepEqual((await fs.readdir(path.join(archive, 'p'))).sort(), ['asuna-attend-old', 'asuna-errand-old', 'asuna-summary-old']);
    assert.deepEqual(await retireOneShotSessions(path.join(dir, 'none'), path.join(dir, 'none-archive'), now), { moved: 0, dropped: 0 });
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('ADR-065: her restart fast-forwards the checkout to origin/main only when it can, and says why when not', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-ff-'));
  const git = (cwd, ...args) => execFileSync('git', ['-C', cwd, ...args], { encoding: 'utf8' }).trim();
  const commit = (cwd, file, text) => { fsSync.writeFileSync(path.join(cwd, file), text);
    git(cwd, 'add', file); git(cwd, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '-m', file); };
  try {
    const origin = path.join(dir, 'origin.git'), checkout = path.join(dir, 'checkout'), other = path.join(dir, 'other');
    execFileSync('git', ['init', '-q', '--bare', '-b', 'main', origin]);
    execFileSync('git', ['clone', '-q', origin, other]);
    git(other, 'checkout', '-q', '-b', 'main'); commit(other, 'a.txt', 'a'); git(other, 'push', '-q', 'origin', 'main');
    execFileSync('git', ['clone', '-q', origin, checkout]);
    assert.equal((await fastForwardCheckout(checkout)).state, 'up_to_date');
    commit(other, 'b.txt', 'b'); git(other, 'push', '-q', 'origin', 'main');
    const before = git(checkout, 'rev-parse', '--short', 'HEAD');
    // Not on main, and changed tracked files: nothing moves.
    git(checkout, 'checkout', '-q', '-b', 'feature');
    assert.deepEqual(await fastForwardCheckout(checkout), { state: 'not_main', detail: 'feature' });
    git(checkout, 'checkout', '-q', 'main');
    fsSync.writeFileSync(path.join(checkout, 'a.txt'), 'changed');
    assert.deepEqual(await fastForwardCheckout(checkout), { state: 'changed_files', detail: '1 file(s), first a.txt' });
    git(checkout, 'checkout', '-q', '--', 'a.txt');
    fsSync.writeFileSync(path.join(checkout, 'untracked.txt'), 'not in git');      // untracked files do not stop it
    assert.equal(git(checkout, 'rev-parse', '--short', 'HEAD'), before);
    const moved = await fastForwardCheckout(checkout);
    assert.equal(moved.state, 'fast_forwarded');
    assert.equal(git(checkout, 'rev-parse', 'HEAD'), git(other, 'rev-parse', 'HEAD'));
    assert.equal(moved.detail, before + '..' + git(checkout, 'rev-parse', '--short', 'HEAD'));
    // A commit of its own that origin does not have: never merged, rebased or reset.
    commit(other, 'c.txt', 'c'); git(other, 'push', '-q', 'origin', 'main');
    commit(checkout, 'mine.txt', 'mine');
    const mine = git(checkout, 'rev-parse', 'HEAD');
    assert.equal((await fastForwardCheckout(checkout)).state, 'diverged');
    assert.equal(git(checkout, 'rev-parse', 'HEAD'), mine);
    // No origin to fetch from: the start goes on with what is on disk.
    git(checkout, 'remote', 'set-url', 'origin', path.join(dir, 'missing.git'));
    const failed = await fastForwardCheckout(checkout);
    assert.equal(failed.state, 'fetch_failed'); assert.ok(failed.detail.length > 0);
    assert.equal(git(checkout, 'rev-parse', 'HEAD'), mine);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
});

test('ADR-065: a fast-forward git itself refuses leaves the checkout as it was and says so', async () => {
  const answers = { fetch: '', 'symbolic-ref': 'main', status: '', 'rev-parse': 'abc1234', 'merge-base': '' };
  const seen = [];
  const git = async args => {
    seen.push(args[0]);
    if (args[0] === 'merge') return { code: 128, stdout: '', stderr: 'error: x\nfatal: Not possible to fast-forward' };
    if (args[0] === 'rev-parse') return { code: 0, stdout: args.at(-1) === 'HEAD' ? 'abc1234' : 'def5678', stderr: '' };
    return { code: 0, stdout: answers[args[0]] ?? '', stderr: '' };
  };
  assert.deepEqual(await fastForwardCheckout('unused', git),
    { state: 'fast_forward_failed', detail: 'fatal: Not possible to fast-forward' });
  assert.ok(!seen.some(command => ['rebase', 'reset', 'pull'].includes(command)), 'never rebases, resets or pulls');
});

test('a writer lock a Host that stopped left empty is cleared before a start; a lock with content or another file is not', async () => {
  const { clearEmptyLocks } = await import('../../../tools/asuna-launch.mjs');
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-locks-'));
  try {
    await fs.writeFile(path.join(home, '.credentials.yaml.lock'), '');
    await fs.writeFile(path.join(home, 'settings.yaml.lock'), '4242\n');
    await fs.writeFile(path.join(home, 'empty.txt'), '');
    await fs.mkdir(path.join(home, 'folder.lock'));
    assert.deepEqual(await clearEmptyLocks(home), ['.credentials.yaml.lock']);
    assert.deepEqual((await fs.readdir(home)).sort(), ['empty.txt', 'folder.lock', 'settings.yaml.lock']);
    assert.deepEqual(await clearEmptyLocks(path.join(home, 'none')), []);
  } finally {
    await fs.rm(home, { recursive: true, force: true });
  }
});

test('projection-cache records of sessions no longer in the store are removed before a start; a store read as empty is left alone', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-projcache-'));
  try {
    const home = path.join(dir, 'home'), cache = path.join(home, 'storages', 'session_projcache', 'sessions');
    await fs.mkdir(cache, { recursive: true });
    for (const id of ['asuna-role-a', 'asuna-summary-gone', 'asuna-attend-gone']) await fs.writeFile(path.join(cache, id + '.json'), '{}');
    await fs.writeFile(path.join(cache, 'notes.txt'), '');
    assert.equal(await pruneProjectionCache(home), 0, 'no session listed: nothing is removed');
    await fs.mkdir(path.join(home, 'sessions', 'p', 'asuna-role-a'), { recursive: true });
    assert.equal(await pruneProjectionCache(home), 2);
    assert.deepEqual((await fs.readdir(cache)).sort(), ['asuna-role-a.json', 'notes.txt']);
    assert.equal(await pruneProjectionCache(path.join(dir, 'none')), 0);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test("each restart's preparation logs are its own, and the newest ten restarts keep theirs", async () => {
  // A failed rung 0's log was overwritten by rung 1 and its error lost (2026-10-28).
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-prepare-logs-'));
  try {
    // Ids as the supervisor makes them (begin): 'restart-' and the UTC time to the second.
    const ids = Array.from({ length: 12 }, (_, i) =>
      'restart-' + new Date(Date.UTC(2026, 9, 28, 6, i)).toISOString().replace(/[-:.TZ]/g, '').slice(0, 14));
    assert.equal(path.basename(prepareLog(dir, ids[0], 1)), 'prepare-' + ids[0] + '-rung1.log');
    for (const id of ids) for (const rung of [0, 1]) await fs.writeFile(prepareLog(dir, id, rung), id);
    await fs.writeFile(path.join(dir, 'prepare.log'), 'the shared log of an earlier naming');
    await fs.writeFile(path.join(dir, 'last.json'), '{}');
    const removed = await pruneLogs(dir);
    assert.deepEqual(removed.sort(), ['prepare-' + ids[0] + '-rung0.log', 'prepare-' + ids[0] + '-rung1.log',
      'prepare-' + ids[1] + '-rung0.log', 'prepare-' + ids[1] + '-rung1.log', 'prepare.log'].sort());
    const left = (await fs.readdir(dir)).sort();
    assert.equal(left.length, 21, 'ten restarts with two rungs each, and last.json');
    assert.ok(left.includes('last.json') && left.includes('prepare-' + ids[11] + '-rung1.log'));
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
