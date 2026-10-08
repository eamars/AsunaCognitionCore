import { fileURLToPath } from 'node:url';

export const name = 'asuna-yan-sui';
export const inject = ['asuna'];

export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'yan-sui', character_id: 'yan-sui', display_name: '晏绥', version: '0.2.0',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
      { slug: 'ledger', kind: 'ledger', path: 'seeds/ledger.md' },
    ],
    preset: 'asuna-yan-sui',
  });
  ctx.on('dispose', remove);
}
