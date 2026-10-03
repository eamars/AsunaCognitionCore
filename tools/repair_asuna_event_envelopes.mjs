// One-time maintenance for this migration's early, unmarked Asuna receipts.
// Run with the Host stopped. Keep byte-for-byte originals; change envelopes only.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { zstdDecompressSync, zstdCompressSync, constants } from 'node:zlib';
import assert from 'node:assert/strict';
import { validateStoredEvents } from '@deepseek-ai/dsh-session-persistence';
import { ASUNA_EVENTS } from '../packages/cognition-core/src/persistence.js';

const root = path.resolve('.runtime/adr008/home/sessions');
const backupRoot = path.resolve('.runtime/adr008/event-envelope-backups');
const apply = process.argv.includes('--apply');
let count = 0, changed = 0;
function decode(bytes) {
  const chunks = []; let offset = 0;
  while (offset < bytes.length) {
    const result = zstdDecompressSync(bytes.subarray(offset), { info: true });
    if (!result.engine.bytesWritten) throw new Error('Zstandard frame made no progress');
    offset += result.engine.bytesWritten; chunks.push(result.buffer);
  }
  return Buffer.concat(chunks).toString('utf8').trimEnd().split('\n').map(JSON.parse);
}
async function visit(directory) {
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) continue;
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) { await visit(file); continue; }
    if (entry.name !== 'session.v4.jsonl.zstd') continue;
    const bytes = await fs.readFile(file);
    const records = decode(bytes);
    const marked = records.map(record => ASUNA_EVENTS.has(record.type) && !record.ignorable ? { ...record, ignorable: true } : record);
    const headerNeedsFrame = zstdDecompressSync(bytes).toString('utf8').trimEnd().split('\n').length !== 1;
    if (!headerNeedsFrame && !marked.some((record, index) => record !== records[index])) continue;
    const n = marked.filter((record, index) => record !== records[index]).length;
    assert.deepEqual(marked.map((record, index) => record === records[index] ? record : (() => {
      const { ignorable, ...original } = record; return original;
    })()), records);
    validateStoredEvents(marked[0], marked.slice(1));
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (apply) {
      const backup = path.join(backupRoot, digest + '.jsonl.zstd');
      await fs.mkdir(backupRoot, { recursive: true });
      await fs.writeFile(backup, bytes, { flag: 'wx' }).catch(error => { if (error.code !== 'EEXIST') throw error; });
      const encode = rows => zstdCompressSync(Buffer.from(rows.map(record => JSON.stringify(record)).join('\n') + '\n'),
        { params: { [constants.ZSTD_c_checksumFlag]: 1 } });
      // Native JSONL requires the first frame to contain only its header.
      const encoded = Buffer.concat([encode(marked.slice(0, 1)), encode(marked.slice(1))]);
      assert.deepEqual(decode(encoded), marked);
      await fs.writeFile(file + '.asuna-repair.tmp', encoded); await fs.rename(file + '.asuna-repair.tmp', file);
    }
    console.log(JSON.stringify({ session: marked[0].id, records: n, original_sha256: digest, applied: apply }));
    count++; changed += n;
  }
}
await visit(root);
console.log(JSON.stringify({ files: count, informational_envelopes: changed, native_content_changed: false }));
