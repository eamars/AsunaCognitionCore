export const name = 'asuna-attend';
export const inject = ['asuna', 'systemPrompt', 'tools'];
// The relevance gate (attend.py): one small tool-free session per group; answers 接话 or 不理, never speaks.
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.asuna.attachPreset(ctx, 'attend');
}
