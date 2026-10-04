/** Channel contribution: a platform plugin (e.g. @asuna/napcat-qq) registers its kind with Core.
 * Core names no platform; the worker imports the plugin's kind module for its id formats and
 * adapter conventions, and the plugin's adapter is the integration her development tools work on.
 */
import path from 'node:path';

const KIND = /^[a-z][a-z0-9_]{0,15}$/;
const PROJECT = /^[a-z][a-z0-9-]{0,50}$/;
const MODULE = /^[a-z][a-z0-9_]{0,40}$/;

function relative(root, value, field) {
  if (typeof value !== 'string' || !value) throw new Error('CHANNEL_CONTRACT_INVALID: ' + field);
  const inside = path.relative(root, path.resolve(root, value));
  if (!inside || inside.startsWith('..') || path.isAbsolute(inside))
    throw new Error('CHANNEL_CONTRACT_INVALID: ' + field + ' must stay inside resource_root');
  return inside.split(path.sep).join('/');
}

export function normalizeChannel(channel) {
  if (!channel || !KIND.test(channel.kind ?? '')) throw new Error('CHANNEL_CONTRACT_INVALID: kind');
  if (!PROJECT.test(channel.project ?? '')) throw new Error('CHANNEL_CONTRACT_INVALID: project');
  if (typeof channel.title !== 'string' || !channel.title) throw new Error('CHANNEL_CONTRACT_INVALID: title');
  if (typeof channel.resource_root !== 'string' || !channel.resource_root)
    throw new Error('CHANNEL_CONTRACT_INVALID: resource_root');
  if (!MODULE.test(channel.module ?? '')) throw new Error('CHANNEL_CONTRACT_INVALID: module');
  const root = channel.resource_root;
  return Object.freeze({ ...channel,
    python: relative(root, channel.python, 'python'),
    integration_directory: channel.integration_directory === undefined ? null
      : relative(root, channel.integration_directory, 'integration_directory'),
    skill_directories: (channel.skill_directories ?? []).map((directory, index) =>
      relative(root, directory, 'skill_directories[' + index + ']')) });
}

/** Absolute paths for the worker, against the published artifact root when one is selected. */
export function resolveChannel(channel, root = channel.resource_root) {
  const at = file => path.join(root, file);
  return { kind: channel.kind, project: channel.project, title: channel.title, module: channel.module,
    python: at(channel.python),
    integration_release: channel.integration_directory ? at(channel.integration_directory) : null,
    skill_directories: channel.skill_directories.map(at) };
}
