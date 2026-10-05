import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { PeerBridge } from './bridge.js';

export const name = 'asuna-dsh-peer';
export const inject = ['asuna', 'asunaFloor'];

/**
 * config (owner-local, in the profile's editable patch):
 *   url        the peer DSH Web server, e.g. https://192.0.2.10
 *   sessionId  the one peer session this bridge reads and writes
 *   routeId / senderId   the channel route and sender this peer is configured as (channels.dsh in Asuna's settings)
 *   label      first line of every message she sends there, saying who speaks
 *   ownerNote  first line of a peer reply that did not answer her (it answered someone else in that session)
 *   insecureTls  the peer is a LAN service behind its own local CA
 */
export function apply(ctx, config = {}) {
  const remove = ctx.asuna.registerChannel({
    kind: 'dsh', title: 'DSH', project: 'dsh-peer',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    python: 'python', module: 'dsh_peer',
  });
  ctx.on('dispose', remove);
  if (!config.url || !config.sessionId || !config.routeId || !config.senderId) {
    ctx.logger?.info?.('dsh-peer: no peer session configured; the bridge is idle');
    return;
  }
  const bridge = new PeerBridge({
    peer: { url: config.url, sessionId: config.sessionId, routeId: config.routeId, senderId: config.senderId,
            label: config.label ?? '', ownerNote: config.ownerNote ?? '', insecureTls: config.insecureTls === true },
    endpoint: () => ctx.asuna.channelEndpoint('dsh'),
    statePath: path.join(ctx.asunaFloor.dataRoot, 'bridges', 'dsh-' + config.routeId + '.json'),
    log: message => ctx.logger?.warn?.('dsh-peer: ' + message),
  });
  bridge.start().catch(error => ctx.logger?.warn?.('dsh-peer: ' + error.message));
  ctx.on('dispose', () => bridge.stop());
}
