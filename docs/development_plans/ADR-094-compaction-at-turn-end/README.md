# ADR-094: Compaction at the turn's end

Status: **Built 2026-10-23, not installed; waits on the owner's DSH pin.** Decided by the owner on 2026-10-23
(~11:45 NZDT) on the recommendation of a review of the whole compaction design run on Fable 5.1 at his instruction
(`.runtime/private/compaction-review/report.md`, 2026-10-23 10:30–10:50 NZDT). Xiaoman agreed the same day with
three conditions (§8). The first (keep her whole last turn) is built on both sides (§7): DSH's part is a branch of
the owner's fork, and until the pin moves to it the turn end compacts nothing. It installs in a restart of its
own, with nothing else, and is read as §6 says from that restart's `back_at`.

## 1. The owner's words

"Yes, go ahead with the turn-end compaction. Reason: Even human cannot track the word-by-word history in a busy
group, or after a prolong period if time. Keeping word-by-word memory is a waste of resources so I support your
decision."

His brief for the review (2026-10-23 ~10:20): "The compaction cache hit is low again. I want you to do a brief research
first. If the design is legitimately wrong, then launch a fable 5.1 card session to review the full compaction design,
and make proposal of the systematic fix. Noted the design must satisfy both local and API usage. For local deployment,
if the strata server discards the cache there is nothing to help, but the design of Xiaoman should NOT be the failure
point. We should do whatever the optimization we should do before blaming the model server."

## 2. What was found (role sessions since 10-18; numbers only; read by review scripts since retired, whose readings `.agents/skills/asuna-cache-readout` now gives)

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

