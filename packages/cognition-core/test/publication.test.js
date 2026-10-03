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
  const floor = new PublicationFloor({ workspace, defaultProject: 'persona', projects: [{ id: 'persona', root: source, format: 'package' }] });
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
