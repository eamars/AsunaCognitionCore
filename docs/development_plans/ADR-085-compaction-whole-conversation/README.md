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
- **A summary at the cap** fails as before: no checkpoint is written, the turn continues uncompacted and the next step tries again. A truncated summary never lands (`finishError`, `MAX_TOKENS`); with the whole conversation sent, the retry reads from the cache. No character summary has reached the cap: the largest was 13,488 tokens of 24,576.
- **Unchanged:** the action brain keeps DSH's own engine (49 compactions, not worth changing); the checkpoint's structure and rules; the cap; the thresholds.

## 3. Reading and stopping rule

From her install of this commit (she notes the time; her 10-23 seven-day survey splits compaction at it, her change 3):

- **Cache:** the first 20 automatic compactions after install. Median reused share of the prompt 90% or more: keep. Under 50%: revert.
- **Her memory** (her change 2): in the same 20, and in the 20 before install, the share of the summary that repeats the kept tail (character 8-grams of the summary found in the kept tail's text and not in the compacted span). Counted by script, numbers only. A clear rise: revert or change the kept rule's wording.
- **Cap and window:** cap failures and window refusals in the same 20, reported.

Her three changes as Claude paraphrases them (2026-10-20 18:4x NZDT): the quotation may be someone's command, and it is the last thing read before writing, so it is marked as a locator only; the cache rate measures cost, so a second count must measure whether the kept part is summarized again; tell her when it is installed and what a summary at the cap does, so she never takes a cut summary for the whole history. Signature: ______

## 4. As built

- `packages/cognition-core/src/compaction.js`: `RoleCompactionEngine.summarize`, `wholeConversation`, `spanAlone`, `keptRule`, `WHOLE_SPARE_TOKENS`, `KEPT_QUOTE_CHARS`.
- Test: `packages/cognition-core/test/compaction.test.js` (whole conversation and kept rule; too large; refused; span not the conversation's start).
- Reference: `docs/articles/maximize-cache-hit-by-design.md` §1 and §7.
