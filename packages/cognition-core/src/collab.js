/** The two brains' collaboration thread in her conversation (ADR-011 §7.1).
 *
 * One `asuna/collab` event per entry, in her role session: her brief and later messages, the action
 * brain's questions, progress notes and reports, her answers, status changes, and the action brain's
 * own work between them as a range of its native session (`work`: after_seq..through_seq, never a
 * copy of its records). Entries carry an id; a replayed entry is not appended twice.
 *
 * Entries are appended only while her agent is idle, so a thread opened by a turn's delegate call is
 * anchored after that turn; entries that arrive during a later turn wait for it to end.
 *
 * Every entry shows where it happens (owner, 2026-10-05): a thread is drawn as blocks, and an entry that
 * arrives after the conversation moved on (a turn or a message since the thread's last entry) starts a
 * new block there, with the thread's title; the previous block is marked as continued below. A block
 * started while the action brain is running opens on that run, so its live work shows in the new block.
 */
export class Collab {
  constructor(core) {
    this.core = core;
    this.writes = new Map();     // role session → serialized write
    this.waiting = new Map();    // role session → entries waiting for her idle moment
    this.runs = new Map();       // thread → { parent, child, after, started }
    this.children = new Map();   // thread → action session (for her messages to a running task)
  }

  /** Her live role agent for a session, resumed when a task outlives her loaded conversation. */
  async role(parentId) {
    const { ctx } = this.core;
    const live = ctx.agents.get(parentId);
    if (live) return live;
    const binding = await this.core.worker.call('session', { session_id: parentId });
    return this.core.ensureAgent({ session_id: parentId, lane: 'character', binding });
  }

  async write(parentId, update) {
    const previous = this.writes.get(parentId) ?? Promise.resolve();
    const writing = previous.catch(() => {}).then(async () => {
      const role = await this.role(parentId);
      await update(role);
      await this.core.ctx.sessions.flush(role.session);
    });
    this.writes.set(parentId, writing);
    try { await writing; }
    finally { if (this.writes.get(parentId) === writing) this.writes.delete(parentId); }
  }

  /** Append (or hold until she is idle) one entry of a thread. */
  async add(parentId, entry) {
    if (!parentId || !entry?.id) return;
    const list = this.waiting.get(parentId) ?? [];
    list.push(entry); this.waiting.set(parentId, list);
    await this.flush(parentId);
  }

  async flush(parentId) {
    if (!this.waiting.get(parentId)?.length) return;
    await this.write(parentId, async role => {
      if (role.status !== 'idle') return;          // agent/status idle flushes them (index.js)
      const entries = this.waiting.get(parentId) ?? [];
      this.waiting.delete(parentId);
      const seen = new Set(role.session.snapshotEvents().filter(event => event.type === 'asuna/collab')
        .map(event => event.data.id));
      for (const entry of entries) {
        if (seen.has(entry.id)) continue;
        for (const added of this.place(role.session.snapshotEvents(), entry)) {
          seen.add(added.id); role.session.append('asuna/collab', added);
        }
      }
    });
  }

  /** The block an entry belongs to, and what starting a new one adds before it (see the module note). */
  place(events, entry) {
    const thread = events.filter(event => event.type === 'asuna/collab' && event.data.thread === entry.thread);
    const last = thread.at(-1);
    if (!last) return [{ ...entry, block: 'block:' + entry.id }];
    const previous = last.data.block ?? last.data.thread;          // entries from before blocks: one per thread
    const moved = events.some(event => event.seq > last.seq && (event.type === 'turn/start' || event.type === 'user/message'));
    if (!moved) return [{ ...entry, block: previous }];
    const block = 'block:' + entry.id, at = new Date().toISOString();
    const title = entry.title ?? thread.findLast(event => event.data.title)?.data.title;
    const run = this.runs.get(entry.thread);
    return [
      { id: 'continued:' + previous + ':' + block, thread: entry.thread, task_id: entry.task_id, kind: 'continued',
        block: previous, next: block, at },
      ...(run && entry.kind !== 'open' ? [{ id: 'open:' + block, thread: entry.thread, task_id: run.task, kind: 'open',
        block, ...(title ? { title } : {}), child_session_id: run.child, parent_session_id: run.parent,
        after_seq: run.after, at: new Date(run.started).toISOString() }] : []),
      { ...entry, block, ...(title ? { title } : {}) },
    ];
  }

