# ADR-028: a conversation that no longer fits continues in a new session, carrying its last summary

Status: **Accepted and built** 2026-10-08. The owner chose the recovery; Claude decided the details under the
owner's delegation of development decisions.

## 1. Context

DSH's compaction (`dsh-compaction-basic`) summarizes the older part of a session when it passes the threshold
(her character preset: 0.80 of the 262,144-token window). Two of its properties decide what happens when one step is
large:

- The summary request replays the span it summarizes and reserves the summary's own output, without first checking
  that this fits the window.
- On a model request rejected with `CONTEXT_WINDOW_EXCEEDED` it tries one overflow compaction (`maxOverflowRetries`
  1). If that fails too, the original error ends the turn. There is no "drop the oldest" fallback; the summary-error
  hook only offloads pictures.

On 2026-10-05 her local session was at about 218k tokens when one turn's notice added about 43k. The summary request
no longer fit, the overflow retry failed the same way, and every later turn failed. The only remedy was a manual one:
stop the Host, give the scene a new `character_context`, restart. Navigation then opened an empty session and
archived the old one, so she lost everything the old session held in context, including the summaries DSH had
already made.

What bounds a step since then: the turn ceiling (ADR-014, now hard, 48,000 JSON characters), the thinking budget
(8,192 tokens for "high"), and the output cap. These make a repeat unlikely, not impossible: DSH's token estimate is
about half the real count for her text, and a session can still reach the window between two compactions.

The owner rejected overriding DSH's compaction (2026-10-05) and on 2026-10-08 chose, from four options, "Recover with
a carried summary": an overflow should cost one summary, not her whole context. They also asked what happens when a
bounded step still exceeds the window, which this recovery answers.

## 2. Decisions

- **D1 — Trigger.** A turn of her character brain in her main conversation for a scene ends with
  `CONTEXT_WINDOW_EXCEEDED` (the DSH error code, found on the error or its causes). That already means DSH's own
  overflow compaction failed for this turn, so the recovery starts at once instead of waiting for a second failed
  turn: waiting would cost another unanswered message and change nothing. Other lanes are out of scope: an action
  session belongs to one task, and the summary, attention and appraisal sessions are small and owned by the program.
- **D2 — What is carried.** The text of the old session's last `compaction/summary`, which DSH writes cumulatively:
  each summary also summarizes the checkpoint of the one before it, so the last one covers everything up to its span.
  No new model call: the recovery happens because a model request no longer fits, and asking the same model to
  summarize the same material in pieces would add a slow, fallible step while she is waiting to answer. What
  happened after that summary is not summarized; her recent messages come back through the program's own blocks
  (D4), and everything else stays in Mongo, readable through recall. A session that was never compacted carries
  no summary, and the notice says so.
- **D3 — The switch.** The scene gets a new `character_context`. A new main binding for that context replaces the
  old one; the old binding is retired, keeps an explicit `character_context`, and names the new session as its
  `successor_id`. Everything that resolves her conversation through `continued_session` (her turns, task feedback,
  consults, scheduled plans) reaches the new session; following a chain of successors, not one step. The Host creates
  the new session the way navigation does (title, workspace, no seed of the old events) and archives the old one
  once it is idle. A restart keeps the new session as the main one.
- **D4 — Re-delivery.** The stage that overflowed is sent again, once, to the new session, with the same notice. In a
  session with nothing in it, the notice brings the whole turn context again (recent history, memories, notes), as
  any first turn does. A second overflow there fails the turn normally; there is no loop.
- **D5 — The carried block.** The first notice in the new session carries a `carried_from_program` block: the summary
  and a note that her earlier conversation no longer fit, that this is the summary the old session last kept, and
  that older details are in her records. It is sent once (marked delivered after that stage succeeds), so it is not
  sent again when it scrolls out of the recent stretch. Its size is bounded by a new row in ADR-014's limits table
  (`CARRIED_CHARS` 12,000; the summaries her sessions kept so far are 2,200–6,000 characters); over it the text is
  cut with the same note as the turn ceiling's.
- **D6 — Work in progress.** A task whose action session was started under the old session keeps that session and
  its parent, so its native transcript stays whole; only its feedback goes to the new conversation. Tasks begun after
  the switch belong to the new session.

## 3. Consequences

- An overflow costs the verbatim context since the last compaction, not everything: she continues with her own last
  summary plus the program's recent history.
- The old session stays readable in the Web UI under archived conversations, read-only like any retired one.
- The owner, in the local chat, sees the old conversation leave the sidebar and a new one with the same title appear;
  the answer to the message that overflowed arrives in the new one.
- If DSH gains bounded summarization upstream, D1 simply stops firing.

## 4. As built

- `packages/cognition-core/src/index.js`: `agent/error` on a character session checks the error chain for
  `CONTEXT_WINDOW_EXCEEDED` and, if found, sends the stage result with `carry: {summary}` (the last
  `compaction/summary` text); the `carry_session` Host request (`carrySession`) prepares the new session through
  `organizeNativeWorkspaces`, announces it to the sidebar, and archives the old one once its agent is idle.
- `src/asuna/native_worker.py`: `ContextOverflow` (the stage's exception when a result carries `carry`);
  `NativeLane.generate` retries a character stage once after `BusinessWorker.carry_session` (new context, bindings,
  audit `native.context.carried`); `continued_session` follows the whole chain; `action_session_id` finds an action
  session under any session of the chain and keeps its parent; the carried block is added to the stage's context
  and marked delivered on success.
- `src/asuna/context_budget.py`: `CARRIED_CHARS`, `carried_block`.
- Tests: `tests/test_carried_session.py`, `packages/cognition-core/test/carry.test.js`. Current reference:
  [RUNTIME_API.md](../../../RUNTIME_API.md).
