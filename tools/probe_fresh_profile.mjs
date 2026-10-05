// ADR-010 M1 acceptance: a brand-new DSH profile installs the released tarballs with `dsh plugin add` and takes
// nothing else from this checkout. The probe prepares only what DSH itself owns — a synthetic model provider that
// is never called, and the database URI in that profile's own credential store — then prints how to open the
// profile. Asuna is configured afterwards on its settings page, like any user would.
//
//   node tools/probe_fresh_profile.mjs --home <empty dir> --persona @asuna/demo [--channel @asuna/napcat-qq]
//     [--release <url or path of a released .tgz> ...] [--mongo-from config/local.json]
// With --release, the core and channels come from those files or links (a GitHub Release) instead of this
// checkout's pack; the persona still comes from the pack, since no persona is ever released.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Context } from '@deepseek-ai/cordis';
import Credentials from '@deepseek-ai/dsh-credentials-local';
import { credentialRef } from '@deepseek-ai/dsh-credentials';
import { initProfile, PROFILE_TEMPLATES } from '@deepseek-ai/dsh-app-boot';
import YAML from 'yaml';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
const option = name => { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : undefined; };
const all = name => args.flatMap((arg, index) => arg === name ? [args[index + 1]] : []);
const home = path.resolve(option('--home') ?? '');
const profile = 'fresh';
assert(option('--home'), 'pass --home <empty dir>');
assert(!home.toLowerCase().startsWith(path.resolve(root).toLowerCase()), 'the fresh home must be outside this checkout');
await fs.mkdir(home, { recursive: true });
assert.equal((await fs.readdir(home)).length, 0, 'the fresh home must be empty');

// The release assets: core plus the named persona and channels, never the checkout's patched DSH UI packages.
const released = all('--release');
const wanted = new Set(released.length ? [option('--persona')]
  : ['@asuna/cognition-core', option('--persona'), ...all('--channel')].filter(Boolean));
const artifacts = JSON.parse(await fs.readFile(path.join(root, '.runtime/adr008/packages/manifest.json'), 'utf8'))
  .filter(artifact => wanted.has(artifact.name));
assert.equal(artifacts.length, wanted.size, 'pack these packages first (tools/pack_plugins.py)');
artifacts.push(...released.map(url => ({ name: url, path: /^https?:/.test(url) ? url : path.resolve(url) })));

const profileDir = path.join(home, 'profiles', profile);
initProfile(profileDir, PROFILE_TEMPLATES.web.bundles);
const bin = path.join(root, 'node_modules/@deepseek-ai/dsh/lib/bin.js');
const added = await new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [bin, 'plugin', '--profile', profile, 'add', ...artifacts.map(a => a.path)], {
    cwd: home, env: { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: '1' }, windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.on('data', data => { output += data; }); child.stderr.on('data', data => { output += data; });
  child.once('error', reject); child.once('exit', code => resolve({ code, output }));
});
assert.equal(added.code, 0, added.output);

// A model provider is DSH's (its Models page); a synthetic one answers nothing, so no model is ever called.
const patchPath = path.join(profileDir, 'cordis.patch.yml');
const rows = YAML.parse(await fs.readFile(patchPath, 'utf8').catch(() => '')) ?? [];
const model = { id: 'synthetic-model', contextWindow: 65536, maxTokens: 4096,
  reasoningEfforts: { off: null, high: 'high' }, input: ['text', 'image'] };
rows.push({ id: 'llm-pi-ai', config: { providers: { synthetic: { api: 'openai-completions', baseURL: 'http://127.0.0.1:9/v1',
  apiKeyEnv: 'SYNTHETIC_MODEL_KEY', compat: { supportsDeveloperRole: false, maxTokensField: 'max_tokens' }, models: [model] } } } });
await fs.writeFile(patchPath, YAML.stringify(rows));

const ctx = new Context();
try {
  const credentials = new Credentials(ctx, { dshHome: home, watch: false });
  await credentials.set(credentialRef('SYNTHETIC_MODEL_KEY'), 'synthetic');
  const mongo = option('--mongo-from');
  if (mongo) await credentials.set(credentialRef('ASUNA_MONGO_URI'),
    JSON.parse(await fs.readFile(path.resolve(root, mongo), 'utf8')).mongo_uri);
} finally { await ctx.fiber.dispose(); }

console.log(JSON.stringify({ home, profile, installed: artifacts.map(a => a.name),
  open: `DSH_HOME=${home} node ${bin} --profile ${profile} --no-open --host 127.0.0.1 --port 8782` }, null, 2));
