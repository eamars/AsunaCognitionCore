/** Read only this action's native spill directory; never widen its workspace. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { sessionDir } from '@deepseek-ai/dsh-spill-local';

export async function readSpill(store, sessionId, args) {
  if (!store?.root || typeof args.path !== 'string' || !path.isAbsolute(args.path)) return;
  const directory = sessionDir(store.root, sessionId), file = path.resolve(args.path);
  if (path.dirname(file) !== directory) return;
  let entry;
  try { entry = await fs.lstat(file); } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    throw new Error(`SPILL_FILE_NOT_FOUND: 这次行动的溢出目录里没有 '${path.basename(file)}'；path 照工具结果里给的溢出路径原样抄`);
  }
  if (entry.isSymbolicLink() || await fs.realpath(path.dirname(file)) !== await fs.realpath(directory))
    throw new Error(`SPILL_PATH_DENIED: '${path.basename(file)}' 是链接，或溢出目录被转到了别处，不读；重试也一样：只读工具结果里给的溢出路径`);
  const offset = args.offset ?? 0, limit = args.limit ?? 16000;
  if (!Number.isSafeInteger(offset) || offset < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 32000)
    throw new Error('INVALID_SPILL_PAGE: ' + [
      !Number.isSafeInteger(offset) || offset < 0 ? `offset 是 ${JSON.stringify(offset)}，只能是 0 或更大的整数（字节）` : '',
      !Number.isSafeInteger(limit) || limit < 1 || limit > 32000 ? `limit 是 ${JSON.stringify(limit)}，只能 1..32000（字节）` : '',
    ].filter(Boolean).join('，') + '；改了再读，下一页用上次结果里的 next_offset');
  const handle = await fs.open(file, 'r');
  try {
    const size = (await handle.stat()).size, data = Buffer.alloc(limit);
    const { bytesRead } = await handle.read(data, 0, limit, offset);
    return { path: args.path, text: data.subarray(0, bytesRead).toString('utf8'), offset,
      next_offset: offset + bytesRead < size ? offset + bytesRead : null, bytes: size, source: 'native-tool-spill' };
  } finally { await handle.close(); }
}
