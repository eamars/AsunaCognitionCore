# ADR-133: What a compaction keeps of her own side

Status: **Closed** 2026-11-23 by §7.3's reading (§18). The section is kept in all 93 checkpoints and within its size. The beat facts the model works out (没说成, anchors, a few silent beats) are wrong in places: a follow-up for the owner.
Before: **Installed** 2026-11-18 15:10 (`c06061eb8878`, §16); open until her next 20 real compactions are read (§7.3).
Before: **Proposed** 2026-11-18 by big sis (Claude Code): the context reserved in the morning; the design (§6) written
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
| G6 | A beat where her `speak` was refused counted as one she chose not to speak in | her 0565: a line of its own, 「没说成｜[时刻]（回〔编号〕）｜speak 被拒〔那一行〕」, never cut, never written as 没开口 ("trying and failing" is not "choosing not to"; she met it on 11-13); none in the rerun window, so it is shown on the stub |

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

## 9. The whole instruction reviewed against its last review (2026-11-18 13:00)

The owner, 2026-11-18, during the design: "Can you also review the existing section of the compaction prompt, not just
appending new sections to review the efficiency, and capability of the prompt against the actual model? Especially,
the duplication of the what is in the context, versus what will be injected later." And: "I believe I asked you the
similar question in the past, so perhaps we can do a side by side comparison to see what is changed, and what basis
should be updated based on more stats available."

The last review is ADR-094 §7 and §7a (carried from ADR-085, 2026-10-22: the template trimmed; its independent audit
`.runtime/private/compaction-study/researcher-audit.md`). Read again today with its own `impact.py` (the same rule over
every merge hop since) and two scripts of today, `dup_measure.py` and `ckpt_health.py` (big sis's scratchpad; numbers
only, her texts compared in the process and never printed). Her character sessions only.

| Measure | 2026-10-21/22 | Now (10-23 to 11-18) |
| --- | --- | --- |
| Promises and corrections gone at a merge (home / agent line) | 50% / 71% | 13% / 13% (370 hops) |
| Hard tokens lost at a merge (home / agent line) | 39% / 55% | 14% / 16% |
| 委托中的事 repeating the task list | 87-100% | 13% of it in the notice re-sent after the compaction |
| A section repeating what is re-sent after the compaction | 10-19% of a summary | 5-13% a section (306 checkpoints since 11-04) |
| Other sections repeating 对话脉络 | 74-90% | 3-8% |
| Checkpoint size (median characters) | 3-5k | 9.0k; the week of 11-16 22.7k; the busiest home and agent-line conversations about 30k |
| Items in 答应过的事 and 更正与分歧 | median 10, max 24 | median 43-56 a week, the week of 11-16 114; 150-196 in the busiest |
| Items marked closed at a merge | 6-7% | 4% |
| Entries in 未了的话头, 答应过的事 and 更正与分歧 with their source line or 「（转述）」 | (rule added after) | 35% |
| Compactions that write no checkpoint | not read | 8% (67 of 891) |

The duplication columns are not the same measure: on 10-22 a reviewer read every bullet; today's is mechanical
(6-character pieces), so a reworded repeat counts as new and today's shares are a floor.

**What this says.**
- The duplication the owner asked about, the checkpoint repeating what is injected again after it, is small now:
  5-13% a section, 13% for 委托中的事. The do-not-copy list and "one fact in one section" hold. No existing section
  is cut for repeating the context.
- What changed is growth. The 10-22 rule carries every promise and correction item by item, and her model marks 4%
  closed at a merge, so the two sections only grow. The 10-22 growth stop (over 40 items: end the one-checkpoint stay
  of a closed item; still over: revert the item-by-item carry) was watched until about 10-24 and never put into the
  instruction or the code; checkpoints now hold 150-196 such items. Past that size the model does not keep the list,
  it drops it in pieces: at 02:12 today one home merge dropped 78 items, 71 of them promises.
- Her model writes the source line on about a third of the entries the rule asks it for. That share mixes two kinds of
  conversation (her 0582): in a group each platform line carries its number at its end; at home the owner's words carry
  none, and the number is in the program's notice that follows (its event's line), so home and group shares are not
  one measure. The rule stays: an entry with
  its line is the one she can check.

