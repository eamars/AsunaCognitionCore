/** The optional affect appraiser's preset plugin: a tool-free session that proposes affect events and never speaks. */
export const name = 'asuna-appraiser';
export const inject = ['asuna', 'systemPrompt', 'tools'];
// Optional affect appraiser route (ADR-009 §6.7): tool-free, proposes only, never speaks.
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.asuna.attachPreset(ctx, 'appraiser');
}