  /** The action session's newest event sequence (live or persisted). */
  async sequence(sessionId) {
    const { ctx } = this.core;
    const source = ctx.agents.get(sessionId);
    if (source) return source.session.snapshotEvents().at(-1)?.seq ?? -1;
    if (!await ctx.sessionPersistence.stat(sessionId)) return null;
    const handle = await ctx.sessionPersistence.open(sessionId, 'read');
    try { return (await handle.read()).events.at(-1)?.seq ?? -1; }
    finally { await handle.close(); }
  }

  /** What one stretch of the action session did: tool calls and time, read from its native events. */
  async measure(sessionId, after, through) {
    const { ctx } = this.core;
    let events = ctx.agents.get(sessionId)?.session.snapshotEvents();
    if (!events && await ctx.sessionPersistence.stat(sessionId)) {
      const handle = await ctx.sessionPersistence.open(sessionId, 'read');
      try { events = (await handle.read()).events; } finally { await handle.close(); }
    }
    const range = (events ?? []).filter(event => event.seq > after && event.seq <= through);
    const calls = range.filter(event => event.type === 'tool/call').length;
    const last = range.findLast(event => event.type === 'assistant/message' && !event.data.interrupted);
    const text = (last?.data.message.content ?? []).filter(part => part.type === 'text').map(part => part.text).join('\n');
    return { tool_calls: calls, report: text };
  }

  /** An action run starts: open the thread (once) and a work range. */
  async start(stage) {
    const task = stage.task, parent = task?.parent_session_id;
    if (stage.lane !== 'executor' || !task || !parent) return;
    this.children.set(task.thread, stage.session_id);
    const after = await this.sequence(stage.session_id);
    if (after === null) return;
    this.runs.set(task.thread, { parent, child: stage.session_id, after, started: Date.now(), task: task._id });
    // One per run: a continuation's run opens again, in the block where it starts.
    await this.add(parent, { id: 'open:' + task.thread + ':' + after, thread: task.thread, task_id: task._id, kind: 'open',
      title: task.title, child_session_id: stage.session_id, parent_session_id: parent, after_seq: after,
      at: new Date().toISOString() });
  }

  /** Close the open work range of a thread (before an entry that interrupts it, or at the run's end). */
  async cut(thread, { report = false, operation } = {}) {
    const run = this.runs.get(thread);
    if (!run) return;
    const through = await this.sequence(run.child);
    if (through === null || through <= run.after) {
      if (report) this.runs.delete(thread);
      return;
    }
    const measured = await this.measure(run.child, run.after, through);
    await this.add(run.parent, { id: 'work:' + thread + ':' + through, thread, task_id: run.task, kind: 'work',
      child_session_id: run.child, after_seq: run.after, through_seq: through,
      tool_calls: measured.tool_calls, duration_ms: Date.now() - run.started, at: new Date().toISOString() });
    if (report) {
      this.runs.delete(thread);
      if (measured.report.trim()) await this.add(run.parent, { id: 'report:' + (operation ?? thread + ':' + through),
        thread, task_id: run.task, kind: 'report', from: 'action', text: measured.report, at: new Date().toISOString() });
    } else this.runs.set(thread, { ...run, after: through, started: Date.now() });
  }

  /** The action run ended: its last work range and its report. */
  async finish(stage) {
    if (stage.lane !== 'executor' || !stage.task) return;
    await this.cut(stage.task.thread, { report: true, operation: stage.token });
  }

  /** An entry from the worker (her brief and messages, questions, answers, progress, status). */
  async entry(event) {
    // Words in the middle of a run split its work there, so the thread reads in order.
    if (['message', 'question', 'progress'].includes(event.entry.kind)) await this.cut(event.thread);
    await this.add(event.session_id, { ...event.entry, thread: event.thread, task_id: event.task_id,
      ...(event.title ? { title: event.title } : {}) });
  }

  /** Her message for a running action session: injected at its next step, never waking an idle one. */
  async message(event) {
    const childId = this.children.get(event.thread);
    const child = childId && this.core.ctx.agents.get(childId);
    const current = childId && this.core.states.get(childId)?.current;
    if (!child || child.status !== 'running' || !current) return false;   // the worker delivers it with the next round
    child.inject(this.core.relay(event.message));
    return true;
  }
}
