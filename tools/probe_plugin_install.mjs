// Install real tarballs outside this checkout and exercise DSH's public resolver.
// No Host, Python worker, Mongo database, model request or channel consumer starts.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Context } from '@deepseek-ai/cordis';
import { initProfile, PROFILE_TEMPLATES, loadProfileDirectory,
  createRuntimeResolution, PluginPackages } from '@deepseek-ai/dsh-app-boot';

const root = fileURLToPath(new URL('../', import.meta.url));
const home = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-plugin-install-'));
assert(!home.toLowerCase().startsWith(root.toLowerCase()));
const profileDir = path.join(home, 'profiles', 'package-probe');
initProfile(profileDir, PROFILE_TEMPLATES.web.bundles);
const artifacts = JSON.parse(await fs.readFile(path.join(root, '.runtime/adr008/packages/manifest.json'), 'utf8'));
const installAnchor = path.join(root, 'node_modules/@deepseek-ai/dsh/package.json');
const install = await new Promise((resolve, reject) => {
  const child = spawn(process.execPath, [path.join(path.dirname(installAnchor), 'lib/bin.js'),
    'plugin', '--profile', 'package-probe', 'add', ...artifacts.map(a => a.path)], {
    cwd: home, env: { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: '1' },
    windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  child.stdout.on('data', data => { output += data; });
  child.stderr.on('data', data => { output += data; });
  child.once('error', reject);
  child.once('exit', code => resolve({ code, output }));
});
assert.equal(install.code, 0, install.output);
const profile = loadProfileDirectory('package-probe', profileDir, installAnchor);
assert.deepEqual(profile.skippedBundles, []);
const resolution = await createRuntimeResolution({ installAnchor, profile, home });
const ctx = new Context();
try {
  const packages = new PluginPackages(ctx, { resolution });
  const coreRoot = path.join(profileDir, 'node_modules/@asuna/cognition-core');
  const manifest = JSON.parse(await fs.readFile(path.join(coreRoot, 'package.json'), 'utf8'));
  for (const name of Object.keys(manifest.peerDependencies)) {
    assert.equal(resolution.entries.find(entry => entry.name === name)?.scope, 'installation', name);
    assert(packages.packageOf(name, pathToFileURL(path.join(coreRoot, 'src/index.js')).href), name);
  }
  const imported = [];
  for (const [subpath, target] of Object.entries(manifest.exports)) {
    if (subpath === './client') continue; // Native browser module, reviewed in the Web UI.
    await import(pathToFileURL(path.join(coreRoot, target)).href);
    imported.push(subpath);
  }
  // Persona packages come from the packed artifacts; core tooling never names a persona.
  const personaPackages = artifacts.map(a => a.name)
    .filter(name => name.startsWith('@asuna/') && name !== '@asuna/cognition-core');
  assert(personaPackages.length >= 1, 'no persona package among the packed artifacts');
  for (const name of personaPackages) {
    await import(pathToFileURL(path.join(profileDir, 'node_modules', name, 'src/index.js')).href);
  }
  const result = { passed: true, profile: profileDir, hostVersion: '0.2.0-rc.2',
    coreExports: imported, nativePeers: Object.keys(manifest.peerDependencies).length,
    artifacts: artifacts.map(({ name, sha256 }) => ({ name, sha256 })),
    liveConsumersStarted: false };
  const evidence = path.join(root, '.runtime/adr008/evidence');
  await fs.mkdir(evidence, { recursive: true });
  await fs.writeFile(path.join(evidence, 'independent-install.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} finally {
  await ctx.fiber.dispose();
}
