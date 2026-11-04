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

Amended by the exchange below: D6's B3 and the lexical-pool index move ahead of D2 and D3; the B6 profile reading
is the new ADR's first step; D7 joins the D1 batch.

---

## Exchange with the lead (Claude Code, 2026-11-05 afternoon), with the measurements it asked for

The lead read the review, checked three claims against the code (they hold), agreed with D1, D3-A, D4-A, D5b-A,
D5c-A, D6 and the order, and raised five points. The reviewer's answers, each with the data read for it (her
database, read-only, 2026-11-05 13:00–13:30 NZDT), and the amendments that follow. The lead then agreed on all
five as amended (2026-11-05 afternoon) with one addition under point 3, and takes the agreed set to the owner; the
"Decided" lines stay his.

### Point 1 → D7. Duplicates one level below items: two units of one source message in a turn

Measured on the 7 days' 2,030 retrieval manifests, with the selected units fetched by id:

| Pair in one turn's six | Pairs | Turns | Share of turns |
|---|---|---|---|
| a chunk and the dialogue summary covering its message | 268 | 198 | 9.8% |
| two halves of one long message (the chunker cuts at 900 bytes, no overlap) | 122 | 119 | 5.9% |
| two of her thoughts from one turn | 3 | 3 | 0.1% |

Long messages are selected out of proportion: chunks of multi-segment messages are 16% of the distinct chunks
selected (401 of 2,481) but 23% of chunk selections (1,904 of 8,202).

