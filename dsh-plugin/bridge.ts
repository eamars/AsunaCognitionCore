import { readFileSync } from 'node:fs';

export const name = 'asuna-prompt-boundary';
export const inject = ['systemPrompt'];

// Intentionally thin. No database, publication, scheduling or business state.
// Verified against dsh-system-prompt at fb2c4b9e (section/suppressRuntimeContext).
export function apply(ctx, config) {
  const text = readFileSync(config.promptFile, 'utf8');
  if (text.trim().length < 80) throw new Error('ASUNA_REQUIRED_PERSONA_MISSING');
  ctx.systemPrompt.section({ name: 'asuna-complete', order: 0, complete: true,
    interpolate: false, text });
  ctx.systemPrompt.suppressRuntimeContext();
}
