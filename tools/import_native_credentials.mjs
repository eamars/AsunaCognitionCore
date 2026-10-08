/** One-time private migration through DSH's credential provider; never logs values. */
import { Context } from '@deepseek-ai/cordis';
import Credentials from '@deepseek-ai/dsh-credentials-local';
import { credentialRef } from '@deepseek-ai/dsh-credentials';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { home, values } = JSON.parse(input);
const ctx = new Context();
try {
  // The store reads its file when its service starts: wait for that, or every value reads as missing and is overwritten.
  ctx.plugin(Credentials, { dshHome: home, watch: false });
  const credentials = await new Promise(resolve => ctx.inject(['credentials'], child => resolve(child.credentials)));
  for (const [name, value] of Object.entries(values)) {
    if (!value) continue;                      // an empty value is no credential; the store refuses it
    const ref = credentialRef(name);
    if (!await credentials.resolve(ref)) await credentials.set(ref, value);
  }
  process.stdout.write('Native provider credentials available; existing values preserved.\n');
} finally { await ctx.fiber.dispose(); }