| Option | Pros | Cons | Cost |
|---|---|---|---|
| **A. One slot per message: when two halves of one message are selected, they are joined in segment order into one entry** (recommended) | Frees a slot in 6% of turns and loses no text (the lead's "keep the best-scoring half" would drop the half the query may have matched; the halves are different text) | The joined entry is longer than one chunk; the turn's excerpt cap (800 characters) cuts it as it cuts any unit; recall reads the rest | build: hours in `retrieval.search` after selection; risk: none visible |
| B. One unit per message, best-scoring kept (the lead's proposal) | Same slot saving | Drops text that matched | build: hours |
| C. Also collapse chunk + summary pairs (keep the chunk) | Frees a slot in 10% of turns | They are not one idea: the chunk is the line, the summary the batch's gist with its attribution; the step-back rule already removes faded chunks a summary covers, these are fresh ones | build: hours; risk: losing the window's context |
| D. Nothing | – | 6% of turns spend a slot on a second half | – |

Not covered by any option and left as a known number: the same six units as the previous turn of the conversation
in 8.6% of turns (partly by design: two slots are reserved for the most recent statements).

**Recommendation.** A, in the D1 batch. **Decided:** —

### Point 2 → D2 amended: no interim state; the lapse order gets a tie-break

The lead's worry: 6 of the 12 program lapses came back within 0.1 day, so a program lapse as the default overflow
should wait until D1 has run a week; meanwhile an over-ceiling write would land and she would be told she is over,
with no lapse.

Data: (a) the heartbeat echo does not touch the carried set's order: of the 120 carried items, none has a
`surfaced_again` moment (their last moments: rewritten 58, none 55, recalled 4, cited 3); the echo lands on
at-hand journal rows. A week of D1 changes nothing in the pick. (b) The regret comes from the pick rule among the 55
carried items that never had a moment: ties go by document order, the oldest section first, which is arbitrary.
(c) The drift of an unbounded week: the persona and `self` grew +171 and +181 characters a day net over the last 14
days with the gate refusing 5.7 writes a day; a landed growing step is +258 characters at the median (+750 at p90).
If the refused writes had landed: worst case +1,470 characters a day, about +7,700 estimated tokens in a week (63%
of the home ceiling); a middle case +3,000–4,000 (25–30%). A week of that is paid in every home turn's prefix.

Amendment to D2-A: (i) no interim "land without lapse" state: D1 and the one-line fixes land now, D2-A lands whole
later (a week later if the owner wants D1's readings first, though they do not bear on the pick); (ii) the lapse
order among items with equal `memorable_at` is by the program's own carried score, `carried_counts.program_score`
over the last 30 days (how many turns' retrieval would have brought the section up; ADR-096 D5 keeps it per
section, pair and day: 5,428 rows for 21 days), lowest first, `felt` last as now; (iii) the order weighs the pair
that is over: a section carried only there frees room only there. Her choice turn, the moved line and her 0.1-day
reversal stay the safety net the 12 cases show. **Decided:** —

### Point 3 → D5a amended: the hard case without a pin

The lead's proposal: sections she marks as a boundary or a promise leave the carried set only by her let_go, never
by overflow or lapse. The reviewer disagrees with it as designed: it is a pin by another name, which ADR-062 rejected
on measured grounds, her told text rules out (「我也不能喊留着；只有放手是我自己的动作」) and the owner upheld on 10-18.

Counts: no boundary can be counted in the person records today (they are bodies, not sections); across her
documents 16 items carry `from: 别人说的` (14 facts, 2 memories) and 17 carry a line anchor (ADR-108 D2), so the
marking habit exists and is small. After her split the count is the sections with 别人说的 and an anchor per person.

Alternative with the same guarantee where it exists today, structural (the program reads `from` and the anchor,
never the text):
1. The carried budget per person is today's 4,000 characters, not an item count: every record is carried whole
   as today until it passes 4,000; only the owner's record (3,563) is near it.
2. Over the budget: her choice turn first, then the lapse order puts sections that are someone's own stated words
   with the line they rest on (`from: 别人说的` + anchor) last, after `felt`. A visible tie-break, not an
   exemption: it can still lapse when the whole carried set is such sections, which is the honest limit.
3. In groups, the woken person's entry carries, beside the short, that person's carried sections with 别人说的 and
   an anchor, up to a bound (about 300 characters). That is what puts a boundary in front of her in a group turn;
   no short-only design does.

If the owner wants the exemption anyway: model it on ADR-096 D6's note pins (bounded, at most K per person, hers
to set, never a program act), not on a `nature` value, so a pin budget cannot become the whole record. Her own
promises have no `from` word today (主人定的 and 查过的 do not fit); if they are to get the tie-break, that is a new
word on the table, hers to name.

**Addition (the lead, 2026-11-05, agreed by the reviewer):** her own promises to a person are the other half of
the hard case. The ADR asks her to name a `from` word for them (hers; the program only reads it), and a section
with that word gets the same lapse-last tie-break as an anchored 别人说的 section. The bounded note-pin model above
stays the fallback to offer the owner if he wants an exemption. **Decided:** —

### Point 4 → D6 reordered: the memory side's load on the shared box, per turn

Measured 13:10 NZDT on the three busiest scopes of the week:

| Read, every character turn | Round trips | Bytes | Server work |
|---|---|---|---|
| the lexical pool (`retrieval.search`: the newest 4,096 units of the scope) | 1–2 | 9.1 MB | an index scan of every active unit of the scope (8,116 / 10,234 / 19,506 examined), a fetch of each, an in-memory sort, then the first 4,096: 111 / 111 / 209 ms |
| the authoritative recheck of candidates (one get per candidate) | about 50 | small | index gets |
| `Tiers.sync` (every document's current revision: an entry probe, a head, a revision each; the journal's rows) | about 125 (3 × 40 documents + the journal's 4) | 1.8 MB + 3.6 MB | index gets; 43 + 15 ms |
| `tick`, `things`, `deliver`, `overflows` (tier row scans), room, moves, came_back | about 10 | 1.7 MB each scan | collection scans of `memory_tiers`, 21 ms each |

About 200 round trips and 15 MB a turn from the memory side alone, about 300 turns a day; the admission figure the
lead cites (150 sequential round trips) is the same order. The round-trip count for `sync` is from the code
(`DocumentStore.read` per slug), not from a driver trace.

Amendment: B3 and the pool move ahead of D2 and D3. The pool's first fix is an index that carries the sort: with
`occurred_at` in the index after (scope_key, status, policy_epoch) the scan stops at 4,096 and the SORT stage goes
(one catalog line); the 9.1 MB transfer stays until the per-scope lexical index of review §6.5 replaces the window.
**Decided:** —

### Point 5 → B6 into the ADR; the expected order of a recall's parts

Agreed: the profile reading is the new ADR's first step. What the code and one measurement say about the parts:

1. **`crossing.history('work_log')` rebuild.** Its cache seal is the journal's last revision; the journal gets 33
   revisions a day and she recalls 8.7 times a day, so nearly every recall with a query rebuilds. A rebuild reads the
   frozen document's 250 revisions (88.8 MB serialised, 548 ms warm) and the 988 journal revisions (40 ms), then
   diffs in Python (11 ms): about 0.6 s a recall today, growing with the journal and cold reads. Top suspect.
   Fix: the pre-rows history is fixed since 10-12; read it once per process (or drop it from `history()` once the
   rows' own revisions hold the changes) and key the cache on the journal alone.
2. **The recall's own `prepare`** (everything a normal turn builds, the pool's 9.1 MB and sort, about 50 recheck
   round trips, a query embedding; the retrieval cache never hits because the pool is capped).
3. **`crossing.top_up`:** the group lines since the mark, each cut by jieba in Python, then one update per word;
   50 lines were waiting right after the 11-04 settlement rebuild, hundreds between recalls. Estimate 0.1–0.5 s.
4. **Two embedding calls** (retrieval and her thoughts elsewhere), on the local route; unmeasured.
5. Headings, keys, past versions' matching: small.

The profile should write one duration per part into the `tool.time` row of a recall, then bound the largest.
**Decided:** —
