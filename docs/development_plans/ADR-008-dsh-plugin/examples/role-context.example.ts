/** Wiring example only; compile against the user's fixed DSH packages in P0.
 * No fictional DSH persona service is used here.
 */
import type { Context } from '@deepseek-ai/cordis';
import { PERSONA_PREFIX_SECTION } from '@deepseek-ai/dsh-system-prompt';

export interface PreparedRoleText {
  /** Stable installed/selected character material; no technical tool transcript. */
  readonly coreText: string;
  /** Current authorised self/relationship/scene snapshot, prepared outside render. */
  readonly currentText: string;
}

export function installRoleText(
  agentContext: Context,
  getPrepared: () => PreparedRoleText,
  dynamicOrder: number,
): () => void {
  // Call once in the genuine ROLE agent's scoped setup, not at global Host scope.
  const removeCore = agentContext.systemPrompt.section({
    name: PERSONA_PREFIX_SECTION,
    order: agentContext.systemPrompt.getSectionOrder('DEPLOYMENT_PERSONA_PREFIX'),
    text: () => getPrepared().coreText,
  });
  const removeCurrent = agentContext.systemPrompt.context({
    name: 'asuna:role-current',
    order: dynamicOrder,
    text: () => getPrepared().currentText,
  });
  // Respect Cordis scope lifetime as well as explicit disposal by the owner.
  return () => { removeCurrent(); removeCore(); };
}

// This scoped prefix shadows the global deployment persona. Mount it only if
// the same ROLE scope does not already own that prefix; reuse its owner otherwise.
// Do not add a second complete prompt or globally erase DSH tool guidance. This example does not
// define phase order, fetch Mongo, fabricate history, or police role output.
