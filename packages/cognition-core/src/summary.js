/** The dialogue-summary preset plugin: a tool-free session on the action route that writes low-priority
 * conversation summaries. */
export const name = 'asuna-summary';
export const inject = ['asuna', 'systemPrompt', 'tools'];
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.asuna.attachPreset(ctx, 'summary');
}
