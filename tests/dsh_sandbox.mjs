// Tests confine commands exactly as the live Host does: DSH's own sandbox provider (dsh-sandbox-local) picks the
// runner for this OS (Windows ACL token, Linux bubblewrap or Landlock, macOS Seatbelt). Prints, for one write root,
// the wrapping around a command as {prefix, suffix, enforcement}; or {error} when this machine has no usable runner.
import { Context } from '@deepseek-ai/cordis';
import Sandbox from '@deepseek-ai/dsh-sandbox-local';

const SENTINEL = '\u0000asuna-argv';
const ctx = new Context();
ctx.plugin(Sandbox, {});
let result;
try {
  // cordis mounts the plugin asynchronously: the provider appears on ctx once it has started.
  for (let waited = 0; !ctx.sandbox && waited < 5000; waited += 20) await new Promise(resolve => setTimeout(resolve, 20));
  if (!ctx.sandbox) throw new Error('DSH sandbox provider did not start');
  const confined = await ctx.sandbox.confine([SENTINEL], { mode: 'workspace-write', workspaceRoot: process.argv[2] });
  const at = confined.argv.indexOf(SENTINEL);
  if (at < 0) throw new Error('the runner does not pass the command through verbatim');
  result = { prefix: confined.argv.slice(0, at), suffix: confined.argv.slice(at + 1), enforcement: confined.enforcement };
} catch (error) {
  result = { error: String(error?.message ?? error) };
}
process.stdout.write(JSON.stringify(result));
process.exit(0);
