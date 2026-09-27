/** Proposed Asuna interface, NOT an existing DSH API.
 * This describes one installed resource contribution, not an authorization grant.
 * Preserve the running persona/state IDs through the existing binding layer.
 */
export interface PersonaContribution {
  readonly id: string;
  readonly displayName: string;
  readonly packageVersion: string;
  readonly resourceRoot: string;
  readonly defaults: Readonly<{
    characterCore?: string;
    currentSelf?: string;
    voice?: string;
  }>;
  readonly skillDirectories: readonly string[];
  readonly presetDirectory?: string;
}

/** One small registration boundary for Core, if it has no equivalent already. */
export interface PersonaContributions {
  register(contribution: PersonaContribution): () => void;
}

// Paths are metadata for the host to resolve within the installed contribution.
// Do not use a model-provided path or a persona ID to infer resource permissions.
// Current runtime self-state remains in existing state heads; defaults do not
// overwrite it on startup or package upgrade.
