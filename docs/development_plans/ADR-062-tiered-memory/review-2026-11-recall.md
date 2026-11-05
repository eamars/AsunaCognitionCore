# ADR-062 review: where a recall's prepare spends its seconds (2026-11-05)

For ADR-117's recall fix (the step before L4). The lead's question, after L1 went live at bb6eab16 and the per-part
profile of her recalls spoke: what in a recall's `prepare` costs about 4 s, the smallest bound that keeps the results
identical, and why `own_thoughts_elsewhere` takes about 1.1 s every time. Read-only; the measurements below are from
one bounded probe on her database and from the Host's own records.

## 1. What her records say

Five full recalls today (02:04–02:08 UTC, her agent line, home class), `tool.time` parts in seconds:

| part | min | max |
|---|---|---|
| prepare | 4.13 | 4.50 |
| own_thoughts_elsewhere | 1.05 | 1.28 |
| elsewhere | 0 | 1.55 |
| before | 0 | 0.69 |
| read_sections, recalled, headings | 0 | 0.03 |

The query embedding, from the Host's evidence records today: 13 calls, p50 0.239 s, max 0.291 s.

## 2. The probe

`review-2026-11/recall_probe.py`: the live code (bb6eab16) run from the worker's machine (1 Gbps Ethernet to the
database box), writes refused by a guard, the embedding route never called (a stored vector of the scene stands in),
the query the script's own words, started only after 90 s without a turn of hers. It times the pieces of
`retrieval.search`, `own_thoughts`, the tier reads `deliver` makes, and a recall's `_prepare` with retrieval off
(everything a recall builds that is not its memories), counting round trips and bytes by collection.

