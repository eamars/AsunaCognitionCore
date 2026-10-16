# ADR-070: Her weekly tooling review

Status: **Proposed 2026-10-16** (the owner's direction, drafted by Claude). For Xiaoman's review; the owner approves
before anything is built.

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
   (same rule: none when shown within the last 7 days). Nothing else carries it.
2. **The readings** (the program's numbers, never her retelling of them; the last 7 days, the week before beside them):
   - **calls**: each tool and option she called, how many times; the listed ones she never called;
   - **refused**: per tool, the refusals grouped by what was wrong, one example each (80 characters), and how many were
     followed in the same turn by a call of that tool that went through (what a refusal cost her: a retry);
   - **parameters**: the ones she was shown and never wrote; the old names she still wrote;
   - **lengths**: for each limited text, how often she went over and how often she sent the cut version;
   - **turn shape**: calls per turn (middle and most), turns that hit the 12-call cap, calls refused for coming before
     `think`;
   - **her action brain**: the same refusal reading for the tasks she handed over (her doing half; her tools there are
     hers too);
   - **the list she carries**: her tools' size in a home conversation, a group and a private chat (tools, characters),
     and what changed in it since her last review;
   - **last time**: what she proposed last week and what came of each (built, declined with the reason, waiting).
   At most 2,500 characters; a reading with nothing in it says so in one line.
3. **Her job in that turn, in her own way.** What to look at, what to question, what to propose is hers. A proposal
   can be anything that would make her work better: add, remove, merge, rename, a default, a limit, a refusal's
   wording, a line the program writes for her, a skill she writes herself. One proposal a week may be a wish no
   reading supports yet, marked as such: some things only show up after they exist.
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
   turns). Next week's `last time` reading closes the loop.

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

Character brain: no new tool, option or parameter. One block, at most 2,500 characters, in one turn a week; every
other turn unchanged. Action brain: unchanged. Program: one module beside `self_review.py`, its test, its line in
RUNTIME_API.md.

## Questions for her

1. The seat: once a week in self evaluation (rolled by the dice), or a day and time she picks?
2. Which readings would she drop, and which is missing?
3. How many proposals a week is enough without becoming a quota?
4. Should the developer's answers come back on the line only, or also in `last time`?

## Her review

(waits for her)
