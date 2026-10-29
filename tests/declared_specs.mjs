// Reads {specs, calls} from stdin: registers every declared spec of her tools with DSH's defineTool and validates each call
// against its tool's declared parameters with DSH's validateArgs. Prints {registered: [...], failed: {name: message}, calls:
// [{tool, violations}]}. Run by tests/test_declared_specs_dsh.py.
import { defineTool, validateArgs } from '@deepseek-ai/dsh-tools';

let text = '';
for await (const chunk of process.stdin) text += chunk;
const { specs, calls } = JSON.parse(text);
const registered = [], failed = {}, byName = {};
for (const spec of specs) {
  byName[spec.name] = spec;
  try {
    defineTool({ ...spec, output: { schema: { type: 'json' } }, execute: async () => ({}) });
    registered.push(spec.name);
  } catch (error) { failed[spec.name] = String(error?.message ?? error).slice(0, 300); }
}
const results = calls.map(({ tool, args }) => ({ tool, violations: byName[tool] ? validateArgs(byName[tool].parameters, args) : null }));
console.log(JSON.stringify({ registered, failed, calls: results }));
