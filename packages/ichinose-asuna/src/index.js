import { fileURLToPath } from 'node:url';

// 一之瀬アスナ: an original persona inspired by a Blue Archive character, run on the Asuna core (owner 2026-10-07,
// the first persona deployed in Docker, ADR-019). Her text is written fresh; nothing here is copied game text.
export const name = 'asuna-ichinose';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'ichinose-asuna', character_id: 'ichinose-asuna', display_name: '一之瀬アスナ', version: '0.2.0',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
    ],
    skill_directories: [fileURLToPath(new URL('../skills/', import.meta.url))],
    preset: 'asuna-ichinose',
  });
  ctx.on('dispose', remove);
}
