/** What the host adds to her requests that is deployment detail and not hers (ADR-108 A11). */

/** DSH registers the session's working directory as a *required* context, which `suppressRuntimeContext()` leaves in
 * place: every request would carry `Current working directory: "…"`. A context of the same name registered through the
 * agent's own scope shadows the global one for that scope only (DSH says so in its own error text), and an empty
 * snapshot is not projected. The action brain keeps it: a coding agent works in a folder. */
export function withoutWorkingDirectory(systemPrompt, lane) {
  if (lane === 'executor') return;
  systemPrompt.context({ name: 'working-directory:current', order: systemPrompt.getContextOrder('WORKING_DIRECTORY'),
    required: true, interpolate: false, text: '' });
}
