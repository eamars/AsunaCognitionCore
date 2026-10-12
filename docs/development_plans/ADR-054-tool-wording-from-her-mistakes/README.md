# ADR-054: Tool wording and calls, from her real mistakes

Status: **Draft 2026-10-12**: the owner's direction (word each tool so her first guess lands on the right one); her
review pending. Not built.

## Context

The owner, 2026-10-12, after a side-by-side tool-pick check (local Qwen and DeepSeek, 144 runs) and a study of other
harnesses: keep one flat tool list; merge near-duplicates; and word each tool from her common mistakes so her guess is
likely right. Not prompt tuning for one model: each change states when to use this tool rather than its sibling, or
moves a decision from her guess into the program.

Her character-tool calls, all turns to 2026-10-12: 5,557 calls, 394 refused (7%). By cause:

- Called before `think` in that turn: about 80, across most tools. By design (her reason comes first); the refusal
  says so and she corrects at once. Unchanged.
- Over a length limit: `think` 94 (the limit is in its description), `message_developer` 14 of 54 calls (no limit
  in its description), `update_self` 8, `note_idea` 4, notes 5.
- `plan` without `op`: 12.
- `write_document` with `correction` on a document that is not a ledger: 16.
- A note answering a note that was already an answer: 10.
- Elsewhere: `visit` where it cannot go (7), `feel` with a stale reference (7).

Wrong tool, from the side-by-side check (the same confusions in both models): a person's liking written with
`write_document` or `promote_memory` instead of `understand_person`; the action brain's report "answered" instead of
read; old group talk handed to the action brain instead of recalled.

## Decision

Wording: each confusable tool says in one sentence when to use it rather than its sibling, and states its length
limit where it has one:

1. `understand_person`: what she learns about a person (likes, habits, how to talk with them) goes here, not into a
   document or long-term memory.
2. `write_document`: `correction` is for ledgers only; a working document or the persona takes `replace_section`.
3. `answer_action`: only in the turn the action brain asked her something; to see what it handed back, `read_report`;
   never to answer a person. `read_report`: reads what it handed back; it answers nothing.
4. `delegate`: a task already handed over that needs more words, a change or to go on takes `message_action`, not a
   second `delegate`.
5. `recall`: what was said in her conversations is recalled, not handed to the action brain, unless it needs counting
   or a full search across many conversations.
6. `pass_note` / `leave_note`: a note that is itself an answer needs no answer.
7. Length limits in the description of `message_developer`, `update_self`, `note_idea` and the notes, as `think` has.

Program, not her guess (deterministic, said back in the result as `tool_args.py` already does for the action
brain's tools):

8. `plan` without `op`: with `intent` and one timing and no `plan_id` it is a `create`; the result says so. With a
   `plan_id` the refusal stays (update or cancel cannot be guessed).

## Cost (AGENTS.md)

About 500 more characters of tool descriptions in her character brain (budget raised in the same change), no new
tool, no new per-turn line. One fewer refusal round for each `plan` call without `op`.

## What it does not try

Occasional wrong or refused calls are accepted (owner): a refusal costs one corrected step. Only causes that repeat
are worth a wording line or a program decision; a one-off miss gets neither.

## How it is checked

Before and after, on the same cases: the side-by-side harness's confusion cases on both models; then her refusal rate
and the causes above over the following week against the 7% here.
