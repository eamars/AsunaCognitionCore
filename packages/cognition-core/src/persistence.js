/** DSH 0.2.1-rc.1 compatibility seam for informational plugin event envelopes.
 * Session.append cannot set ignorable, and DSH's plugin-record API is limited to its own experimental packages.
 * The public persistence handle can. DSH's JSONL backend is mounted as its own plugin in an isolated scope, and the
 * service this plugin provides delegates to it, marking Asuna's events on the way in.
 * All storage, leases, sequence validation, compression and reads remain native.
 */
import SessionPersistence from '@deepseek-ai/dsh-session-persistence';
import * as Jsonl from '@deepseek-ai/dsh-session-persistence-jsonl';

// asuna/action-linked, asuna/action-range, asuna/model-fault and asuna/model-view are retired but remain in older logs.
export const ASUNA_EVENTS = new Set(['asuna/stage', 'asuna/stage-result', 'asuna/schedule', 'asuna/collab',
  'asuna/web-search', 'asuna/model-view', 'asuna/model-fault', 'asuna/action-linked', 'asuna/action-range']);
const compatible = event => ASUNA_EVENTS.has(event.type) ? { ...event, ignorable: true } : event;
export function compatibleHandle(handle) {
  return { id: handle.id, header: handle.header, access: handle.access,
    inheritedEventCount: handle.inheritedEventCount,
    read: (...args) => handle.read(...args), flush: (...args) => handle.flush(...args),
    close: () => handle.close(), [Symbol.asyncDispose]: () => handle.close(),
    append: (events, options) => handle.append(events.map(compatible), options),
  };
}

class AsunaPersistence extends SessionPersistence {
  constructor(ctx, backend) {
    super(ctx);
    this.backend = backend;
  }
  async create(header, options) { return compatibleHandle(await this.backend.create(header, options)); }
  async open(id, access, options) { return compatibleHandle(await this.backend.open(id, access, options)); }
  flush() { return this.backend.flush(); }
  stat(id, options) { return this.backend.stat(id, options); }
  list(options) { return this.backend.list(options); }
  locate(meta) { return this.backend.locate(meta); }
}

export const name = 'asuna-session-persistence';
export const Config = Jsonl.Config;

export async function apply(ctx, config) {
  // The JSONL backend also observes published live events directly: adapt that public subscription as well as
  // pre-publication handle.append. Its own service stays inside this scope; only the delegating one is public.
  const scope = ctx.isolate('sessionPersistence').extend({
    on: (event, listener, ...options) => ctx.on(event, event === 'session/event'
      ? (session, value) => listener(session, compatible(value)) : listener, ...options),
  });
  await scope.plugin(Jsonl, config);
  const backend = await new Promise(resolve => scope.inject(['sessionPersistence'], inner => resolve(inner.sessionPersistence)));
  await ctx.plugin({ name: 'asuna-session-persistence-service', apply: serviceCtx => { new AsunaPersistence(serviceCtx, backend); } });
}

export default { name, Config, apply };
