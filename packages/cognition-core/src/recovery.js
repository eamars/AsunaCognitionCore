/** The recovery preset plugin: a repair session limited to the project development tools, which runs through the
 * publication floor even while the cognition worker is down. */
import fs from 'node:fs/promises';
import { defineTool } from '@deepseek-ai/dsh-tools';
import { PERSONA_PREFIX_SECTION } from '@deepseek-ai/dsh-system-prompt';
import { deliberate, nativeRoute, sameSelection, selectFor } from './settings.js';

export const name = 'asuna-recovery';
export const inject = ['asunaFloor', 'tools', 'systemPrompt'];
export async function apply(ctx) {
  const manifest = JSON.parse(await fs.readFile(new URL('../runtime-manifest.json', import.meta.url), 'utf8'));
  const specs = manifest.developmentTools.filter(tool => tool.name !== 'development_database_read');
  const allowed = new Set(specs.map(tool => tool.name));
  // Only the project tools run: the guard refuses any other a step calls. DSH 0.2.2 hands a prompt assembly no tools
  // and resolves a step's tools apart, so the step is offered every tool the session sees; a restriction cannot name
  // this preset's own tools while it mounts, and an empty one hides them too.
  ctx.tools.guard(exec => allowed.has(exec.name) ? undefined : 'Recovery only grants the configured project tools');
  ctx.systemPrompt.section({ name: PERSONA_PREFIX_SECTION,
    order: ctx.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX'), interpolate: false,
    text: 'You are repairing an explicitly authorized Asuna plugin project through its stable publication floor. '
      + 'Use development_files to inspect current state and actual failure evidence. Preserve private state and existing grants. '
      + 'Publish a corrected forward version; never reset Mongo, replay messages, or claim a failed activation succeeded. '
      + 'The cognition worker may be unavailable. The native Host and these project tools run independently of it.' });
  // The floor's route, unless a model was chosen in DSH for this session. DSH 0.2.2 fixes a step's route when it
  // prepares the step, so it is selected when input arrives, before the turn; a request then goes on the step's own,
  // and one that still differs (the floor's route changed meanwhile) is selected for the next step.
  const route = agent => nativeRoute(deliberate(agent.session) ?? ctx.asunaFloor.config.route);
  ctx.on('agent/inbox/inserted', ({ agent }) => { if (agent) selectFor(agent, route(agent)); });
  ctx.on('agent/request', async ({ agent }, next) => {
    const request = await next(), wanted = route(agent);
    if (!sameSelection(wanted, request)) { selectFor(agent, wanted); return request; }
    return nativeRoute({ ...request, ...wanted, reasoningEffort: wanted?.reasoningEffort });
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
