# ADR-030: a program watchdog catches a handover between the brains that failed

Status: **Accepted and built 2026-10-09; live check waits for the owner's restart.** The owner set the direction and the constraints (catch the failure
mode only; cheapest and most deterministic; the clock starts when the action brain starts; legitimate slowness is
not a failure). Claude and Xiaoman agreed the design below.

## 1. Context

When the character brain delegates work, the action brain runs it and its report is handed back to her in a turn of
her own (`TaskService.feedback`). That hand-back is one attempt, queued in the worker's memory. Three times it failed,
each for a different reason, and each time she was never told:

| When (UTC) | Cause |
|---|---|
| 2026-09-24 | The DSH bridge had no listener for the session (`NO_DURABLE_SESSION_LISTENER`) |
| 2026-10-05 | Her turn on the result overflowed the model's context |
| 2026-10-08 | The result held a BSON value that could not be written as JSON (fixed in a2dd70ba) |

A Host restart has the same effect without an error: the queued hand-back is in memory and is lost. Finished tasks
were then paused, and her task list showed raw fields (`PAUSED`, `host_restart`), which she read as "waiting for the
owner" and left alone.

The broken invariant: **a handover that was started is either completed or someone is told it was not.** Nothing
enforced it.

Measured on 2026-10-09 (115 tasks with times, 144 action sessions):

- Tasks finish with a median of 3.4 minutes; 66% within 5, 94% within 10, all within 14.
- 9 of 115 tasks queued behind another (one task runs at a time), for at most 4.4 minutes.
- Inside a running action turn, the longest silence was 172 seconds, always the model queueing or prefilling before
  its first output (one executor model shared by both brains). Longer silences occur only between runs.
- The action brain's lease is renewed every 30 seconds while it waits on the model and on every tool step; it
  expires after 10 minutes without renewal. Model calls end after the provider idle timeout (30 minutes).
- `ask_character` is synchronous: her answer turn runs inside the action brain's tool call, and a failure comes
  back to the action brain at once as a tool error that tells it to use its own judgement and say so in its report.

## 2. Decision

**D1. A program watchdog, not her.** A sweep in the worker reads task state from the database. It costs no model
call and decides the same way every time. In normal operation it finds nothing and does nothing: no turn, no
message, no record. She is never woken to hear that something is still running.

**D2. Only definite failures count; slowness is not one.** Wall-clock age is not a failure signal: one executor model
serves both brains, so queueing and context switches make legitimate runs slow. The watchdog acts on two states only:

- *A result was lost on its way back.* The task finished (`RETURNED`, `BLOCKED`, `DONE`, `PARTIAL`,
  `NEEDS_CHARACTER_DECISION`, `UNKNOWN`), its hand-back has not been taken (`feedback_state` is not `DELIVERED` or
  `WAITING_TASK`), and its hand-back is neither queued nor running in this worker. Queue membership, not time,
  decides, so a hand-back waiting behind her other turns is never mistaken for a lost one.
- *A run was orphaned.* The task is `RUNNING`, its lease has expired, and this worker is not running it. It is
  closed as `BLOCKED` with what it had done so far, and its result is handed back like any other.

**D3. The clock starts when the run starts.** `claim` records `started_at`. A queued task has no clock.

**D4. What a lost result gets, by cause.** The cause is recorded where the failure happens, so the watchdog never
guesses it:

- `report`: the hand-back failed before her turn (building it, or reaching her session). Hand back the full result
  again, once. If that fails, hand back the short version.
- `turn`: her turn on the result failed (for example her context overflowed after ADR-028's one carried rerun).
  Hand back the short version directly: resending the full result would likely fail the same way.
- `restart`: the hand-back was lost without an error (the worker restarted). Hand back the full result.

The short version holds her brief, the report text and when the run finished, with no tool records. A report
longer than the short version's limit is cut, and the cut is stated in words, so she never takes part of a report
for all of it. If the short version fails too, the program leaves the developer a note in `developer_inbox` and
stops. The thread's card shows each step: handing, taken, or missed with its cause.

**D5. One sweep per worker.** It runs every minute in the worker that owns the Host, first one minute after start
(never during start-up). The durable part is the task state in MongoDB, which survives a restart; the sweep only
reads it, so it needs no timer of its own that survives a restart. One sweep per worker, not one DSH schedule per
delegation: per-task schedules would add a DSH task-page row and a scheduler-session message for every delegation.

**D6. Restart.** A finished task is no longer paused at start-up: its result counts as lost (`restart`) and the
first sweep hands it over. An unfinished task is still paused until the owner asks for it to continue, as before.

**D7. Her task list in words.** `task_state_from_program` gives each task one phrase instead of raw `state`,
`feedback_state`, `pause_reason` and `cancel_reason`: queued, running, finished and the result is with her,
finished and the result is still on its way to her, finished and could not be handed over (the developer was told),
stopped at a restart before finishing, not finished, stopped. A task carried on by a later one points to the later one, which is the one to go by (two runs of one task otherwise read alike). Her summary of what she did in her other conversations uses the same phrases.

**D8. Every handover.** All delegations use one task path (`delegate` and `message_action` continuations, in every
scene, including her self-improvement and heartbeat turns), so D1–D7 cover all of them. `ask_character` needs no
watchdog: it is synchronous, and its failure already reaches the action brain as an error.

## 3. Consequences

- Normal operation is unchanged and costs nothing more.
- A lost result reaches her within about two minutes, or within the first sweep after a restart.
- A result can reach her twice only if a hand-back is retried after her turn on it committed but before the task
  recorded it; `feedback` already treats an episode that exists for the task as the same hand-back.
- Two finished tasks paused before this change (`PAUSED` with a finished `paused_state`) are settled by hand once:
  one result already reached her through its continuation.

## 4. Not decided here

- Whether a stalled but alive run (lease renewed, no progress) should ever wake her. Nothing like it has been seen;
  the provider idle timeout bounds a hung model call.

## 5. Implementation (2026-10-09)

- `src/asuna/handover.py`: the rules (lost, orphaned, next step by cause, cause for the card, her task-list phrases).
- `chat.py`: `hand_back` (one queue entry per task, tracked while on its way), the `asuna-handover-watchdog` thread and
  `sweep`; a failed hand-back records its failure (or closes its failed turn) and no longer marks the asking line failed.
- `tasks.py`: `claim` records `started_at`; `feedback(short, again)`; `_short_event`; `record_handback_failure`;
  `give_up_handback`; `close_orphan`; a result whose scene changed is settled as `SUPPRESSED` instead of retried. The
  full hand-back also carries when the run finished.
- `host.py`: finished tasks are not paused at start-up; the watchdog thread starts with the other workers.
- `context.py`: `task_state_from_program` carries one `status` phrase per task and lists every finished task whose
  result has not reached her; `role_tools.exposed` reads task state from the database.
- `developer_inbox.py`: the program's notes (`source.by: program`) count against none of her limits and are not
  shown to her as hers.
- The card (`client.js`) shows a retry, a short-version hand-back and the final miss, in each UI language.
- Tests: `tests/test_handover_watchdog.py` (normal operation costs nothing; queued and slow work left alone; restart;
  full → short → developer; failed turn → short; orphan; changed scene; task-list phrases).
- The two finished tasks paused before this change were settled by hand: one as delivered (its continuation reached
  her), one returned to "finished, not yet handed back" for the watchdog.
