/** The safety classifier's preset plugin (ADR-135 D9): a small tool-free session for each question, judging one
 * text against the owner's policy (classifier.py), never speaking itself. */
export const name = 'asuna-classify';
export const inject = ['asuna', 'systemPrompt', 'tools'];
export function apply(ctx) {
  ctx.tools.restrict({ allow: [] });
  ctx.asuna.attachPreset(ctx, 'classify');
}
