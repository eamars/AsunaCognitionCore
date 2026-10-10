/** The agent-line channel plugin: registers the channel kind `agent`, the lines coding agents use to talk with
 * her; agents post and poll through the channel API themselves (tools/agent_line.py). */
import { fileURLToPath } from 'node:url';

export const name = 'asuna-agent-line';
export const inject = ['asuna'];

/** The kind only: an agent posts and polls through the channel API itself (tools/agent_line.py); no bridge runs here. */
export function apply(ctx) {
  const remove = ctx.asuna.registerChannel({
    kind: 'agent', title: 'Agent', project: 'agent-line',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    python: 'python', module: 'agent_line',
  });
  ctx.on('dispose', remove);
}
