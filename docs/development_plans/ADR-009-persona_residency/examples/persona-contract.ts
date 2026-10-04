/** ADR-009 persona contribution v2 — a proposed Asuna interface, NOT a DSH API.
 *
 * The core must run any package that satisfies this contract (a synthetic `demo`
 * persona is the reference fixture). Nothing here grants authorization: source
 * roots, heartbeat targets and canonical-person mappings come from the owner's
 * local (ignored) configuration, never from a package.
 */
export interface PersonaSeed {
  readonly slug: string;                 // doc:<persona>:<slug>
  readonly kind: 'persona' | 'voice' | 'dossier' | 'ledger' | 'working' | 'contract' | 'index' | string;
  readonly path: string;                 // relative to resource_root; markdown split on '##'
  readonly title?: string;
}

export interface PersonaJob {
  readonly id: string;
  readonly entry: string;                // relative to the PUBLISHED package artifact
  readonly runtime: 'python';
  readonly grants: ReadonlyArray<'persona_data.write' | 'probe'>;
  readonly sources: readonly string[];   // source-root ids; paths are resolved from owner local config
  readonly timeout_s: number;
}

/** Field names follow the existing snake_case registerPersona call (packages/<name>/src/index.js). */
export interface PersonaContributionV2 {
  readonly id: string;                   // stable persona id (existing records keep their id)
  readonly character_id: string;
  readonly display_name: string;
  readonly version: string;
  readonly resource_root: string;
  readonly model: string;                // persona model JSON, validated against persona-model.schema.json
  readonly seeds: readonly PersonaSeed[];
  readonly jobs?: readonly PersonaJob[];
  readonly skill_directories: readonly string[];
  readonly integration_directory?: string;
  readonly preset: string;               // thin role preset name
  /** @deprecated replaced by a seed of kind 'persona'; read-compatible in P1, removed in P7. */
  readonly persona_file?: string;
}

export interface PersonaRegistry {
  /** Throws (and leaves Core inert with a readable status) when the model fails validation. */
  registerPersona(contribution: PersonaContributionV2): () => void;
}

// Rules the implementation must keep:
// - Seeds only initialise missing document heads; package upgrades never overwrite live state.
// - A package must not default the private policy keys rhythm.timezone / rhythm.sleep_window.
// - Core code and prompts contain no persona name; everything persona-specific arrives here or
//   from persona-private data in MongoDB.
