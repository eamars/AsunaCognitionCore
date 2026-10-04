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
