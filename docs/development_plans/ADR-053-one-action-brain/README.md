# ADR-053: One action brain: a shared queue, a fresh context per task, tools fenced per task

Status: **Approved 2026-10-12**: her decision (home turn), the owner confirmed after weighing the leak between home
and public; the tool fence is the owner's guard rail. Not built.

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

1. **A fresh context per task** (cache: see below). Each task starts its own action session; a continuation of the same task (her
   follow-up words, a revision) stays in it. Nothing of an earlier task's tool output is in a later task's context, so
   home results do not ride along into a group's task. What must carry over, she writes to disk herself.
2. **One queue, visible.** Tasks still run one at a time. When she hands one over she is told what is ahead of it (how
   many, which conversation, long or short), so a quick group request is not stuck behind a scan without her knowing.
3. **Tools fenced per task (the owner's guard rail).** Information cannot be fenced once it is in the action brain;
   tools can. The tool list the model is shown is the same for every task (cache: every task shares one warm
   prefix); which of them this task may use is said in text at the start of the task, by the conversation it came
   from, and enforced by the program as today (the plugin's guard and the broker). A task from a public conversation
   cannot run commands, develop, use integrations or anything else the class does not give, whatever it reads.
4. **One system prompt.** `executor.md` is the same for every task; the class's values move into the task's opening
   text, next to its tool list, so the shared prefix is the same for home and public tasks.
5. **Reports stay with their sources.** A report says how much it scanned and from which root, and quotes rows as the
   tools returned them (the invented rows above).
6. **Two rules, not one.** What a task may read stays bound to the conversation it came from; which turns hand over
   which tools stays decided by the kind of turn (ADR-051). Sharing the queue changes neither.

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

Decision: fresh per task, no pin. (4) matters here: home and public tasks share the head checkpoint only if their
system prompts are identical. A related saving outside this ADR: her group relevance gates are about a fifth of all
requests and each parks a ~0.3 GiB entry; marking them one-shot would free that at about 0.6 s per gate.

## Any endpoint, and an idle limit (owner, 2026-10-12)

The design must suit any OpenAI-compatible endpoint (DeepSeek and others), not only the local server. Such an API is
taken to cache without a space limit, as long as an entry has not expired: there **time** decides what is cached; on
the local server **space** does. Nothing here depends on one server's request fields.

- **Fresh per task suits both.** Every task starts with the same head (one system prompt, one tool list), which an
  API caches by prefix and the local server by its head checkpoint; a task's prompt carries no earlier task, so an
  API bills fewer input tokens per step and the local server holds at most one leftover task entry.
- **An idle limit for an action context (the owner's idea), 30 minutes by default.** A continuation of a task (her
  follow-up, a revision) goes on in the task's own context only if that context was used within the limit;
  otherwise it starts a fresh context that carries the task's brief, its last report and her new words. After that
  long both kinds of endpoint have most likely dropped the cache, so carrying on would read the whole old context
  cold, at full price and with no benefit over a shorter fresh start. The limit is one setting, not tied to a model.
- **Server-specific savings stay optional.** A field only one server knows (the local server's one-shot flag for her
  group gates) is sent only to a route configured to take it; every other endpoint never sees it.

## Consequences

- The model server holds one action context at a time instead of one per conversation; the warm prefix (system
  prompt and tool list) is shared by all tasks.
- The model sees tools a task may not use; a call to one is refused with the list of what it may use (as today),
  costing a step, not a breach.
- Old per-conversation action sessions stay as history; new tasks do not continue them.
