# ADR-053: Action brains: a context per task, an idle limit, and she is told

Status: **Approved 2026-10-12** (owner and Xiaoman), rewritten the same day after a correction: the action brain
already starts a fresh context for every task. Built 2026-10-12 (with the owner's widening of the development grant
to her own plans and trusted notes); live after her next restart.

## Context

The owner's open question (ADR-052): one action brain for all her conversations, or one each. Her home turn first
chose one shared brain, on the day's evidence: continuity bought nothing (three attempts to fetch original words
were all reruns; the one that carried on did so from a file on disk); database-wide jobs (one scanned more than
730,000 rows across 37 conversations) need a visible queue and an uninterrupted worker; the model server keeps about
7 conversations and switches about 3 quickly. The owner confirmed after weighing the leak between home and public,
with a guard rail: information cannot be fenced once it is in the action brain, tools can.

**Correction (2026-10-12).** The discussion assumed each conversation's action brain carried on from task to task.
It does not: an action session is keyed by the task (`execution_binding` = `task:<id>:<scope>:<epoch>:<revision>`,
`native_worker.action_session_id`), so every task already starts a fresh context, and only a continuation of the same
task (her follow-up words, a revision; `continues_task_id`) goes on in it. Measured: 260 action sessions for 257
distinct keys, none shared by two tasks. So, as built:

- Home and public never share an action context; no task sees another task's tool output.
- The owner's guard rail already holds: each task is shown only its own tools, and a call outside them is refused by
  the plugin's guard and by the worker's broker (`CAPABILITY_DENIED`). No refusal in the logs (262 action sessions)
  was of a tool the running task had.
- Tasks run one at a time (one action worker in `chat.py`), so a quick group request can wait behind a scan unseen.
- A report has already invented rows and platform ids that are not in the database.

What the evidence asked for is therefore not a shared brain but the rest of this ADR.

## Decision

1. **A context per task, as now.** One action context per task; a continuation of that task goes on in it.
2. **An idle limit on a continuation.** If the task's context has been idle longer than the action route's limit
   (`idleMinutes`, set in the settings with the route; 30 minutes when empty), the continuation starts a fresh
   context carrying the task's brief, its last report and her new words, and is told it is fresh: earlier tool output
   is gone, so what it needs it fetches again instead of recalling it from the report. Same rule on the local server
   and on any API. The limit is a cost setting, not a safety boundary.
3. **She is told, by the program (owner).** The result of handing a task over or adding to one says, in words, whether
   the action brain starts fresh or carries on (and, when fresh after the limit, that it has only the brief, the last
   report and her new words), and what is ahead of it in the queue (how many, from which conversation, running for
   how long). Decided once at hand-over and kept on the task, so what runs is what she was told; deterministic, not
   left to her remembering. Where (her ruling): in the tool result of `delegate` and of `message_action`, always, as
   the program's line; an empty queue says so explicitly ("前面没有排着的"), never by leaving the line out, which she
   would read as the feature not working.
4. **Refusals she can act on.** A refused tool says which kind of turn or conversation gives it and which does not
   here, and that retrying will not change it, so neither brain invents a motive (her case: three refusals she read
   as "only self-improvement turns have it"). One sentence for both layers (the plugin's guard and the worker's
   broker), from one table of which kinds of turn give which tools, so the two brains never get two versions to
   guess between (her ruling, the same rule as ADR-051's "both readers read the same").
5. **Reports stay with their sources.** A report says how much it scanned and from which root, and quotes rows as the
   tools returned them.
6. **Two rules, not one.** What a task may read stays bound to the conversation it came from; which turns hand over
   which tools stays decided by the kind of turn (ADR-051).

## Cache

A fresh context is not a new GPU slot: the server runs one request at a time either way. What it costs is parked
history in the server's 24 GiB budget (about 316 MiB plus 19.8 KiB a token per entry, least recently used out first).
The model server's session read the engine's source at the running commit and its log (2026-10-12):

- A request resumes only from an entry, or one of its checkpoints, that its prompt fully extends; checkpoints sit at
  the end of a long system prompt (the tool list renders inside it), at each assistant turn and every 16K tokens.
- **A context per task:** a new task resumes from the previous task's head checkpoint when the heads are the same;
  the previous task's branch is parked first as its own entry (a 40K task about 1.1 GiB), and the next task usually
  takes that entry and rewinds it (0.1–0.3 s). Steady state: about one dead task entry at a time. A task interrupted
  by one of her turns resumes its own parked branch: no re-reading per step.
- **One continued session** would grow by tens of thousands of tokens a task, its entry with it, and need compaction.
- **Pinning the head** (`strata_prefix`) keeps a whole task branch out of eviction for good. Not used.
- **`strata_checkpoint: false`** stops a request from leaving an entry but must be set before the request; only for
  truly one-shot requests. Her group relevance gates are about a fifth of all requests and each parks a ~0.3 GiB
  entry; marking them one-shot would free that at about 0.6 s per gate (outside this ADR; the owner's call).

## Any endpoint

The design must suit any OpenAI-compatible endpoint (DeepSeek and others), not only the local server: on an API
**time** decides what stays cached, on the local server **space**. A context per task suits both (the shared head is
cached by prefix on an API, by its checkpoint locally; no task carries another's history). Nothing here depends on one
server's request fields; a field only one server knows is sent only to a route configured to take it.

The idle limit is per route, from each provider's cache life, then tuned by measurement (a continuation's first step
records whether its history was still cached; neither kind of endpoint can say beforehand which histories it holds):

| Endpoint | How long an unused prefix lasts (its docs, 2026-10-12) | A cache hit costs |
|---|---|---|
| DeepSeek | best effort, "usually within a few hours to a few days" | about 2% of a miss |
| OpenAI, current models | at least 30 minutes after the last use | discounted |
| OpenAI, earlier models | about 5–10 minutes in memory (up to an hour), or the 24-hour option | discounted |
| Anthropic | 5 minutes by default, 1 hour as a paid option | 10% (writes cost extra) |
| The local server | until pushed out by space; her long conversations push entries out in 5–30 minutes | free |

## Consequences

- A continuation after the limit has only the brief, the last report and her new words. Her rule for herself (her
  words): she quotes in full what it needs, or says plainly to fetch it again; the program's line at hand-over (3)
  reminds her each time.
- Old action sessions stay as history.
