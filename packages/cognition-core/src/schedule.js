/** Business receipt adapter over the single native Host scheduler.
 * These are Asuna acknowledgments, never fabricated DSH schedule/change events.
 */
export class NativeSchedules {
  constructor(core) { this.core = core; this.ctx = core.ctx; this.serial = Promise.resolve(); }

  async agent(sessionId) {
    const existing = this.ctx.agents.get(sessionId);
    if (existing) return existing;
    const setup = scope => this.ctx.agentPresets.mount(scope, 'asuna-scheduler').then(() => undefined);
    const saved = await this.ctx.sessionPersistence.stat(sessionId);
    const handle = saved
      ? await this.ctx.agents.resume({ resumeSessionId: sessionId, setup })
      : await this.ctx.agents.create({ sessionId, meta: { cwd: this.ctx.asunaFloor.dataRoot,
        agentPreset: 'asuna-scheduler' }, setup });
    this.core.handles.set(sessionId, handle);
    if (!saved) await this.ctx.sessionController.rename({ sessionId, title: 'Asuna schedules' });
    return handle.agent;
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
    const catalog = (await this.ctx.schedule.catalog()).filter(row => row.sessionId === agent.session.id
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
      if (record.status !== 'inactive' || rows.some(e => e.data.operation === 'delete' && e.data.id === record.id)) continue;
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
        const result = await this.ctx.schedule.create(sessionId, {
          title: title || 'Asuna · ' + planId, prompt: 'ASUNA_PLAN:' + planId, ...timing });
        if (result.id) agent.session.append('asuna/schedule', { operation: 'create', schedule: result });
        await this.ctx.sessions.flush(agent.session);
        return result;
      }
      if (path === '/schedule/update') {
        // ADR-009 D-5: change timing in place (native schedule_update), logged like create/delete
        // so reconciliation never mistakes it for a delete followed by a create.
        // `expected` is the record exactly as stored (Schedule's `list`, as its own schedule_update tool reads
        // it). A catalog entry also carries sessionId, status and lastDelivery, and is refused as invalid.
        const expected = (await this.ctx.schedule.list({ sessionId })).find(row => row.id === payload.id);
        if (!expected) return { id: payload.id, updated: false, code: 'schedule_not_found' };
        const request = { sessionId, id: payload.id, expected };
        if (payload.change) request.change = payload.change;
        if (payload.title) request.title = payload.title;
        const result = await this.ctx.schedule.update(request);
        if (result.updated && result.record) {
          agent.session.append('asuna/schedule', { operation: 'update', schedule: result.record });
          await this.ctx.sessions.flush(agent.session);
        }
        // A change that leaves the record as it is (a no-op) answers with the record too.
        return result.record ?? result;
      }
      if (path === '/schedule/delete') {
        const result = await this.ctx.schedule.delete({ sessionId, id: payload.id });
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
    const rows = await this.exclusive(() => this.refresh(agent));
    await this.core.ready();
    for (const event of rows.filter(e => e.data.operation === 'dispatch'))
      await this.core.worker.call('schedule.deliver', {
        session: agent.session.id, seq: event.seq, id: event.data.id });
    for (const id of queued) agent.inbox.remove(id);
    if (queued.length) await this.ctx.sessions.flush(agent.session);
  }
}