| piece | seconds | round trips | bytes |
|---|---|---|---|
| `retrieval.search`, whole | 0.49 | 56 | 10.3 MB |
| · the pool fetch (4,096 units; server 25 ms, SORT_MERGE of 3 index scans) | 0.14 | 1 | 9.3 MB |
| · lexical CPU: `terms` over the pool 0.14, the `Counter` 0.07, scoring 0.02, the state-revision sha 0.01 | 0.24 | 0 | |
| · 46 authoritative rechecks (1.3 ms each) | 0.06 | 46 | 185 KB |
| · `nearest`, exact, k=24 | 0.03 | 1 | |
| · every identity, for aliases | 0.04 | 1 | 808 KB |
| the query embedding (Host evidence, not the probe) | 0.24 | HTTP | |
| `deliver`: `tiers.items()` 0.05 (1.2 MB), rarity 0.004, `rank` 0.05–0.12 (the pilot's own `job_ms` at 790 items) | 0.15–0.20 | 2–4 | 1.4 MB |
| the rest of `_prepare` (retrieval off): 22 blocks, 35 K characters | 1.05 warm, 1.46 cold | 325 | 16.1 MB |
| the writes a live recall's prepare makes (about ten, about 10 ms each) | ≈0.10 | ≈10 | |

The rest, by collection (warm): messages 14 calls 0.22 s; artifacts 4 calls 0.97 MB 0.20 s; journal_entries 104 calls
3.6 MB 0.15 s; tasks 5 calls 9.3 MB 0.12 s; state_revisions 65 calls 1.7 MB 0.07 s; state_heads 70 calls 0.06 s;
memory_tiers 12 calls 0.04 s; scenes 15, notes 12, episodes 10. By function (cumulative profile): `ledger_block` 0.35 s
(`docs.slugs()` then every one of 52 documents read whole to find the ledgers, the work log's 3.6 MB of entries
included, with two `is_journal` probes per document); `task_pages` / `observations_of` 0.17 s (artifacts);
`notes.sent_block` 0.17 s; `People.scene_title` ×13 0.14 s (one message read per conversation named);
`tasks.recent_with_inputs` 0.13 s (every task of the scene with its whole result text: the 9.3 MB);
`recent_thoughts` 0.06 s; `render_system` 0.05 s. Every turn of hers pays this too; a recall pays it again for the
three keys it reads (`memories`, `coverage_from_program`, `held_back_from_program`).

The writes: `audit retrieval.selected` (the stream's newest seq is an indexed lookup, (stream_id, seq)), six
`touch_salience`, zero to two tier marks (`used`, `memorable`), one evidence file. About 10 ms a write, from `think`'s
`tool.time` p50 0.047 s for three or four writes.

## 3. Answer 1: the ranking

Measured, per recall, from the worker's machine:

1. The blocks a recall builds and never reads: 1.05–1.46 s, 325 round trips, 16 MB. The largest, and the one that
   scales with the box's latency (325 waits).
2. The lexical CPU on the pool: 0.24 s.
3. The query embedding: 0.24 s (and the same query embedded again inside `own_thoughts_elsewhere`, 0.24 s more).
4. `deliver`: 0.15–0.20 s.
5. The pool transfer and decode: 0.14 s for 9.3 MB. Not the cost it looked like.
6. The writes: about 0.10 s.
7. The 46 rechecks: 0.06 s.
8. `nearest`: 0.03 s.

The sum is 2.1–2.5 s against the live 4.1–4.5 s. About 2 s are not reachable from outside the process. The candidates:
the box's per-round-trip latency under her own load (at 6 ms a wait instead of 3, the rest alone is 2 s); the GIL time
of the pilot's job, which starts at `submit` and runs through `deliver` and the rest (50–120 ms today, once 945 ms);
garbage collection in a 350–450 MB process. Three `part()` marks inside `_prepare` (`prepare.search`,
`prepare.deliver`, `prepare.rest`; `tool_watch.part` works in any function of the call's thread) settle it in one day
of her recalls. Whatever the remainder is, it rides on the round trips, and the bound below removes most of them.

## 4. Answer 2: the smallest bound with identical results

`ContextBuilder.recall(event, persona, turn_kind)`, made of these lines of `_prepare` at bb6eab16 and nothing else:
375 (authorize), 380 (`counts`), 391–394 (scope, moment, session class, place), 409–416 (`read`, `target`: config
only), 436–508 (the source line, the history rows exactly as now with their projection, the group catch-up and the
linked merge, and `tail_sources`), 525–575 (`search`, `submit`, `deliver`; the cue is already skipped for a recall),
593–627 (`facts`), 681–690 (`held_back`, the coverage line). It returns `{'memories', 'coverage_from_program',
'held_back_from_program'}`. `_prepare` calls the same helper for its own memories, so there is one code path and the
results are identical by construction, not by test. `tool_recall` (role_tools 1808 and 1812, the place and the
errand's home) calls it instead of `prepare(..., recall=True)`. `prepare`'s `finally` (`anchors_shown`) stays in the
wrapper if byte-identical behaviour is wanted; it pops the scene's anchored state once a turn, and a recall popping it
again mid-turn changes nothing visible.

Expected per recall: search 0.49 + embedding 0.24 + deliver 0.2 + history 0.05 + writes 0.1 ≈ 1.1 s, from 4.1–4.5 s;
round trips about 380 → about 65; bytes 26 MB → 10 MB. Her three recalls in one turn: 12.6 s → 3.3 s.

Not identical: reusing the turn's own prepare (its memories are for the message; a recall's are for her question).
Second-order, later: a per-turn cache of the pool and its `document_terms`, keyed by (scope, epoch, newest unit id,
count), 0.38 s per extra recall in the same turn; `all_identities` projected to display name and person id (0.8 MB a
search → kilobytes).

Tests: `tests/test_adr117_counts.py:80` calls `prepare(..., recall=True)`; it keeps working if `prepare` keeps the flag
as a thin wrapper over the helper. One new unit test on the in-memory adapter earns its place: `recall(event)` equals
the three keys of `prepare(event, recall=True)[1]` for one event, frozen once.

## 5. Answer 3: `own_thoughts_elsewhere`, 1.1 s every time

- 0.71 s: the monologue read, `readable(23 group pairs, kind='monologue', by=('formed_at', '_id')).rows(limit=2048)`.
  Explain: an OR of 23 index scans on the scope index, FETCH of 173,283 documents (every unit of the 23 groups), the
  `kind` filter after the fetch, an in-memory SORT by `formed_at`, then the limit: 778 ms server time, 2.7 MB out.
  No index carries `kind` or `formed_at`; the 2,048 bound limits the transfer, not the scan. 4,851 of the 173,283 are
  monologues.
- 0.24 s: the query embedded a second time (`retrieval.py:203`), though `query_vector(query)` holds the vector the
  search computed a second earlier.
- 0.1–0.2 s: three authoritative gets, `reasons.then`'s audit reads, and `People.scene_title`'s one message read per
  group named (two reads, 0.2 s here).

The fix that keeps results identical: an index `(scope_key, status, policy_epoch, kind, formed_at, _id)` on
`memory_units`, so the plan becomes the pool's (SORT_MERGE of index scans, 2,048 keys, about 25 ms server time); about
15–20 MB, built by hand while she is quiet, as L1's was; and `v = self.query_vector(query) or self.embed(...)` in
`own_thoughts`. Same filter, same sort, same vector: about 0.15 s.

## 6. Evidence

- `review-2026-11/recall_probe.py` (usage: `python -X utf8 recall_probe.py <config/local.json> <scene id> <out.json>`),
  rerun after the fix on the same basis. Its JSON output of this run stayed in the session's scratch folder.
- Her `tool.time` rows with `parts` (ADR-117 L1) and the Host's `provider.response` evidence records are the live
  numbers; the probe's are a lower bound measured from outside the worker.
