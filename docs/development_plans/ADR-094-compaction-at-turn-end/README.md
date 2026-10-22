# ADR-094: Compaction at the turn's end

Status: **Built 2026-10-23, not installed.** Decided by the owner on 2026-10-23 (~11:45 NZDT) on the recommendation
of a review of the whole compaction design run on Fable 5.1 at his instruction (`.runtime/private/compaction-review/
report.md`, 2026-10-23 10:30–10:50 NZDT). Xiaoman agreed the same day with three conditions (§8): the first needs a
DSH change and is the owner's; the other two are folded into §6. It installs in a restart of its own, with nothing
else, and is read as §6 says from that restart's `back_at`.

## 1. The owner's words

"Yes, go ahead with the turn-end compaction. Reason: Even human cannot track the word-by-word history in a busy
group, or after a prolong period if time. Keeping word-by-word memory is a waste of resources so I support your
decision."

His brief for the review (2026-10-23 ~10:20): "The compaction cache hit is low again. I want you to do a brief research
first. If the design is legitimately wrong, then launch a fable 5.1 card session to review the full compaction design,
and make proposal of the systematic fix. Noted the design must satisfy both local and API usage. For local deployment,
if the strata server discards the cache there is nothing to help, but the design of Xiaoman should NOT be the failure
point. We should do whatever the optimization we should do before blaming the model server."

## 2. What was found (role sessions since 10-18; numbers only; `.runtime/private/compaction-review/scripts/`)

The deployed character: window 262,144; `thresholdRatio` 0.80 (compaction at 209,715 tokens); `retainRatio` 0.16, a
kept tail of 36,700 tokens in DSH's measure (characters ÷ 4), which for her Chinese is about 100k real tokens and
about 30 of her steps.

