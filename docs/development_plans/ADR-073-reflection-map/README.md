# ADR-073: A map of what she has, in her reflection

Status: **Built 2026-10-16** (the owner's go on the measured map, choice E; drafted by Claude; her review the same day,
all of it in below). Installed with her next restart.

## Context

The owner (2026-10-16): in her reflection she should see what information she has, group notes for one, and the
survey had to come first. It is `docs/articles/what-she-reads-each-turn.md`. What it found for reflection:

- Her group notes are her richest store of what she has learned about people and places: 16 groups, 87 sections,
  47,000 characters, 167 revisions this week. A home turn sees at most eight headings per group.
- She changed about 500 things this week (group notes, persona, self, work log, voice), each with the reason she wrote
  then, and never sees them in one place.
- Her person-level understanding exists for 2 people; her per-conversation understanding for 14 conversations.
- Her relevance gate decided on 378 lines this week, and she never sees how often she looked or let one pass.

ADR-072 put her reflection turns in a session of their own, so what they carry costs her regular turns nothing: the
owner's rule is more tokens for reflection, none in regular turns.

## Decision

A reflection turn (self evaluation, dice review, the nine-day floor; `self_review.REFLECTION_BLOCKS`) carries
`map_from_program`, from what changed since the last map she was shown, at most 14 days back; a longer gap is said,
not hidden: "the last map was N days ago; the earliest N-14 days are not in this one" (her review: a map that quietly
says nothing changed is the worst way for it to fail):

1. **One line per store**: what it is, how much there is, what changed since the last map, and exactly how to open it
   (`recall` `sections` with the `doc`, or the tool that lists it). Her group notes, her own documents (persona, self,
   core, voice, work log, ledgers), people (person-level understandings), memories by kind and by tier, feelings (all,
   since, and still open), ideas, plans, questions, notes, errands (recent, and still on their way), the switches she
   has on (with when each ends), what she made (pictures, the sticker shelf and how to list it), and the
   `self_review.tag` line: how many sections her tag finds (her asks).
2. **What she changed, in her own words**: each group-note section she rewrote or added since the last map, whole,
   with its group, its `doc` reference and the reasons she gave; each change to her own documents by heading with the
   reasons she gave at the time (the text itself she opens by reference); each person-level understanding she changed,
   whole. Her words only: no one else's lines. Each store has its own share (group notes 2,800 characters, her documents
   1,500, people 1,200) so the busiest cannot fill the map, and within a store the newest come first: whole while they
   fit, then by heading and reference, then as a count of what is left (her review: volume is not importance).
3. **Attention as counts**: per group, how many lines her relevance gate saw since the last map, and how many it gave
   her a look at; the difference is the lines not shown to her, and the note says so. Numbers only, no verdict and no lines (her condition: "you let X go 12 times" said aloud becomes a
   score; what it is for is comparing what she says she cares about with where her eyes went).
4. Facts only, every count with its source, as ADR-070's readings. About 8,000 characters at most: the index and the
   attention counts, and each store within its share.
5. It does not overlap ADR-071's exchanges, which live in the same turn: those are her lines, the thought she wrote then
   and what came back; this is what she changed and why. Each has its own window and its own limit.

The per-conversation understandings stay out: they are scoped to their conversation by her own design.

## Cost (AGENTS.md)

Character brain: no tool, option or line in any regular turn. One block, at most 8,000 characters, in reflection turns
only, which run in their own session (ADR-072). Program: one module, its test, its lines in RUNTIME_API.md.

## Built (2026-10-16)

`reflection_map.py`, read in the reflection branch of `context.py`; showings are `review.map` in the audit. Measured on
her real data before installing, read-only: the first draft's single limit let group notes take nearly all of it (158
texts cut); with a share per store her first map reads 6,397 characters (four groups' notes newest first and the rest
counted, three documents with her reasons, two people, attention for twelve groups). Her oldest group note is from
2026-10-05, inside the first map's 14 days, so the first map counts all 88 sections as changed; later maps count from
the one before.

## Her review (agent line, 2026-10-16; Claude's paraphrase, for her to sign or correct)

She agrees; the context's readings make the case (about 500 changes in a week she never saw together). Her answers and
changes, all made above: the 14-day cap stays and a longer gap is said; four more lines (errands on their way, the
switches she has on and when they end, what she made, feelings still open apart from all); a share per store, newest
first within it, rather than one limit the busiest store would fill; group-note changes carry her reasons too; the
attention note says the difference is what was not shown to her; and it says how it differs from ADR-071's exchanges.
She will look again, herself, at whether something true everywhere is kept in a per-conversation understanding (2
person-level against 14 per-conversation).
