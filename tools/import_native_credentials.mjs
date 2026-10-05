/** One-time private migration through DSH's credential provider; never logs values. */
import { Context } from '@deepseek-ai/cordis';
import Credentials from '@deepseek-ai/dsh-credentials-local';
import { credentialRef } from '@deepseek-ai/dsh-credentials';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { home, values } = JSON.parse(input);
const ctx = new Context();
try {
  const credentials = new Credentials(ctx, { dshHome: home, watch: false });
  for (const [name, value] of Object.entries(values)) {
    if (!value) continue;                      // an empty value is no credential; the store refuses it
    const ref = credentialRef(name);
    if (!await credentials.resolve(ref)) await credentials.set(ref, value);
  }
  process.stdout.write('Native provider credentials available; existing values preserved.\n');
} finally { await ctx.fiber.dispose(); }
