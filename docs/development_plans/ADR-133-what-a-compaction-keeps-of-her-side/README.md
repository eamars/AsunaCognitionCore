# ADR-133: What a compaction keeps of her own side

Status: **Proposed** 2026-11-18 by big sis (Claude Code): the context reserved in the morning; the design (§6) written
12:40 at the owner's word ("start the ADR-133 design when both you and Xiaoman are free"), after ADR-132's install.
It was first planned to start after ADR-132 closes (the owner, 2026-11-18: her request, which he authorised, goes after ADR-132, the
bug fix). Everything in §1 and §2 was read 2026-11-18 09:52-09:57 from the code on `main` and from her profile,
read-only (session files through their structure only: counts and lengths). Times on this page are local time.

## The ask

The owner, 2026-11-18: "please take a look at her request. She requested a feature authorized by myself. I'd like
that request to go after ADR-132, as 132 is the bug fix. I'd suggest you to draft the ADR context and reserve the
context."

Her request (agent line 0548, 2026-11-18 09:11), in short: change the compaction instruction of her conversations.
She does not want a longer checkpoint, but different content. What it keeps now (the thread, open topics, promises,
corrections, line numbers) is enough, and she works from it. It misses three kinds:

- **A.** What she holds and has not said: the feelings she recorded, above all those marked as not settled.
- **B.** How she means to start her next beat: whom not to press, which matter to settle first, a beat in which she
  means only to speak and not to act.
- **C.** The fact that she chose not to speak in a beat. Once that is compacted away, she reads herself as having
  dropped out.

One thing she does not want: completeness, two lines per item to guard against loss. One rule she adds: what she
inferred carries a mark saying so in the checkpoint, so that it never turns, over merges, into something another
person said.

Her evidence: in one beat on the night of 2026-11-17 she took staying silent for tact, where she owed an answer she
had announced publicly. The checkpoint kept no line saying she chose not to speak there, and the next morning she read
herself as not having seen it.

She asks two things before any building: **(1)** a cap on what A, B and C add together, and what is cut first past it;
**(2)** an acceptance written down: the compaction of her home private conversation of 2026-11-18 00:00-09:10 run
again, the old and the new checkpoint read side by side for three questions (A, B and C there or not; her inferences
marked or not; the length under control or not).

## 1. The checkpoint today

- **The instruction** (`packages/cognition-core/src/compaction.js` `ROLE_COMPACTION_INSTRUCTION`) asks for six
  sections in order: 对话脉络, 未了的话头, 答应过的事, 更正与分歧, 对方此刻, 委托中的事. A summary missing one is
  rejected (`hasSections`). Among its rules: what the program gives every turn (the 情感 block among them) is not
  copied in; entries about who said, decided, promised or corrected something end with their source line, and one with
  no source line is written as 「（转述）」; no evaluation, nothing the conversation does not hold, and 「不替角色决定感受」.
