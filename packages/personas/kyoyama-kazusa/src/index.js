import { fileURLToPath } from 'node:url';

// 杏山カズサ: an original persona inspired by a Blue Archive character, run on the Asuna core. Her text is written
// fresh; nothing here is copied game text.
export const name = 'asuna-kazusa';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'kyoyama-kazusa', character_id: 'kyoyama-kazusa', display_name: '杏山カズサ', version: '0.2.0',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
    ],
    skill_directories: [fileURLToPath(new URL('../skills/', import.meta.url))],
    preset: 'asuna-kazusa',
  });
  ctx.on('dispose', remove);
}
