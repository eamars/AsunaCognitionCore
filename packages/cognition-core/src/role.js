/** The character brain's preset plugin: her role session gets the worker-rendered system prompt and her role tools
 * (`attachRole` in index.js). Each persona package's preset mounts it. */
export const name = 'asuna-role';
export const inject = ['asuna', 'systemPrompt', 'tools'];
export function apply(ctx) {
  ctx.asuna.attachPreset(ctx, 'character');
  ctx.on('agent/created', async ({ agent }) => { await ctx.asuna.attachRole(agent); });
}
