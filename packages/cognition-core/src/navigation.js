import { projectionCacheDomainSpec } from '@deepseek-ai/dsh-session-projection-cache';

const needsTitle = (events, title, previous) => {
  const latest = events.findLast(event => event.type === 'session/title')?.data;
  return !latest?.title || latest.title === 'Untitled'
    || previous && latest.title === previous && latest.title !== title;
};
const titleData = title => ({ title, source: { kind: 'user' }, messageSeqs: [] });

async function checkpointCold(ctx, header, inheritedEventCount, events) {
  // coldSnapshot owns the fold and write-back. Await its public durability
  // event so the first sidebar listing can already read the checkpoint.
  let dispose, timer;
  try {
    await new Promise((resolve, reject) => {
      dispose = ctx.on('domain/changed', change => {
        if (change.domain === projectionCacheDomainSpec.name && change.key === header.id
            && ctx.sessionProjectionCache.cachedSnapshot(header)?.asOfSeq === events.length - 1) resolve();
      });
      timer = setTimeout(() => reject(new Error('NATIVE_TITLE_CHECKPOINT_TIMEOUT: ' + header.id)), 10000);
      ctx.sessionProjectionCache.coldSnapshot(header, inheritedEventCount, events);
    });
  } finally { clearTimeout(timer); await dispose?.(); }
}

/** Lines kept waiting before her first turn in a conversation: the most a catch-up brings (context.py). */
export const PENDING_LINES = 40;

/** The next-step list DSH's inbox fold reconstructs from a log's durable splices. */
const pendingOf = events => events.reduce((list, { type, data }) => type !== 'agent/inbox/spliced'
  || data.target !== 'next-step' ? list : list.toSpliced(data.start, data.removedCount ?? 0, ...data.inserted), []);

/** The splices that queue one line, dropping the oldest beyond PENDING_LINES (they stay in Mongo). */
const queueing = (pending, message) => {
  const excess = Math.max(pending.length + 1 - PENDING_LINES, 0);
  return [...excess ? [{ target: 'next-step', start: 0, removedCount: excess, inserted: [], outcome: 'canceled' }] : [],
    { target: 'next-step', start: pending.length - excess, inserted: [message] }];
};

/** Settles when a running first turn has written its head, or has stopped without one. */
function headOrIdle(ctx, agent) {
  let dispose;
  const head = new Promise(resolve => { dispose = ctx.on('session/event', (session, event) => {
    if (session === agent.session && event.type === 'system/message') resolve();
  }); });
  return Promise.race([head, agent.whenIdle()]).finally(() => dispose());
}

/** Record a received platform message in her conversation without starting inference.
 *
 * DSH requires a conversation's first visible event to be the system head its agent writes on its first
 * step; a line placed before that makes the log unloadable after the turn. So a line that arrives before
 * her first turn here waits in the conversation's durable inbox (next-step), and that turn's first step
 * claims it right after the head, in arrival order, before the stage notice. Once headed, a line joins the
 * surface as it arrives. The inbox is used only while no turn runs: a line claimed after a turn had begun
 * would add a model step outside the stage it belongs to. */
export async function recordChannelInput(core, receipt) {
  const { ctx } = core, { session_id: id, binding, input } = receipt;
  const channel = core.channelOf(binding.scene_id);
  if (!await ctx.sessionPersistence.stat(id)) await organizeNativeWorkspaces(core, {
    first: false, archive_ids: [], workspaces: { [channel.title]: binding.cwd, Local: core.config.deployment.chat.workspace },
    entries: [{ session_id: id, workspace: channel.title, binding }] });
  await ctx.workspaceRegistry.unarchiveSession(id);
  const message = await channelMessage(core, receipt);
  const headed = events => events.some(event => event.type === 'system/message');
  const contains = events => events.some(event => event.type === 'user/message' && event.data.source.receipt === input.id)
    || pendingOf(events).some(line => line.source.receipt === input.id);
  const agent = ctx.agents.get(id);
  if (agent?.status === 'running' && !headed(agent.session.snapshotEvents())) await headOrIdle(ctx, agent);
  const hot = ctx.sessions.get(id);
  if (hot) {
    const events = hot.snapshotEvents();
    if (contains(events)) { /* already recorded */ }
    else if (headed(events)) hot.append('user/message', message, { surfaceOp: 'append' });
    else if (agent) for (const splice of queueing(agent.inbox.nextStep, message))
      agent.inbox.splice('next-step', splice.start, splice.removedCount ?? 0, splice.inserted);
    else for (const splice of queueing(pendingOf(events), message)) hot.append('agent/inbox/spliced', splice);
    await ctx.sessions.flush(hot);
  } else {
    const handle = await ctx.sessionPersistence.open(id, 'write');
    try {
      const { events } = await handle.read();
      if (!contains(events)) {
        const added = (headed(events) ? [{ type: 'user/message', data: message, surfaceOp: 'append' }]
          : queueing(pendingOf(events), message).map(data => ({ type: 'agent/inbox/spliced', data })))
          .map((event, index) => ({ ...event, seq: events.length + index, time: Date.now() }));
        await handle.append(added); events.push(...added);
      }
      await handle.flush(); await checkpointCold(ctx, handle.header, handle.inheritedEventCount, events);
    } finally { await handle.close(); }
  }
  const catalog = await ctx.sessionController.list({}, new AbortController().signal);
  const summary = catalog.items.find(row => row.sessionId === id);
  if (summary) ctx.emit('api-session/added', summary);
}

