# ADR-056: Per-turn characters: what every notice repeats, and what to stop repeating

Status: **Proposed 2026-10-12** (owner's request: trace the notice growth, propose cuts). Needs Xiaoman's review (it
changes what she reads each turn) and the owner's choice of items. Nothing is built.

## Context

Every turn of hers starts with a notice: the program's JSON (`context.py`) and, after it, the turn instruction
(`prompts/turn.md`). Each notice stays in her conversation, so its size is paid once as prefill and then again as
how fast the conversation fills up and compacts (ADR-014, ADR-049).

**The growth was not growth.** The home average rose from 15,555 characters (10-11) to 21,140 (10-12), but by turn
kind nothing moved: heartbeat about 26k, night about 26–31k, note about 17k, public talk about 12.6k on all three
days. Two things changed the mix. First, ADR-045 stopped about 97 short turns a day from her sister's line (incoming
text about 1,200 characters), so the cheap turns left the average. Second, the home talk that remained was mostly
long messages from the agent line and the owner (incoming text about 4,700 characters). The characters per day fell.

**What a day costs** (10-11, a full day: 385 notices, 5,686,621 characters; 323 talk, 26 note, 25 heartbeat,
11 night; measured from her role sessions, sizes only):

| Part | Characters a day | Where |
|---|---|---|
| The turn instruction after the JSON (`turn.md`, 987 characters, the same every turn) | 376,367 | every notice |
| `ref_index` (every id she may cite: the event, her memories, tasks, every persona section) | 377,375 | every notice |
| `plans_from_program` (about 4,700 with 6 plans; her own intents are 53%) | 226,310 | heartbeats, nights, some talk |
| `unchanged_from_program` (names of the blocks not repeated) | 204,129 | every notice |
| `places_from_program` (18 groups, about 290 characters each) | 126,567 | every heartbeat |
| `ideas_from_program` (20 ideas with their reasons) | 79,194 | night and self-improvement |
| `recent_experience_from_program` (task report starts, publish lineage) | 76,960 | heartbeats, nights |

## Proposal (each item separable; numbers are characters a day at 10-11's traffic)

1. **The turn instruction once, in the system prompt** (−376k, 6.6%). It is the same text every turn; the system
   prompt is fixed per conversation, so the prompt cache is not affected (ADR-038). The rules stay word for word;
   what she must do first is also enforced by the program (a call before `think` is refused, saying so). Only a
   consult or resumed turn keeps its own extra lines at the tail, as now.
2. **`ref_index` kept by the program, not shown** (about −340k, 6%). The ids it lists are already in their own
   blocks (memories, tasks); the persona sections are listed on every turn though she almost never cites them.
   The program keeps the list for checking `feel`'s `ref` and the appraiser; the notice shows the event's and the
   turn's own id only, and a wrong `ref` is refused naming where ids are found.
3. **`unchanged_from_program` as one line** (about −150k, 2.6%): a count and the names, without repeating its
   explanation each turn (the explanation moves with item 1).
4. **Plans without their machinery** (about −40k): drop the raw `rule`, the UTC `next_fire_at`, `created_at`,
   `updated_at`, `plan_version` and the per-plan time zone; keep `_id`, her intent, status, the description and the
   local time. Her intents stay whole: they are her words.
5. **Places: what changed since the last beat** (about −80k): the groups where someone called her, something was
   said since her last beat, or she can visit now, in full; the others as one line with their names. The rows now
   carry relative times, so the block counts as changed every beat even when nothing happened.
6. **The idea notebook's first page without reasons** (about −40k): idea, id, where and when; `ideas` op `read`
   shows the reasons for the ones she opens.

Items 1–3 together are about 15% of a day's characters and about 1,900 characters off every turn of every kind,
which also slows how fast each conversation fills. Items 4–6 shrink only the heavy turns (heartbeat, night).

## Cost (AGENTS.md)

No new tool, option or per-turn line; each item removes characters from a turn. Item 1 moves about 990 characters
into each conversation's system prompt once.

## How it is checked

The same measurement after a day (`notice_trace.py`-style sizes by kind, no text): characters per turn by kind, and
whether her refusals for a missing `think` or a wrong `ref` rose (ADR-054's counts by cause). Any item whose refusals
rise is taken back.