*Superseded in part by §7 and §8 (as built): the turn end keeps her whole last turn (`compactNow` with a keep-from
point, not `/compact`), the summary request sends the span before it alone, and her next turn there stops a running
one. Items 1, 2 and 5 and the expected numbers below are the decision as first made.*

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
- Nothing waits for the summary: her next turn in that conversation (a stage or a consult) stops it, and the
  conversation stays as it was until the next turn end (§7). As first decided, a line arriving during the summary
  (~46 s) waited for it, and with it every other conversation of hers, since her turns run one at a time (the
  worker's coordinator lock). In the replayed days the next turn came within 45 s of a turn-end compaction 1 time in
  19 at home and 6 in 24 on the agent line (where it is Claude).
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

## 6. Reading after install (`.agents/skills/asuna-cache-readout`: `compactions`, and `hits` for the next requests)

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
  `turnEndTokens`, `compactAtTurnEnd`, `lastTurnStart` (the first surface node after the turn end before her last
  turn, so the line that opened it stays), `keepsTurns` (whether DSH's `compactNow` takes a fourth parameter,
  `options`), `compactTurnEnd` (`compactNow(agent, signal, undefined, { keepFrom })`, marked so `summarize` sends the
  span alone, like an automatic compaction).
- Her turn takes precedence (review of 2026-10-23, owner's decision): `TurnEnds` in `compaction.js` keeps an
  `AbortController` for each running turn-end compaction; a stage starting in that conversation (`stage` in
  `index.js`, which a consult also is) aborts it first and keeps a new one from starting until the stage is handed to
  DSH; any message put into her inbox there (DSH's `agent/inbox/inserted`, the owner's Web chat as well) aborts it
  too (`preempt`), so no message waits for a summary; each one also stops at `TURN_END_DEADLINE_MS` (180 s, `AbortSignal.any` with `AbortSignal.timeout`). An abort
  cannot leave DSH's compaction half-open: `compactSurfaceRegion` writes `compaction/end` with the error on every
  failure before the summary commits, and the commit itself is synchronous; an abort that lands during the
  durability flush comes after the commit and is reported as compacted. Tested on the installed (pinned) DSH, whose
  compaction transaction the keep-from branch leaves as it is.
- `lastTurnStart` goes by place on the surface, not by seq (a replacement takes a new seq at an old place): the node
  after the last one from before the end of her turn before it; a turn that left no surface node (rejected, or its
  message removed) does not count.
- Errors keep DSH's code and the cause chain (`errorChain`). `commit` and `persistence` are logged as warnings; after
  a `commit` error turn-end compaction stops in that conversation until it is opened again (a new agent).
- After a commit, the node right after the new checkpoint must be her turn's first node; if it is not, the Host warns
  and turns turn-end compaction off for the rest of its run. A walk-back to an earlier balanced place (which keeps
  more) would turn it off too; it is not expected at the start of a turn, and the in-turn guard is unchanged.
- `packages/cognition-core/src/index.js`: `turnEnd`, called from the `agent/status` idle hook of the character lane,
  runs `TurnEnds` (the engine's `compactTurnEnd`, not `/compact`); on a DSH that keeps no turn it compacts nothing and
  says so once in the Host log; `compactSession` unchanged.
- Test: `packages/cognition-core/test/compaction.test.js` (the ratio and its default; the pinned DSH keeps no turn, so
  nothing runs; fires at the ratio, not below; busy is left for the next turn end; only her conversations on the
  character lane; her last turn found from the turn ends, by surface place past a replaced span, a rejected last turn
  and a replaced system head; `keepFrom` passed; the span sent alone; nothing to compact, a commit error with its
  cause chain and a single turn reported; on the installed DSH, a preempted and a timed-out compaction closed and the
  surface unchanged, the kept-turn check both ways, an abort after the commit reported as compacted; her stage stops
  a running one and holds off a new one; the deadline; a commit error stops them in that conversation until it is
  opened again, a persistence error warns, a turn not kept stops them for the run; the in-turn guard's test stands).
- DSH (the owner's fork, his local copy): branch `asuna/0.2.1-rc.2-keepfrom`, one commit `4000a552ce` on the pin
  `5713aab796`, three files: `compaction-basic/src/region.ts` (`selectCompactableRange` takes an optional `keepFrom`,
  the existing balanced-cut walk-back unchanged), `compaction-basic/src/index.ts` (`compactNow`'s optional `options`),
  and a new test file (five cases, among them: without `options` exactly today's result). Not pushed; additive, so his
  dedicated deployment on the same fork behaves as before; the abstract `CompactionEngine` type is left as it is
  (owner: the smaller diff, fewer upstream conflicts). Moving Asuna's pin to it is the owner's (`tools/dsh-inline/
  source.json`).
- References: `docs/articles/maximize-cache-hit-by-design.md` §7 and §13; `packages/cognition-core/DSH_API.md`.
- Her preset (`packages/personas/xiaoman/cordis.patch.yml`): `turnEndRatio: 0.70` beside `thresholdRatio`, and the
  note on DSH's kept tail.
- Evidence: `.runtime/private/compaction-review/report.md` (19 KB; numbers only).

## 8. Her conditions (2026-10-23, on Claude's agent line; Claude's paraphrase)

1. **Keep her whole last turn verbatim, not only its last message.** One turn of hers is often several parts (words
   and a file, words and a sticker and a picture); a promise made in its first part must not go into the checkpoint.
   **Not possible from our side alone.** Between turns the only compaction DSH offers is `compactNow` (the path of
   `/compact`), whose retained tail is fixed at 0 tokens, which keeps the last message; `compactRegion`, which takes a
   range, refuses to run outside an open turn (`compactRegion: no open turn`); the range selection and the compaction
   transaction (`region.ts`) are not exported by `@deepseek-ai/dsh-compaction-basic` (its `lib/index.js` exports the
   engine class alone). So the condition needed **the owner's DSH change**:
   `CompactionEngine.compactNow(agent, signal, sourceCommandId?, options?)` with `options.keepFrom: SessionSeq`, the
   first surface node to keep; `BasicCompactionEngine.compactNow` passes it to `selectCompactableRange` as the index
   to keep from (the cut still walks back to a tool-pairing-balanced place, as today), instead of the fixed 0-token
   tail; `/compact` itself unchanged. Our side (built, §7): `turnEnd` finds her last turn's first surface node
   (the first node after the turn end before it, so the line that opened the turn stays) and calls the engine's `compactNow` with it, marks that
   compaction so `summarize` sends the span alone (as for an automatic one: a summarizer that reads the kept turn
   would restate it, ADR-085 §4b–§4c), and the reading tells the two apart by the Host log line, not by
   `sourceCommandId`. **Its cost on the local engine, from §2's data:** the span then ends after the previous turn's
   last reply, which the engine holds only while her last turn had at most four steps (five rotating checkpoints);
   that is 61% of her home turns and 74% of agent-line turns (since 10-18); the rest read the span cold as today's
   automatic compactions do, about 20 s inside nobody's turn. Sending the whole conversation instead would hit every
   time but shows the summarizer the kept turn. With the last message kept (this version) the hit is by construction.
2. **Her mechanical counts** on the first two checkpoints: §6 (h).
3. **A restart of its own, and the reading window from `last.json` `back_at`:** the status line and §6.

## 9. First readings after install (2026-10-24, `.agents/skills/asuna-cache-readout`)

10-23 17:57 to 10-24 11:00, her home conversation and agent line, numbers only:

- Turn-end summaries read 99.4–99.5% from cache when her last turn had at most four steps (3 of 3) and 8.3–9.3% when
  it had five or more (4 of 5; one six-step turn still hit); one more stopped for her turn. On a hit the summary read
  exactly the previous turn's last request's input less 5 tokens; on a miss, 16.5–16.6k tokens, the system prompt and
  tools her conversations share. That is §8's prediction: the span ends after the previous turn's last reply, which
  the local engine holds only while her last turn had at most four steps.
- No turn waited on any of them; a miss makes the summary take 93–131 s instead of 67–94 s, inside nobody's turn.
- Owner, 10-24: accepted as the engine's capacity, the span alone stays (the whole conversation would hit every time
  but shows the summarizer her kept turn, ADR-085 §4c). On a provider whose cache serves any prefix of a cached prompt
  the span alone would hit; whether a given API does is read from its documentation when the move to it is made.
