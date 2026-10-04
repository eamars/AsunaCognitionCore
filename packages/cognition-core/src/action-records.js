/** Durable references into native action logs; never a second message history. */
import { randomUUID } from 'node:crypto';

function references(role) {
  const rows = new Map();
  for (const event of role.session.snapshotEvents()) {
    if (event.type === 'asuna/action-linked') {
      const id = event.data.segment_id ?? event.data.session_id;
      rows.set(id, { ...event.data, segment_id: id });
    } else if (event.type === 'asuna/action-range') {
      const row = rows.get(event.data.segment_id);
      if (row) rows.set(row.segment_id, { ...row, ...event.data });
    }
  }
  return [...rows.values()];
}

export class ActionRecords {
  constructor(core) { this.core = core; this.writes = new Map(); }

  async write(roleId, update) {
    const previous = this.writes.get(roleId) ?? Promise.resolve();
    const writing = previous.catch(() => {}).then(async () => {
      const role = this.core.ctx.agents.get(roleId);
      if (!role) return;
      await update(role);
      await this.core.ctx.sessions.flush(role.session);
    });
    this.writes.set(roleId, writing);
    try { await writing; }
    finally { if (this.writes.get(roleId) === writing) this.writes.delete(roleId); }
  }

  async sequence(sourceId) {
    const { ctx } = this.core;
    const source = ctx.agents.get(sourceId);
    if (source) return source.session.snapshotEvents().at(-1)?.seq ?? -1;
    if (!await ctx.sessionPersistence.stat(sourceId)) return null;
    const handle = await ctx.sessionPersistence.open(sourceId, 'read');
    try { return (await handle.read()).events.at(-1)?.seq ?? -1; }
    finally { await handle.close(); }
  }

  append(role, data) {
    role.session.append('asuna/action-linked', { ...data, segment_id: randomUUID(),
      turn: role.session.snapshotEvents().findLast(e => e.type === 'turn/start')?.data.turn });
  }

  async link(stage, { completed = false } = {}) {
    if (stage.lane !== 'executor' || !stage.binding?.role_session_id) return;
    await this.write(stage.binding.role_session_id, async role => {
      const rows = references(role).filter(row => row.session_id === stage.session_id);
      const last = rows.at(-1);
      // A receipt replay is not a new segment. A continued task on the same
      // native source needs its own range after the preceding task settled.
      if (rows.some(row => row.operation === stage.token)) return;
      if (last && last.through_seq === undefined) throw new Error('ASUNA_ACTION_RANGE_STILL_OPEN');
      const through = await this.sequence(stage.session_id);
      if (through === null) throw new Error('ASUNA_ACTION_SOURCE_NOT_FOUND');
      this.append(role, { session_id: stage.session_id, task_id: stage.binding.task_id,
        parent_session_id: stage.binding.parent_session_id,
        operation: stage.token, after_seq: last?.through_seq ?? -1,
        ...(completed ? { through_seq: through, state: 'completed' } : {}) });
    });
  }

  async pause(roleId) {
    await this.write(roleId, async role => {
      for (const row of references(role).filter(row => row.through_seq === undefined)) {
        const through = await this.sequence(row.session_id);
        if (through === null) continue;
        role.session.append('asuna/action-range', { segment_id: row.segment_id,
          session_id: row.session_id, through_seq: through, state: 'paused' });
      }
    });
  }

  async resume(roleId) {
    await this.write(roleId, async role => {
      const latest = new Map(references(role).map(row => [row.session_id, row]));
      for (const row of latest.values()) {
        const current = this.core.states.get(row.session_id)?.current;
        if (row.state !== 'paused' || current?.lane !== 'executor') continue;
        this.append(role, { session_id: row.session_id, task_id: row.task_id,
          parent_session_id: row.parent_session_id,
          operation: current.token, after_seq: row.through_seq });
      }
    });
  }

  async finish(stage) {
    if (stage.lane !== 'executor' || !stage.binding?.role_session_id) return;
    await this.write(stage.binding.role_session_id, async role => {
      let row = references(role).findLast(row => row.session_id === stage.session_id && row.operation === stage.token);
      if (!row || row.state === 'completed') return;
      const through = await this.sequence(stage.session_id);
      if (through === null) return;
      if (row.through_seq !== undefined) {
        if (through <= row.through_seq) return;
        this.append(role, { session_id: row.session_id, task_id: row.task_id,
          parent_session_id: row.parent_session_id,
          operation: stage.token, after_seq: row.through_seq });
        row = references(role).at(-1);
      }
      role.session.append('asuna/action-range', { segment_id: row.segment_id,
        session_id: row.session_id, through_seq: through, state: 'completed' });
    });
  }
}
