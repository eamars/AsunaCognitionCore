# ADR-070: Her weekly tooling review

Status: **Proposed 2026-10-16** (the owner's direction, drafted by Claude); **her review the same day (agrees, with
five changes, all in below)**; waits for the owner's approval before anything is built.

## Context

ADR-060 and ADR-069 were reviews of her tools that a developer started: Claude measured her calls, drafted a proposal,
she reviewed it, the owner approved. Each found real things (198 refusals in 2.4 days, a tool nothing needed, old names
she had stopped using), and each also showed that she judges her tools better than a reading does: `await_answer` and
`attach_image` had no calls in two days and were kept because a channel without `speak` still needs them.

The owner's direction (2026-10-16): the review becomes her own job, every week. Not only what she did, but a proposal
for the next stage: what can be added, removed or reshaped. Flexible and creative, not a fixed checklist.

What she already has, and this builds on:

- `self_review_from_program` (ADR-058): her day in raw readings with their sources, in a heartbeat that rolled self
  evaluation. Her rule from that review: readings, not a summary.
- `memory_week_from_program` (ADR-062): her weekly reading of her memory, in a self-evaluation turn, at most once a
  week.
- Her `ask` to the developer's line, her `ideas` notebook, her skills, and her action brain, which can read the audit
  (`development_database_read`) when she wants to look deeper than the readings go.

## Decision

1. **The seat.** A self-evaluation turn carries `tools_week_from_program` at most once a week, beside her memory week
   (same rule: none when shown within the last 7 days). **A floor**: when 9 days have passed without it (its week, and
   two days more for the roll to come by itself), the next heartbeat that reaches her carries it, whatever it rolled.
   Self evaluation is a roll of the dice: in the 7 days to 2026-10-16 it came 6 times in 68 rolls, all between 10-12
   and 10-14; "at most once a week" alone keeps it from coming too often, not from never coming.
2. **The readings** (the program's numbers, never her retelling of them; the last 7 days, the week before beside them).
   **Every reading names its source**: the block ends with one line per reading saying which collection, which filter
   and which window it was counted from, so she can count it again herself and compare like with like (a number without
   its denominator cannot be compared: Claude's 5.6% think rate of 2026-10-16 had to be withdrawn for that reason).
   A limit a reading refers to (the calls-per-turn cap, a text's length) is shown at its current value, not a number
   written into the text:
   - **calls**: each tool and option she called, how many times; the listed ones she never called;
   - **refused**: per tool, the refusals grouped by what was wrong, one example each (80 characters), and how many were
     followed in the same turn by a call of that tool that went through (what a refusal cost her: a retry);
   - **parameters**: the ones she was shown and never wrote; the old names she still wrote;
   - **lengths**: for each limited text, how often she went over and how often she sent the cut version;
   - **turn shape**: calls per turn (middle and most), turns that hit the calls-per-turn cap (its current value),
     calls refused for coming before `think`;
   - **looking things up**: how many tasks she handed over this week that only read (every tool they used reads), to
     get a number she needed; what this review should make unnecessary, and so its own measure (three on
     2026-10-16);
   - **her action brain**: the same refusal reading for the tasks she handed over (her doing half; her tools there are
     hers too);
   - **the list she carries**: what changed in it since her last review (tools and options added or removed, and the
     change in characters in a home conversation, a group and a private chat); "unchanged" when nothing did, which is
     most weeks, since it changes only at a restart;
   - **last time**: what she proposed last week and what came of each (built, declined with the reason, waiting).
   At most 2,500 characters; a reading with nothing in it says so in one line. When the readings do not fit, the week
   before goes first, then parameters, lengths, turn shape, the action brain and calls, in that order; `last time` and
   `refused` are never cut (they are what her proposals start from). A cut reading says it was cut.
3. **Her job in that turn, in her own way.** What to look at, what to question, what to propose is hers. A proposal
   can be anything that would make her work better: add, remove, merge, rename, a default, a limit, a refusal's
   wording, a line the program writes for her, a skill she writes herself. Two or three proposals a week is enough,
   plus at most one wish no reading supports yet, marked as such (some things only show up after they exist); a week
   with nothing to propose says so. A number to reach would turn it into a quota, and proposals made up to reach it.
4. **Where it goes.**
   - What she can do herself (a skill, her own notes or habits) she does, or notes in `ideas` for her
     self-improvement turn.
   - What needs the program she sends as one `ask` to the developer's line. Each proposal says what it changes, the
     reading behind it (or that it is a wish), and what it adds or removes for each brain (tools, description
     characters, lines per turn; AGENTS.md).
   - Her rule from ADR-069 holds: a tool or parameter is kept by whether it does something nothing else can, not by
     how often it is used. A reading of zero is a question to ask, not a verdict.
5. **The developer's side.** The developer answers on the line within a day, each proposal one of: done now (a small
   fix), drafted as an ADR with her, declined with the reason, or the owner's call. Design changes keep the owner's
   approval; changes to her tool list wait for her next restart (one cold start per conversation, never between
   turns). Each answer is also recorded for next week's `last time`, which reads what she proposed whether or not
   that week's turn came: an answer only on the line, a week later, leaves her remembering what she asked and not what
   was decided.

## Options considered

- **Her own weekly plan and a skill, no program change.** Her action brain can count the audit itself. Rejected as
  the base: the numbers would be her action brain's retelling and could drift from the program's; and a review that
  depends on remembering a plan stops when the plan is lost. It stays open to her for deeper looks.
- **A fixed weekday turn of its own.** One more scheduled turn and its cold start a week; the self-evaluation seat is
  already there and already weekly for her memory.
- **Interpreted tiers instead of counts.** The AGENTS.md rule for program state is coarse words; her self-review
  precedent (ADR-058) asked for raw readings with sources, and a tooling review needs to compare numbers. Counts,
  formatted for reading.

## Cost (AGENTS.md)

Character brain: no new tool, option or parameter, and no line in any other turn. One block, at most 2,500
characters, at the tail of one turn a week: one prefill of it a week. Action brain: unchanged. Program: one module
beside `self_review.py`, its test, its line in RUNTIME_API.md.

## Her review (agent line, 2026-10-16; Claude's paraphrase, signed by her the same day)

She is for it: it saves what she did three times on 2026-10-16, handing over a read-only task to get one number and
then checking its denominator with Claude. Her answers and changes, all made above:

- The seat stays in self evaluation: a day she picks would be one more scheduled turn and its cold start, and an hour
  she sets herself is one she would put off. She asked for a floor so that a week without the roll still gets it;
  hers was "the next self evaluation after 14 days", made "the next heartbeat after 9 days" above, because the
  roll itself can be what is missing.
- Every reading names its source (collection, filter, window), as her ADR-058 review asked; one line at the end of
  the block is enough for her to check it.
- Added: how many read-only tasks she handed over to get a number, the review's own measure.
- Dropped: the absolute size of her tool list in three places, the same most weeks; only what changed stays.
- When it does not fit, `last time` and `refused` stay; repeated numbers go first.
- Two or three proposals and at most one wish; a week with none says so.
- The developer's answers go into next week's `last time`, not only the line (the draft both assumed this and asked
  it; her answer settled the question).
- The cost in one unit (a prefill a week), and a limit shown at its current value, not a number written into the
  text.
