import { defineTool } from '@deepseek-ai/dsh-tools';

export const name = 'asuna-controlled-tools';
export const inject = ['tools'];
export function apply(ctx, config) {
  for (const spec of config.tools) {
    ctx.tools.register(defineTool({
      name: spec.name, description: spec.description, parameters: spec.parameters,
      output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      async execute(args, exec) {
        if (!exec.agent) throw new Error('NO_OWNING_AGENT');
        const response = await fetch(config.url + '/tool', {
          method: 'POST', signal: exec.signal,
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + process.env.ASUNA_BROKER_TOKEN },
          body: JSON.stringify({ session: exec.agent.session.id, call_id: exec.callId, tool: spec.name, args }),
        });
        const value = await response.json();
        if (!response.ok) throw new Error(JSON.stringify(value));
        return value;
      },
    }));
  }
}
