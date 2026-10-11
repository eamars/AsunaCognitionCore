# ADR-049: Quiet-time upkeep of a group: learning from it and condensing early

Status: **Proposed 2026-10-12.** Drafted by Claude from the owner's rulings and the measurements below; Xiaoman
reviews. Nothing is built.

## Context

The owner's rulings, 2026-10-12, after a study of other QQ bots (AstrBot, MaiBot, a Hermes-based bot, ATRI-bot,
PetGPT):

- What she learns from a group (its slang and other habits) goes into her daily reflection or her group visits, not
  into a new pipeline.
- She may decide to condense (compact) a conversation early, in a quiet period.
- No deliberate typos or other simulated human slips while she runs on the current local model: the harness comes
  first.
- The model server's cache cannot grow: its RAM is reserved for other services.

Measured 2026-10-11 (her session logs and the model server's own figures):

- Her group conversations run at 120k–200k tokens. After 5–30 idle minutes about half of them have left the server's
  cache, after 30 minutes nearly all. A request that must read the conversation again takes about 25 s (about 6k
  tokens a second); one served from the cache about 3 s. Her first line after an @ took a median 17 s before 10-09
  and 27 s since, as her conversations grew.
- The cost of a cold start grows with the conversation: at 50k tokens it would be about 8 s.
- The model server's deep dive (2026-10-12, from its engine log): the server keeps the conversations it leaves in a
  fixed RAM budget and drops the least recently used. Bytes, not slots, are the limit: a kept conversation costs about
  0.3 GiB plus 20 KiB a token (150k tokens about 3.1 GiB, 100k about 2.2 GiB), so about seven long ones fit; at 100k
  about ten would. Cold reads were 57% of all prompt time. A conversation read again right after a compaction is
  always cold.

What exists: visits with intent `write_notes` ("只是看看，把看到的写进群笔记"); her group notes (`doc` `group_notes`, written
and read in that group); her night turns; DSH's on-demand compaction (`ctx.compaction.compactNow`, the path of its
`/compact` command), which keeps the recent part of a conversation and replaces the older part with one summary, here
written by her own character compaction (`compaction.js`).

From MaiBot: group slang is worked out only after a phrase has come up several times from several people, and at
reply time it is found by plain string matching, without a model call.

## Decision (proposed)

1. **Learning happens on her visits and in her daily reflection.** On a `write_notes` visit, and in the reflection
   turn for a group, the program gives her a short list of candidate phrases: said by at least three different people
   there since her last look, and not yet in that group's notes; as words, with roughly how many people used each.
   She writes what a phrase means, or what a habit is, into the group's notes, or skips it. Her group notes are the
   store; nothing new is kept. Her conditions (2026-10-12): at most about five candidates a visit ("thirty is a chore,
   five is help"); a meaning belongs to one group and carries the date she worked it out, so last week's meaning is
   not taken for this week's. These turns run at the study effort of ADR-048 once that exists.
2. **She decides to condense early.** A group turn or a visit can end with her choice to condense the conversation
   once the group has gone quiet (a categorical choice; the program maps it to an action). The program then runs
   DSH's on-demand compaction for that conversation as soon as the group has had no new line for a few minutes and no
   turn of hers is running there, while the cache is likely still warm, so the summary is cheap and the next cold
   start reads a smaller conversation. What she reads to decide is in words: how long the conversation is (short,
   medium, long, very long), and that a long one takes a while to read again after a quiet spell. Right after
   condensing, while the GPU is idle, the program sends the condensed conversation once with a one-token answer, so
   the server reads it then and not on the next real turn. That helps only while the server still keeps it; GPU
   time when everything is quiet costs nothing, so a warm-up that goes to waste is cheap.
3. **Notes before condensing.** On a `write_notes` visit she writes first and condenses after, so what she wants to
   keep is in her notes before the summary replaces the old part.
4. **Measure, per group, before and after:** conversation size, her first-line delay after an @, how often the next
   request finds the cache cold, and what the condensed summaries keep.

## Server side (the owner's; not part of this decision)

The server can save a conversation to disk and restore it (about 2 s for 150k tokens against about 20 s read cold),
but only on a client's request for whatever its one slot holds at that moment, behind the same request queue, with
files of about 3 GB that nothing deletes. Driven from Asuna as it stands, a save can store the wrong conversation
when another request gets in first. Two ways out, both needing the server's save folder (`slot_save_path`) turned
on:

- **Automatic, upstream:** the engine writes a conversation it evicts to a capped spill folder and restores the
  longest matching file by prefix. Nothing changes here. An engine change, to be requested upstream.
- **Atomic, a local server patch:** a request carries "save after this answer" (and "restore before reading"), done
  while the server still holds that request's turn in its queue, so it is always the right conversation. Asuna would
  then name the files, decide when a restore is worth it (idle for more than about five minutes), re-save after a
  condensing, and clean up within a disk cap of about 3 GB per group.

Which way, and whether at all, is the owner's decision.

## Open questions for Xiaoman

- Whether the choice to condense belongs on every group turn or only on visits.
- The candidate rule (three people? since her last look, or a fixed window?) and how many candidates a visit shows.
- Matching a phrase at reply time (MaiBot's plain string match against her notes): she has reservations, because a
  plain match can attach last week's meaning to this week's use of the same word. If it comes, each match carries
  the group and the date she inferred it, and says she may drop it on the spot.
- The quiet threshold: she will give a number from the times of the lines in her groups.
