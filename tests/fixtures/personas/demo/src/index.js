import { fileURLToPath } from 'node:url';

// Synthetic persona used by tests and the demo environment. It proves the core
// runs any persona package; nothing here describes a real persona.
export const name = 'asuna-demo';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'demo', character_id: 'demo', display_name: '演示', version: '0.1.0',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    persona_file: fileURLToPath(new URL('../persona/core.md', import.meta.url)),
    skill_directories: [fileURLToPath(new URL('../skills/', import.meta.url))],
    preset: 'asuna-demo',
  });
  ctx.on('dispose', remove);
}
