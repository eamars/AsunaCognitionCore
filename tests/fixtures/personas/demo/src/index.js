import { fileURLToPath } from 'node:url';

// Synthetic persona used by tests and the demo environment. It proves the core
// runs any persona package; nothing here describes a real persona.
const root = fileURLToPath(new URL('../', import.meta.url));
export const name = 'asuna-demo';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerPersona({
    id: 'demo', character_id: 'demo', display_name: '演示', version: '0.2.0',
    resource_root: root,
    model: 'persona-model.json',
    seeds: [
      { slug: 'persona', kind: 'persona', path: 'seeds/persona.md' },
      { slug: 'voice', kind: 'voice', path: 'seeds/voice.md' },
      { slug: 'ledger', kind: 'ledger', path: 'seeds/ledger.md' },
    ],
    skill_directories: ['skills'],
    preset: 'asuna-demo',
  });
  ctx.on('dispose', remove);
}
