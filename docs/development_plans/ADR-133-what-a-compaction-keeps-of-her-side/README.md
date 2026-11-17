# ADR-133: What a compaction keeps of her own side

Status: **Proposed, reserved** 2026-11-18 by big sis (Claude Code). This page holds the number and the context only; the
design starts after ADR-132 closes (the owner, 2026-11-18: her request, which he authorised, goes after ADR-132, the
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
