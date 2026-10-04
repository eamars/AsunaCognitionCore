/** Build the reviewed native rendering extension from the exact ADR-008 DSH release. */
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { parseArgs } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const baseCommit = '639ed015397290b3745d163aafe02ffee4aa3f84';
const version = '0.2.0-rc.2-asuna.1';
const { values } = parseArgs({ options: { source: { type: 'string' } } });
if (!values.source) throw new Error('Usage: node tools/build_dsh_inline.mjs --source <dedicated DSH rc.2 checkout>');
const source = path.resolve(values.source);
const destination = path.join(root, '.runtime/adr008/packages');
await fs.mkdir(destination, { recursive: true });
const patchPath = path.join(root, 'tools/dsh-inline/rc2-inline.patch');
const patch = await fs.readFile(patchPath, 'utf8');
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const git = args => {
  const result = spawnSync('git', args, { cwd: source, encoding: 'utf8', windowsHide: true });
  if (result.status !== 0) throw new Error(result.stderr || 'Native source Git check failed');
  return result.stdout;
};
if (git(['rev-parse', 'HEAD']).trim() !== baseCommit) throw new Error('Native extension requires the pinned DSH release commit');
const status = git(['status', '--porcelain']).trim();
if (!status) {
  git(['apply', '--check', patchPath]); git(['apply', patchPath]);
  git(['add', '--intent-to-add', 'packages/client/ui-chat/src/client/chat/ChatContent.tsx']);
}
const diff = git(['diff', '--binary', '--no-ext-diff']).replaceAll('\r\n', '\n');
if (diff !== patch.replaceAll('\r\n', '\n')) throw new Error('Source changes differ from the reviewed inline patch; use a dedicated clean checkout');
const untracked = git(['ls-files', '--others', '--exclude-standard']).trim();
if (untracked) throw new Error('Unexpected files in the native source checkout: ' + untracked);

// PowerShell quotes each argv literally on Windows; no shell interpolation of paths.
function run(command, args, cwd, step) {
  if (process.platform === 'win32' && command === 'npm') command = 'npm.cmd';
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
await run('pnpm', ['exec', 'tsdown', '--env.DSH_BUILD_FACE', 'host'], source, 'inline-host-build');
await run('pnpm', ['exec', 'tsc', '-b', 'packages/client/ui-chat/tsconfig.json', '--pretty', 'false'], source, 'inline-client-types');
await run('pnpm', ['--filter', '@deepseek-ai/dsh-client-ui-chat', '--filter', '@deepseek-ai/dsh-client-ui-renderer', 'bundle'], source, 'inline-client-build');

const staging = await fs.mkdtemp(path.join(os.tmpdir(), 'asuna-native-inline-pack-'));
const artifacts = [];
for (const name of ['ui-chat', 'ui-renderer']) {
  const packageName = '@deepseek-ai/dsh-client-' + name;
  const folder = path.join(staging, name);
  await fs.mkdir(folder);
  // Released manifests have concrete dependency versions, unlike workspace manifests.
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'node_modules', packageName, 'package.json'), 'utf8'));
  if (manifest.version !== '0.2.0-rc.2') throw new Error('Installed DSH differs from the reviewed release');
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
    kind: 'native-rendering-extension', sourceCommit: baseCommit, patchSha256: digest(patch),
    files: packed.files.map(row => row.path) });
}
await fs.writeFile(path.join(destination, 'native-inline-manifest.json'), JSON.stringify(artifacts, null, 2));
process.stdout.write(JSON.stringify(artifacts.map(({ files, ...artifact }) => artifact), null, 2) + '\n');
