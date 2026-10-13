import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { ensureWorkingCopies, ensureWorkingCopy } from '../src/working-copy.js';

const git = (cwd, ...args) => execFileSync('git', ['-C', cwd, ...args], { encoding: 'utf8' }).trim();

test('ADR-065: her working copy is a full clone made once, with the checkout\'s origin, never reset', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/working-copy-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const checkout = path.join(workspace, 'checkout'), home = path.join(workspace, 'data/work/local-user');
  await fs.mkdir(checkout);
  git(checkout, 'init', '-q', '-b', 'main');
  await fs.writeFile(path.join(checkout, 'a.txt'), 'a\n');
  git(checkout, 'add', 'a.txt');
  git(checkout, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '-m', 'a');
  git(checkout, 'branch', 'someone-elses-work');
  git(checkout, 'remote', 'add', 'origin', 'https://example.invalid/project.git');
  assert.deepEqual(await ensureWorkingCopy(undefined, home), { state: 'no checkout', path: path.join(home, 'working-copy') });
  const made = await ensureWorkingCopy(checkout, home);
  assert.equal(made.state, 'created');
  assert.equal(git(made.path, 'remote', 'get-url', 'origin'), 'https://example.invalid/project.git');
  assert.equal(git(made.path, 'log', '--format=%s'), 'a');
  assert.equal(git(made.path, 'branch', '--all', '--format=%(refname:short)'), 'main\norigin/main');
  assert.equal(git(made.path, 'config', 'remote.origin.fetch'), '+refs/heads/*:refs/remotes/origin/*');
  // What she does there stays: a second start finds it and changes nothing.
  await fs.writeFile(path.join(made.path, 'a.txt'), 'hers\n');
  assert.equal((await ensureWorkingCopy(checkout, home)).state, 'present');
  assert.equal(await fs.readFile(path.join(made.path, 'a.txt'), 'utf8'), 'hers\n');
  await assert.rejects(fs.stat(made.path + '.partial'));
});

test('ADR-065: every home place gets its own working copy, each made once; one that fails does not stop the rest', async t => {
  await fs.mkdir(path.resolve('.runtime/adr008'), { recursive: true });
  const workspace = await fs.mkdtemp(path.resolve('.runtime/adr008/working-copies-'));
  t.after(() => fs.rm(workspace, { recursive: true, force: true }));
  const checkout = path.join(workspace, 'checkout');
  await fs.mkdir(checkout);
  git(checkout, 'init', '-q', '-b', 'main');
  await fs.writeFile(path.join(checkout, 'a.txt'), 'a\n');
  git(checkout, 'add', 'a.txt');
  git(checkout, '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', 'commit', '-q', '-m', 'a');
  git(checkout, 'remote', 'add', 'origin', 'https://example.invalid/project.git');
  const homes = ['work/local-user', 'channels/agent-one', 'channels/peer'].map(name => path.join(workspace, name));
  const blocked = path.join(workspace, 'blocked');
  await fs.writeFile(blocked, 'a file where a folder should be');
  const warned = [];
  const made = await ensureWorkingCopies(checkout, [homes[0], blocked, homes[1], homes[2]], () => {}, text => warned.push(text));
  assert.deepEqual(made, homes.map(home => path.join(home, 'working-copy')));
  assert.equal(warned.length, 1);
  for (const home of homes) assert.equal(git(path.join(home, 'working-copy'), 'log', '--format=%s'), 'a');
  assert.deepEqual(await ensureWorkingCopies(checkout, homes), [], 'a second start makes none');
});
