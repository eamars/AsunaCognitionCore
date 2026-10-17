import { fileURLToPath } from 'node:url';
import manifest from '../package.json' with { type: 'json' };

export const name = 'asuna-shirase-shiori';
export const inject = ['asuna'];

export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'shirase-shiori', character_id: 'shirase-shiori', display_name: '白濑栞', version: manifest.version,
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
      { slug: 'ledger', kind: 'ledger', path: 'seeds/ledger.md' },
    ],
    preset: 'asuna-shirase-shiori',
  });
  ctx.on('dispose', remove);
}
