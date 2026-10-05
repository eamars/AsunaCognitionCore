export const name = 'asuna-role';
export const inject = ['asuna', 'systemPrompt', 'tools'];
export function apply(ctx) {
  ctx.asuna.attachPreset(ctx, 'character');
  ctx.on('agent/created', async ({ agent }) => { await ctx.asuna.attachRole(agent); });
}