/** A received platform line as her conversation records it. */
async function channelMessage(core, { binding, input }) {
  const { createUserMessage } = await import('@deepseek-ai/dsh-llm');
  return createUserMessage({ source: { kind: 'user', channel: core.channelOf(binding.scene_id).kind, receipt: input.id,
    sender: input.sender, received_at: input.received_at },
    content: [{ type: 'text', text: input.text }] });
}

/** The line a stage answers is in the conversation, or waiting in this agent's inbox, before that stage's turn
 * begins. On a conversation's first turn the record can miss: a line written to a loaded session that had no
 * agent yet was not in the log the agent then opened, so the turn began without it and the line only arrived
 * with the next stage, after her monologue. Queue it again on the agent itself; its first step claims it right
 * after the head, before the stage notice. Returns whether the line had to be placed. */
export async function lineBeforeTurn(core, agent, receipt) {
  const events = agent.session.snapshotEvents(), id = receipt.input.id;
  if (events.some(event => event.type === 'user/message' && event.data.source?.receipt === id)
    || agent.inbox.nextStep.some(line => line.source?.receipt === id)) return false;
  const message = await channelMessage(core, receipt);
  if (events.some(event => event.type === 'system/message')) agent.session.append('user/message', message, { surfaceOp: 'append' });
  else for (const splice of queueing(agent.inbox.nextStep, message))
    agent.inbox.splice('next-step', splice.start, splice.removedCount ?? 0, splice.inserted);
  await core.ctx.sessions.flush(agent.session);
  return true;
}

/** Native workspace/session migration. No client layout or alternate chat store. */
export async function organizeNativeWorkspaces(core, plan) {
  const { ctx } = core;
  const workspaces = new Map();
  for (const [title, directory] of Object.entries(plan.workspaces)) {
    const workspace = await ctx.workspaceRegistry.create(directory, title);
    await workspace.setTitle(title);
    workspaces.set(title, workspace);
  }
  for (const entry of plan.entries) {
    const { session_id: id, binding } = entry;
    const persisted = await ctx.sessionPersistence.stat(id);
    let session = ctx.sessions.get(id);
    if (session) {
      if (needsTitle(session.snapshotEvents(), binding.native_title, binding.previous_native_title))
        session.append('session/title', titleData(binding.native_title));
      await ctx.sessionProjectionCache.write(session);
    } else if (!persisted) {
      let seed;
      const source = binding.source_session_id;
      if (source && await ctx.sessionPersistence.stat(source)) {
        const handle = await ctx.sessionPersistence.open(source, 'read');
        try {
          const result = await handle.read();
          // Migrate a completed prefix only. Pending tools/messages are never
          // admitted a second time by opening the continued conversation.
          const end = result.events.findLastIndex(event => event.type === 'turn/end');
          if (end >= 0) seed = result.events.slice(0, end + 1);
        } finally { await handle.close(); }
      }
      session = ctx.sessions.prepare(id, { meta: { cwd: binding.cwd,
        agentPreset: core.personas.get(core.config.persona).preset,
        ...(seed ? { parentSession: source, isSeeded: true } : {}) },
        ...(seed ? { seed, inheritedEventCount: seed.length } : {}) });
      session.append('session/title', titleData(binding.native_title));
      const handle = await ctx.sessionPersistence.create(session.header,
        { inheritedEventCount: session.inheritedEventCount });
      try {
        await handle.append(session.snapshotEvents()); await handle.flush();
        await checkpointCold(ctx, handle.header, handle.inheritedEventCount, session.snapshotEvents());
      }
      finally { await handle.close(); }
    } else {
      // Renaming a cold session must not resume its Agent or replay its inbox.
      const handle = await ctx.sessionPersistence.open(id, 'write');
      try {
        const { events } = await handle.read();
        if (needsTitle(events, binding.native_title, binding.previous_native_title)) {
          const title = { type: 'session/title', seq: events.length, time: Date.now(),
            data: titleData(binding.native_title) };
          await handle.append([title]);
          events.push(title);
        }
        await handle.flush();
        await checkpointCold(ctx, handle.header, handle.inheritedEventCount, events);
      } finally { await handle.close(); }
    }
    await workspaces.get(entry.workspace).attachSession(id);
    if (!persisted || plan.first) await ctx.workspaceRegistry.unarchiveSession(id);
  }
  for (const id of plan.archive_ids) {
    if (await ctx.sessionPersistence.stat(id)) await ctx.workspaceRegistry.archiveSession(id);
  }
  if (plan.first) {
    const keep = new Set([...workspaces.values()].map(workspace => workspace.id));
    for (const workspace of ctx.workspaceRegistry.list())
      if (!keep.has(workspace.id)) await ctx.workspaceRegistry.delete(workspace.id);
  }
  // Platform workspaces (QQ, …) list above the local chat.
  for (const [title, workspace] of workspaces)
    if (title !== 'Local') await ctx.workspaceRegistry.insertBefore(workspace.id, workspaces.get('Local').id);
}
