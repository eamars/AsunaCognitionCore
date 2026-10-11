import { fileURLToPath } from 'node:url';

export const name = 'asuna-wen-qi';
export const inject = ['asuna'];

export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'wen-qi', character_id: 'wen-qi', display_name: '白濑栞', version: '0.2.3',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
      { slug: 'ledger', kind: 'ledger', path: 'seeds/ledger.md' },
    ],
    preset: 'asuna-wen-qi',
  });
  ctx.on('dispose', remove);
}
