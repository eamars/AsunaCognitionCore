/** Her own working copies of the local checkout (owner 2026-10-13, ADR-065): a full clone in each home place's working
 * folder (a command writes only its own folder), where her confined commands may write, commit and push. Its `origin`
 * is the checkout's own origin. The Host makes each when it is missing and never changes one that is there; none is
 * the checkout, and nothing the Host runs is in one. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';

export const FOLDER = 'working-copy';

const git = (args, options = {}) => new Promise((resolve, reject) => execFile('git', args,
  { windowsHide: true, maxBuffer: 1 << 20, ...options }, (error, stdout) => error ? reject(error) : resolve(stdout.trim())));

/** Make `<workspace>/working-copy` from `checkout` unless it exists: {state: 'present' | 'created' | 'no checkout', path}. */
export async function ensureWorkingCopy(checkout, workspace) {
  const target = path.join(workspace, FOLDER);
  if (!checkout) return { state: 'no checkout', path: target };
  if (await fs.stat(target).then(() => true, () => false)) return { state: 'present', path: target };
  const origin = await git(['-C', checkout, 'remote', 'get-url', 'origin']);
  const branch = await git(['-C', checkout, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD'])
    .then(ref => ref.replace(/^origin\//, ''), () => 'main');
  // Made beside it and renamed: a copy half made by a stopped Host is never taken for hers.
  const partial = target + '.partial';
  await fs.rm(partial, { recursive: true, force: true });
  await fs.mkdir(workspace, { recursive: true });
  // From the checkout on this disk (no network at start); its own object files (no hard links into the checkout).
  await git(['clone', '--quiet', '--no-hardlinks', '--single-branch', '--branch', branch, checkout, partial]);
  await git(['-C', partial, 'remote', 'set-url', 'origin', origin]);
  await git(['-C', partial, 'config', 'remote.origin.fetch', '+refs/heads/*:refs/remotes/origin/*']);
  await fs.rename(partial, target);
  return { state: 'created', path: target };
}

/** A working copy in each of these folders (the worker's home_workspaces), one after another; says what it made or
 * could not make. */
export async function ensureWorkingCopies(checkout, workspaces, info = () => {}, warn = () => {}) {
  const made = [];
  for (const workspace of workspaces) {
    try {
      const copy = await ensureWorkingCopy(checkout, workspace);
      if (copy.state === 'created') { made.push(copy.path); info('Asuna: made her working copy at ' + copy.path); }
    } catch (error) {
      warn('Asuna: her working copy in ' + workspace + ' was not made: ' + String(error?.message ?? error));
    }
  }
  return made;
}
