# ADR-053: Action brains: one per conversation, discarded when idle; a visible queue; tools fenced per task

Status: **Approved 2026-10-12**, revised the same day by the owner (keep one action brain per conversation, discard
it when idle) after the cache review; the tool fence is the owner's guard rail. Xiaoman chose one shared brain first;
her agreement to the revision is pending. Not built.

## Context

The owner's open question (ADR-052): one action brain for all her conversations, or one each. Her home turn chose one,
on the day's evidence:

- Continuity bought nothing: three attempts to fetch original words were all reruns; the one that carried on did so
  from a file on disk.
- Database-wide jobs (one scanned more than 730,000 rows across 37 conversations) are the heavy work; quick group
  requests must not wait behind them unseen.
- The model server keeps about 7 conversations and switches about 3 quickly; contexts the action brain does not hold
  can go to her conversations.

What exists:

- One action session per (conversation × speaker), continued from task to task (`native_worker.action_session_id`).
- Tasks already run one at a time (one action worker in `chat.py`).
- The action brain's system prompt is `executor.md` plus her values for the conversation's class (owner-private or
  public); the task's brief is its first message.
- Each task carries its own `allowed_capabilities`, decided by where it was asked and by whom (class, grants,
  kind of turn). Today the model is shown only those tools, and a call outside them is refused twice, by the plugin's
  guard and by the worker's broker (`CAPABILITY_DENIED`).
- A report has already invented rows and platform ids that are not in the database.

## Decision

Revised by the owner the same day, after the cache review below: keep one action brain per conversation as today,
and let it drop its history after an idle limit. That is a smaller change and does nearly what one shared brain
would: measured over 7 days (256 tasks), when a task started, one conversation had used the action brain in the
past 30 minutes in 61% of cases, two in 35%, three in 4%; with the limit, at most two or three action histories are
alive at once, and none outlives its use. Home and public never share one.

1. **One action brain per conversation, discarded when idle.** A conversation's action context carries on from task
   to task while it is in use; once it has been idle longer than the route's limit (default 30 minutes, tuned per
   route from measurement, below), the next task there starts a fresh context, carrying the task's brief, and for a
   continuation its last report and her new words. What must carry over longer, she writes to disk herself. Same
   rule on the local server and on any API.
2. **One queue, visible.** Tasks still run one at a time. When she hands one over she is told what is ahead of it (how
   many, which conversation, long or short), so a quick group request is not stuck behind a scan without her knowing.
