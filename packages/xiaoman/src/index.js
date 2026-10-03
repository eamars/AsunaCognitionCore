import { fileURLToPath } from 'node:url';

export const name = 'asuna-xiaoman';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'local-xiaoman', character_id: 'xiaoman', display_name: '小满', version: '0.1.0',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    persona_file: fileURLToPath(new URL('../persona/core.md', import.meta.url)),
    skill_directories: [fileURLToPath(new URL('../skills/', import.meta.url))],
    integration_directory: 'integrations/qq-napcat-adapter',
    preset: 'asuna-xiaoman',
  });
  ctx.on('dispose', remove);
}
