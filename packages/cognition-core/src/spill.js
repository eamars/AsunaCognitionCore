/** Read only this action's native spill directory; never widen its workspace. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { sessionDir } from '@deepseek-ai/dsh-spill-local';

export async function readSpill(store, sessionId, args) {
  if (!store?.root || typeof args.path !== 'string' || !path.isAbsolute(args.path)) return;
  const directory = sessionDir(store.root, sessionId), file = path.resolve(args.path);
  if (path.dirname(file) !== directory) return;
  if ((await fs.lstat(file)).isSymbolicLink() || await fs.realpath(path.dirname(file)) !== await fs.realpath(directory))
    throw new Error('SPILL_PATH_DENIED');
  const offset = args.offset ?? 0, limit = args.limit ?? 16000;
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 32000)
    throw new Error('INVALID_SPILL_PAGE');
  const handle = await fs.open(file, 'r');
  try {
    const size = (await handle.stat()).size, data = Buffer.alloc(limit);
    const { bytesRead } = await handle.read(data, 0, limit, offset);
    return { path: args.path, text: data.subarray(0, bytesRead).toString('utf8'), offset,
      next_offset: offset + bytesRead < size ? offset + bytesRead : null, bytes: size, source: 'native-tool-spill' };
  } finally { await handle.close(); }
}
