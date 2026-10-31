# ADR-114: The kept tail in real tokens

Status: **Built**, installed 2026-11-01 01:00 as `ec9211cc` (the engine `dsh-compaction-basic` `3153519e45ac`, her persona package `3fdf9c4c8f3e`). The owner agreed the design in the session just after midnight on
2026-11-01 (§1). DSH: `d9d52adae4` on `asuna/0.2.1-rc.2-realtail`, pushed to the fork at the owner's word. Xiaoman
read the page at `d5d77088` on her agent line (2026-11-01 00:49); her corrections are in §2, §3 and §7, and she
agreed to the change in her own preset (D2). She reads the install from her side (§9).

All times are New Zealand local time. Token counts are the provider's own (`usage` in her DSH session logs) unless
they are called estimates; estimates are DSH's (characters ÷ 4).

## 1. The ask

The owner, 2026-11-01 00:00: "Hey big sis, it looks like Xiaoman stucks at context compressing. Can you take a look?"

His decisions, in the same session:

- On the fix: "Proper fix only" (not a lower setting as a stopgap), and of the places for it, "DSH fork, always on".
- On her character brain: "If the character brain changes nothing then I'm good. my concern is action brain."
- "Yes please go ahead with ADR and build it."

In scope: how much recent history a compaction inside a turn keeps word for word, for every brain, so that a
compaction always ends below its threshold. Out of scope: the 30-minute stage limit (ADR-112 C1, the owner's), the
shape of the summary request (the character brain's cache-first one, ADR-085 and ADR-094, is unchanged), compaction
at a turn's end and on command (they keep a turn or the last message, not this tail).

## 2. What happened (2026-10-31 23:30 to 2026-11-01 00:00)

Read from the action session of her home chat (`work/local-user`) with the structure-only helper and
`asuna-cache-readout compactions`. The task was her daily self-reflection, `task-ff21807ebabe5e538cd02d626749d561`
(`scene_id` `local-dm`, from the owner), started 23:30:27:

- The task was one turn of 65 steps. By step 36 (23:36) the context was 196,509 tokens; the tool-result pruner cut it
  to 136,211. At 23:41 it crossed the action brain's threshold, 196,608.
- From 23:41 to 00:00 there were 13 compactions, one at nearly every step, each 40 to 115 seconds. Each folded 5k to
  15k estimated tokens; the next request was still 180k to 201k. Three ended in an error of 87 characters (its text
  was not read; DSH's refusal of a summary not smaller than what it replaces has that length, §8). From 23:58 on the folded range was the previous summary alone, which grew from 14,738 to 19,334
  characters.
- The stage limit cut the turn at 00:00:31 (1,800 s); the task record went BLOCKED with `failure_type`
  `TimeoutError` (read 00:08). Its continuation, `task-426f83f0b9b54912e5ff2e041bd40eb5`, started 00:01:46, was at
  115,033 tokens at 00:07 and RETURNED before it reached the threshold. Whether the continuation covered the whole
  day is hers to check (her note, 00:49).
- Failed action compactions before, each with a next request near 200k: 10-22 (6), 10-24 (1), 10-25 (2); and 10-31
  (4) and 11-01 (1, the stage limit's abort).

## 3. Root cause

The broken invariant: **a compaction inside a turn ends below the threshold that started it.**

DSH (`dsh-compaction-basic`, `compactIfNeeded`) starts a compaction when the meter's total reaches the threshold.
That total rests on the provider's usage of the last request (`dsh-token-meter` `measure`: `baseline.kind: 'usage'`).
It then keeps a recent tail of `retainTokens` (`retainRatio` × (window − output reserve)) and folds what is before it
(`selectCompactableRange`). The tail is priced with the per-message estimate, characters ÷ 4. The two are different
units. After a compaction the conversation is the fixed prompt, the summary and the tail; it ends below the threshold
only while

  fixed + summary + `retainTokens` × (real ÷ estimate) < threshold.

The action brain: window 262,144, output reserve 32,768, `thresholdRatio` 0.75, `retainRatio` 0.32. Threshold
196,608; tail 73,400 estimated. At 23:41 the kept tail was about 162k real tokens (the next request, 180,559, less the
first request's fixed part, 12,925, and the summary, 5,451), 2.2 times its estimate. With the fixed part and the
summary the compaction landed at about 181k; one step later the conversation was over 196,608 again, and each later
compaction could only fold the few nodes in front of a tail that already filled the window. The ratio depends on the
content: about 1.9 over the task's first 36 steps (before the pruner), 2.2 at the first compaction.

Her character brain: window 262,144, output reserve 24,576, `retainRatio` 0.16, threshold 209,715; tail 38,010
estimated. Claude measured her twelve compactions inside a turn since 10-24 (2026-11-01, a scratch script over her
`asuna-role-*` sessions): the kept tail's real size is the last request's prompt and output before the compaction
less the prompt and output of the last request at or before the cut. Nine rows gave 65,879 to 86,774 (median 76,561;
1.7 to 2.3 times the estimate), with next requests of 107k to 127k: below the threshold, so it converges, but by luck
of the ratio, not by design. Three rows gave 184k to 197k, more than their next requests (97k to 123k) leave room
for, so the subtraction did not measure them; why was not checked. Xiaoman has not recomputed these rows (her
sandbox cannot read the session logs).

The class is every brain's compaction inside a turn. Compaction at a turn's end (`compactNow` with `keepFrom`) and on
command (`compactNow`, the last message kept) do not use this tail. Overflow recovery keeps none.

## 4. Census (DSH `asuna/0.2.1-rc.2-keepfrom`, `4000a552ce`)

- `retainTokens` reaches range selection at one call site: `compaction-basic/src/index.ts` `compactIfNeeded`, the
  pressure loop (`selectCompactableRange(agent.session, measurement, spec.retainTokens)`). Overflow passes 0;
  `compactNow` passes 0 or `keepFrom`.
- `resolveCompactSpec` (`config.ts`) computes it and checks it is below the threshold; that check is right once both
  are in the same unit.
- The meter's measurement already carries what is needed: `baseline` (`kind`, `tokens`), `surfaceTokens` (the current
  estimate) and `surfaceDeltaTokens` (current estimate minus the estimate of the request the usage belongs to), so the
  estimate of that request's surface is `surfaceTokens − surfaceDeltaTokens`.
- Released DSH `dsh-v0.2.1-rc.3` (the newest tag in the fork checkout, read 2026-11-01) selects the tail the same way.
- Not touched: Asuna's own estimate for her prompt blocks (`src/asuna/render.py`, one token per CJK character, the
  rest characters ÷ 4), by which her carried blocks are bounded (12,288, `carried.py`). It is a different measure for
  a different limit.
- Asuna: `retainRatio` in `packages/cognition-core/cordis.patch.yml` (action, summary, appraiser: 0.32) and in each
  persona package's `cordis.patch.yml` (Xiaoman 0.16; also claude-chan, ichinose-asuna, kyoyama-kazusa,
  shirase-shiori, yan-sui at 0.16). `RUN_ASUNA.md` states 32% and 16%. No test reads the values.

## 5. Decisions

### D1. DSH: the tail is counted in the threshold's unit

In `compactIfNeeded`'s pressure loop the tail budget given to `selectCompactableRange` is `retainTokens` converted to
the estimate's unit by the ratio the meter already holds:

- When the measurement rests on provider usage (`baseline.kind === 'usage'`), the budget is
  `retainTokens × (surfaceTokens − surfaceDeltaTokens) ÷ baseline.tokens`: the estimate of the last request's surface
  over that request's real size. The tools' estimate is in the real size but not in the surface's, so the ratio is a
  little higher than the truth and the tail a little smaller than asked: the safe side.
- Otherwise (no usage yet, or the envelope changed since) the total is itself an estimate, both sides are in one
  unit, and the budget is `retainTokens` as today.
- A retry after a compaction measures again; the request the usage belongs to is the same, so the ratio is the same.

`retainRatio` and `retainTokens` then mean what they say: that much of the window in the model's own tokens. Always
on (the owner's choice): every deployment on the fork keeps the tail its setting names. A deployment whose setting
was tuned against the estimate keeps less than before (0.16 of a 262,144 window: about 38k real instead of about
75k); the fork's README says the unit. One commit on a new branch `asuna/0.2.1-rc.2-realtail` from the pin
(`4000a552ce`), in a worktree of the owner's local fork; his checkout on `asuna/0.2.1-rc.3` is not touched.

Rejected: a tokenizer per model (not for one model; a dependency per route); per-node real prices from each step's
usage delta (exact only back to the last prune or compaction, and a meter change for no gain at this size); an opt-in
key (keeps the wrong unit alive); our own engine re-implementing `compactIfNeeded` (none of DSH's helpers are
exported; it would copy them and break quietly on an upgrade); halving the tail on each retry (a guard over the unit
error, not its fix).

### D2. Asuna: the settings in the new unit

- Her character brain (Xiaoman's preset): `retainRatio` 0.16 → **0.32**, 76,021 real tokens, the median of what her
  compactions inside a turn keep today as Claude measured it (§3). After such a compaction she is where she is now,
  about 107k to 127k. The file is in her persona package; she agreed to Claude changing it (2026-11-01 00:49).
- The base of every share is the window less the output cap (`config.ts`, `messageBudgetTokens`): 237,568 for her,
  229,376 for the action brain. A change of a preset's model or output cap moves the kept tail with it; whoever makes
  that change sets the share again.
- The action, summary and appraiser presets keep **0.32**, now 73,400 real tokens.
- The other persona packages keep 0.16. None runs here; each keeps about 38k real tokens after a compaction inside a
  turn.
- `RUN_ASUNA.md` says the shares and that they are counted in the model's tokens; the comment in Xiaoman's preset says
  the same.

### D3. The pin

`tools/dsh-inline/source.json` moves to the new branch and commit; `tools/dsh-inline/README.md` lists what the
compaction engine's build adds. The inline build (`node tools/build_dsh_inline.mjs --source <the DSH worktree>`)
packs `dsh-compaction-basic` from it. D2 and D3 land in one commit: the settings mean real tokens only with the new
engine.

## 6. What it changes, in the owner's terms

Both windows are 262,144 tokens; the space held back above each threshold does not change.

| | Action brain | Character brain |
|---|---|---|
| Held back for compaction (unchanged) | 65,536: compacts at 196,608 | 52,429: inside a turn at 209,715; at a turn's end at 183,500 |
| Right after a compaction inside a turn, today | 180k–193k (fixed ~13k, summary 5k–10k, kept ~160k) | 107k–127k |
| Room for work after it, today | 0–15k: it compacts again at once | 83k–103k |
| Right after it, with this change | ~95k–100k (fixed ~13k, summary 5k–10k, kept 73,400–80k) | 107k–127k, unchanged |
| Room for work after it, with this change | ~100k | 83k–103k, unchanged |

For the action brain's cache: each compaction is followed by one request that starts with a new summary and finds
nothing cached (3.5% to 3.9% cached tonight). Tonight that request was about 185k tokens, twelve times; with this
change it is about 90k, and compactions are minutes apart instead of one per step. The summary request itself (about
13k uncached) is unchanged.

## 7. Failure modes

- **The tail is denser than the conversation's average** (fresh raw tool results behind older pruned ones): it keeps
  more than its setting by that difference; a tail twice as dense as the average would keep about 147k and land the
  action brain near 170k, still under its threshold. DSH's retry and its errors stay as they are for the case that is
  left: a compaction that fails is logged and the turn goes on with its history as it was (`index.ts`, the pre-step
  listener, "step compaction failed …; continuing the turn"); a request the model then refuses for its window is
  DSH's overflow recovery.
- **No usage yet, or a changed envelope**: the total is then an estimate too and the budget is not converted, so
  both sides are in one unit. That total reaches a threshold before the window itself is full only while the real
  count is under window ÷ threshold times the estimate (1.25 for her, 1.33 for the action brain); her conversations run 1.7 to
  2.3, so on this path she is not compacted at all, before or after this change. If she were, she would keep 76,021
  estimated (about 152k real at 2 to 1) and land at about 170k to 175k: under her threshold inside a turn, 209,715,
  about 10k under her turn-end point, 183,500 (Xiaoman, 00:49). The action brain and the presets whose setting did not
  change behave on this path as before.
- **A provider that reports less than the estimate**: the meter then takes the estimate as the total (its existing
  rule), so the budget is not scaled.
- No new I/O, state or file; nothing to survive a restart. A Host still on the old engine with the new settings would
  keep 0.32 estimated in her character brain (about 152k real): D2 and D3 land together, and the landing checks the
  loaded engine (§9).

## 8. Tests

- DSH, `compaction-basic.spec.ts`, one case ("counts the retained tail in provider tokens when usage reports more
  than the estimate"): a conversation whose last request reports usage at twice the estimate, with a tail setting
  that, read as an estimate, leaves it above the threshold. It compacts once and ends below the threshold. Mutation
  check (2026-11-01, after 00:33): with the conversion removed the case fails: its second attempt can fold only the first
  checkpoint, which DSH refuses as not smaller than what it replaces. Tonight's three failed compactions ended with an
  error of that length (87 characters); their text was not read. The package's suite: 158 passed; its typecheck and
  lint pass; the new function is covered (the package's one uncovered line is DSH's summary recovery, as before).
- Asuna: none new (settings and a pin). The landing's suite runs as usual.
- Real data (2026-11-01, before 00:39): tonight's session replayed into DSH's own `Session` and meter up to its first
  compaction (the events only; numbers printed). Total 199,869 (usage), surface estimate 90,388 (2.2 to 1). The old
  rule keeps 90 of 112 surface nodes, 73,861 estimated (about 162k real). The new rule's budget is 33,278 estimated;
  it keeps 35 nodes, 36,238 estimated (the cut rounds to a whole tool pair), about 80k real: with the fixed part and
  the summary, about 100k after the compaction.

## 9. Landing and checks

Packing refuses an inline build whose commit is not the pin (`tools/pack_plugins.py`), so the landing goes in three
steps with nothing between them: `land.py` without a restart (gates, fast-forward, push); the inline build from the
main checkout (`node tools/build_dsh_inline.mjs --source <the DSH worktree>`); `land.py --restart-only` in the next
slot Xiaoman gives. Then, from the live Host:

- The loaded `dsh-compaction-basic` is the inline build of the new commit (the activation's package hashes).
- The first compactions inside a turn: the action brain's next request near 95k–100k and no second compaction within the
  next steps; the character brain's next request in its usual 107k–127k.
- Her check: the first development task that compacts, read by her from her side.

## 10. The owner's

- Pushed `asuna/0.2.1-rc.2-realtail` to the fork at his word (2026-11-01 00:44); the fork's next upgrade is his, by
  another agent.