3. **Tools fenced per task (the owner's guard rail), one tool list per context.** The tool list a context is shown
   stays the same from task to task (the tool list is part of the cached head: today 71 of 241 consecutive tasks in
   one conversation changed it, which makes the whole carried context read cold again); which tools this task may
   use is said in text at its start and enforced by the program as today (the plugin's guard and the broker). A task
   from a public conversation cannot run commands, develop, use integrations or anything else the class does not
   give, whatever it reads.
4. **Reports stay with their sources.** A report says how much it scanned and from which root, and quotes rows as the
   tools returned them (the invented rows above).
5. **Two rules, not one.** What a task may read stays bound to the conversation it came from; which turns hand over
   which tools stays decided by the kind of turn (ADR-051).

Dropped from the first draft: a fresh context for every task and one system prompt for all (a conversation's class
does not change, so its system prompt is already stable).

## Cache (the owner's concern, 2026-10-12)

A fresh context is not a new GPU slot: the server runs one request at a time either way. What it costs is parked
history in the server's 24 GiB budget (about 316 MiB plus 19.8 KiB a token per entry, least recently used out first).
The model server's session read the engine's source at the running commit and its log (2026-10-12):

- A request resumes only from an entry, or one of its checkpoints, that its prompt fully extends; checkpoints sit at
  the end of a long system prompt (the tool list renders inside it), at each assistant turn and every 16K tokens.
- **Fresh per task:** the next task resumes from the previous task's head checkpoint; the previous task's branch is
  parked first as its own entry (a 40K task about 1.1 GiB), and the next task usually takes that entry and rewinds it
  (0.1–0.3 s). Steady state: about one dead task entry at a time; if her conversations push it out, the next task
  reads the ~15K head again (about 2.5 s). A task interrupted by one of her turns resumes its own parked branch: no
  re-reading per step.
- **One continued session:** grows by tens of thousands of tokens a task, its entry with it; needs compaction; every
  task carries the earlier ones. Worse.
- **Pinning the head** (`strata_prefix`): keeps a whole task branch out of eviction for good and only helps
  back-to-back tasks, which already resume cheaply. Not used.
- **`strata_checkpoint: false`** stops a request from leaving an entry, but must be set before the request, and a
  task's last step is known only afterwards; on every step it would make each step re-read the task. Used only for
  truly one-shot requests.

The review's answer at the time: fresh per task, no pin; the owner's revision (Decision) keeps a conversation's
context while in use instead, which on this server costs one entry per conversation used within the idle limit,
replaced in place as the context grows, and nothing once the limit passes. No pin either way. A related saving outside this ADR: her group relevance gates are about a fifth of all
requests and each parks a ~0.3 GiB entry; marking them one-shot would free that at about 0.6 s per gate.

## Any endpoint, and an idle limit (owner, 2026-10-12)

The design must suit any OpenAI-compatible endpoint (DeepSeek and others), not only the local server. Such an API is
taken to cache without a space limit, as long as an entry has not expired: there **time** decides what is cached; on
the local server **space** does. Nothing here depends on one server's request fields.

- **An idle limit for an action context (the owner's idea), 30 minutes by default.** A conversation's action
  context goes on only if it was used within the limit; otherwise the next task starts a fresh one, carrying its
  brief (and for a continuation the last report and her new words). After that
  long both kinds of endpoint have most likely dropped the cache, so carrying on would read the whole old context
  cold, at full price and with no benefit over a shorter fresh start. The limit is one setting, not tied to a model.
- **The limit is set per route, from measurement (owner: on the local server space matters more than time).**
  Knowing directly whether a task's history is still held is not possible: the local server reports only totals
  (entries, bytes, evictions), not which histories it holds, and an API reports nothing ahead of a request. Both
  report afterwards how much of a prompt came from cache. So each route has its own idle limit (default 30 minutes),
  and a continuation's first step records whether its history was still there; the limit is tuned from that record
  (on the local server, where her long conversations push entries out within 5–30 minutes, it will likely end up
  shorter). Guessing wrong costs seconds either way: continuing a dropped history reads the task cold, starting
  fresh needlessly loses the task's detailed tool output.
- **What providers say (their docs, 2026-10-12).** Every one drops an unused prefix after a while, and use refreshes
  it; the while differs by an order of magnitude, so the limit cannot be one number:

  | Endpoint | How long an unused prefix lasts | A cache hit costs |
  |---|---|---|
  | DeepSeek | best effort, "usually within a few hours to a few days" | about 2% of a miss |
  | OpenAI, current models | at least 30 minutes after the last use (a `30m` setting) | discounted |
  | OpenAI, earlier models | about 5–10 minutes in memory (up to an hour), or the 24-hour option | discounted |
  | Anthropic | 5 minutes by default, 1 hour as a paid option | 10% (writes cost extra) |
  | The local server | until pushed out by space; her long conversations push entries out in 5–30 minutes | free |

  Each route's default follows its provider (an API that keeps prefixes for hours gets a longer limit; one that keeps
  them for minutes a shorter one), then the measurement tunes it.
- **Server-specific savings stay optional.** A field only one server knows (the local server's one-shot flag for her
  group gates) is sent only to a route configured to take it; every other endpoint never sees it.

## Consequences

- The model server holds at most the action contexts used in the last idle period (measured: usually one or two)
  instead of every conversation's, each with a head that stays the same from task to task.
- The model sees tools a task may not use; a call to one is refused with the list of what it may use (as today),
  costing a step, not a breach.
- An action session idle past the limit stays as history; the next task in that conversation starts a new one.
