/**
 * Executable illustration of ONE rule: replace a complete display snapshot
 * at the same seat, instead of appending a final duplicate or final text.
 * NOT a stream engine, production store, provider parser, or DSH replacement.
 * The real integration should use DSH's existing settle/assembler mechanism.
 */

/**
 * @template {{key: string}} T
 * @param {readonly T[]} rows
 * @param {T} fullSnapshot A source-assembled full snapshot, not a token delta.
 * @returns {readonly T[]}
 */
export function replaceAtSameSeat(rows, fullSnapshot) {
  const index = rows.findIndex(row => row.key === fullSnapshot.key);
  if (index === -1) return [...rows, fullSnapshot];
  if (rows[index] === fullSnapshot) return rows;
  const next = rows.slice();
  next[index] = fullSnapshot;
  return next;
}

/** No model/task operation is triggered by an observer's connection state. */
export function observerNotice(state) {
  if (state === 'disconnected') return '观察连接中断；后台状态暂未同步';
  if (state === 'connecting') return '正在重新连接观察流';
  return null;
}
