/** Business receipt adapter over the single native Host scheduler.
 * These are Asuna acknowledgments, never fabricated DSH schedule/change events.
 *
 * Every change is made as her scheduler session (DSH's `actorSessionId`): DSH tells each other session a task involves
 * about a change by an injected `[SCHEDULE CHANGE]` notice, and a change of hers would otherwise reach a model. A
 * firing is told from such a notice by its first line, `[SCHEDULE REMINDER` (single or batch); both carry
 * `schedule_id_json`.
 */
const FIRING = '[SCHEDULE REMINDER';
/** Python sends DSH's selector alone ({after_seconds}, {every_seconds}, {daily}, {weekly}); DSH takes it with its kind. */
const KINDS = { after_seconds: 'after', every_seconds: 'every', daily: 'daily', weekly: 'weekly', at: 'at' };
export function timingOf(selector) {
  const keys = Object.keys(selector);
  if (keys.length !== 1 || !KINDS[keys[0]]) throw new Error('Asuna schedule timing needs exactly one selector: ' + keys.join(', '));
  return { kind: KINDS[keys[0]], [keys[0]]: selector[keys[0]] };
}
/** A task of hers: delivered to that session. */
const targets = (row, sessionId) => row.target?.kind === 'session' && row.target.sessionId === sessionId;
/** DSH 0.2.2 ends a finished one-shot; a record stored by an older DSH reads `inactive`. */
const ended = status => status === 'ended' || status === 'inactive';
export class NativeSchedules {
  constructor(core) { this.core = core; this.ctx = core.ctx; this.serial = Promise.resolve(); }

  async agent(sessionId) {
    this.sessionId = sessionId;
    const existing = this.ctx.agents.get(sessionId);
    if (existing) return existing;
    const setup = scope => this.ctx.agentPresets.mount(scope, 'asuna-scheduler').then(() => undefined);
    const saved = await this.ctx.sessionPersistence.stat(sessionId);
    const handle = saved
      ? await this.ctx.agents.resume({ resumeSessionId: sessionId, setup })
      : await this.ctx.agents.create({ sessionId, meta: { cwd: this.ctx.asunaFloor.dataRoot,
        agentPreset: 'asuna-scheduler' }, setup });
    this.core.handles.set(sessionId, handle);
    if (!saved) await this.ctx.sessionController.rename({ sessionId, title: this.core.uiTitles?.schedules ?? 'Asuna schedules' });
    return handle.agent;
  }

  /** The scheduler session's title in the language of the names the program gives (ui-language.js). */
  async retitle() {
    const title = this.core.uiTitles?.schedules;
    if (!this.sessionId || !title) return;
    const agent = await this.agent(this.sessionId);
    if (agent.session.snapshotEvents().findLast(event => event.type === 'session/title')?.data?.title !== title)
      await this.ctx.sessionController.rename({ sessionId: this.sessionId, title });
  }

  exclusive(work) {
    const result = this.serial.then(work);
    this.serial = result.catch(() => {});
    return result;
  }

  rows(agent) { return agent.session.snapshotEvents().filter(e => e.type === 'asuna/schedule'); }

  // The fields that say what a record is and when it runs next. When DSH changes one (it advances the next
  // target after each delivery, or the owner edits the task in DSH's task page), the change is logged as an
  // update, so the worker always reads the record as it is now.
  static fields(record) {
    const { kind, title, prompt, scheduledAt, everySeconds, afterSeconds, at, time, timeZone, weekdays, expression, status } = record;
    return JSON.stringify({ kind, title, prompt, scheduledAt, everySeconds, afterSeconds, at, time, timeZone, weekdays, expression, status });
  }

