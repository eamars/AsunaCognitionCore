/**
 * Steer in her role sessions (owner 2026-10-06). Her turn takes a person's words only at a turn's start, through
 * the worker, with the program's context (index.js, system-prompt/assemble); a message steered into a running
 * turn used to fail that turn. It now waits as the next turn instead, exactly where Queue would have put it.
 * Her program's own stage notes (source `asuna`) and platform lines keep their own delivery.
 * @param agent - the role session's agent (its durable inbox).
 * @param message - the message DSH just inserted.
 * @param busy - whether a stage of hers is unfinished in this session.
 * @returns whether the message was moved to the next turn.
 */
export function holdSteeredInput(agent, message, busy) {
  if (!busy || message?.source?.kind !== 'user' || message.source.channel) return false;
  if (!agent?.inbox?.nextStep?.some(item => item.id === message.id)) return false;
  agent.inbox.remove(message.id);
  agent.inbox.append('next-turn', message);
  return true;
}
