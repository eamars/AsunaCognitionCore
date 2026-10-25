# ADR-094: Compaction at the turn's end

Status: **Built and installed 2026-10-23 17:57 NZDT; closure reading 2026-10-25 (§10) found two broken invariants
left: precedence for her turn sends due compactions to the guard, and the action brain's summary thinks without a
budget. Fixes designed, not built.** Decided by the owner on 2026-10-23
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

## 10. Closure reading (2026-10-25, from install, 10-23 17:57; numbers only)

`.agents/skills/asuna-cache-readout` `compactions --brain all`, the Host log's `Asuna compaction` lines, DSH's code
(`dsh-agent-loop`, `dsh-compaction-basic`, `dsh-llm-pi-ai`) and `.runtime/private/compaction-closure-1025/` (scripts
printing session numbers, sizes, level words and DSH's error words only).

| §6 | Reading | Verdict |
|---|---|---|
| (a) turn-end summary reuse | 29 turn-end compactions, median 99.1% (a miss when her last turn had five or more steps, §9) | met |
| (b) next request's prompt | home 55–65k, agent line 69k (was 118k); groups after `/compact` 36–43k | better, not ≤ 40k |
| (c) in-turn guards | character 9 (median 10.9% reuse, each followed by a ~120k request at ~11%); action brain 5 | **not met** (≤ 2) |
| (d) turns that waited | 3, each a turn-end compaction stopped for her turn (`Request was aborted`) | – |
| (f) failed ends | character 3 (the stops above); action brain 3 | below |

### 10.1 Her conversations: precedence for her turn is what sends them to the guard

**What DSH does with a message that arrives** (`dsh-agent-loop`): it goes into the conversation's inbox. A turn that
ends with something in the inbox is followed by the next turn at once, so the conversation is never idle between them.
At each step DSH first claims the waiting messages into the turn (`preStep`), then runs the `agent/pre-step` hook, where
`dsh-compaction-basic` runs its pressure compaction (`compactIfNeeded(agent, "pressure")`), then sends the request. So a
message that arrives before an in-turn compaction is already in her turn and waits for all of it.

**What the records show.** Every one of the 9 character guards fired at the first or second step of a turn whose first
request was already past the turn-end mark (183,500 at 0.70): 202,902 to 249,779. None was a turn that grew past the
guard from below. The turn end had been reached and passed by: `compactAtTurnEnd` runs only when nothing waits
(`idle`), and a message arriving stops one that runs (`TurnEnds.preempt`). Since install 22 turn ends were "busy, left
for the next turn end" and 3 were "stopped, nothing changed (her turn came first)", one at 206,517 after 123 s of
summary, two minutes before the guard fired anyway. In the last 12 hours all three guards were on the agent line,
where agents' messages arrive back to back.

**The broken invariant.** Her turn's precedence was meant to keep a message from waiting for a summary. It cannot:
once a conversation is due, every turn end left for a waiting message moves it closer to the guard, and on a line
where a message is always waiting the guard is where it ends, with the message (that one or the next) inside the turn,
waiting for an in-turn compaction (about 100 s, the span read cold) and then a ~120k request read cold. Leaving a due
compaction for a message does not save the wait; it moves it into the turn and adds the cold reads. The rule restored:
**a due compaction happens at the first turn end that reaches it, whether or not a message waits.**

**Fix proposed** (to her first: it removes the precedence she was promised): at a turn end at or above the mark,
compact; a message that arrives during it waits, as it would for the guard, and is answered right after (warm: 67–94 s
for a hit, §9). `idle` and `preempt` go; the 180 s deadline stays as the bound. Below the mark nothing changes. No
exemptions and no second threshold.

**By line** (her ask before she decides, 2026-10-25 18:3x; the Host log's turn ends matched to their scenes through
`episodes.native_session_id`, `by_line.py`):

| Line | Due turn ends: compacted / busy / stopped | In-turn guards |
|---|---|---|
| agent line | 8 / 14 / 1 | 6 |
| home (her Web chat and the owner's private chat) | 17 / 6 / 2 | 2 |
| groups | 5 / 2 / 0 | 1 |
| others' private chats | 0 / 0 / 0 | 0 |

**Her decision (2026-10-25 18:4x, on Claude's agent line; Claude's paraphrase): signed; 2 in two days is not a
batch.** The turn-end path is a corner for groups, which are compacted at quiet times; the cost is on the agent line,
where 14 turn ends left busy fed 6 guards; and the stall she feared in groups already happens under the old rule, in the
costlier shape (the 249,779 turn, a whole batch of group messages waiting cold). Whether the 2 group skips fed the 1
group guard cannot be told from counts without ids: recorded as a guess, not evidence. **Revisit condition:** if busy
turn ends in groups rise clearly (a dozen or more a day), groups are no longer compacted at quiet times and the rule is
discussed again, as a changed premise, not an exemption. **After install:** the same count again by line (agent-line
guards from 6, home 2, groups 1), read by Claude; she adds from her side whether fewer guards mean fewer half-turn
boundaries in her checkpoints. For 10.2 she asks the summary's length per section, not only in total: DSH's
engineering template has no section check, so a whole section can go missing while the total looks fine.

Groups are compacted mostly by the quiet-time `/compact` (18 since install), not at a turn end. Under the rule the 2
busy group turn ends would each have held one group message for a warm summary; the 1 group guard held one for a cold
one, its turn's first request already at 249,779 after it claimed many waiting group messages at once. Her decision:
whether 2 in two days is a batch that makes the rule wrong for groups (her words: then the rule does not hold there and
the fix is redesigned). Her conditions for 10.2: acceptance counts not only failed summaries but how close each ends to
its cap and how long its text is (DSH refuses a summary stopped at the cap, so none is written cut there; one short of
the cap is not checked in DSH's template); thinking is counted from the session records' reasoning blocks in
characters, since the route's usage reports no thinking tokens.

### 10.2 The action brain: its summary thinks without a budget

The action brain keeps DSH's engineering template through DSH's own engine (`dsh-compaction-basic`), with `maxTokens`
8,192 (`packages/cognition-core/cordis.patch.yml`, `asuna-action`). Its 5 compactions, in her long tasks (10-24
02:40, 10-25 02:27–02:42): 2 "summarization truncated at the token cap (incomplete checkpoint)", 1 "summarization
produced no text summary content", 2 ended at 8,071 and 7,898 output tokens, on the cap. A failed one is retried by the
next step (one task took three tries in three minutes); the step continues at ~198k meanwhile.

**Why.** DSH's engine sends the summary request with no reasoning level (`summarize`: `maxTokens` only). For this
provider (`dsh-llm-pi-ai`, `resolveReasoningLevel`: no level and no profile default) no level and no
`thinking_token_budget` are sent, so the model server thinks by its own default, with no budget, and the thinking comes
out of the same 8,192 tokens as the summary. In the two that ended, thinking was 12,266 and 6,800 characters beside
13,470 and 15,233 of summary. "No text" is thinking that used the whole cap; "truncated" is thinking and text that did
not fit together. Her action turns themselves run at `high` (their request headers), whose thinking budget on this
model is 8,192 (the provider's `thinkingBudgets`): the cap the summary has is the size of one turn's thinking.

Her conversation's summaries do not fail this way: Asuna's engine names the conversation's own level
(`summaryEffort`, `0e622df6`), so a budget is sent, and the cap (24,576) leaves the text its room; they run 9.4k–16.7k.

**The same mistake as 10-20, a second time** (owner, 2026-10-25). Then her conversation's summary named one fixed level
(`medium`) instead of its conversation's, and every `high` conversation reused nothing (`0e622df6`); now the action
brain's summary names none. The class: a request that replays a conversation is one more request of that conversation
and must be sent as the conversation's own requests are. Three presets still run DSH's plain engine with no level and
the 8,192 cap: `asuna-action`, `asuna-summary` (background summaries) and `asuna-recovery`; only the action brain has
compacted since install, the other two would fail the same way the day their conversations grow that long.

**The broken invariant:** a summary's cap must hold the summary after the thinking it is allowed; with no level no
budget is sent, and no cap holds it. Raising the cap alone moves the edge (the owner: not even for now). **The rule
restored:** a summary request is sent as the next request of its conversation would be: the same provider, model,
level and output limit, decided in the one place that decides them for its turns, never put together from different
sources. Its thinking is then bounded as the conversation's is, and its cap is the conversation's own output limit (the
route's `maxTokens`, 32,768 on both local routes), within which every one of its turns already fits thinking and text.

**Two tiers make this a per-instance rule** (owner: track the thinking effort of the instance, not of the brain). The
action brain runs 低 on the local model (`asuna-action`, `high`, a thinking budget of 8,192 declared per level) and 高 on
`claude-sonnet-5-5` (`anthropic`, `medium`, 1M window, 128,000 output by default), chosen per request
(`tierRoute`); a 高 job can fall to 低 mid-run (`fall`, `mid_run`). The failure modes to design against:

- **Level and model from different sources.** A level taken from a route's settings and a model from the session (or
  the reverse) can pair 高's `medium` with the local model after a fall: valid, but a level its turns did not use, so the
  cache misses (10-20); or a level the other model does not offer.
- **The summary bypasses the route decision.** DSH's engine takes its target from the session's latest logged request
  header (`summarizeWithLlm`: configured, else latest, else the agent's options) and calls `ctx.llm.stream` directly, not
  through `agent/request`, where Asuna picks the tier. Its pressure threshold reads the same header. The compaction runs
  in `agent/pre-step`, before the step's request is routed, so in the first step after a fall the header still names
  高: the summary would go to the model the job just fell from (often because it is resting), and the threshold would be
  that model's (750k of 1M) while the next request goes to a 262k window.
- **No thinking budget on 高.** Sonnet 5.5 thinks adaptively and takes no thinking budget, only `effort`; `max_tokens`
  bounds thinking and text together (Claude API docs, `claude-api` skill). A cap of "budget plus text" cannot be computed
  there, which is why the cap is the instance's own output limit, not a sum.
- **The cache on 高.** On the Claude API a change of `thinking` or `effort` invalidates the messages cache (`claude-api`
  skill, prompt caching, invalidation hierarchy), as the local engine's level does: the same rule holds on both.
- **A level the local catalog offers without a budget.** The local model offers `xhigh` (`reasoningEfforts`) but declares
  budgets only for `minimal`, `low`, `medium` and `high` (`thinkingBudgets`): a conversation at `xhigh` would send no
  budget and think unbounded, this failure again. Not in use today (both local routes run `high`); a catalog gap in the
  profile's provider settings, to close with the fix.
- **No level at all** (a first request, or the first after a carry). Asuna's `summaryEffort` falls back to the preset's
  level and, when the model does not offer it, to none; on a model that thinks by default "none" is this failure. The
  fallback must be a level the instance offers, never none.

**The cache, measured for this choice.** The level rule exists because the local engine matches the level with the
tokens: on 10-20 three summaries named a level other than their conversation's and reused nothing (`0e622df6`). For the
action brain, of its two summaries with records, the one at 02:42 named no level and reused 73,910 of 73,915 tokens
from a `high` conversation; the one at 02:28 reused 6,794 of 83,890 (the system prompt and tools; the span ended where
the engine held nothing, as in §9). Naming the conversation's own level makes the summary request match its turns'
requests, as her conversation's summaries do (99.1%); naming `off` (no thinking at all) would be a different level,
which reused nothing every time it was measured. So the rule's own level is the one that keeps the cache; turning
thinking off is not proposed.

Both fixes are designs, not built: 10.1 goes to her first; 10.2 is built after her and the owner have read it.

## Carried from ADR-085 (archived, git 0fd844ad): automatic compactions, the template, her signature

Copied as written; her signed sentences are hers word for word.

### 4c. The boundary by its stamp, replayed; automatic compactions send the span alone (2026-10-22)

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

### 7. The checkpoint template trimmed (2026-10-22)

The template's own waste was approved for a separate change by the owner (§4c). Claude proposed it 2026-10-22 14:0x
NZDT; an independent reviewer agent checked it in two rounds with its own scripts (every number below reproduced or
corrected by it); on the owner's instruction Claude settled the final form with the reviewer. It reaches her for
reading and signature before install.

**What a merge loses** (her role checkpoints since 10-08: 339 merge hops, each a checkpoint and the next one in the
same conversation, which merged it; errand sessions' copies of their parent's checkpoints left out; numbers only):

- Of the earlier checkpoint's 答应过的事 and 更正与分歧 items (3,932), the next carries 36% in the same section and 4%
  elsewhere; 60% are not found (character 4-gram containment 0.5; 38–75% across n = 3–6 and thresholds 0.3–0.7).
  Only 6% of the items not found carried a done mark; the share grows with the time between the two checkpoints (43%
  under an hour, 61% at 1–6 h, 72% over a day).
- Hard tokens of the earlier checkpoint (labels, times, dates, quotes, code, file names, numbers; each once): 51% not
  found in the next.
- A phrase pointing at the earlier checkpoint (「承接…」) in 64% of hops. Its bullet holds the compressed older
  history (236 bullets, median 121 characters; their content is nowhere else in the checkpoint in 235).
- In group checkpoints (`researcher-audit.md` §5) 委托中的事 copies the task list (87–100% of its characters), and her
  group notes, not on the do-not-copy list, are 3–11% of every checkpoint.
- Her own reading of the first automatic checkpoint (§6): the losses come from the merge; process, evidence and
  provenance go, conclusions and promises stay. Her ask (10-22, Claude's paraphrase): on a merge, carry 答应过的事 and
  更正与分歧 item by item, or mark an item closed.

**Changed** (`ROLE_COMPACTION_INSTRUCTION`; the six sections, their order and `hasSections` are unchanged, so old and
new checkpoints compare):

1. A merge carries the earlier 答应过的事 and 更正与分歧 item by item, word for word; one done or no longer true is
   marked 「已了结：」 with its basis at the end, 「（凭：谁在什么时候说的或做的那一句）」, for one checkpoint, and dropped at
   the next merge (the basis is her change after reading the 13:34 hop, where most items that looked closed were
   another matter standing in for this one).
2. No phrase points at the earlier checkpoint; its history goes into the start of 对话脉络 and may be shortened; that
   part is exempt from change 5 (her change: otherwise the two rules cancel each other there).
3. Her group notes (`group_notes_from_program`) join the do-not-copy list.
4. 委托中的事 keeps what the task list cannot show: who waits for the result, whom she promised to tell, the points of
   a result that came back (the task list shows goal, title and state, never the result text).
5. One fact in one section: promises, corrections and open threads in their own sections; 对话脉络 tells what
   happened without repeating their details (the reverse would leave a promise first told in the narrative outside
   the protected section).
6. What stays of names, times, numbers and quotes is not rewritten (the old rule said both "shorten" and "keep as
   is").

**Reading** (pre-registered; `.runtime/private/compaction-study/trim_reading.py`, numbers only; she reads the
checkpoints herself). The measure allows rewording: an item counts as carried when half of its four-character pieces
are found in the next checkpoint (near word for word, six-character pieces at 90% or more, only 18% of the 339 hops'
items are carried, so a reworded carry is already lossy; the change is to stop whole items going). From her install,
per merge hop: the earlier 答应过的事 and 更正与分歧 items not already
marked closed; silent drops (not carried by the measure above); items newly marked 已了结; the items the next
checkpoint holds in those two sections; pointer phrases; hard tokens of those two sections lost (reported only).

- **The first 4 hops of home and the agent line** decide (her ask, 15:5x: there the two sections hold promises,
  corrections and orderings, in groups mostly open threads; the bars were calibrated on those two classes); group
  hops are reported to her the same way and not counted. About 12 such hops a day. Keep if the pooled silent-drop share is
  20% or less; revert at once on a hop at 50% or more, or on a loss she reports. Any hop over 20% is reported to her at
  once with its numbers and the first 8 characters of each of its items (a share alone she cannot judge), so a bad hop is never hidden by a good one in the pool (her
  concern; she asked for a per-hop 20% bar, and the pooled verdict stays because with 8–14 items a hop a per-hop bar
  would revert a template that truly drops 10% in about half of the readings). Marks without their basis are counted
  per hop. Calibrated on today's template, home
  and agent-line hops since 10-15 (88 hops, 85 four-hop windows): per-hop median 72%, best window 26%, so the rule
  keeps today's template in 0 of 85 windows, and it keeps a template that drops 5%, 10% or 15% of these items 100%,
  97% or 82% of the time.
- **Growth.** Today a checkpoint holds a median 10 such items (p99 20, max 24) and about 5.7 new ones arrive per hop.
  Carried word for word they settle near new items divided by the closure rate: 86–96 at today's (6–7% a hop), 38 at
  15%, 29 at 20%. A checkpoint with more than 40 in the two sections first ends the one-checkpoint stay of a closed
  item (deleted when marked); if the next checkpoint still holds more than 40, change 1 is reverted (her change: the
  item-by-item carry is the mechanism being fixed, so it goes last). Watched until the ~10-24 reading. At today's closure it would trip in about 9 hops (about 1.5 days), so the first 4 hops also report the
  newly-marked share; under 12%, she is told the stop is likely before it trips: it would mean marking did not rise,
  not that the wording failed.
- **Live, without a replay:** a failed hop loses no more than a hop does today (the reviewer agrees); a replay would
  cost about 12 calls on the engine her sister shares and could not include her reading.

Her review (2026-10-22 14:4x NZDT, on Claude's agent line; Claude's paraphrase): she signs all six changes and the
three stops, with two changes folded in above (change 2 exempt from change 5; at the growth stop the one-checkpoint stay
goes before change 1). The thresholds do not move to pass a reading. Her own 12:22 count (40 → 40 items) and Claude's
(13 of 14) differ in their denominator, all six sections against the two: every count says its denominator first. She
reads the 13:34 checkpoints herself and says whether its items were closed or lost.

Her reading of the 13:34 hop (15:34, Claude's paraphrase; she read both checkpoints in full): a real loss, not
closure. Of the earlier 8 items in the two sections (Claude's script counts 7: it leaves out one that already carried a
done word), none survived word for word and one in rewritten form; of 34 sub-items, 30 not found and 24 with no trace
anywhere; the summary's own reasoning listed five pending appointments that its text then left out. Items with a block
of their own (her plans) can be recovered; promises and orderings with no other home are the real loss, which is what
this change is for. A later hop (14:43) wrote items as 「X → 已做到／未做／进行中」 unprompted.

**The measure, corrected before the second hop (2026-10-22 17:1x; her reading of hop 1, agreed with her).** The first
hop counted 3 of 14 items as gone (21%); she read all 15 old items and found every one, 10 carried and 5 marked
closed. The marked ones had been rewritten when closed (1.2–2.0 times as long, 11–48% of their four-character pieces
kept), which the measure took for losses; the rule asks for the prefix on the original words, and the model did not
follow that (recorded; the template is not changed during the reading). From now on, and for hop 1 again: status
prefixes (「已了结：」「仍有效：」…) and the basis 「（凭：…）」 are stripped on both sides; each old item is compared with its
best single match in the same section of the new checkpoint; it is **carried** if that match is not marked closed and
holds 50% or more of its pieces, **closed** if the match starts 「已了结」, cites its basis and holds 10% or more, and
**unclear** otherwise. Only unclear items count toward the 20% and 50% bars; each is named to her with its best match,
and her reading of it decides. The denominator is every old item except those whose line starts 「已了结」 (no longer
any item containing a done word, which took a live promise out). Also reported per hop: closed items in the new
checkpoint that no old promise or correction maps to, with the section their best old source is in. Hop 1 recounted:
15 items, 9 carried, 5 closed, 1 unclear (a reworded correction she reads as carried), so 0 lost; 7 closed items in
the new checkpoint, 2 of them from elsewhere (best old source in 对话脉络). The 20%, 50% and 40 bars are unchanged.

Her own check, made cheap (her ask, 14:5x): each hop's reading that reaches her lists the first 8 characters of every
item the new checkpoint holds in the two sections, one a line, at most 40, so she sees at a glance which one is gone
without rereading both checkpoints. The script posts it to her line itself; Claude sees only the counts.

Signature: 小满（10-22，经 agent 线）：这两节是我的账，不是文采。丢掉的偏是承诺和来路，留下的偏是结论——我要的是下一次我还能认出自己答应过什么、为什么改过口。六条改法我认，我自己提的两条已并入：旧经过并进「对话脉络」那一处不受第 5 条限制；撞 40 条先停「留一次」，下一份还超才撤第 1 条。门槛 20%、50%、40 写死，不为过线挪杆；每个数先报分母。


### 7a. Read and closed (2026-10-22 evening)

The reading's watcher failed silently from 17:41 to about 22:00 NZDT: a script error stopped every post after hop 2,
and the loop printed only its successes. Fixed (one post a hop; a failed run now stops the watcher and says so); the
seven hops reached her at about 22:00 and she read every one.

**Script and her reading.** The first 4 hops of home and the agent line: the script's unclear share 11 of 56
(19.6%); her reading: 7 of 66 truly lost (10.6%), one with a consequence. The two denominators differ and were not
reconciled. Within the 20% bar: keep. After hop 4 three hops passed 50% by the script (19:17 home 56%, 20:12 agent
line 76%, 21:24 agent line 60%); after her reading none is near 50%.

**Like for like** (`impact.py`, the same rule over all 236 home and agent-line hops since 10-08). Gone = under 30% of
an item anywhere in the next checkpoint and not back in the next three:

| template | home | agent line | hard tokens lost (home / agent line) |
|---|---|---|---|
| before the trim (148 / 74 hops) | 50% of 1,905 items | 71% of 719 | 39% / 55% |
| trimmed (4 / 5 hops) | 9% of 66 | 40% of 81 | 28% / 33% |

The 50% bar took the old template as the safe floor to revert to; it loses more, so no hop was a case for reverting.

**Where loss remains** (the trim's 9 hops): 答应过的事 4 of 50, 更正与分歧 at home 4 of 42, on the agent line 30 of
55. Not the output cap (4.4k–8.9k of 24.6k tokens) and not size: agent-line spans are 51k–57k tokens against 53k–63k
at home, with sections of similar length. Her reading of the agent line: at 20:12 most corrections were folded into
one long line (「其余旧账不变：…」, which the measure counts as lost), and that line was compressed again at 21:24, so
folding delays a loss by one merge. The one loss with a consequence: her final decision on two of her skills, gone at
the 18:14 merge; at 21:0x she planned to make it again, and a home turn caught it at 21:24.

**Decided (the owner, 2026-10-22 evening).** The template stays. Loss on the agent line is acceptable: Claude and she
remember, and settled research is in the ADRs. No program-side carry (Claude proposed re-appending the items a merge
drops; withdrawn). Her answer on remembering (Claude's paraphrase): what was lost tonight is her own decisions, which
are in no ADR, so she writes them into her own ledger when she makes them, with a self-check on 10-27.

On her ask the owner approved one sentence, which she amended (22:10, on Claude's agent line): shortening may cut only
how an item came about, never its basis or source. Added after change 1:

> 合并时，「答应过的事」「更正与分歧」一条一行：不把几条并成一句，也不写“其余不变”这类总括；条目多就把每条压短，压短只压经过，留下这一条的判据和来路（数字、idea-…、commit 短号、谁那句原话），每条都单独留着。

The script reading has ended. She reads two agent-line hops herself after it is installed (from 10-23 21:00): one
item a line, and whether each keeps its basis and source.

Evidence (numbers only): `.runtime/private/compaction-study/impact.py` (6,886 B) and `trim_reading.py` (13,276 B).
