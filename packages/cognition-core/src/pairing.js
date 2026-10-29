/** A tool call and its result stay adjacent in her conversation, and a compaction sees the surface it summarizes.
 *
 * DSH never writes input between a call and its result: what arrives while tools run goes to the next step, after
 * the results, and Anthropic's API refuses a request with anything in between. A platform line is held the same way
 * for the whole of a step, because a request is built from the surface when the step starts: a line appended later
 * lands after the call that never saw it, and the order of her conversation would say she had. So a platform line
 * that arrives while a step is open (from `step/start` to `step/end`: the request, her reply, every tool call and
 * result) is held here and joins the conversation at the next boundary: the step's end, the next step's start, or
 * the turn's end. It never extends a turn. A line already written between a call and its result, from before this
 * rule, is replaced in place by an empty line, which no provider is sent.
 *
 * A compaction inside her turn refuses its summary when the surface changed while it was written; a line that
 * arrives while a compaction runs on its conversation is held too, and joins the conversation as the compaction ends
 * (`compaction/end`, whether it committed or failed). */
import { createUserMessage } from '@deepseek-ai/dsh-llm';

/** Whether a step runs on the conversation: the latest of its markers is a `step/start`. DSH appends `step/end` in a
 * `finally`, so a failed or aborted step closes too. As with a compaction, a start older than the log's last
 * `session/end-seed` (the conversation was opened again since, e.g. after the process stopped mid-step) runs no more. */
export function stepOpen(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    const type = events[i].type;
    if (type === 'step/start') return true;
    if (type === 'step/end' || type === 'turn/start' || type === 'turn/end' || type === 'session/end-seed') return false;
  }
  return false;
}

/** Whether a compaction runs on the conversation: its last `compaction/start` has no `compaction/end` yet. As in DSH's
 * compaction lock, a start older than the log's last `session/end-seed` (the conversation was opened again since,
 * e.g. after the process stopped mid-compaction) runs no more. */
export function compactionOpen(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === 'compaction/end' || events[i].type === 'session/end-seed') return false;
    if (events[i].type === 'compaction/start') return true;
  }
  return false;
}

/** Whether a platform line arriving now waits: the conversation has its head, and a step or a compaction runs. A
 * step counts only where the conversation has an agent (`hasAgent`): a conversation without one runs no step. */
export function mustHold(events, hasAgent) {
  return events.some(event => event.type === 'system/message')
    && (Boolean(hasAgent) && stepOpen(events) || compactionOpen(events));
}

/** Hold a line until the open step ends, or the running compaction. */
export function hold(core, id, message) {
  const held = core.held.get(id) ?? [];
  if (!held.some(line => line.source?.receipt === message.source?.receipt)) held.push(message);
  core.held.set(id, held);
}

export function isHeld(core, id, receipt) {
  return (core.held.get(id) ?? []).some(line => line.source?.receipt === receipt);
}

/** Write the held lines into the conversation, in arrival order; true when any was written. Their receipts are
 * acknowledged to the worker once the conversation is flushed (`core.written`): a held line lives only in memory, and
 * an unacknowledged receipt is projected again at the next start. */
export function release(core, session) {
  const held = core.held.get(session.id);
  if (!held?.length) return false;
  core.held.delete(session.id);
  const recorded = new Set(session.snapshotEvents().filter(event => event.type === 'user/message')
    .map(event => event.data.source?.receipt));
  for (const message of held)
    if (!recorded.has(message.source?.receipt)) session.append('user/message', message, { surfaceOp: 'append' });
  core.written?.(session, held.map(message => message.source?.receipt).filter(Boolean));
  return true;
}

/** Lines held while a step or a compaction ran join the conversation as it ends (after the event is published: DSH
 * refuses an append from inside a session observer). `step/end` is the one point every step passes, a failed or an
 * aborted one included: `agent/turn-stopping` is dispatched only after a step that returned. Returns the listener's
 * disposer. */
export function releaseAtBoundary(core) {
  return core.ctx.on('session/event', (session, event) => {
    if ((event.type !== 'compaction/end' && event.type !== 'step/end') || !core.held.get(session.id)?.length) return;
    queueMicrotask(() => {
      const events = session.snapshotEvents();
      if (!stepOpen(events) && !compactionOpen(events) && release(core, session))
        core.ctx.sessions.flush(session).catch(error => core.ctx.logger.warn('Asuna: lines held during a step or a compaction: ' + String(error)));
    });
  });
}

/** Seqs of the lines on the conversation's surface that sit between a tool call and its result. */
export function strayLines(events, nodes) {
  const surface = new Set(nodes), open = new Set(), stray = [];
  for (const event of events) {
    if (event.type === 'tool/call') open.add(event.data?.callId);
    else if (event.type === 'tool/result') open.delete(event.data?.message?.source?.callId);
    else if (event.type === 'step/start' || event.type === 'turn/start') open.clear();
    else if (event.type === 'user/message' && open.size && surface.has(event.seq)
      && event.data?.content?.length) stray.push(event.seq);
  }
  return stray;
}

/** Replace each stray line with an empty one in place (DSH's surface replace); returns how many. */
export function repair(session) {
  const stray = strayLines(session.snapshotEvents(), session.surface.nodes);
  for (const seq of stray) {
    const original = session.snapshotEvents(seq, seq + 1)[0];
    session.append('user/message', createUserMessage({ source: original.data.source, content: [] }),
      { surfaceOp: { op: 'replace', startSeq: seq, endSeq: seq }, sourceEventSeqs: [seq] });
  }
  return stray.length;
}
