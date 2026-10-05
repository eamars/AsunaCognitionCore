import path from 'node:path';

/** This profile's data folder (ADR-010 D3): the dataRoot setting, otherwise the profile's own folder in the DSH
 * home ($DSH_HOME/asuna/<profile>). Everything Asuna writes for a profile — activation, candidates and their
 * baselines, working folders, locks, channel grants, evidence — lives under it; the installed package is never
 * written. The worker gets the same folder as ASUNA_DATA_ROOT. */
export function dataRoot(ctx, config) {
  if (config?.dataRoot) return path.resolve(config.dataRoot);
  let profile;
  try { profile = ctx?.reflect?.get('profileContext'); } catch { profile = undefined; }
  if (profile?.home && profile?.name) return path.join(profile.home, 'asuna', profile.name);
  throw new Error('ASUNA_DATA_ROOT_UNKNOWN: set the dataRoot setting');
}

/** The local chat's working folder, as the worker derives it (config.local_workspace). */
export function localWorkspace(root) {
  return path.join(root, 'work', 'local-user');
}

/** The floor's own state inside the data folder: activation, baselines, frozen copies and artifacts. A profile
 * set up before ADR-010 keeps its state in a subfolder (stateDir); a new one keeps it at the top. */
export function floorState(root, config) {
  return config?.stateDir ? path.join(root, config.stateDir) : root;
}