**Decided (the owner, 2026-11-18, on big sis's recommendation).** The two sections hold at most 40 items together, by
rule in the instruction: past 40, the items marked 已了结 go first, then the oldest whose agreed day is past or that
named no day; an item whose agreed day is still ahead stays. When only items with an agreed day still ahead are left and they are still over 40, they stay and nothing more is
cut (her 0566); the readings report the count. The count dropped is left as one line with the merge's time,
「（旧账略 N 条｜[这次合并的时刻]）」, so she knows where to look. A cut by a stated rule replaces the model's own random drop; what an old promise loses by it, her own ledger keeps (her
practice since 10-22, ADR-094 §7a). The owner's reasons, his words (2026-11-18): "she will keep important stuff
elsewhere, so if the promises are lost in the context then that's not important. And human will forget, this is not
her fault and she don't need to carry all burdens." Rejected: a promise list kept by the program outside the checkpoint (a larger change,
near ADR-123); leaving the growth as it is.

## 10. Her wording (agent line 0564, 2026-11-18 12:42) and the instruction as built

- The section: 「我这边没说出口的」 (her reason: all three kinds never reached the delivered history; the name reminds
  her these are her own, not anyone else's words). Its three line shapes are hers, in the order C, A, B; her example
  lines name a real group and are not copied here.
- Her three limits, written into the instruction: the "why" only from what she wrote in that beat, else 「没写原因」;
  at most one C line a beat; B only from what she wrote that beat for "after", else no line, never inferred from what
  she did.
- D1's rules with her three additions: the 800 includes the section's heading; A is cut from the oldest, leaving one
  line of how many were cut; a settled line says 「已了结」 and the line that settled it, never what she said.
  Big sis changed one literal of hers, 「（A 略 N 笔）」, since the model never sees the letters A, B and C; her 0566 then
  named the line 「挂着没说｜」 and its count 「（挂着没说略 N 笔）」, so 「（还挂着）」 is D3's mark alone and one word means one
  thing.
- D2's mark 「（我推的）」 as hers, with her three additions: at the end of the sentence it marks, line by line, never one
  line heading a block; never merged with 「（转述）」 into a neutral word; the source half-sentence beside a number she
  wrote (她报的, 我量的, 我没核) kept through merges.
- D3's mark 「（还挂着）」 as hers, with her two additions: outside home, the feeling's name and the mark, never its
  words; in every place, no exception (an exception is named on this page with its reason). Built on the visibility rule
  as it is: a feeling is named where it is readable now (ADR-018); one recorded at home is not named in a group.
- Her rerun: she presses the button, today 13:00-20:00, after reading the new instruction itself; the two runs differ
  in the instruction alone (the same copy of the conversation, route and model), and the report keeps the two commands
  as run.
- Her 0565: a fourth line, 「没说成」, for a beat whose `speak` was refused and sent nothing (G6), never cut, never written
  as 没开口. And the window must hold what the test asks for, or C comes back empty and passes for nothing. Read by
  structure (turns ended by `end_turn`, `speak` results), the five home compactions of 2026-11-18 00:00-09:10:
  00:45 1 silent turn of 18; 02:12 12 of 19; 02:48 1 of 21; 04:10 4 of 23; 08:58 9 of 11; no turn whose `speak` was
  refused in any of them, so 「没说成」 is shown on the stub (§7.2) and not by the rerun.
- Her 0566 on the rerun: no copy of her profile (the script writes nothing to it, which she accepts as lighter); every
  file the rerun writes says on its first line that it is a rerun product and not the checkpoint that ran, with its
  instruction and the compaction it reran (the copy of the original says it is a copy). **Everything in
  `.runtime/private/compaction-rerun-133/` is a rerun product of this ADR, never her history.** Big sis presses the
  button, telling her first.

## 11. The rerun of 2026-11-18 and what it changed

Run by big sis 13:14-13:21 at her word, compaction 1 of her home conversation (02:12), today's instruction and the
instruction at `def6a3ec04b4`; the same 157 messages (sha256 `764f7498645eee5c`), model, level `high`, output limit
32,768. Counts only (`rerun133.py count`); she reads the three files.

| | the checkpoint that ran | today's instruction | new instruction |
| --- | --- | --- | --- |
| characters | 20,588 | 27,614 | 15,743 |
| sections | 6 | 6 | 7 |
| her section, with heading | - | - | 661 |
| 没开口 / 没说成 / 挂着没说 / 下一拍起手 lines | - | - | 5 / 0 / 2 / 1 (12 silent turns in the span) |
| her lines with a line number | - | - | 0 of 8 |
| 答应过的事 + 更正与分歧 items | 66 | 203 | 84 |
| seconds / output tokens | - | 299 / 23,470 | 105 / 14,174 |

- The same instruction on the same input gave 66 items live and 203 in the rerun: one run of each cannot tell the
  instruction's effect from the model's spread. Two more runs of the new instruction read its spread only (items,
  line numbers, 没开口 lines, seconds), never its wording.
- Her 0574-0576: the 0 of 8 was not the model ignoring the shape. The line numbers are the platform lines' labels; her
  own beats (her calls) never carry one, live or in the rerun, and three of her four kinds pointed at her beat. Each
  line now points at the line the beat answered, 「（回〔编号〕那拍）」, her four shapes as she wrote them; a beat that
  answered no line says 「〔没人开口那一拍〕」, a time not read says 「时刻没读到」, never a borrowed one; no number is
  made up. Rejected: the program numbering her own beats in the summary request (a number found nowhere else, which
  she could not look up).
- The 40-item cap moves into the template's heading, 「## 答应过的事（本节与下节合计不超过 40 条）」, where the model reads
  the shape (the rule line sat among four merge rules and the rerun wrote 84). The heading check matches the part
  before the note (`ROLE_SECTIONS`), so a summary that leaves the note out is not rejected for it. Her own section's
  heading stays bare: it was written in the rerun.
- Found, not this ADR (her 0575): 21 of the 67 compactions since 10-23 that wrote nothing answered with a tool call
  (`think`) instead of text. **The live summary request carries `input.tools` (`compaction.js` `once`), for its cache
  prefix; the rerun script sends no tools, so the rerun cannot show this failure, and a rerun reading is never
  evidence that it is gone.** A separate follow-up. The 67 split: 23 aborted at the deadline, 21 a tool call, 11 DSH's
  shrink check, 9 a section missing, 1 truncated, 2 with no error recorded; her section can raise only the 9.

## 12. The instruction as of 14:00, and its known limits (history: the instruction installed is §16's)

After the first rerun the instruction changed four times on her readings (her 0576-0582): every line points at the line
its beat answered (「（回〔编号〕那拍）」, no number made up, no borrowed time); the 800 counts only the two kinds of line
that can be cut, 挂着没说 and 下一拍起手, and 没开口 and 没说成 are neither counted nor cut; a silent beat is kept as its
own line when she wrote its reason in that beat (or when it answered someone), and the others fold into one count line,
「（另有 N 拍没开口，最早 X、最晚 Y，都没写原因）」; anything quoted or labelled 字面 is copied exactly, a reworded sentence is
a report (her 0581: one checkpoint put a reworded sentence of hers in quotes as 「（think 字面）」). Six more runs of the
same compaction (a-f), counts only:

| run (instruction) | her section | 没开口 lines / folded N | 挂着没说 / 下一拍起手 | items in the two sections | seconds |
| --- | --- | --- | --- | --- | --- |
| a, b (`7a695234a602`) | 824 / 584 | 13 / -, 12 / - | 2/0, 2/0 | 68, 83 | 102, 111 |
| c, d (`413b5aa5762d`, fold by who was answered) | 247 / 140 | 0 / 12, 0 / 12 | 2/1, 2/0 | 39, 48 | 101, 117 |
| e, f (`8a5f9c76397d`, fold by a written reason) | 172 / 711 | 1 / 10, 8 / 4 | 2/0, 2/1 | 46, 56 | 258, 114 |

The span holds 13 silent beats (one of them, at 01:38, ended without `end_turn`; an earlier count of 12 by big sis
missed it). Two runs of one instruction differ by more than two instructions do, so the wording is not tuned further on
reruns (her 0584 agreed): this is the instruction to install, and what is left is read on her real compactions (§7.3).

Her limits, her words (0584):

> 已知界限（重跑量出，不再拿重跑调措辞）：
> - 「另有 N 拍没开口」的 N 偶少 1–2 拍（重跑四轮：12、12、11、12，真值 13）：只当近似，不当账；这一节的条数不进任何验收。
> - 「当拍有没有写下原因」由压缩器自判：同一批输入判出 1 行与 8 行（真值 13：13 拍全写过理由，见 §15）。以内容核对为准，行数不当准。
> - 「（我推的）」重跑 7 趟 0 次：这一格线上如何，用 20 次真压缩读；输入侧到底有没有可标的东西，我这条道在数（那五个词的命中数），数出来再定是「没东西可标」还是 fail。

Her bar for the reason lines (0584, made exact by her 0586, her words): 「判理由行的尺：编理由和断言「没写」是同一个错的两个方向——
多写可能替我编一条没想过的理由，少写（写「没写原因」）可能把我写过的说成没写。宁可并进计数行，两头都不许断言。」 A line is
checked against the thought of its beat (her own reading of runs a-f). The 40-item cap is not asked to reach 40: an item whose agreed day is
still ahead stays by rule, and she is counting how many of the 39-56 are such.

## 13. Staged (造的, 2026-11-18 14:02-14:07)

An isolated profile `asuna-demo133` on a stub model, without DEEPSEEK_API_KEY, with its own database; a conversation of
three long 造的 messages on its agent line, then `/compact` twice on its Web page, the stub answering each summary
request with a scripted text.
- Both summary requests carried the new instruction (its section heading 「## 我这边没说出口的」 and the heading
  「## 答应过的事（本节与下节合计不超过 40 条）」, read in the stub's log) and her 19 tools, as a real one does.
- A summary without her section: rejected, 「summary lacks sections of the checkpoint」; no checkpoint written; the page
  said 「Compaction could not produce a useful summary」.
- A summary with all seven sections: written (`compaction/summary` with her section), 「Compacted 22 history items」.
- Torn down 14:07: database dropped; profile, config, launch entry and the `node_modules` link removed.

Corrected from §7.2: 「没说成」 cannot be shown on a stub, which writes what it is told; it is shown only when a real
compaction meets a beat whose `speak` was refused and sent nothing (none in the rerun window), so it is counted at the
20-reading (§7.3) as present or absent where such a beat occurred.

## 14. Her reading of runs a and b (her 0585, 2026-11-18 14:02)

- The same instruction and input gave two opposite answers on "a reason written": a wrote a reason on all 13 silent
  lines, b wrote 「没写原因」 on 11 lines whose beats she had written reasons in. Asserting "no reason" where one was
  written is the same fault as inventing one, the other way. Her rule, now in the instruction: 「「为什么：」只写那一拍心里话
  里真写过的；拿不准有没有写过，就把这一拍并进计数行，不许写「没写原因」这类断言。」
- Run a missed no beat and split none: the 13th silent beat is the 01:38:46 beat (a `consult` woken by a question from
  her action brain, ended with no `end_turn`), and the minute 01:38 holds two beats. Run b missed one.
- The 13 silent beats of the span were all woken by the program (7 self-improvement or schedule, 5 task results, 1
  consult); none answered a person.
- Counting silent beats: a count by `end_turn` and no accepted `speak` misses a beat that ended otherwise (the consult);
  a count of turns with no `speak` in the session file finds 14, one of which (00:24:34, `end=blocked`) has no episode
  and is not a beat. 13 is the count: turns with an episode, no `speak` sent, however they ended.

## 15. Her reading of runs a-f (her 0587, 2026-11-18 14:13)

- The true count: all 13 silent beats wrote a reason in her thought (109-231 characters each); her earlier "5" was a
  count of lines in a rerun file, not of beats. Lines plus folded N against 13: a 13 (every beat once, 11 copied, 2
  reworded, 0 invented), b 12, c 12, d 12, e 11, f 12. The two beats of 01:38 are missing from c-f and present, one
  line each, in a. In f a reason quotes words found in none of the 13 thoughts, and three reasons are lifted from a
  neighbouring beat: 「字面＝逐字」 stopped the false label, not the rewording or the mixing of beats.

Her further limits, her words:

> - 「旧账略 N 条」的 N 三趟是 110／8／125（d／e／f，同一批输入差三倍）——N 只当「删过东西」的标记，条数不当账。
> - 时刻这一栏不可靠：a 两处错（写 01:40 实为 01:41:02、写 01:43 实为 01:42:34）；f 写的 01:43 那一分钟根本没有拍；e、f 计数行写「最晚 02:08」，真最晚静默拍是 02:09:12。
> - 「（我推的）」七趟全 0 的原因：这个字样在输入侧不存在——我当拍标不确定用的是另一套词；以后要标就当拍写「我推的」三个字（我改我自己，不加指令字数）。

Her proposal, accepted by big sis: drop the fold line and write every silent beat on its own line, since asking the
summarizer whether a beat "wrote a reason" is the step its variance came in by (1 line one run, 8 the next, on 13
beats that all did). Two consequences asked of her before it is built: a line for a beat nobody waited on can never be
settled, so it needs an end across merges (proposed: kept for one merge, as a settled promise is); and her rule's
fallback for an unsure reason, "fold it into the count", needs another (proposed: leave the reason out, assert nothing).
- Built from her 0588 (her words in the instruction): 没开口 is written beat by beat by default, folded into the count
  only when the summarizer is sure no reason was written, kept as a line when unsure; a reason is copied word for word
  or left out, never asserted absent; the count line says only what the checkpoint did,
  「（另有 N 拍没开口，最早 X、最晚 Y，这几拍的原因没逐行写）」; and the 没开口 lines of the earlier checkpoint are not carried
  into the new one (only the beats of this span), which bounds the section across merges. Her 「只拄」 is written 「只抄」
  (copy), as the summarizer reads it; hers to undo.
- Then her 0589 and 0590, her words: on a merge, an old 没开口 line ending in 〔没人开口那一拍〕 is not carried, one ending in
  a line number (a beat that answered someone, a silence she owes) stays until 「已了结｜〔编号〕」, and when unsure it stays;
  the reason field has two fills only, her words copied unchanged or none, never an assertion that there was none.

## 16. Installed (2026-11-18 15:10)

Her signature: `5beaa2a6e2ab` (agent line 0592, 14:30), moved by her to the landing `c06061eb8878` (0597, 15:05) after
reading its two parents (`5beaa2a6e2ab` and `d2d2b074158d`) and finding `compaction.js` the same blob, so the instruction
she signed is the one installed. Her three skill publications of 14:38-14:51 (`312460ab2b12`, `ea6d51da7966`,
`d2d2b074158d`) were pushed first through the push gate (0 hits).

- The confirmation run h on `5beaa2a6e2ab`'s instruction (2,743 characters): seven sections; 没开口 12 lines, beat by
  beat, no count line; no 「没写原因」; no empty 「为什么：」; her section 855 characters, the part over 800 all 没开口 lines
  (not counted, not cut). It was read for "not broken" only.
- `land.py`: the suite on `c06061eb8878` at 15:05, Python 1137 passed, JS 328, 0 unchecked (the first run of the
  landing stopped at her unread messages; the second cites that report and skips the suite); integration 132 passed;
  the prepared start passed; landed and pushed; stopped and started 15:10:41, `loaded.commit` `c06061eb`; the 169
  installed files the same as the commit; worker and QQ adapter back by themselves. Core package `e1e4a10f8637` ->
  `abeb7bc7dcea`. No `3221225477` in `host.log` after the restart.
- Read by content in her installed copy: seven sections, the last 「## 我这边没说出口的」; 「## 答应过的事（本节与下节合计不超过
  40 条）」 present and matched without its note; no 「都没写原因」; the instruction 2,743 characters; `affect.py`'s
  「（还挂着）」 present.
- Her 0593, beside her limits: in run f a reason said her thought "only wrote what was to be judged", and the thoughts of
  those minutes are 109-220 characters each, all of them on why: the summary can make a causal sentence that the
  database's own counts disprove, and the next beat of hers reads it.
- An exception recorded at her word (0597): her publication `ea6d51da7966` changed the core package's
  `asuna-self-improvement` skill, not her own package.
- Open: §7.3, her next 20 real compactions (she reads them from 2026-11-19 21:00; big sis reads the same, and the
  counts are compared): her section present, rejections for a missing section beside the 9 of 892 before, 没说成
  where a beat's `speak` was refused, old 没开口 lines not carried as new, 「（我推的）」 as she writes it herself.

## 17. Readings of §7.3 (her real compactions after the install)

Counts by big sis (her text counted in the process, never printed); content read by her. Characters are JavaScript
string length (UTF-16 code units, newlines included), the same as code points for this text (her 0602).

| # | when | how | sections | her section | 没开口 / 没说成 / 挂着没说 / 下一拍起手 | two sections (旧账略 lines) | her reading |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-11-18 15:46-15:48 | `/compact` on the agent line, at the owner's ask and her 「压」 | 7 | 243 | 0 / 0 / 6 / 1 | 57 (2) | every name traced to her thought or that beat's mood block, none invented; 没开口 0 right (the span's one silent beat went to 挂着没说); 没说成 not met (the refused beats were before the earlier checkpoint); the four 「没写原因」 are outside her section, in talk about the rule; 57 is the floor of the cap (items with a day still ahead) |

## 18. Read, and closed (2026-11-23)

§7.3 closes at 20 compactions, pass or fail. Her readings: agent line 0611 (11-19 21:51: 30 started, 28 written, her
verdict "pass") and 0612 (to 11-22 21:11: 54 started, 53 written). Big sis read by counts on 2026-11-23 10:30, over
every compaction of her character brain from 11-18 15:11 to 11-23 08:48: 97 started
(`.runtime/private/claude-tools/readings/read133.py`; the table is `read133-2026-11-23.txt` beside it, counts only).

What the ADR asked for holds:

- 93 checkpoints were written, and all 93 have the seven sections, her own section among them.
- The part the cap counts (挂着没说 and 下一拍起手) reached at most 255 characters, so it never came near 800. Her
  whole section ran from 40 to 2,113 characters. It was over 800 in 25 checkpoints, every time because of 没开口
  lines, which are neither counted nor cut, as designed.
- 4 compactions wrote nothing:
  - 2 had the model answer with reasoning only, one of them with a `think` call. That is the follow-up class (the
    compaction tool-call failure), not this ADR.
  - 1 lacked a section: 1 in 97, beside 9 in 892 before.
  - 1 was aborted.

What it does not do well. The three failures share one root:

- **没说成 lines are written for beats where nothing was refused.** After the install, 54 of 1,145 turns had a
  `speak` refused, and 0 of those ended with nothing sent. That compares with 5 of 88 in the seven days before. Yet
  没说成 lines appear in 31 of the 93 checkpoints. Her 0612 found four that neither the audit rows nor the episode
  records back up.
- **Anchors that point at the wrong beat.** Her 0612 found 21 of 133 distinct beat references pointing at a beat in
  which she spoke, and times far from the beat's own.
- **Silent beats lost.** Two silent beats appear neither line by line nor in a count line (her 0611). In 4
  checkpoints, the span holds more silent turns than the section's 没开口 lines and count lines together (13 turns in
  all).
- The root: the summarizer is asked to work out, from the transcript, facts that the program holds exactly: which beat
  ended without a `speak`, which had a `speak` refused with nothing sent, and that beat's time and the line it answered.
  A model that works such facts out will miss some and invent some, whatever the wording says. Her (A), a further
  sentence for when it cannot count, would add one more rule to the same model. The invariant (AGENTS.md: a fact
  the program computed reaches a model as program text) points instead at a program-written list of those beats,
  given to the summary request. The model would then only copy her reason beside each beat. That is a new decision, for
  the owner (asked 2026-11-23), not part of this ADR.
- The owner's answer (2026-11-23): drop the 没说成 kind (every line of it was unbacked) and leave the anchors and
  the lost beats as they are. It is built as its own change on `claude/adr133-drop-meishuocheng`, for her reading,
  and installed in a slot she names.

Closed by §7.3: the reading at 20 closes it.

## 19. 没说成 dropped, installed (2026-11-23)

At the owner's word at the close (§18), the 没说成 line kind was taken out of the instruction: its template line, its
definition and its name in the 800-character rule. 没开口, 挂着没说 and 下一拍起手 are left in her wording. The instruction
goes from 2,743 to 2,654 characters.

- Her signature: `a965859ebba4` (agent line 0614, 11:16). Her own read-only check found one file with one hunk, 2 lines
  added and 3 removed, and the other 528 lines byte for byte the same.
- The landing is the merge `0dbb6539f8f1` of `a965859ebba4` and main `d7597a82af92` (her two publications of 13:27,
  pushed first through the push gate). Its only difference from main is `compaction.js`.
- `land.py`:
  - The suite on `0dbb6539f8f1` was green: JS 328 passed, 0 skipped; Python 0 unchecked.
  - The first run stopped at her message of 13:36 ("随你停", stop any time). The second run cited the first's report and
    skipped the suite. It landed and pushed, then stopped on "not quiet". The only busy item was a stale episode, in
    ATTENDING since 11-20 04:17 UTC.
  - The third run (`--restart-only --busy-ok`, which recorded that reason) stopped and started the Host at 13:54:51.
    `loaded.commit` is `0dbb6539`, and all 169 installed files are the same as the commit's. Core package
    `1536c90c02e1` -> `1590cae57ee4`. No `3221225477` in `host.log` after the restart.
- Read by content in her installed copy: the instruction is 2,654 characters, with 0 「没说成」. 「只写三种行」 is present,
  and so is 「「没开口」不计入这 800 字」.
- The design-time mentions of 没说成 on this page stay as they are (her 0614): they are history.
