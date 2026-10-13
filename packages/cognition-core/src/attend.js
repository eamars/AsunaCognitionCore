/** The relevance gate's preset plugin: a small tool-free session for each question, deciding whether she joins
 * in (attend.py), never speaking itself. */
export const name = 'asuna-attend';
export const inject = ['asuna', 'systemPrompt', 'tools'];
// The relevance gate (attend.py): one small tool-free session per question; answers 接话 or 不理, never speaks.
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.asuna.attachPreset(ctx, 'attend');
}
