/** Build the reviewed native rendering extension from the pinned commit of the Asuna branch on the DSH fork. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { parseArgs } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const pin = JSON.parse(await fs.readFile(path.join(root, 'tools/dsh-inline/source.json'), 'utf8'));
const version = pin.dsh + '-asuna.1';
const { values } = parseArgs({ options: { source: { type: 'string' } } });
if (!values.source) throw new Error('Usage: node tools/build_dsh_inline.mjs --source <dedicated checkout of ' + pin.branch + '>');
const source = path.resolve(values.source);
const destination = path.join(root, '.runtime/adr008/packages');
await fs.mkdir(destination, { recursive: true });
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const git = args => {
  const result = spawnSync('git', args, { cwd: source, encoding: 'utf8', windowsHide: true });
  if (result.status !== 0) throw new Error(result.stderr || 'Native source Git check failed');
  return result.stdout;
};
if (git(['rev-parse', 'HEAD']).trim() !== pin.commit) throw new Error('Native extension requires commit ' + pin.commit + ' (' + pin.branch + ')');
if (git(['status', '--porcelain']).trim()) throw new Error('The native source checkout has changes; use a dedicated clean checkout');
process.env.COREPACK_ENABLE_DOWNLOAD_PROMPT = '0';

// PowerShell quotes each argv literally on Windows; no shell interpolation of paths.
function run(command, args, cwd, step) {
  if (process.platform === 'win32' && command === 'npm') command = 'npm.cmd';
  // DSH pins its pnpm through corepack, which ships with Node.
  if (command === 'pnpm') [command, args] = ['corepack', ['pnpm', ...args]];
  const quote = value => "'" + value.replaceAll("'", "''") + "'";
  const result = process.platform === 'win32'
    ? spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      '$ErrorActionPreference = "Stop"; & ' + [command, ...args].map(quote).join(' ') + '; exit $LASTEXITCODE'], { cwd, encoding: 'utf8', windowsHide: true, maxBuffer: 32 * 1024 * 1024 })
    : spawnSync(command, args, { cwd, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 });
  const log = path.join(destination, step + '.log');
  return fs.writeFile(log, (result.stdout ?? '') + (result.stderr ?? '')).then(() => {
    if (result.status !== 0) throw new Error(step + ' failed; inspect ' + log);
    process.stdout.write(step + ' passed\n'); return result.stdout;
  });
}
await run('pnpm', ['install', '--frozen-lockfile', '--ignore-scripts'], source, 'inline-install');
await run('pnpm', ['exec', 'tsc', '-b', 'tsconfig.host.json', '--pretty', 'false'], source, 'inline-host-types');
await run('pnpm', ['exec', 'tsdown', '--config-loader', 'native', '--env.DSH_BUILD_FACE', 'host'], source, 'inline-host-build');
await run('pnpm', ['exec', 'tsc', '-b', 'packages/client/ui-chat/tsconfig.json', '--pretty', 'false'], source, 'inline-client-types');
// One package per call: pnpm refuses one filtered run over the two packages, which depend on each other.
for (const name of ['ui-renderer', 'ui-chat'])
  await run('pnpm', ['--filter', '@deepseek-ai/dsh-client-' + name, 'bundle'], source, 'inline-client-build-' + name);

const staging = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-native-inline-pack-'));
const artifacts = [];
for (const name of ['ui-chat', 'ui-renderer']) {
  const packageName = '@deepseek-ai/dsh-client-' + name;
  const folder = path.join(staging, name);
  await fs.mkdir(folder);
  // Released manifests have concrete dependency versions, unlike workspace manifests.
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'node_modules', packageName, 'package.json'), 'utf8'));
  if (manifest.version !== pin.dsh) throw new Error('Installed DSH differs from the pinned release ' + pin.dsh);
  manifest.version = version;
  await fs.writeFile(path.join(folder, 'package.json'), JSON.stringify(manifest, null, 2));
  await fs.cp(path.join(source, 'packages/client', name, 'lib'), path.join(folder, 'lib'), { recursive: true });
  await fs.copyFile(path.join(source, 'packages/client', name, 'README.md'), path.join(folder, 'README.md'));
  await fs.copyFile(path.join(source, 'LICENSE'), path.join(folder, 'LICENSE'));
  const packed = JSON.parse(await run('npm', ['pack', '--json', '--pack-destination', destination], folder, 'inline-pack-' + name))[0];
  const original = path.join(destination, packed.filename);
  const sha256 = digest(await fs.readFile(original));
  const artifact = original.replace(/\.tgz$/, '-' + sha256.slice(0, 12) + '.tgz');
  await fs.copyFile(original, artifact);
  artifacts.push({ name: packageName, path: artifact, sha256, integrity: packed.integrity,
    kind: 'native-rendering-extension', sourceRepository: pin.repository, sourceBranch: pin.branch, sourceCommit: pin.commit,
    files: packed.files.map(row => row.path) });
}
await fs.writeFile(path.join(destination, 'native-inline-manifest.json'), JSON.stringify(artifacts, null, 2));
process.stdout.write(JSON.stringify(artifacts.map(({ files, ...artifact }) => artifact), null, 2) + '\n');
