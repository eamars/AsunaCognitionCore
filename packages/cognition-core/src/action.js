/** The action brain's preset plugin: each action agent gets the executor's system prompt and only the tools its task
 * was granted (`attachAction` in index.js). */
export const name = 'asuna-action';
export const inject = ['asuna', 'systemPrompt', 'tools', 'attachments'];
export function apply(ctx) {
  ctx.asuna.attachPreset(ctx, 'executor');
  ctx.on('agent/created', async ({ agent }) => { await ctx.asuna.attachAction(agent, ctx.attachments); });
}
