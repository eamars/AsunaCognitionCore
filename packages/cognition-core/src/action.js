export const name = 'asuna-action';
export const inject = ['asuna', 'systemPrompt', 'tools', 'attachments'];
export function apply(ctx) {
  ctx.asuna.attachPreset(ctx, 'executor');
  ctx.on('agent/created', async ({ agent }) => { await ctx.asuna.attachAction(agent); });
}
