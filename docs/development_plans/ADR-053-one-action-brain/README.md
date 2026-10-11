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

1. **A fresh context per task.** Each task starts its own action session; a continuation of the same task (her
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

## Consequences

- The model server holds one action context at a time instead of one per conversation; the warm prefix (system
  prompt and tool list) is shared by all tasks.
- The model sees tools a task may not use; a call to one is refused with the list of what it may use (as today),
  costing a step, not a breach.
- Old per-conversation action sessions stay as history; new tasks do not continue them.
