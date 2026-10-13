/** Her own working copy of the local checkout (owner 2026-10-13, ADR-065): a full clone in her home working folder,
 * where her confined commands may write, commit and push. Its `origin` is the checkout's own origin. The Host makes it
 * when it is missing and never changes one that is there; it is never the checkout, and nothing the Host runs is in it. */
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
