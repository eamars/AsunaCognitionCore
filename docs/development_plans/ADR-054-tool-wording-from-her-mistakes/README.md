# ADR-054: Tool wording and calls, from her real mistakes

Status: **Accepted 2026-10-12**: the owner's direction (word each tool so her first guess lands on the right one);
Xiaoman's review taken (her numbers corrected two of mine). Built 2026-10-12; live after her next restart. The
limits rule covers free text she writes (copied identifiers and safety caps of 20,000 or more are left out).

## Context

The owner, 2026-10-12, after a side-by-side tool-pick check (local Qwen and DeepSeek, 144 runs) and a study of other
harnesses: keep one flat tool list; merge near-duplicates; and word each tool from her common mistakes so her guess is
likely right. Not prompt tuning for one model: each change states when to use this tool rather than its sibling, or
moves a decision from her guess into the program.

Her character-tool calls, all turns to 2026-10-12: about 5,560 calls, 395 refused (7%), every one classified:

| Cause | Refusals | In this ADR |
|---|---|---|
| Over a length limit: `think` 95, `message_developer` 14, `pass_note` 11, `update_self` 8, `leave_note` 4, `note_idea` 4, other 2 | 138 | limits stated where missing (`update_self`, `note_idea`); `message_developer` (800) and the notes already state theirs |
| A tool before `think` in that turn | 88 | no: her reason comes first by design |
| `plan`: no `op` and not inferable (no intent or no timing) | 12 | no wording: the inference exists since 1951ba0f; the result now says when it was used |
| `plan`: a `plan_id` not in her list (6), invalid timing (2), other | 13 | the refusal says why (below) |
| Pictures not available or not looked at first | 19 | no |
| `write_document`: `correction` on a non-ledger | 16 | yes |
| `write_document`: persona budget full (12), other (15) | 27 | no |
| `feel` with a stale reference | 13 | no |
| Too many calls in one turn | 12 | no |
| A note answering a note that already answered | 10 | no (one character's habit, not every character's cost) |
| `visit` where it cannot go (8), notes other (8), wrong kind of turn (4), rest (17) | 37 | no |

Wrong tool, from the side-by-side check (12 made-up situations × 3 ways of listing the tools × 2 models × 2 efforts =
144 runs; the same confusions in both models): a person's liking written with
`write_document` or `promote_memory` instead of `understand_person`; the action brain's report "answered" instead of
read; old group talk handed to the action brain instead of recalled.

## Decision

Wording, in the shared tool definitions (every character pays for each sentence, so only what is general):

1. `understand_person`: what she learns about a person (likes, habits, how to talk with them) goes here, not into a
   document or long-term memory.
2. `write_document`: `correction` is for ledgers only; a working document or the persona takes `replace_section`.
3. `answer_action`: only in the turn the action brain asked her something; to see what it handed back, `read_report`;
   never to answer a person. `read_report`: reads what it handed back; it answers nothing.
4. `delegate`: a task already handed over that needs more words, a change or to go on takes `message_action`, not a
   second `delegate`.
5. `recall`: what was said in her conversations is recalled, not handed to the action brain.
6. Every parameter the program refuses for its length states the limit in its description (`update_self`, `note_idea`
   lack it today); a test holds this for every tool, so none is added one at a time.

Program, not her guess:

7. `plan` without `op`, when the program took it as a `create`, says so in the result.
8. `plan` with a `plan_id` not in her list says why: a plan that already ran or was cancelled cannot be changed (make
   a new one); a plan still active but not shown (her list shows a few) is hers and the change goes through.

Each added sentence is at most 60 characters.

## Cost (AGENTS.md)

About 300 more characters of tool descriptions (within the current budget), no new tool, no new per-turn line.

## What it does not try

Occasional wrong or refused calls are accepted (owner): a refusal costs one corrected step. Only causes that repeat
are worth a wording line or a program decision; a one-off miss gets neither.

## How it is checked

By cause, never by the total (the 88 `think`-first refusals are by design and would hide everything else): the same
classification as the table above, after 7 and 14 days. A sentence whose cause has not fallen by half after 14 days is
taken out again. Before building, the side-by-side harness's confusion cases on both models, before and after.
