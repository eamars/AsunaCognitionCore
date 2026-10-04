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

/** Append a received platform message without opening an Agent or starting inference. */
export async function recordChannelInput(core, receipt) {
  const { ctx } = core, { session_id: id, binding, input } = receipt;
  if (!await ctx.sessionPersistence.stat(id)) await organizeNativeWorkspaces(core, {
    first: false, archive_ids: [], workspaces: { QQ: binding.cwd, Local: core.config.deployment.chat.workspace },
    entries: [{ session_id: id, workspace: 'QQ', binding }] });
  await ctx.workspaceRegistry.unarchiveSession(id);
  const { createUserMessage } = await import('@deepseek-ai/dsh-llm');
  const message = createUserMessage({ source: { kind: 'user', channel: 'qq', receipt: input.id,
    sender: input.sender, received_at: input.received_at },
    content: [{ type: 'text', text: (input.sender_name || 'QQ · ' + input.sender) + '\n' + input.text }] });
  const hot = ctx.sessions.get(id);
  const contains = events => events.some(event => event.type === 'user/message' && event.data.source.receipt === input.id);
  if (hot) {
    if (!contains(hot.snapshotEvents())) hot.append('user/message', message, { surfaceOp: 'append' });
    await ctx.sessions.flush(hot);
  } else {
    const handle = await ctx.sessionPersistence.open(id, 'write');
    try {
      const { events } = await handle.read();
      if (!contains(events)) {
        const event = { type: 'user/message', data: message, surfaceOp: 'append', seq: events.length, time: Date.now() };
        await handle.append([event]); events.push(event);
      }
      await handle.flush(); await checkpointCold(ctx, handle.header, handle.inheritedEventCount, events);
    } finally { await handle.close(); }
  }
  const catalog = await ctx.sessionController.list({}, new AbortController().signal);
  const summary = catalog.items.find(row => row.sessionId === id);
  if (summary) ctx.emit('api-session/added', summary);
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
  await ctx.workspaceRegistry.insertBefore(workspaces.get('QQ').id, workspaces.get('Local').id);
}
