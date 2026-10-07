import { fileURLToPath } from 'node:url';

export const name = 'asuna-xiaoman';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'local-xiaoman', character_id: 'xiaoman', display_name: '小满', version: '0.2.0',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    // Contract v2: neutral model defaults only; persona-private values live in her policy store.
    model: 'persona-model.json',
    seeds: [{ slug: 'persona', kind: 'persona', path: 'seeds/persona.md' }],
    skill_directories: [fileURLToPath(new URL('../skills/', import.meta.url))],
    preset: 'asuna-xiaoman',
  });
  ctx.on('dispose', remove);
}
