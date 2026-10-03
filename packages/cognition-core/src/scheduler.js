export const name = 'asuna-scheduler';
export const inject = ['asuna', 'tools'];
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.on('agent/pre-step', async ({ agent }) => {
    await ctx.asuna.schedules.delivered(agent);
    return { kind: 'reject' };
  });
}
