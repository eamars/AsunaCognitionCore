/** A tool call and its result stay adjacent in her conversation, and a compaction sees the surface it summarizes.
 *
 * DSH never writes input between a call and its result: what arrives while tools run goes to the next step, after
 * the results, and Anthropic's API refuses a request with anything in between. A platform line that arrives while one
 * of her tool calls waits for its result is held here and joins the conversation at the next step boundary (the next
 * step's start, or the turn's end), never extending a turn. A line already written between a call and its result,
 * from before this rule, is replaced in place by an empty line, which no provider is sent.
 *
 * A compaction inside her turn refuses its summary when the surface changed while it was written; a line that
 * arrives while a compaction runs on its conversation is held too, and joins the conversation as the compaction ends
 * (`compaction/end`, whether it committed or failed). */
import { createUserMessage } from '@deepseek-ai/dsh-llm';

/** Whether a tool call of the running step still waits for its result. */
export function toolCallOpen(events) {
  const answered = new Set();
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (event.type === 'tool/result') answered.add(event.data?.message?.source?.callId);
    else if (event.type === 'tool/call') { if (!answered.has(event.data?.callId)) return true; }
    else if (['step/start', 'step/end', 'turn/start', 'turn/end'].includes(event.type)) return false;
  }
  return false;
}

/** Whether a compaction runs on the conversation: its last `compaction/start` has no `compaction/end` yet. */
export function compactionOpen(events) {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === 'compaction/end') return false;
    if (events[i].type === 'compaction/start') return true;
  }
  return false;
}

/** Hold a line until the open tool call has its result, or the running compaction its end. */
export function hold(core, id, message) {
  const held = core.held.get(id) ?? [];
  if (!held.some(line => line.source?.receipt === message.source?.receipt)) held.push(message);
  core.held.set(id, held);
}

export function isHeld(core, id, receipt) {
  return (core.held.get(id) ?? []).some(line => line.source?.receipt === receipt);
}

/** Write the held lines into the conversation, in arrival order; true when any was written. */
export function release(core, session) {
  const held = core.held.get(session.id);
  if (!held?.length) return false;
  core.held.delete(session.id);
  const recorded = new Set(session.snapshotEvents().filter(event => event.type === 'user/message')
    .map(event => event.data.source?.receipt));
  for (const message of held)
    if (!recorded.has(message.source?.receipt)) session.append('user/message', message, { surfaceOp: 'append' });
  return true;
}

/** Lines held while a compaction ran join its conversation as it ends (after the event is published: DSH refuses an
 * append from inside a session observer). Returns the listener's disposer. */
export function releaseAfterCompaction(core) {
  return core.ctx.on('session/event', (session, event) => {
    if (event.type !== 'compaction/end' || !core.held.get(session.id)?.length) return;
    queueMicrotask(() => {
      if (!toolCallOpen(session.snapshotEvents()) && !compactionOpen(session.snapshotEvents()) && release(core, session))
        core.ctx.sessions.flush(session).catch(error => core.ctx.logger.warn('Asuna: lines held during a compaction: ' + String(error)));
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
