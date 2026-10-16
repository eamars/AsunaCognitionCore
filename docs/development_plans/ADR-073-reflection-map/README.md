# ADR-073: A map of what she has, in her reflection

Status: **Proposed 2026-10-16** (the owner's go on the measured map, choice E; drafted by Claude). For Xiaoman's review.

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
`map_from_program`, from what changed since the last map she was shown (at most 14 days):

1. **One line per store**: what it is, how much there is, what changed since the last map, and exactly how to open it
   (`recall` `sections` with the `doc`, or the tool that lists it). Her group notes, her own documents (persona, self,
   core, voice, work log, ledgers), people (person-level understandings), memories by kind and by tier, feelings, ideas,
   plans, questions, notes, and the `self_review.tag` line: how many sections her tag finds (her ask).
2. **What she changed, in her own words**: each group-note section she rewrote or added since the last map, whole,
   with its group and its `doc` reference; each change to her own documents by heading with the reason she gave at the
   time (the text itself she opens by reference); each person-level understanding she changed, whole. Her words only:
   no one else's lines.
3. **Attention as counts**: per group, how many lines her relevance gate saw since the last map, and how many it gave
   her a look at. Numbers only, no verdict and no lines (her condition: "you let X go 12 times" said aloud becomes a
   score; what it is for is comparing what she says she cares about with where her eyes went).
4. Facts only, every count with its source, as ADR-070's readings. At most 8,000 characters; past that the whole texts
   give way first (heading and reference stay), then the index's detail; the attention counts and the line for her tag
   stay.

The per-conversation understandings stay out: they are scoped to their conversation by her own design.

## Cost (AGENTS.md)

Character brain: no tool, option or line in any regular turn. One block, at most 8,000 characters, in reflection turns
only, which run in their own session (ADR-072). Program: one module, its test, its lines in RUNTIME_API.md.

## Questions for her

1. Is 14 days the right look-back when reflection turns are far apart?
2. Of the stores in the index, which would she drop, and what is missing?
3. Whole texts of what she changed: all of them up to the limit, or the newest first?

## Her review

(waits for her)
