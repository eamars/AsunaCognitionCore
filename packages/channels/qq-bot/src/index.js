/** The QQ Bot channel plugin: registers the channel kind `qqbot` and, once the channel is configured, runs the bridge
 * (bridge.js) between her and the official QQ Bot open platform. */
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { QQBotBridge } from './bridge.js';

export const name = 'asuna-qq-bot';
export const inject = ['asuna', 'asunaFloor'];

/** The bridge reads its bot (the channel's `account_id`, the AppID, and `app_secret`) from the channel settings
 * (`channels.qqbot`) each time it connects, so it waits idle until they are applied. */
export function apply(ctx) {
  const remove = ctx.asuna.registerChannel({
    kind: 'qqbot', title: 'QQ Bot', project: 'qq-bot',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    python: 'python', module: 'qq_bot',
  });
  ctx.on('dispose', remove);
  if (!ctx.asunaFloor) return;                 // registering the kind alone (no Host data folder): no bridge
  const bridge = new QQBotBridge({
    endpoint: () => ctx.asuna.channelEndpoint('qqbot'),
    statePath: path.join(ctx.asunaFloor.dataRoot, 'bridges', 'qqbot.json'),
    log: message => ctx.logger?.warn?.('qq-bot: ' + message),
    info: message => ctx.logger?.info?.('qq-bot: ' + message),
  });
  bridge.start().catch(error => ctx.logger?.warn?.('qq-bot: ' + error.message));
  ctx.on('dispose', () => bridge.stop());
}
