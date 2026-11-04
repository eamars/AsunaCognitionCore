# ADR-062 review, 2026-11: the decisions, each with its options, pros, cons and costs

Companion to [review-2026-11.md](review-2026-11.md) (the numbers; section references below point there). Written
2026-11-05 at the owner's request so that a briefing session can take each decision with the owner without re-reading
the records. Nothing here is decided: the "Decided" line under each one is empty until the owner fills it. A decision
taken becomes its own ADR, or an amendment to ADR-062 with a new number and what changed and why; she reads what
touches her before it is built.

Six decisions. D1 and D6 are small and independent; D2, D3, D4 and D5 are design changes under the owner's rule of
2026-11-05 (fading only on the carried side; the store left as it is).

Cost words used below: *build* is the lead's estimate of coding and testing; *her part* is what she must do or read;
*risk* is what could go wrong on the real system; *running* is the cost per turn or per day once live.

---

## D1. Program-text turns and what counts as use (review B1)

**What is decided.** Whether a turn whose query is program text (a heartbeat, a scheduled turn, a visit) may count
an item it brings up as used, and as a memorable moment when a second such conversation brings it up.

**Why it comes up.** Nine fixed heartbeat texts drive retrieval. The same three journal rows came up in 28 of 29
heartbeats of 11-01..11-04, two at a time in 24 of them; each surfacing resets `last_use_at`, and the home heartbeat
and the groups' scheduled turns are "different conversations", so 114 memorable moments and 76 of the 82 几处都提到
night offers come from this echo. ADR-062 §4.1 meant to exclude exactly this ("one conversation echoing itself counts
nothing"); the pilot's own rule was "none in heartbeats".

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. A program-text turn surfaces but counts nothing** (recommended) | Removes the echo at its source; the two own-item slots in heartbeats stay free for a real match or fall back to memories; 几处都提到 regains its meaning; nothing she reads changes except that heartbeats stop repeating the same rows | A row that only ever comes up in heartbeats will cool like any unused row (that is the rule's intent) | build: hours (`deliver` already knows `turn_kind`; one condition in `surfaced`/`used`); her part: none; risk: none visible; running: none |
| B. Keep counting, but exclude heartbeats from surfacing own items at all | Same effect on the slots | Hides a real match in a heartbeat; a second rule where one condition does | build: hours; same otherwise |
| C. Leave as is | Nothing to do | The echo keeps three rows alive indefinitely and feeds the night list with offers she mostly ignores (17 acts on 82) | running: two of six memory slots in every heartbeat |

**Recommendation.** A. **What would change it.** Evidence that heartbeat turns ever act on those rows (none in 4 days:
no rewrite, no recall of them from a heartbeat). **Depends on.** Nothing; it can land alone or inside D2.

**Decided:** —

---

## D2. The carried side: one ceiling and one overflow rule, no refusal (review B4, §6.1)

**What is decided.** What limits what she carries, and what happens when the limit is reached. Today four
mechanisms overlap: per-store count caps (self 12, persona 18, notes 10, voice 6, core 12), the ADR-096 token
ceiling per (place, class) pair (12,288 estimated tokens), her `let_go`, and the stay lapse by memorable moments.

**Why it comes up.** In 22 days her `let_go` made 191 of 229 moves; the count caps overflowed 11 times; the stay
lapse fired once. The token ceiling binds first and refuses: 125 refusals, home at 12,278 of 12,288. ADR-062 §4.2
step 3 was built so that "adding a 13th does not refuse: the least recently memorable lapses"; the later gate undid
that, and the ADR's own §7 failure sign ("refusals for length do not reach zero: the cap is still doing the
forgetting") has held for three weeks. Her answer to being compressed is the one §1 measured before the ADR:
details packed into the same space.

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. One ceiling per pair (tokens), one overflow rule: her choice for a turn, then the least recently memorable lapses until the pair fits; count caps removed; no refusal for length** (recommended) | The flip ADR-062 was built for finally runs: the newest stays, the stalest goes down, she is told once; the 10-18 addendum (her choice first) is kept; four mechanisms become two (ceiling + her let_go) with the lapse as the default; the `CAPS` table and per-store `_overflow` go | A program lapse may put down something she wanted (6 of 12 program lapses came back within 0.1 day; her choice turn mitigates); a public section is carried in several pairs, so freeing room in one pair lapses it everywhere (the lapse order must weigh the over pair); a big section may be needed to fit, so more than one may lapse at once (the "over by one item for one turn" rule becomes "over by N tokens for one turn") | build: 2–3 days (`carried.gate` already measures before the write and `placement_after` already plans; the plan becomes lapses instead of a refusal; tests in `test_carried.py`, `test_action_tiers.py` change); her part: reads the new rule and the room line wording; risk: a wrong lapse order on day one, visible in `moved` lines and reversible by her rewrite; running: none added |
| B. Keep the gate; raise the ceiling | Cheapest change | The pressure moves, it does not go; the carried layer costs more in every turn of that pair; the idle lapse stays idle | build: one number; running: more carried text in every turn |
| C. Keep the gate and the caps; fix only D1 | No design change | Refusals continue at 5–6 a day; she keeps compressing; two count caps that never bind stay in the code | nothing |
| D. Remove the ceiling, keep the count caps as the only limit | Simplest rule to tell her | Count caps do not bound tokens: ADR-096 measured the self layer at 3.9× its designed size under count caps alone; the owner's discipline condition (a reasonable budget she may want to exceed) goes | build: hours; risk: the layer grows again |

**Recommendation.** A. **What would change it.** If she prefers refusals to program lapses (her 10-18 ask was to
choose herself; A keeps that choice for one turn). **Depends on.** D1 should land with it or before, so that program
text does not decide which item is "least recently memorable".

**Decided:** —

---

## D3. The stored side: remove the imitation of forgetting (review §6.6)

**What is decided.** Whether the mechanisms that act on the stored text or on a stored state in ADR-062's name of
fading stay: the gist step (her gist replaces the head text, the verbatim kept behind `detail_of`, two nights to
write it), cooling of memories 手边→收着 as a stored state (journal rows after 30 days unused, others by the
forgetting formula), supersession through the `correction` op, the mandatory merge offer for fact stores, and the
几处都提到 offers that graduate items into `core`.

**Why it comes up.** The owner's rule: the store is left as it is; compression happens when she picks what to carry.
In 22 days: 6 gists written, 0 skipped; 0 coolings (the first wave is due 11-13); 0 supersessions, because
`correction` is allowed only on ledgers and no ledger exists (41 attempts, 41 refusals); 0 merges by the designed
path; 82 graduation offers and 1 new core item. The night list is 104 of 128 offers about journal rows.

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. Remove all five in one ADR; keep 放手, the three place words (随身 carried, 手边 may come up by itself, 收着 only when asked), `nature`/`from` as her words on an item, and the near-duplicate pairs (they still serve the confirmation rule and D4's write-time line)** (recommended) | About 300 lines and six tables go (`GIST_*`, `_gist_rewrite`, `gist_refusal`, `claim_chars`, `detail`, the cooling branch of `tick`, the superseded branch, the night list's merge and repeated kinds, their offers); the night list shrinks to nothing on most nights (about 2,500 characters saved in a settlement turn when it fired); the store stops being rewritten in the name of fading; "what did I hold before" stays answerable through the revision ledger and `crossing.before`'s 「已被更正」 marks; the 6 gists keep their verbatims in the ledger | Loses the designed "detail fades into gist" story and the 几处都提到 → core path (she writes core herself; 1 item came through the offers); her told text (`memory.tiers_told`, her own words: 「…淡下去不是删掉…事实只会被更正替换，不会因为没人用而退；记忆会淡」) no longer describes the system and is hers to rewrite; without cooling, the per-turn candidate pool of `deliver` needs its bound from an age filter instead of a state (same effect, no row written) | build: 1–2 days plus the removal of tests that guarded the removed paths; her part: reads the ADR, rewrites her told text, says whether she wants to keep writing gists by hand (she may: a rewrite is a rewrite); risk: low (nothing that fired is lost); running: fewer night-list characters, one scan less at settlement |
| B. Wait for the first cooling wave (11-13) and re-read in two weeks | Evidence on what cooling does to the pool and to recall before deciding | Two more weeks of the night-list chore and of a broken correction path; the decision is the same unless cooling shows a benefit, and the owner's rule already rejects it as a stored state | nothing now |
| C. Keep all five and fix `correction` (allow it wherever `replace_section` is) | The designed supersession path finally works | Keeps five stored-side mechanisms the rule rejects; she rewrites in place anyway (611 replaces), so supersession would add a second way to do what one sid already does | build: hours for the op; the rest stays |
| D. Remove the gist and merge chores only; keep cooling and correction | Smaller change | Correction stays broken unless fixed as in C; cooling stays a stored state; the night list keeps the 几处都提到 echo (unless D1 lands) | build: 1 day |

**Recommendation.** A. **What would change it.** Her saying she wants the gist step kept as a habit (then keep the
night listing as an offer with no clock, and drop the two-night rule). **Depends on.** D1 (the repeated offers are
mostly its echo) and D4 (the write-time line replaces the merge offer; the pair detection stays either way).

**Decided:** —

---

## D4. The storage model: copies, deltas, rows (review §6.4)

**What is decided.** Whether the revision ledger changes shape (deltas, or content-addressed sections), and whether
the program tells her of a near-duplicate at write time.

**Why it comes up.** The owner suspected near-duplicates as a big retrieval problem and asked whether storage should
be delta-based like git. Measured: near-duplicates among current items are 0 (persona), 2 of 40 (self), 2 of 208
(group notes), 32 of 1,098 (journal rows, written 0.9 days apart); across stores 5 pairs; none at 0.97. In retrieval
15% of turns return two units from one source message and 6% two halves of one message; no superseded version is
ever returned (nothing is superseded; she rewrites in place). The waste is whole-document copies: 113 MB of revisions
for 1.03 MB of live text, because each revision copies every section to change one (persona: 1 changed, 58 copied,
240 times); one working document she uses as a log is 320 KB a write, 145 revisions in 18 days, and reaches the 1 MiB
revision wall at about 400 sections (two months at its pace). The heads model (one current revision per entity,
revisions with parents, nothing overwritten) is already git's; what is missing is only the sharing of unchanged
content, which git does with content-addressed blobs, not with deltas (its packfile deltas are an on-disk encoding).

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. Rows for logs, plus a write-time line** (recommended): any document she appends to as a running record is `kind: journal` (she re-creates #12 as one, as `work_log` was moved in phase 0); an append whose body is at 0.93 or above to an existing item of the same store gets one line in its result naming that item's ref (no refusal, no merge); the night merge offer goes (D3) | Removes the 320 KB copies and the wall where they are, with a mechanism that exists (journal rows are 2.4× the live text); identity at write time stays hers, at the moment the memory is active (reconsolidation), instead of a chore a day later (0 merges in 22 nights); the same comparison sets `confirmed` for her "a judgment becomes a fact when someone else says the same" rule | Her log, once rows, is indexed and may come up by itself at home (today it is a working document: not tiered, not indexed, reachable by heading only), a change she must want; the write-time line needs the new body's vector at write time: one embedding call in the tool body (50–100 ms on the memory route, skipped silently when the route is down; the index's 10-minute sync can reuse the vector); a converted log's old document stays as history | build: 1 day (the line; `_journal_import` exists for configured journals: her re-creation or a one-time import by kind, the owner's call as in phase 0); her part: re-create or accept the import; read the line's wording; risk: low; running: one embedding per append |
| B. Content-addressed sections (git's tree + blob): a revision lists (sid, body hash); bodies stored once | Disk 110× → about 2×; snapshot semantics kept; history reads stay simple (one query by hash list) | Benefit is disk only (15–20 MB a week today: no cost the deployment feels); touches `documents._commit`, `DocumentStore.read`, `history()`'s four readers, `detail()`, the memory tab; old revisions stay fat (not wrong, only big), so two shapes are read: a compatibility path the discipline dislikes | build: 2–3 days plus a restart; her part: none; risk: a reader that misses one shape; running: one more query per document read |
| C. Delta chains with periodic snapshots | Disk saved | Every history read becomes a replay; a new encoding every reader must learn; no retrieval effect; git itself keeps deltas out of its model | build: 3–4 days; risk: moderate |
| D. Nothing | No work | 1 GB a year of copies; the #12 wall in about two months, after which she must split the document by hand (as she had to with `work_log` before phase 0) | running: 15–20 MB a week |

**Recommendation.** A now; B only if the ledger's size ever becomes a cost; never C. **What would change it.** A
measured retrieval problem from near-duplicates (none today: the pairs are 0–3%). **Depends on.** D3 for the merge
offer's removal; nothing else.

**Decided:** —

---

## D5. Phase 3: understanding as items, the idea age word, sticker last-used words (review §6.2)

Three sub-decisions; 5b and 5c are closures.

### D5a. Understanding layers as items

**What is decided.** Whether the person layer (one record per person, read wherever she meets them) and the here
layer (one per person and conversation) become items she writes and the tiers carry, with a carried cap per person.

**Why it comes up.** The person layer is carried whole in every one-to-one turn with that person (599 of 599 such
turns in 4 days, 5.8k characters with the here layer); she rewrites it whole, and it grows 194 characters a rewrite
(p50). The owner's own record is at 3,563 of the 4,000-character cap after 20 revisions: within about two rewrites
the cap refuses it and she compresses into the space, the `current_self` failure ADR-062 §1 measured, on the record
read about 600 times a day. In groups she already carries a one-line short of the person who woke the turn (74% of
entries), which is compression at carry time. The understanding block is outside the ADR-096 identity ceiling, so
nothing bounds it today. The hard case (a person's stated boundary, her promise to them) is carried today in 1:1 by
carrying everything, and in groups only if she put it in the short.

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. A document per person, sections as items, a carried cap per person (the phase-3 plan)** (recommended): `understand_person` keeps its name and its read-first rule and writes sections; the tiers carry up to N per person, the rest is at hand (by meaning, by key, by `recall person`); the short is one fixed section; the one-time split is hers, record by record, never forced (a record may stay one section) | The carried part of a person becomes her choice, which is the rule; reuses `write_document`'s ops, the tiers, `recall`'s sections and the index, as `self` does; a boundary or promise she keeps carried stays carried (facts never cool); the understanding block gets a bound without a refusal; measured first on the owner's record | ADR-082's revision pins and write rule move onto document base revisions (same CAS, new wording); the entry and `person_view` read sections; about 35 documents more (one per person written), which the per-turn `sync` walks today (review B3 should land first or with it); the here layer's one-per-conversation shape must stay per conversation (a document per person and scene, or sections tagged by scene) | build: 3–4 days plus ADR and tests; her part: reads it, splits the records she wants split; risk: a wrong carried default on day one (take the whole record as carried, as `self` did, so nothing lapses on the switch); running: the carried text per person falls to what she keeps carried |
| B. Keep one body; raise the 4,000 cap | No build | The carried block grows without bound in every one-to-one turn (it is outside the identity ceiling); no compression anywhere; the same failure later at the new cap | build: one number; running: more characters in every home turn |
| C. A carried part beside the body (a long short, say 600 characters): the body on recall only | Smaller than A; one more field in the same revision, like `short` | Two texts to keep in step by hand (what she carries can drift from the body); the carried part has no items, so no lapse, no key, no heading to recall by; still a cap she must compress into | build: 1 day; her part: writes the carried part for each record; risk: drift |
| D. Nothing now | No work | The owner's record hits the cap in weeks; she compresses | nothing |

**Recommendation.** A, after she reads it, measured on the owner's record first. **What would change it.** Her saying
the person layer is not something she wants in items (she said yes to items for `self`, whose shape §4.4 called the
same). **Depends on.** Review B3 (per-turn walks) for the document count; D2 for the ceiling's shape if the
understanding block is to join it.

**Decided:** —

### D5b. The idea age word (很久没动)

**What is decided.** Whether an open idea unread for 30 days is listed with the word 很久没动 and the choices 还要 /
放弃 (ADR-062 §4.4).

**Why it comes up.** Her pattern: an open idea is decided within a day (9 open, all under 2.4 days old); the pile is
`deferred` (323 ideas, median 5.3 days since the last decision, max 22.5; 20 touched twice), where each entry already
shows its date (`at`) and its earlier reason (`deferred_before`), and the page says how many are left.

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. Drop the item** (recommended) | Nothing to build or read; the dates already there say what the word would | None found: the word would apply to no idea today | nothing |
| B. Build it as designed (open ideas at 30 days) | Follows the plan | Applies to nothing; one more word in the ideas block | build: hours; running: none |
| C. Build it for deferred ideas instead | Fits where the pile is | Adds a program word for what the date already says; the deferred page is hers to read when she wants | build: hours |

**Recommendation.** A. **What would change it.** Open ideas starting to age (none in four weeks).

**Decided:** —

### D5c. Sticker last-used words

**What is decided.** Whether to build "the weekly review gains last-used words" (ADR-062 §4.4).

**Why it comes up.** `stickers.review_block` already says 收了以后还没发过 for a never-sent sticker and 上次发是 plus a
rough-ago tier for an idle one, once a week or whenever the shelf is at 80% (it is 60 of 60, so every week). Her
pattern: 245 sends in all, 9 never sent, median 7 days since last use, max 28.

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. Close the item as already built** (recommended) | True to the code | None | nothing |
| B. Add per-sticker last-used words to the sticker block in every turn | Visible outside the review | A per-turn block that changes often (a cache cost) for a weekly question | build: hours; running: block churn |

**Recommendation.** A.

**Decided:** —

---

## D6. Scaling fixes to schedule (review B3, B5, B6, B7, B8)

**What is decided.** Which of the small, independent fixes land, and when. None changes what she reads.

| Fix | What | Why now | Cost | Recommendation |
|---|---|---|---|---|
| B7 | an index on `state_revisions` (entity_key, created_at) | `history()` is a collection scan on every recall with a query (10 ms today, 113 MB and growing) | one line in the catalog; a restart | now |
| B5 | stop indexing the legacy `current_self` lines once `self` exists | 16 dead items in the index, one false pair | hours | now |
| B3 | tiers bookkeeping incremental: rows made on write, an index on `memory_tiers` (row, persona, place, store), counts kept per store instead of walking every row and every journal entry each turn | 100–150 ms of worker CPU per turn today, linear in the store (about 10× in a year) | 1–2 days; risk: a counter that drifts (a nightly recount guards it) | within a month |
| B8 | the chunk watermark per scene, not on the message row | 314 write conflicts in 22 days make the indexer pause up to 5 minutes per conflict; no loss, but delayed chunks | 1 day | within a month |
| B6 | one profile reading of a recall's parts (a line per part in `tool.time`), then bound the slow one | recall takes 2.8–4.9 s at the median and her use of it fell by two thirds | the reading: hours; the fix: unknown until read | the reading now; the fix after |
| B9 | her `budget_per_place.py` (hers: pass the real `Store` it already builds) | crashes at `memory_tiers.py:239` since ADR-104 | three lines, hers | tell her |

**Alternative:** defer all until D2–D5 are decided. Cost of deferring: B3's growth and B6's latency are the two
things in the review that get worse with time; the rest can wait.

**Decided:** —

---

## Order, if all are taken

1. D1 (hours) and D6's B7, B5, B6 reading (hours each): no design change, land as small batches.
2. D2 with D1 as one ADR (the carried side).
3. D3 with D4-A as one ADR (the stored side), after she has read both.
4. D5a as its own ADR, after B3; D5b and D5c closed in ADR-062's index row.
5. D6's B3 and B8 as their own landings.
