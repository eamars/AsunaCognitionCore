import { fileURLToPath } from 'node:url';
import manifest from '../package.json' with { type: 'json' };

export const name = 'asuna-claude-chan';
export const inject = ['asuna'];

export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'claude-chan', character_id: 'claude-chan', display_name: 'Claude酱', version: manifest.version,
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
      { slug: 'ledger', kind: 'ledger', path: 'seeds/ledger.md' },
    ],
    preset: 'asuna-claude-chan',
  });
  ctx.on('dispose', remove);
}
