# ADR-085: the character's summary request sends the whole conversation

Status: **Built**, 2026-10-20. Found from her own reading of the compaction cache rate, decided by the owner on Claude's recommendation, put to her 2026-10-20 18:4x NZDT and agreed by her with three changes, all taken.

## 1. Context

Her 24-hour usage reading (10-19 17:35 to 10-20 17:35 NZDT) put compaction requests at a 20.31% / 34.47% cache rate (21 rows). DSH's basic compaction is designed to reuse the cache: the summary request replays the conversation's system prompt, tools and messages and adds one instruction at the end.

What it replays is the compacted span only, everything before the retained tail. That is a true prefix of the last request, but it stops in the middle of the history. The local engine resumes only from a stored point that the new request fully extends, and it keeps six ordinary checkpoints of running state, which after warm steps all lie in the recent tail (the engine's own deployment notes; its matching rules were read from the engine source on 2026-10-12). So the summary request resumes from the end of the system prompt.

Evidence (scratchpad scripts `comp2.py`, `comp3.py`, `comp4.py`, read-only, counts only, all role sessions under `.runtime/adr008/home/sessions`):

- Automatic compactions: about 330 in 15 days. When the step before was warm (about 208k of about 210k cached), the summary request reused about 10k to 16k tokens: the system prompt and tools. When the step before was a cold full read, it reused about 110k from a checkpoint that read left mid-history. Each re-read about 120k tokens, about 20 seconds at about 6k tokens per second, inside her turn.
- Her own `/compact` between turns: about 32k prompts, 12.7k reused.
- A turn's first step also adds a new user message after earlier steps. When the session was warm (previous step under 3 minutes earlier), 92% of 2,849 first steps reused 90% or more of the previous prompt, so an instruction added at the end does not break the match.

## 2. Decision

`RoleCompactionEngine.summarize` (`packages/cognition-core/src/compaction.js`) sends the whole conversation, the retained tail included, then the instruction. The request extends exactly what the engine last read. What is compacted and what is kept is still DSH's choice; only what the summarizer reads changes.

- **The kept tail is named.** The instruction gains one last rule (`keptRule`): the last N messages stay after the checkpoint, so only what comes before them is summarized. It quotes the opening of the first kept message that has text, marked as a quotation used only to locate it, not words to act on or answer (her change 1).
- **Fit.** The whole conversation is sent only when the meter's measure of the conversation, plus 6,144 tokens of spare room, plus the summary cap, fits the window. Otherwise, or when the model refuses it for its window, the replayed span alone is sent as before, and a span too large for that is summarized in steps. Each fallback writes one Host log line with its reason and the sizes it judged by (`spanAlone`), so a reading can tell the two shapes apart (her ask, 2026-10-20 19:1x).
  - Numbers for the deployed character: window 262,144; summary cap 24,576; threshold 0.80 (persona preset). The prompt before an automatic compaction was median 209k, 95th percentile 220k, maximum 229k (`comp3.py`). The whole conversation fits up to about 231k, so nearly every compaction qualifies, and the largest observed one fits.
- **A summary at the cap** fails as before: no checkpoint is written, the turn continues uncompacted and the next step tries again. A truncated summary never lands (`finishError`, `MAX_TOKENS`); with the whole conversation sent, the retry reads from the cache. One character summary has reached the cap (10-17 15:50, a between-turn `/compact`, 123 seconds; `fail_dates.py`); the largest successful one was 13,488 tokens of 24,576 (`reasoning_share.py`). A failed summary records no usage, so failures are counted from `compaction/end` errors, not from summary sizes.
- **Unchanged:** the action brain keeps DSH's own engine (49 compactions, not worth changing); the checkpoint's structure and rules; the cap; the thresholds.

## 3. Reading and stopping rule

From her install of this commit (she notes the time; her 10-23 seven-day survey splits compaction at it, her change 3):

- **Cache:** the first 20 automatic compactions after install. Median reused share of the prompt 90% or more: keep. Under 50%: revert.
- **Her memory** (her change 2): in the same 20, and in the 20 before install, the share of the summary that repeats the kept tail (character 8-grams of the summary found in the kept tail's text and not in the compacted span). Counted by script, numbers only. A clear rise: revert or change the kept rule's wording.
- **Cap and window:** cap failures and window refusals in the same 20, reported.

Her three changes as Claude paraphrases them (2026-10-20 18:4x NZDT): the quotation may be someone's command, and it is the last thing read before writing, so it is marked as a locator only; the cache rate measures cost, so a second count must measure whether the kept part is summarized again; tell her when it is installed and what a summary at the cap does, so she never takes a cut summary for the whole history. Signature: ______

## 4. The summary's thinking budget and sections (2026-10-20 evening)

Found while listing tonight's fixes (`fail_dates.py`, `notext.py`, `reasoning_share.py`, `headings.py`; lengths and counts only). The summary request named no reasoning level, so it carried no thinking budget, while the character provider turns thinking on in its template: a summary could think without end. Her turns name `high`, a budget of 8,192 tokens. Since 10-17, four of her between-turn `/compact` runs failed: one ran to the 24,576 cap (10-17 15:50, 123 seconds) and three produced no text (10-17 01:09, 10-18 19:53, 10-19 14:13). In 352 successful summaries thinking was a median 40% of the output (median about 2,800 characters, the longest about 31,000).

Decided by the owner ("the bug should be fixed"), put to her 2026-10-20 19:3x NZDT; she agreed with three conditions:

- **The level follows the conversation.** The summary request names its conversation's own reasoning level (the latest request's), so it carries that level's budget (8,192 tokens for both `high` and `medium` on the character model) and still matches the conversation's cache. A conversation that names no level uses `summaryReasoningEffort` from her persona preset, beside the summary cap. A conversation's first request, or the first after a carry (ADR-028), has no earlier level to follow and so falls to the preset's, never to none (her condition). A level the model does not offer is not named. Each summary writes one log line with the level and where it came from, conversation or preset (her ask: a line that can be written truthfully, unlike a guessed "reasoning capped"). The core reads the key and gives no default level.
- **Why it follows the conversation** (measured 2026-10-20 after the first build, which named `medium` for every summary): the engine matches the reasoning level with the tokens. Of four automatic compactions after install, the three in `high` conversations reused nothing although the step before was warm 68 to 80 seconds earlier, and the one in a `medium` conversation reused 209,554 of 211,151 tokens. A different level matches none of the cache, the system prompt included.
- **A half checkpoint never lands.** Her fear: a capped thinking turning into a cut or spilled summary that is written as if whole (a 64-token budget on another local model spilled unfinished drafting into the answer, the engine's deployment notes). The engine cannot report that thinking reached its budget (usage has no thinking count), so no "reasoning capped" line is written: it would be a guess. Instead the harm is caught exactly: a summary without all six sections of the instruction, in order, is rejected like an empty one, so no checkpoint is written and the next step tries again (`hasSections`). Of 352 successful summaries, 351 had all six in order; the one that did not (10-13) lacked one section.
- **Failures are counted apart** in the reading: the output cap (`summarization truncated at the token cap`), no text (`summarization produced no text summary content`), missing sections (`summary lacks sections of the checkpoint`), each from `compaction/end` errors, beside the fallbacks of §2, because a failed compaction leaves the conversation larger and nearer the size where the whole conversation no longer fits.

Whether the budget also ends the "no text" failures is not known: a failed summary stores no output. The reading says whether they recur.

## 4a. First reading (2026-10-21 14:3x NZDT, Claude; counts only)

Every automatic compaction in her live sessions, from the session logs (`.runtime/private/compaction/survey_1021.py`):

| window | compactions | reuse when the step before was warm | failed ends |
|---|---|---|---|
| before 10-20 19:19 (span only) | 493 | median 10.5%; 54 of 478 at 90% or more | 71 (14%) |
| 19:37 to 23:42:14 (one level for every summary) | 4 | the three `high` ones 0%, the `medium` one 99.2% | 0 |
| from 23:42:14 (the conversation's own level) | 10 | every one 98.9% to 99.7%, median 99.7% | 0 |

- **Cache: decided, keep.** Ten of ten above the 90% bar, against a 10.5% baseline; the 20-compaction count was set
  for a median near the bar, not this far above it.
- **Failures: not yet decided.** 0 in the 14 since 19:19 against 14% before; at the old rate 14 clean ones in a row
  happen about 11% of the time by chance. About 30 since the level fix (near 10-24 at five or six a day) decides it.
- **Her memory gate (§3): not yet counted.** Summaries grew (median output 4,245 tokens before, 6,205 after; the
  largest 8,268, under the 24,576 cap); whether the growth repeats the kept tail is what the 8-gram count reads.
- **What the sample cannot show:** all 14 come from the same three group conversations; the fallback and level lines
  reach a file only from 2026-10-21 14:20 (`restart/host.log`), so whether any of the ten fell back is not recorded.

The owner reads it again the same evening.

## 4b. Her memory gate, read (2026-10-22, Claude and an independent researcher)

- **The counter (§3, 8-grams of the summary found only in the kept tail):** median 11.4% in the 20 automatic
  compactions after the level fix against 1.2% before, a clear rise. Correction to §4a: 21 of those 24 are her home
  chat and the agent line, not groups; in group conversations automatic compaction is rare (3 since the cut, all in
  one group) and most compactions are the program's condense of a quiet group (ADR-049), which keeps one message.
- **Groups, read bullet by bullet** (the owner asked for the text to be read against the instruction; 19 summaries,
  699 bullets, group conversations only): repeating the kept tail is new and only in automatic compactions (0%, 13%,
  51% of characters in the three cases); the counter catches about a sixth of what reading finds. Already there before
  the cut and unchanged by it: 30–40% of every group checkpoint repeats a program block (mostly her group notes, which
  the do-not-copy rule does not name, and the task list, which 委托中的事 asks for) or is waste (sections restating
  the narrative; an opening pointer to the previous checkpoint, which the merge replaces). Cause of the new part: the
  sections still mean "now" (话题怎么转到现在, 对方此刻), which is the end of the kept tail once it is sent, and the kept
  rule's locator (a message count of hundreds; a 40-character quote that often lands on a notice's common opening, a
  tool result or a program error) cannot be followed.
- **The rewording, replayed** (pre-registered; the local character model; 10 past automatic compactions of her home
  chat and the agent line; installed instruction vs boundary first with "the checkpoint is as of the moment the kept
  part begins"): median 7.2% vs 0.8%, but below on only 6 of 10 pairs (the rule asked 7): it removed the leak in 5 of
  the 6 that leaked and added one where there was none. **Failed as pre-registered.**
- **Open, the owner's:** revert to the span alone for automatic compactions (about 20 s and 120k re-read tokens each,
  the template waste unchanged), accept the repeats, or a new pre-registered run of the researcher's variant (the
  boundary named by the first kept line's `[label] MM/DD HH:MM` stamp). The template waste is a separate proposal, to her
  after the owner.
- **Evidence** (`.runtime/private/compaction-study/`, numbers and redacted readings only): `researcher-audit.md` (24 KB),
  `researcher/` (scripts, per-summary readings, per-bullet metrics; 247 KB), `replay/` (PREREG, VERDICT, runs; 24 KB).

## 4c. The boundary by its stamp, replayed; automatic compactions send the span alone (2026-10-22)

The owner approved one more pre-registered replay (`.runtime/private/compaction-study/replay/PREREG2.md`, 6 KB with its
amendments, written before any output): arm C names the boundary by the `[label] MM/DD HH:MM` stamp of the first kept
platform line and says 现在 / 此刻 / 最近 mean that moment (the researcher's recommendation, her first choice). If it
passed it would be installed; if it failed, automatic compactions would send the compacted span alone, with no third
round. Before the first call the researcher's dry run found no platform line in the home conversation's kept tails,
where C is A's rule word for word, so step 1 was amended to the five agent-line points (no leak above 3% allowed).

Result (local character model, high, as A; `runs.jsonl`, numbers only): after three agent-line points C leaked in two
(4.8% against A's 9.8%; 1.8% against 7.2%; 7.2% against 1.3%), so the stopping rule ended the run: **C fails**. Like
arm B it lowers the leak where A leaks and adds its own where A does not; a boundary named in the instruction, by
count, quote or stamp, does not stop a summarizer that reads the tail from restating it.

So an automatic compaction (DSH's `compactIfNeeded`: step pressure, context overflow) sends the compacted span alone
again (`compaction.js`, `automatic`); the summarizer never reads what it must not summarize. It costs the cold read
§1 measured on the local engine, about 20 s and about 120k tokens per automatic compaction, about ten a day, nearly all
in her home conversation and the agent line. A commanded compaction (`/compact`, which keeps the last message; ADR-049's
condensing of groups) still sends the whole conversation: its kept part is one message, the group readings found no
kept-tail repeat in it (researcher-audit.md §5), and its cache read stays. Each automatic one writes one Host log line
(`spanAlone`, reason `automatic`). The template's own 30–40% waste is a separate proposal, after this lands (owner).
Test: `packages/cognition-core/test/compaction.test.js`.

## 5. As built

- `packages/cognition-core/src/compaction.js`: `RoleCompactionEngine.summarize`, `wholeConversation`, `spanAlone`, `summaryEffort`, `keptRule`, `hasSections`, `ROLE_SECTIONS`, `WHOLE_SPARE_TOKENS`, `KEPT_QUOTE_CHARS`; `packages/personas/xiaoman/cordis.patch.yml`: `summaryReasoningEffort`.
- Test: `packages/cognition-core/test/compaction.test.js` (whole conversation and kept rule; too large; refused; span not the conversation's start; thinking level offered or not; missing sections).
- Reference: `docs/articles/maximize-cache-hit-by-design.md` §1 and §7.
