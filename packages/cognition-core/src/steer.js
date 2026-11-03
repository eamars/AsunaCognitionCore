/**
 * Steer in her role sessions (owner 2026-10-06). Her turn takes a person's words only at a turn's start, through
 * the worker, with the program's context (index.js, system-prompt/assemble); a message steered into a running
 * turn used to fail that turn. It now waits as the next turn instead, exactly where Queue would have put it.
 * Her program's own stage notes (source `asuna`) and platform lines keep their own delivery.
 *
 * Running is DSH's own status, from the turn's claim to its end: her stage is admitted only after the worker has
 * built it, which can take minutes, and a step boundary in that time claims whatever was steered.
 * @param agent - the role session's agent (its status and durable inbox).
 * @param message - the message DSH just inserted.
 * @returns whether the message was moved to the next turn.
 */
export function holdSteeredInput(agent, message) {
  if (agent?.status !== 'running' || message?.source?.kind !== 'user' || message.source.channel) return false;
  if (!agent.inbox?.nextStep?.some(item => item.id === message.id)) return false;
  agent.inbox.remove(message.id);
  agent.inbox.append('next-turn', message);
  return true;
}
