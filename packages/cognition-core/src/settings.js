/** Business validation around DSH's authoritative revisioned settings store. */
export function nativeRoute(route) {
  // The settings menu uses an empty value for the provider's own default.
  // DSH accepts an omitted effort, never an invented effort ID.
  if (!route) return route;
  const value = { ...route };
  if (!value.reasoningEffort) delete value.reasoningEffort;
  return value;
}

export function assertSecretReferences(value, path = []) {
  if (!value || typeof value !== 'object') return value;
  for (const [key, item] of Object.entries(value)) {
    if (['mongo_uri', 'api_key', 'token', 'password', 'secret', 'access_token'].includes(key.toLowerCase())) {
      if (!item || typeof item !== 'object' || typeof item.$secret !== 'string' || Object.keys(item).length !== 1)
        throw new Error('USE_NATIVE_SECRET_REFERENCE: ' + [...path, key].join('/'));
    } else assertSecretReferences(item, [...path, key]);
  }
  return value;
}

export function editSettings(current, ops, base = {}) {
  const next = structuredClone(current);
  for (const op of ops) {
    if (!['set', 'unset'].includes(op.op) || !Array.isArray(op.path) || !op.path.length
        || op.path.some(key => typeof key !== 'string' || ['__proto__', 'constructor', 'prototype'].includes(key)))
      throw new Error('INVALID_SETTINGS_EDIT');
    let parent = next, inherited = base;
    for (const key of op.path.slice(0, -1)) {
      parent = parent[key] ??= {}; inherited = inherited?.[key];
    }
    const key = op.path.at(-1);
    if (op.op === 'set') parent[key] = structuredClone(op.value);
    else if (inherited && Object.hasOwn(inherited, key)) parent[key] = structuredClone(inherited[key]);
    else delete parent[key];
  }
  return next;
}