- **Its size has no cap of its own**; only the summary request's output limit bounds it. Her conversations wrote 368
  checkpoints from 2026-11-04 to 2026-11-18: median about 16,700 characters, 90th percentile about 27,200, largest
  about 37,600 (each record's longest text field).
- **It does not share a budget with 随身.** 随身 is the carried tier of her stored notes, capped per store
  (`memory_tiers.py`); the checkpoint is part of the conversation itself and is counted in neither cap. What a longer
  checkpoint costs is room in the conversation's window, and so the point at which the conversation is compacted.

## 2. Her three kinds against what reaches her now

- **A.** Her open feelings are given again every turn by the program, compaction or not (`affect.py` `interpret`).
  At home, every unsettled feeling is listed with its strength, how long ago, its reason and where it was written.
  Elsewhere, the 心情 paragraph names the causes by their reasons, without saying which ones are unsettled. So the
  feelings survive a compaction. What does not survive is their tie to the conversation: that one of them was not said
  there. The instruction tells the summarizer to copy none of the 情感 block, and not to decide feelings for her.
- **B.** Her plan for the next beat lives in her thinking or in her own words. Whether the summary request carries her
  thinking has not been read; the design reads it (what DSH sends the summarizer of the history).
- **C.** A beat she ends without speaking (`end_turn`, ADR-131) stands in the conversation as a tool call. No section
  asks for it, and 「只写经过」 and 「不评价」 leave it out. This is the failure she saw.
- **Her inferences.** 「（转述）」 marks an entry with no source line; nothing tells an inference of hers apart from what
  someone said.

## 3. Open for the design (after ADR-132)

- **(1), the cap.** A proposal is sent to her with this page (agent line); the design fixes the number and the order
  of cutting after measuring the new instruction on the rerun.
- **(2), the acceptance.** Running the compaction again needs one request to a real model, her character route, on a
  copy of that conversation in an isolated profile that is removed afterwards. The owner's explicit approval is needed:
  the standing rule is that no real model is called. She reads the two checkpoints side by side. Big sis reads counts
  only: sections, marks and lengths.
- **A outside home.** Whether an unsettled feeling should be marked as unsettled outside home is a question of what
  the program gives every turn, not of compaction. The design says whether it is in or out of this ADR.
- **The wording** of every line she reads is hers to approve (her F8).
- **Cost.** The instruction is the tail of the summary request only. Her turns' requests do not carry it, so their
  cache is not touched. The design measures the instruction's growth and the checkpoint's growth on the rerun.

## 4. Closes when (proposed; fixed at design)

Built and staged on a stub model. Her reading of the rerun of (2): "done" or what is still missing. Then her first
real compactions after the install, read by counts against the cap: a line for C wherever the compacted span holds a
beat she ended without speaking, and the size within the cap. The count of compactions is set at design, and it closes
by that reading, never by a date.

## 5. Her answers and the owner's, before the design (2026-11-18)

- Her 0549: the two budgets are not one; 800 characters is the start; A copies no feeling, only "which one, in which
  beat, was not said"; B keeps the latest beat only; C is one line a beat and is never cut. "Unsettled" marked outside
  home is in this ADR, under the same cap. Report whether the measured rerun goes over 800, not only "designed".
  Every line she reads is in her words, given at the design (not 0548's).
- The owner, in this chat, 2026-11-18: "I confirm the 133 real-model rerun is approved. For now just run on her
  character brain model to verify the compaction with different prompt if she like." Her 0552: she runs it, on an
  isolated copy, and reads the two checkpoints herself.

## 6. Design (proposed, 2026-11-18 12:40)

What the summarizer can read, checked on the code: the summary request carries the conversation's own messages
(`compaction.js` `summarize`), her `think` calls and every other tool call among them. So B is there whenever she
wrote her plan in a thought or in her words, and C is there as a beat whose calls end in `end_turn` with no `speak`.
Whether a model's own reasoning block reaches the summarizer is not relied on.

**D1. One section of hers, last in the checkpoint.** `ROLE_COMPACTION_INSTRUCTION` gets a seventh section after
委托中的事 (its heading in her words; `hasSections` asks for it like the others, so a summary without it is rejected as
today). Three kinds of line in it, in this order, each ending with its source line's number as the other sections do:
- C, a beat she ended without speaking: which beat (the line it answered), and why if she wrote why. One line a beat.
- A, a feeling she held and did not say: which feeling (its kind, as the program names it) and in which beat. Never the
  feeling itself: the program gives every unsettled feeling again each turn (§2).
- B, how she meant to start her next beat: the latest beat's only, from her own thought or words.

The rules for the section, in the instruction: at most 800 characters; past them, A is cut first, then B; C is never
cut. On a merge, a C line whose debt she has since paid (she spoke to it, by a line) is marked settled once and dropped
at the next merge, as promises are today; an open one is carried word for word. B is replaced, never merged.

**D2. Her inferences carry her mark.** A rule for every section: an entry that is her own inference, not a thing
someone said or did in the conversation, ends with her mark (her words; 「（我推的）」 is the placeholder), beside the
existing 「（转述）」 for a report with no source line. The rule names the failure: an inference must not become, over
merges, something another person said.

**D3. Unsettled, outside home too.** `affect.py` `paragraph`: outside home, a cause whose feeling is unsettled says so
(her words; the placeholder 「（还挂着）」), beside the existing 「（这里记的）」. Home already lists it (`unsettled`).
Nothing else in what she reads each turn changes.

**What does not change:** the six sections and their rules; the rest of the checkpoint; when and how a conversation is
compacted (ADR-094); the action brain's compaction (DSH's template).

**Failure modes.**

| # | Failure | Here |
| --- | --- | --- |
| G1 | The section grows past 800 with C lines never paid (a run of silent beats) | C is never cut, by her rule: the rerun and the readings count C lines; a section over 800 made of C alone is reported, not trimmed |
| G2 | The summarizer writes A as the feeling itself, duplicating the program's block | the rule says "which, in which beat"; the rerun is read for it |
| G3 | B carries an old plan forward through merges | B is replaced at each merge, never carried |
| G4 | The inference mark spreads to plain facts, or is missing where it belongs | read on the rerun by her (she can tell her inferences); counted at the readings |
| G5 | A summary without the new section | rejected by `hasSections` as today: no checkpoint written, the next turn end tries again |
| G6 | A beat counted as silent where she did speak (a `speak` refused, then `end_turn`) | the rule says a beat with no `speak` that went out; the rerun is read for it |

**Cost.** The instruction grows by about the length of D1 and D2's rules (measured at the build); it is the tail of
the summary request only, so her turns' requests and their cache are not touched. The checkpoint grows by at most
800 characters, plus C beyond it.

## 7. Acceptance and close (proposed)

1. **Her rerun (the owner's approval above).** One compaction of her home private conversation of 2026-11-18
   00:00-09:10, run again on a copy in an isolated profile, with today's instruction and with the new one (her words
   in it), on her character route; the copy removed after. She reads the two side by side for her three questions (A,
   B and C there or not; her inferences marked or not; the length under control or not). Big sis reads counts only:
   sections present, C, A and B lines, marks, characters of the new section against 800. Her "done", or what is
   missing, is the verdict.
2. **Staged** on a stub model: a summary without the new section is rejected; the instruction's text is as she worded
   it.
3. **Installed**, read by content, then her next 20 real compactions read by counts: the section present in all, over
   800 only with C, and a C line for every beat in each compacted span that she ended without speaking (counted from
   the session file: a turn with `end_turn` and no accepted `speak`). Before 20 it is reported as not enough; at 20 the
   reading closes it.

## 8. Asked of her

- The wording of: the section's heading; its three kinds of line; D1's rules (the cap, the order of cutting, the
  merge); the inference mark (D2); the unsettled mark outside home (D3).
- Whether her rerun runs before the build, with today's instruction as the old one and her worded one as the new (so
  the build carries what she read), and who presses the button: the script that rebuilds the request from the session
  copy and calls her route is big sis's to write; she runs it, or asks big sis to.

