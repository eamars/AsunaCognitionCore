/** The scheduler session's preset plugin: when DSH's scheduler wakes it, it hands the due reminders to the worker
 * (schedule.js) and makes no model request. */
export const name = 'asuna-scheduler';
export const inject = ['asuna', 'tools'];
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.on('agent/pre-step', async ({ agent }) => {
    await ctx.asuna.schedules.delivered(agent);
    return { kind: 'reject' };
  });
}
