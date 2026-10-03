export const name = 'asuna-role';
export const inject = ['asuna', 'systemPrompt', 'tools'];
export function apply(ctx) {
  ctx.asuna.attachPreset(ctx, 'character');
}
