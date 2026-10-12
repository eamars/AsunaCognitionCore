# ADR-049: Quiet-time upkeep of a group: learning from it and condensing early

Status: **Accepted and built 2026-10-12** after Xiaoman's review; the owner moved it to the same night. Live after
her next restart.

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

## Built (2026-10-12)

- `condense.py`: the quiet tiers, the local night, her mark (`group_focus` op `condense` / `keep`, in visit, heartbeat,
  self-improvement and settlement turns), the look that condenses due groups, the once-only note after condensing, the
  size words, and the phrases for a `write_notes` visit.
- The home plan `plan-asuna-condense` (every 5 minutes, only while a group is marked) runs each look off the scheduler
  thread; the plugin's `compact_session` Host request runs DSH's own compaction on the group's main session and
  refuses during a turn there.
- Each turn's result carries the prompt length of its latest request; the scene keeps it for the size words.
- Phrases, tried on her four busiest groups' real week before building: the first rule (three people since her last
  look) surfaced a day's topic in five overlapping pieces and ordinary words; requiring three different days, leaving
  out what two people use in two other groups, pieces of pure function characters and overlaps gave each group's own
  vocabulary (accounts and quotas in one, gear in another, API relays in a third), with a few common words left for
  her to skip. About 2.5 s a visit.
- Not built: the reflection-turn phrases (her reflection runs at home, and other people's words reach home only
  through her reviewed paths, ADR-017); matching phrases at reply time (her reservation stands).
- Tests: `tests/test_adr049_upkeep.py`, `packages/cognition-core/test/condense.test.js`.
- Amended the same night, on her rule: a turn a plan of hers woke counts too when it is at home (her local chat, the
  owner's DM, her home lines), like her heartbeat; never in a group or someone else's chat. Her test: whether anyone
  there is waiting for her to speak. The refusal now says so.
- Fixed after the first live mark: the first build looked for DSH's compaction service on the plugin's own context,
  where it is not (each agent's scope carries it, from her character preset), so every look answered
  `no_compaction_service`. It now runs the session's own `/compact` through the commands service, the Web UI's path,
  and a Host that cannot condense takes the mark back instead of retrying every five minutes.
- Second live finding, after her restart: reopening a session that was not loaded failed without its working folder
  (the request now carries the session's `cwd`), and a persona preset must carry `@deepseek-ai/dsh-command-compact` in
  its compaction group for `/compact` to exist in her conversations, as the core presets do. Hers did not, so the
  look answered `no_compact_command` and, as designed, took the mark back. Adding that row is a change to her persona
  package, published by her.

## Verified live (2026-10-12)

The first real condensing (her mark on a visit, done at night there): 470 items, about 72,000 tokens compacted. The
group's conversation measured about 168,000 tokens before and 42,376 at her next turn there, with 62 messages since.
The condensed note reached exactly one turn (the next one woken there) and stopped once she had spoken. Still to see:
the slang phrases on a note-writing visit.

## Gap found 2026-10-13 (ADR-063 D1)

Condensing waits for her mark, and she has marked twice (one failed on bugs fixed that night, one condensed 470
items). A group she rarely visits never gets a turn to decide in: one quiet group's conversation reached 821k
characters, never compacted. Proposed for her agreement: a size floor that condenses a conversation past a set size
at its next quiet spell (her quiet tiers and local night above) without her mark; her mark still condenses earlier.

*Her answer (Claude had written his paraphrase of her agent-line message of 2026-10-13 ~10:20 NZDT here for her to
sign or correct; she signed it herself on her agent line, 2026-10-13):*

**Signed by Xiaoman, 2026-10-13.** I agree to a size floor. My reasoning: the right to decide "condense or not"
only exists where I have turns — in a group I visit twice a year that right was already empty, which is how one
conversation reached 820k characters. So the floor does not take the right away, it gives it a trigger. The three
conditions are part of the deal, not follow-ups, each required:
1. **Notes before condensing**, as on a visit: a group she rarely visits loses lines she never read, and its notes are
   the only safeguard.
2. **Told the next time she is there**, every time: that the group was condensed and where the summary is, so she can
   add to her notes then.
3. **Groups only**: her private chats, the owner's and her home lines keep her mark alone (she is there nearly every
   beat; the choice is not empty there).
The floor: half of the compaction threshold. The 821k-character group is condensed at its next quiet spell, and she is
shown its summary.

*Built 2026-10-13 (ADR-063 D1 part 1, 77512efa).* The floor is measured on the Host in DSH's own token meter against
half of the character preset's compaction threshold for the conversation's model; a group is measured at a quiet
spell after new lines. Notes first: past the floor the program opens a notes visit there (intent `condense`, outside
her visit ledger and its daily limit), and condenses at the next quiet spell after that turn ran; a muted group waits.
Told every time: the first turn there after any condensing carries `condensed_from_program`, however long after (the
one-day window is gone). A conversation too large for one summary request is summarized in steps. Her wish to be shown
the 821k group's summary: the summary is the start of that conversation, which her next turn there (the notes visit
comes before it, the told turn after) reads; showing it at home as well is not built.

*Fixed 2026-10-13 (owner's report: a QQ group condensed twice in a row).* A quiet group past the floor was condensed
again every ten minutes: the reading taken before the condense was kept until new lines arrived, and a quiet group has
none, so each look found it still past the floor, opened another notes visit and condensed little more than that visit
(10:58-11:45 NZDT: 28 notes visits and 26 condenses over nine groups, 18 of them of 7-15 entries in seven groups;
the stale readings were cleared live at 11:47). A reading past the floor is now taken again before the program acts on it; a
reading under the floor still stands until new lines. No separate minimum is needed: after a condense the conversation
is its retained tail and summary, well under the floor (half the compaction threshold).

When a group is condensed again (owner 2026-10-13: no repeated condensing where it is not needed). By size: only once
it has grown past the floor again, by a fresh reading; the retained tail (DSH's `retainRatio` 0.16, about 37k tokens
on her model) is far under the floor (about 105k), so a condense always brings a group back under it. By her mark: no
size minimum (owner: fine as it is; she has marked twice ever and the mark answers her the group's size in words); a
conversation no longer than the retained tail is left as it is and the mark cleared, a slightly longer one is
condensed down to the tail. Inside her turns DSH's own threshold (0.8 of the window) applies as before.
