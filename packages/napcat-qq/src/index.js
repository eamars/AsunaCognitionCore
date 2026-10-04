import { fileURLToPath } from 'node:url';

export const name = 'asuna-napcat-qq';
export const inject = ['asuna'];
export function apply(ctx) {
  const remove = ctx.asuna.registerChannel({
    kind: 'qq', title: 'QQ', project: 'napcat-qq',
    resource_root: fileURLToPath(new URL('../', import.meta.url)),
    // The worker imports python/napcat_qq for QQ id formats and the adapter's conventions.
    python: 'python', module: 'napcat_qq',
    // Her integration_* tools develop and run this adapter (owner grant only).
    integration_directory: 'integration',
    skill_directories: [fileURLToPath(new URL('../skills/', import.meta.url))],
  });
  ctx.on('dispose', remove);
}
