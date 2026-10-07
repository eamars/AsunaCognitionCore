/** Business validation around DSH's authoritative revisioned settings store. */
export function nativeRoute(route) {
  // The settings menu uses an empty value for the provider's own default.
  // DSH accepts an omitted effort, never an invented effort ID.
  if (!route) return route;
  const value = { ...route };
  if (!value.reasoningEffort) delete value.reasoningEffort;
  // An empty output limit is the model's own (resolveRoutes); it never overrides a request's limit with nothing.
  if (value.maxTokens === undefined) delete value.maxTokens;
  return value;
}

// A secret in the settings is a reference into DSH's credential store ({"$secret": "ASUNA_MONGO_URI"}), named like an
// environment variable; the value lives only in the store (ADR-010 D6). Matching is by substring, like the
// worker's redaction, so a key such as bot_token or apiKey cannot carry a value either.
const SECRET_KEY = /mongo_uri|api_?key|token|password|secret/i;
const REF = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function assertSecretReferences(value, path = []) {
  if (!value || typeof value !== 'object') return value;
  for (const [key, item] of Object.entries(value)) {
    if (key !== '$secret' && SECRET_KEY.test(key) && (typeof item === 'string' || (item && typeof item === 'object' && '$secret' in item))) {
      if (!item || typeof item !== 'object' || typeof item.$secret !== 'string' || Object.keys(item).length !== 1)
        throw new Error('USE_NATIVE_SECRET_REFERENCE: ' + [...path, key].join('/'));
      if (!REF.test(item.$secret)) throw new Error('INVALID_CREDENTIAL_REFERENCE: ' + [...path, key].join('/'));
    } else assertSecretReferences(item, [...path, key]);
  }
  return value;
}

/** Every credential reference the settings name, in order of appearance. */
export function secretReferences(value, out = new Set()) {
  if (!value || typeof value !== 'object') return [...out];
  if (typeof value.$secret === 'string' && Object.keys(value).length === 1) out.add(value.$secret);
  else for (const item of Object.values(value)) secretReferences(item, out);
  return [...out];
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
