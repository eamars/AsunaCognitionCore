/** Persona contribution v2 (ADR-009 PERSONA_CONTRACT §2): shape checks at registration.
 * Full persona-model schema validation runs in the worker (jsonschema); this keeps an
 * obviously wrong package from ever selecting itself, so Core stays inert with a reason.
 */
import fs from 'node:fs';
import path from 'node:path';

const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;
const GRANTS = new Set(['persona_data.write', 'probe']);

function relative(root, value, field) {
  if (typeof value !== 'string' || !value) throw new Error('PERSONA_CONTRACT_INVALID: ' + field);
  const resolved = path.resolve(root, value);
  const inside = path.relative(root, resolved);
  if (!inside || inside.startsWith('..') || path.isAbsolute(inside))
    throw new Error('PERSONA_CONTRACT_INVALID: ' + field + ' must stay inside resource_root');
  return inside.split(path.sep).join('/');
}

export function normalizePersona(persona) {
  if (!persona || !SLUG.test(persona.id ?? '')) throw new Error('PERSONA_CONTRACT_INVALID: id');
  if (typeof persona.resource_root !== 'string' || !persona.resource_root)
    throw new Error('PERSONA_CONTRACT_INVALID: resource_root');
  const root = persona.resource_root;
  const value = { ...persona };
  if (persona.model !== undefined) {
    value.model = relative(root, persona.model, 'model');
    let model;
    try { model = JSON.parse(fs.readFileSync(path.resolve(root, value.model), 'utf8')); }
    catch (error) { throw new Error('PERSONA_MODEL_UNREADABLE: ' + error.message); }
    if (model?.persona?.id !== persona.id)
      throw new Error(`PERSONA_ID_MISMATCH: model ${JSON.stringify(model?.persona?.id)} != registered ${JSON.stringify(persona.id)}`);
  }
  value.seeds = (persona.seeds ?? []).map((seed, index) => {
    if (!SLUG.test(seed?.slug ?? '') || typeof seed.kind !== 'string' || !seed.kind)
      throw new Error('PERSONA_CONTRACT_INVALID: seeds[' + index + ']');
    return { ...seed, path: relative(root, seed.path, 'seeds[' + index + '].path') };
  });
  if (new Set(value.seeds.map(seed => seed.slug)).size !== value.seeds.length)
    throw new Error('PERSONA_CONTRACT_INVALID: duplicate seed slug');
  value.jobs = (persona.jobs ?? []).map((job, index) => {
    if (!SLUG.test(job?.id ?? '') || job.runtime !== 'python' || !Number.isInteger(job.timeout_s) || job.timeout_s < 1
        || !Array.isArray(job.grants) || job.grants.some(grant => !GRANTS.has(grant))
        || !Array.isArray(job.sources) || job.sources.some(source => !SLUG.test(source)))
      throw new Error('PERSONA_CONTRACT_INVALID: jobs[' + index + ']');
    return { ...job, entry: relative(root, job.entry, 'jobs[' + index + '].entry') };
  });
  value.skill_directories = (persona.skill_directories ?? []).map((directory, index) =>
    relative(root, directory, 'skill_directories[' + index + ']'));
  // Deprecated v1 field: read-compatible until P7; a persona seed supersedes it.
  const personaSeed = value.seeds.find(seed => seed.kind === 'persona');
  if (persona.persona_file !== undefined) value.persona_file = relative(root, persona.persona_file, 'persona_file');
  else if (personaSeed) value.persona_file = personaSeed.path;
  if (!value.persona_file) throw new Error('PERSONA_CONTRACT_INVALID: a seed of kind persona is required');
  return Object.freeze(value);
}

/** Absolute paths for the worker, against the published artifact root when one is selected. */
export function resolvePersona(persona, root = persona.resource_root) {
  const at = file => path.join(root, file);
  return {
    ...persona, resource_root: root,
    model: persona.model ? at(persona.model) : null,
    seeds: persona.seeds.map(seed => ({ ...seed, path: at(seed.path) })),
    jobs: persona.jobs.map(job => ({ ...job, entry: at(job.entry) })),
    skill_directories: persona.skill_directories.map(at),
    persona_file: at(persona.persona_file),
  };
}
