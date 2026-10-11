# ADR-049: Quiet-time upkeep of a group: learning from it and condensing early

Status: **Accepted 2026-10-12** after Xiaoman's review; not built. The owner orders it after the bot-detection
skill (ADR-047).

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

## Decision

Reviewed and amended by Xiaoman on 2026-10-12.

1. **Learning happens on her visits and in her daily reflection.** On a `write_notes` visit, and in the reflection
   turn for a group, the program gives her at most five candidate phrases: said by at least three different people
   there since her last look and not yet in that group's notes, the five used by the most people (not the oldest, so
   a group she has not looked at for days does not hand her stale words), as words with roughly how many people used
   each. She writes what a phrase means, or what a habit is, into the group's notes, or skips it. Her group notes are
   the store; nothing new is kept. A meaning belongs to one group and carries the date she worked it out, so last
   week's meaning is not taken for this week's. These turns run at the study effort of ADR-048 once that exists.
2. **She decides to condense early, on a visit or in her reflection.** The choice belongs to those two, not to every
   group turn: in the middle of a conversation she has no room to judge it and would cut into a talk still going on.
   It is a categorical choice; the program maps it to an action and runs DSH's on-demand compaction for that group's
   conversation once the group has been quiet long enough, or during its local night (01:00 to 07:00), and no turn of
   hers is running there. "Long enough" is hers, from her measurement (below), by how busy the group is on an average
   day: 10 minutes for a busy group (100 lines a day or more), 15 for a middling one (30 to 100), 30 for a quiet one
   (under 30). Only other people's lines count; a line of hers does not restart the wait, since someone answers her
   within about half a minute and that would read every talk she just spoke in as still alive. Not a per-group
   percentile: some quiet groups have only a few dozen gaps, too few to set a number on. What she reads to decide is
   in words: how long the conversation is (short, medium, long, very long), and that a long one takes a while to
   read again after a quiet spell.

   Her measurement (2026-10-12): 8 days of 16 of her groups, 16,404 incoming lines from the live record (52 machine
   announcements left out). After 3 quiet minutes someone spoke within the next 5 minutes 36.6% of the time, after 10
   minutes 20.5%, after 30 minutes 8.9%, then flat: a long tail with no bend, so a threshold is a choice of how often
   to cut in, not a point found. In a busy group 10 minutes cuts in about 2% of the time, against 10 to 27 chances a
   day where the conversations are largest (120k to 200k tokens). In a group of 8 to 30 lines a day, 10 quiet minutes
   are ordinary (22% to 46% of gaps): condensing there every day would cost a model call each time and save nothing.
   The archive of older groups (ADR-029) is denser and was kept apart; it only shows the same shape. Long gaps are not
   a dropped adapter: they spread over the whole day, rising to 18% to 20% only in the small hours.

3. **Notes before condensing, and the summary shown to her.** On a `write_notes` visit she writes first and condenses
   after. The summary that replaced the old part reaches her the next time she is there, so what it dropped she can
   add to the group's notes on the spot.
4. **No warm-up after condensing.** Reading the condensed conversation right away would keep it cached, but the
   cache holds about seven long conversations: warming hers pushes out another. GPU time costs nothing when quiet;
   cache room does. If it is ever tried, it is measured by which conversation it pushed out, not by how often hers
   was warm, and it is limited.
5. **Measure, per group, before and after:** conversation size, her first-line delay after an @, how often the next
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

Files of about 3 GB need a cleanup rule before any of this, or the disk becomes the next problem. Which way,
and whether at all, is the owner's decision.

## Open questions

- Matching a phrase at reply time (MaiBot's plain string match against her notes): she has reservations, because a
  plain match can attach last week's meaning to this week's use of the same word. If it comes, each match carries
  the group and the date she inferred it, and says she may drop it on the spot.