The local engine resumes a request only from a state it still holds and that the request fully extends: the live end
of the conversation, or one of at most six checkpoints, taken at the start of each assistant turn (the end of each
request's prompt) and every 16K prompt tokens, rotated by least recent use, the system prompt's end kept for good
(the engine's `docs/DETAILS.md`, "Conversation cache"). After five warm steps every rotating checkpoint lies inside the
last five steps.

| period (NZDT) | kind | trigger | n | summary request reuse, median | summary duration, median s | next request prompt, median | next request cached | assistant msgs in the kept tail, median |
|---|---|---|---|---|---|---|---|---|
| to 10-20 23:42 (span alone, no level) | home | automatic | 14 | 11.9% | 54 | 113k | 14.8k | 36 |
| to 10-20 23:42 | agent line | automatic | 16 | 10.7% | 54 | 106k | 14k | 32 |
| to 10-22 10:36 (whole conversation, ADR-085 §2) | home | automatic | 12 | 99.7% | 47 | 115k | 14.3k | 39 |
| to 10-22 10:36 | agent line | automatic | 12 | 99.7% | 45 | 108k | 14k | 28.5 |
| since 10-22 10:36 (span alone + level, ADR-085 §4c) | home | automatic | 9 | 12.1% | 69 | 117.5k | 14.3k | 34 |
| since 10-22 10:36 | agent line | automatic | 14 | 11.2% | 70 | 118.8k | 14.3k | 30 |
| 10-20 to 10-23 | groups | commanded (`/compact`, ADR-049) | 18 | 99.3–99.6% | 27 | 36–38k | 7–10k | one message |

- The span-alone summary request reuses the system prompt and tools (~14k) and nothing else, although the step before
  was warm in every case: the engine has no state where the span ends. When the step before was a cold prefill (11 of
  58) it reused 81.6%, a surviving every-16K checkpoint.
- The step after a compaction reads 106–119k with 14k cached in every period, the whole-conversation one included:
  ADR-085 saved the summary request's read and never touched this one. The conversation is ~210k before a compaction
  and ~110–118k after it.
- Per automatic compaction in home and the agent line since 10-22: median 218,726 cold tokens (summary request plus
  the next step), about 36 s of prefill inside her turn, plus the summary's generation (69 s median, 46 s when the
  request was cached). 58 such compactions from 10-20 to 10-23: 14.5 a day. Failed ends since 10-18: 0.
- Her turns since 10-18 (home 378, agent line 470): 4 / 3 steps a turn (p90 7 / 6), growth 7.3k tokens a turn
  (p90 16k / 15k), the first request of a turn adds 4.1k / 4.6k; the idle gap before a turn is a median 421 s / 193 s,
  under 60 s in 14% / 24% of turns.

**The broken invariant.** The kept tail is sized in tokens; the engine's memory is in steps (five). A compaction's
span therefore ends about 30 steps before any point the engine holds, whatever the instruction says, and the large
tail is re-read cold behind the new checkpoint. The invariant restored here: **a compaction's span ends where the
engine's state is, at the live end of the conversation.** Then the summary request reads only the instruction, the
kept part is one message so the next request's cold read is small, and the summarizer never sees a kept tail (ADR-085
§4b–§4c's restatement does not arise). On a hosted API the span-alone request already hits (block prefix cache);
there the waste is the ~100k re-read after every compaction and the compaction count, which the same change halves.

## 3. Decision

1. **Trigger (ours).** When a character-lane conversation's agent goes idle after a turn (`agent/status` in
   `packages/cognition-core/src/index.js`, `turnEnd`) and DSH's measure of it is at or above `turnEndRatio × window`
   (`RoleCompactionEngine.turnEndTokens`), the Host runs DSH's own `/compact` on it at once through `compactSession`
   (ADR-049's path): no quiet wait, no notes visit. Only her own conversations (`asuna-role-*`); a conversation with a
   turn running or queued is left for its next turn's end (`compactAtTurnEnd`, `compaction.js`). One Host log line
   says what was done or that it was busy.
2. **Span and tail.** DSH's `compactNow` as it is: everything but the last message is the span; the request is her
   last request plus the instruction (`summarize` treats it as a commanded compaction: the whole conversation and
   `keptRule` for one message). The instruction, its sections, the cap rule and the level rule are unchanged.
3. **`turnEndRatio`** is one number in the engine's config beside `summaryReasoningEffort`, 0.70 by default; the
   deployed character's preset names it explicitly (§7). 0.70 is below the in-turn threshold by 26k tokens, more than
   a turn's p90 growth; 0.7–0.8% of her turns grow more than that.
4. **The guard.** DSH's in-turn compaction at `thresholdRatio` 0.80 with today's tail stays, for a turn that grows past
   the threshold before its end; its log line `span alone (automatic)` counts it.
5. **Groups** keep ADR-049 (quiet-spell condensing, already this shape). Nothing changes in DSH.

**Expected** (from the 18 commanded compactions measured, and `scripts/sim.py` replaying 6 real days of her turns with
this trigger): summary request reuse ≥ 99% on the local engine and at hosted APIs; the next request ~25k (root 14k
cached, checkpoint ~4k, her last message ~1k, the notice that is new in any design) instead of ~118k; ~33k cold tokens
per compaction instead of ~219k; about 7 compactions a day in home and the agent line instead of 14.5 (a compaction
now removes ~160k, not ~95k); 0 guard firings in the replayed days at 0.70 (1 at 0.75); her first reply after a
compaction 2–4 s of re-read instead of ~17 s, and no summary inside her turn.

## 4. The trade, and what changes for her

- After a compaction her conversation holds the checkpoint and her last message, not the last ~10 turns verbatim
  (~100k tokens). The checkpoint carries those turns: ADR-085 §7's template (promises and corrections item by item)
  and her 10-22 reading rules are what makes that hold; fewer compactions mean fewer merges, and each merge loses
  items (§7a: 9–40% after the trim).
- Compaction comes at ~183k instead of ~210k, but about half as often.
- A line arriving during the summary (~46 s) waits for it; today every compaction is a longer wait inside the turn. In
  the replayed days the next turn came within 45 s of a turn-end compaction 1 time in 19 at home and 6 in 24 on the
  agent line (where it is Claude).
- The `/compact` command and its result are in her session log where it happens (`command/run`, `command/done`), as
  the groups' condensing is today. The `restored_from_program` follow-ups after a compaction mostly disappear: the
  next notice is composed from the new surface.
- Nothing in her prompts, tools or instruction changes.

## 5. Rejected (the review's §5)

The whole conversation as the span (ADR-085 §2; restated the tail, replayed twice, and left the ~100k re-read);
shrinking `retainRatio` with in-turn compaction (a token count is not a step count, and the summary still runs inside
her turn); compacting at a turn's first step (the same request, but she waits); waiting for a quiet spell at home
(the next turn crosses 0.80 mid-turn first; the gain is 4 s once the re-read is ~25k); rolling summaries outside the
conversation (more merges, a second store); a separate summarizer session (no shared prefix); more engine checkpoints
(the owner's engine, RAM-bound, and nothing for API routes).

**The owner's, only if wanted later:** DSH's `compactNow` with a retention option (keep the last turn verbatim), if her
reading of the first checkpoints says one message is too thin.

## 6. Reading after install (`.runtime/private/compaction-review/scripts/turn_end_reading.py`)

The window starts at the `back_at` of the restart that installs it (`<data>/restart/last.json`; the script reads it
when given no time), and that restart carries no other change (her condition, §8). The first 20 compactions of her
home conversation and the agent line; numbers only, she reads the text:

- **(a)** Summary request reuse of the turn-end ones: median ≥ 95% keep (today 11–12%); under 80% revert the trigger
  (one config line): the design is wrong, not the tuning.
- **(b)** The next request's prompt: median ≤ 40k (today 118k).
- **(c)** Guard (in-turn) compactions among those 20+: ≤ 2 (today all).
- **(d)** Turns that began within 5 s of a compaction's end (they were waiting), and the summary duration.
- **(e)** Compactions a day: ~7 against 14.5.
- **(f)** Failed ends (cap, no text, missing sections): count, against 0 of 58 since 10-20.
- **(g)** Her reading of the first two checkpoints, as in ADR-085 §6: anything from the summarized turns that is lost
  and that today's kept tail would have shown her. One such loss reported at once decides between keeping the design
  and asking the owner for the `compactNow` retention (§8).
- **(h)** Her own mechanical counts on the same two checkpoints (her condition, §8), set beside her 10-22 and 10-23
  readings of ADR-085 §7: (a) the anchors of 「答应过的事」 and 「更正与分歧」 still present (`plan-…`, `task-…`, short
  commit shas, `§` references, numbers); (b) the column of 委托中的事 that says whose receipt she is waiting for and
  whom she promised to tell, still there; (c) no item that stood as pending (未了结) written as closed (已了结). She
  counts them on the text herself (the two conversations are owner-private: the program reads numbers only); any one
  loss is reported at once.

No replay against the local engine was needed before install: the summary request's shape is the commanded path that
has run live 18 times at 99.3–99.6%, and the next request's size after it is measured.

## 7. As built

- `packages/cognition-core/src/compaction.js`: `TURN_END_RATIO` (0.70), `turnEndRatio` in `RoleCompactionEngine.Config`,
  `turnEndTokens`, `compactAtTurnEnd`.
- `packages/cognition-core/src/index.js`: `turnEnd`, called from the `agent/status` idle hook of the character lane;
  `compactSession` unchanged.
- Test: `packages/cognition-core/test/compaction.test.js` (the ratio and its default; fires at the ratio, not below;
  busy is left for the next turn end; only her conversations on the character lane; the in-turn guard's test stands).
- References: `docs/articles/maximize-cache-hit-by-design.md` §7 and §13; `packages/cognition-core/DSH_API.md`.
- **Her preset** (`packages/personas/xiaoman/cordis.patch.yml`, her file, not edited here): beside `thresholdRatio`
  add `turnEndRatio: 0.70` with the comment "Compacted at the end of a turn from this share of the window (ADR-094);
  the in-turn threshold below is the guard", and the comment "a short tail keeps the re-prefill after each compaction
  small" becomes "DSH's kept tail is read again only after an in-turn compaction, the guard (ADR-094)".
- Evidence: `.runtime/private/compaction-review/` (report.md 19 KB, scripts 35 KB; numbers only).

## 8. Her conditions (2026-10-23, on Claude's agent line; Claude's paraphrase)

1. **Keep her whole last turn verbatim, not only its last message.** One turn of hers is often several parts (words
   and a file, words and a sticker and a picture); a promise made in its first part must not go into the checkpoint.
   **Not possible from our side today.** Between turns the only compaction DSH offers is `compactNow` (the path of
   `/compact`), whose retained tail is fixed at 0 tokens, which keeps the last message; `compactRegion`, which takes a
   range, refuses to run outside an open turn (`compactRegion: no open turn`); the range selection and the compaction
   transaction (`region.ts`) are not exported by `@deepseek-ai/dsh-compaction-basic` (its `lib/index.js` exports the
   engine class alone). So this version keeps the last message, and the condition waits on **the owner's DSH change**:
   `CompactionEngine.compactNow(agent, signal, sourceCommandId?, options?)` with `options.keepFrom: SessionSeq`, the
   first surface node to keep; `BasicCompactionEngine.compactNow` passes it to `selectCompactableRange` as the index
   to keep from (the cut still walks back to a tool-pairing-balanced place, as today), instead of the fixed 0-token
   tail; `/compact` itself unchanged. Our side then (not built): `turnEnd` finds her last turn's first surface node
   (the first node after the session's last `turn/start`) and calls the engine's `compactNow` with it, marks that
   compaction so `summarize` sends the span alone (as for an automatic one: a summarizer that reads the kept turn
   would restate it, ADR-085 §4b–§4c), and the reading tells the two apart by the Host log line, not by
   `sourceCommandId`. **Its cost on the local engine, from §2's data:** the span then ends after the previous turn's
   last reply, which the engine holds only while her last turn had at most four steps (five rotating checkpoints);
   that is 61% of her home turns and 74% of agent-line turns (since 10-18); the rest read the span cold as today's
   automatic compactions do, about 20 s inside nobody's turn. Sending the whole conversation instead would hit every
   time but shows the summarizer the kept turn. With the last message kept (this version) the hit is by construction.
2. **Her mechanical counts** on the first two checkpoints: §6 (h).
3. **A restart of its own, and the reading window from `last.json` `back_at`:** the status line and §6.