  async refresh(agent) {
    const catalog = (await this.ctx.schedule.catalog()).filter(row => targets(row, agent.session.id)
      && row.prompt.startsWith('ASUNA_PLAN:'));
    let rows = this.rows(agent);
    for (const record of catalog) {
      if (!rows.some(e => e.data.operation === 'create' && e.data.schedule.id === record.id))
        agent.session.append('asuna/schedule', { operation: 'create', schedule: record });
    }
    rows = this.rows(agent);
    const latest = new Map();
    for (const e of rows) if (['create', 'update'].includes(e.data.operation)) latest.set(e.data.schedule.id, e.data.schedule);
    for (const record of catalog) {
      const logged = latest.get(record.id);
      if (logged && NativeSchedules.fields(logged) !== NativeSchedules.fields(record))
        agent.session.append('asuna/schedule', { operation: 'update', schedule: record });
    }
    rows = this.rows(agent);
    const known = new Set(rows.filter(e => e.data.operation === 'dispatch').map(e => e.data.id + ':' + e.data.message_id));
    const created = new Set(rows.filter(e => e.data.operation === 'create').map(e => e.data.schedule.id));
    // Native inbox persistence is the delivery boundary. Read the actual source
    // messages so a crash between delivery and business acknowledgment is safe.
    for (const event of agent.session.snapshotEvents()) {
      const messages = event.type === 'agent/inbox/spliced' ? event.data.inserted
        : event.type === 'user/message' ? [event.data] : [];
      for (const message of messages.filter(m => m.source?.kind === 'schedule')) {
      const text = (message.content ?? []).filter(x => x.type === 'text').map(x => x.text).join('\n');
      if (!text.startsWith(FIRING)) continue;
      const fields = Object.fromEntries(text.split('\n').flatMap(line => {
        const at = line.indexOf(': '); return at < 0 ? [] : [[line.slice(0, at), line.slice(at + 2)]];
      }));
      const deliveries = fields.reminders_json ? JSON.parse(fields.reminders_json)
        : fields.schedule_id_json ? [{ schedule_id: JSON.parse(fields.schedule_id_json),
          occurrence_at: fields.occurrence_at }] : [];
      for (const delivery of deliveries) {
        const key = delivery.schedule_id + ':' + message.id;
        if (!created.has(delivery.schedule_id) || known.has(key)) continue;
        agent.session.append('asuna/schedule', { operation: 'dispatch', id: delivery.schedule_id,
          message_id: message.id, source_seq: event.seq, acceptedAt: delivery.occurrence_at });
        known.add(key);
      }
      }
    }
    rows = this.rows(agent);
    for (const record of catalog) {
      if (!ended(record.status) || rows.some(e => e.data.operation === 'delete' && e.data.id === record.id)) continue;
      const delivered = rows.some(e => e.data.operation === 'dispatch' && e.data.id === record.id);
      if (!delivered || !['after', 'at'].includes(record.kind))
        agent.session.append('asuna/schedule', { operation: 'delete', id: record.id });
    }
    for (const id of created) {
      if (!catalog.some(row => row.id === id) && !rows.some(e => e.data.operation === 'delete' && e.data.id === id))
        agent.session.append('asuna/schedule', { operation: 'delete', id });
    }
    await this.ctx.sessions.flush(agent.session);
    return this.rows(agent);
  }

  request({ session_id: sessionId, path, payload }) {
    return this.exclusive(async () => {
      const agent = await this.agent(sessionId);
      if (path === '/schedule/events') return this.refresh(agent);
      if (path === '/schedule/create') {
        // The worker names each task as she and the owner read it (her plan's words, or her rhythm).
        const { plan_id: planId, title, ...timing } = payload;
        const result = await this.ctx.schedule.create({ title: title || 'Asuna · ' + planId, prompt: 'ASUNA_PLAN:' + planId,
          timing: timingOf(timing), target: { kind: 'session', sessionId } }, sessionId);
        if (result.id) agent.session.append('asuna/schedule', { operation: 'create', schedule: result });
        await this.ctx.sessions.flush(agent.session);
        return result;
      }
      if (path === '/schedule/update') {
        // ADR-009 D-5: change timing in place, logged like create/delete so reconciliation never mistakes it for a
        // delete followed by a create. The edit is checked against the revision just read (`expectedUpdatedAt`).
        const current = await this.ctx.schedule.view({ id: payload.id });
        if (current.code) return { id: payload.id, updated: false, code: current.code };
        const patch = {};
        if (payload.change) patch.timing = payload.change;
        if (payload.title) patch.title = payload.title;
        const result = await this.ctx.schedule.edit({ id: payload.id, action: 'update', patch,
          expectedUpdatedAt: current.updatedAt ?? null }, sessionId);
        if (result.code) return { id: payload.id, updated: false, code: result.code };
        // An edit that leaves the task as it was (the same timing again) answers with the record and is not logged.
        if (NativeSchedules.fields(result) !== NativeSchedules.fields(current)) {
          agent.session.append('asuna/schedule', { operation: 'update', schedule: result });
          await this.ctx.sessions.flush(agent.session);
        }
        return result;
      }
      if (path === '/schedule/delete') {
        const result = await this.ctx.schedule.edit({ id: payload.id, action: 'delete' }, sessionId);
        if (result.deleted) agent.session.append('asuna/schedule', { operation: 'delete', id: payload.id });
        await this.ctx.sessions.flush(agent.session);
        return result;
      }
      throw new Error('Unknown Asuna scheduler operation');
    });
  }

  async delivered(agent) {
    // DSH claims one queued reminder per turn; reminders that arrive during a turn would stay queued for good.
    // The log is what delivers them (refresh reads every inserted reminder), so the ones queued before this
    // reading are removed once it has been read. One arriving later stays and wakes its own turn.
    const queued = agent.inbox.nextTurn.filter(message => message.source?.kind === 'schedule').map(message => message.id);
    // The worker has every dispatch up to `through`: only newer ones go, in one call, so a reminder costs the same
    // however long the log grows. The first reading after a start sends them all once; the worker drops the old.
    const rows = await this.exclusive(() => this.refresh(agent));
    await this.core.ready();
    const fresh = rows.filter(e => e.data.operation === 'dispatch' && e.seq > (this.through ?? -1));
    if (fresh.length) {
      await this.core.worker.call('schedule.deliver', { session: agent.session.id,
        dispatches: fresh.map(e => ({ seq: e.seq, id: e.data.id })) });
      this.through = fresh.at(-1).seq;
    }
    for (const id of queued) agent.inbox.remove(id);
    if (queued.length) await this.ctx.sessions.flush(agent.session);
  }
}
