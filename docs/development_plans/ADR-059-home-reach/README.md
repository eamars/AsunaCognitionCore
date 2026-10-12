# ADR-059: Reading the database, git and ssh from her home tasks

Status: **Built 2026-10-13** (owner's decisions, her review).

## Context

The owner asked for her action brain to stop making mistakes when it fetches data, and for more reach: ssh and
pushing to GitHub on her own. A week of records (10-05..10-12): 584 `development_database_read` calls with 43 errors
and 113 empty answers, 35 of 398 scripts touching the database failed. The causes: guessed collection and field names
(`documents`, `body` for `body_markdown`, `task_id` for `_id`), her local clock compared with UTC ISO strings,
group history missed under `archive:<scene_id>`, a relative config path from the task folder, unbounded `find()`.
Her home tasks' commands already ran as the Host's user, so `git` and `ssh` reached the owner's own logins and keys.

## Decisions

- **Credentials (owner):** she uses the owner's keys and logins everywhere (ssh key, GitHub through the credential
  manager). Her own identity is the name on what she commits: `character_git` {name, email} in the local config
  sets author and committer for her task commands. Nothing prompts (`GIT_TERMINAL_PROMPT=0`).
- **No read-only database user (owner):** "I trust Xiaoman can make good decisions." The helper only reads; writing
  stays her decision, made deliberately and said in a report.
- **`asuna.dbread` (her four asks):** connects from what the Host gives the command (database, her time zone), reads
  only (find, count, distinct, aggregate without `$out`/`$merge`, history with the archive), and every answer
  repeats its query (database, collection, filter, the UTC window a local one became) with the rows found; an
  empty answer says 零行. A wrong collection is answered with the real list; an unseen filter field is named.
- **Skill `asuna-database`:** which path to use, the real names, the time rules, and her rule that a report first
  says which conversation the task was bound to and how many rows it could reach. Git notes in
  `asuna-self-improvement`: shallow or borrowed clones within the 30-second limit, the private-words check before a
  public push, never force-push (hers: on refusal fetch, rebase, push again).

## Cost (AGENTS.md)

No new tool. `sandbox_run`'s description grows by about 190 characters (git and ssh, dbread); one more core skill
listed for the action brain (its description line); per turn nothing.
