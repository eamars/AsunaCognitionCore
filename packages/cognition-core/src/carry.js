/** A conversation that no longer fits the model's window continues in a new session (ADR-028).
 *
 * DSH's compaction tries one overflow compaction before a request rejected for its context window fails the turn.
 * When the turn still fails that way, the plugin reports it with the session's last compaction summary; the worker
 * binds a new session for the scene and asks the Host to prepare it here, then runs the turn again there. */
import { CONTEXT_WINDOW_EXCEEDED_CODE } from '@deepseek-ai/dsh-llm';
import { organizeNativeWorkspaces } from './navigation.js';

/** Whether a failure, or anything in its cause chain, is DSH's canonical context-window rejection. */
export function overflowed(error) {
  const seen = new Set(), stack = [error];
  while (stack.length) {
    const item = stack.pop();
    if (!item || typeof item !== 'object' || seen.has(item)) continue;
    seen.add(item);
    if (item.code === CONTEXT_WINDOW_EXCEEDED_CODE || item.failure?.code === CONTEXT_WINDOW_EXCEEDED_CODE) return true;
    stack.push(item.cause, ...(Array.isArray(item.errors) ? item.errors : []));
  }
  return false;
}

/** The text of the session's last compaction summary (DSH writes each one over the checkpoint of the one before). */
export function lastSummary(events) {
  const summary = events.findLast(event => event.type === 'compaction/summary')?.data?.summary;
  if (typeof summary === 'string') return summary;
  return Array.isArray(summary) ? summary.filter(part => part?.type === 'text').map(part => part.text).join('\n') : '';
}

/** The Host's part of a carry: the new session as navigation makes one (title, workspace, no seed), shown in the
 * sidebar; the old one archived once its agent is idle (archiving refuses an active session). */
export async function carrySession(core, { session_id: old, plan }) {
  const { ctx } = core;
  await organizeNativeWorkspaces(core, plan);
  const catalog = await ctx.sessionController.list({}, new AbortController().signal);
  for (const { session_id: id } of plan.entries) {
    const summary = catalog.items.find(row => row.sessionId === id);
    if (summary) ctx.emit('api-session/added', summary);
  }
  const archive = async () => {
    await ctx.agents.get(old)?.whenIdle();
    await ctx.workspaceRegistry.archiveSession(old);
  };
  archive().catch(error => ctx.logger.warn('Asuna: the session ' + old + ' that no longer fit stays unarchived: ' + String(error)));
  return { session_id: plan.entries[0]?.session_id };
}
