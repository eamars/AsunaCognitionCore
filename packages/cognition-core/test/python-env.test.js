import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ensurePythonEnvironment } from '../src/python-env.js';

test('ADR-010 D2: a built environment is reused while the lock is the same; a package without a lock says so', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-python-env-'));
  try {
    const workerPath = path.join(root, 'package', 'python'), dataRoot = path.join(root, 'data');
    await fs.mkdir(workerPath, { recursive: true });
    await assert.rejects(ensurePythonEnvironment({ dataRoot, workerPath }), /PYTHON_LOCK_MISSING/);
    const lock = 'httpx==0.28.1\n';
    await fs.writeFile(path.join(workerPath, 'requirements.lock'), lock);
    const python = process.platform === 'win32' ? path.join(dataRoot, 'python', 'Scripts', 'python.exe')
      : path.join(dataRoot, 'python', 'bin', 'python');
    await fs.mkdir(path.dirname(python), { recursive: true });
    await fs.writeFile(python, '');
    await fs.writeFile(path.join(dataRoot, 'python', 'asuna-environment.json'),
      JSON.stringify({ lock: createHash('sha256').update(lock).digest('hex') }));
    const steps = [];
    assert.equal(await ensurePythonEnvironment({ dataRoot, workerPath, report: step => steps.push(step) }), python);
    assert.deepEqual(steps, [], 'nothing is built again');
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
