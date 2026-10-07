/** DSH 0.2.0-rc.2 compatibility seam for informational plugin event envelopes.
 * Session.append cannot set ignorable yet. The public persistence handle can.
 * All storage, leases, sequence validation, compression and reads remain native.
 */
import SessionPersistence from '@deepseek-ai/dsh-session-persistence';
import JsonlPersistence from '@deepseek-ai/dsh-session-persistence-jsonl';

// asuna/action-linked and asuna/action-range are retired (ADR-011) but remain in older logs.
export const ASUNA_EVENTS = new Set(['asuna/stage', 'asuna/stage-result', 'asuna/schedule', 'asuna/collab',
  'asuna/model-fault', 'asuna/action-linked', 'asuna/action-range']);
const compatible = event => ASUNA_EVENTS.has(event.type) ? { ...event, ignorable: true } : event;
export function compatibleHandle(handle) {
  return { id: handle.id, header: handle.header, access: handle.access,
    inheritedEventCount: handle.inheritedEventCount,
    read: (...args) => handle.read(...args), flush: (...args) => handle.flush(...args),
    close: () => handle.close(), [Symbol.asyncDispose]: () => handle.close(),
    append: (events, options) => handle.append(events.map(compatible), options),
  };
}

export default class AsunaPersistence extends SessionPersistence {
  static Config = JsonlPersistence.Config;
  constructor(ctx, config) {
    super(ctx);
    // The JSONL backend also observes published live events directly. Adapt
    // that public subscription as well as pre-publication handle.append.
    const backendContext = ctx.isolate('sessionPersistence').extend({
      on: (name, listener, ...options) => ctx.on(name, name === 'session/event'
        ? (session, event) => listener(session, compatible(event)) : listener, ...options),
    });
    this.backend = new JsonlPersistence(backendContext, config);
  }
  async create(header, options) { return compatibleHandle(await this.backend.create(header, options)); }
  async open(id, access, options) { return compatibleHandle(await this.backend.open(id, access, options)); }
  flush() { return this.backend.flush(); }
  stat(id, options) { return this.backend.stat(id, options); }
  list(options) { return this.backend.list(options); }
}
