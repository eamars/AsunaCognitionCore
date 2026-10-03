import fs from 'node:fs/promises';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { PERSONA_PREFIX_SECTION } from '@deepseek-ai/dsh-system-prompt';
import { nativeRoute } from './settings.js';

export const name = 'asuna-recovery';
export const inject = ['asunaFloor', 'tools', 'systemPrompt'];
export async function apply(ctx) {
  const manifest = JSON.parse(await fs.readFile(new URL('../runtime-manifest.json', import.meta.url), 'utf8'));
  const specs = manifest.developmentTools.filter(tool => tool.name !== 'development_database_read');
  const allowed = new Set(specs.map(tool => tool.name));
  // A standing scope's empty restriction would also hide its own tools from
  // descendant agents. The scoped guard and assembly filter enforce this list.
  ctx.tools.guard(exec => allowed.has(exec.name) ? undefined : 'Recovery only grants the configured project tools');
  ctx.systemPrompt.section({ name: PERSONA_PREFIX_SECTION,
    order: ctx.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX'), interpolate: false,
    text: 'You are repairing an explicitly authorized Asuna plugin project through its stable publication floor. '
      + 'Use development_files to inspect current state and actual failure evidence. Preserve private state and existing grants. '
      + 'Publish a corrected forward version; never reset Mongo, replay messages, or claim a failed activation succeeded. '
      + 'The cognition worker may be unavailable. The native Host and these project tools run independently of it.' });
  ctx.on('system-prompt/assemble', async (_assembly, _scope, next) => {
    const assembly = await next(); return { ...assembly, tools: assembly.tools.filter(tool => allowed.has(tool.name)) };
  });
  ctx.on('agent/request', async ({ agent }, next) => {
    const selected = agent.session.snapshotEvents().findLast(event => event.type === 'model/selection')?.data;
    const route = selected ?? ctx.asunaFloor.config.route;
    return nativeRoute({ ...await next(), ...route, reasoningEffort: route?.reasoningEffort });
  });
  // A user can select this preset after a blank Agent was already created.
  // Standing-preset registrations also follow that native recompose boundary.
  for (const spec of specs) ctx.tools.register(defineTool({ ...spec,
      output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      execute: async (args, exec) => {
        const value = await ctx.asunaFloor.call(spec.name, args, { native_session_id: exec.agent.session.id, kind: 'native-recovery' });
        if (value.state === 'APPLIED' && ctx.asunaFloor.activateRecovery)
          return ctx.asunaFloor.activateRecovery(value);
        return value;
      },
    }));
}
