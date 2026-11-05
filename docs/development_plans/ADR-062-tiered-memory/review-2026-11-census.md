# ADR-062 review, 2026-11: code census for ADR-117's five landings

For the lead's ADR-117 (branch `claude/adr117-memory`), at their request of 2026-11-05 afternoon. Counts are from
`grep` over `src/asuna`, `tests` and `integration` at commit `7cc54d3f`; sizes of what she reads are measured
(`tests/test_tool_budget.py`'s method for tool texts; the review's §3.5 for blocks). Read-only; her database was not
touched for this page except where the review already had the number. Each landing: (1) code, (2) stored state and
its life cycle, (3) tests, (4) what she reads, (5) failure modes, (6) what needs her answer.

Common to every landing: `docs/map` is regenerated (`tools/project_map.py`; `tests/test_project_map.py` fails while
stale); RUNTIME_API.md and the module docstrings change in the same commit where an interface does; the character's
tool budget constant (`tests/test_tool_budget.py`, `CHARACTER_TIERED = (30, 21139)`; measured today 30 tools,
21,079 characters declared) moves by the deltas given.

---

## L1. Indexes, B5, the B6 profile, D1, D7

### 1. Code

| Change | Where | Kind | Call sites |
|---|---|---|---|
| lexical pool index | `store/catalog.py:321` (`memory_units` indexes) | replace `index(scope_key, status, policy_epoch)` by `index(scope_key, status, policy_epoch, occurred_at, _id)` and put the old name in `retired`; `ensure` (`store/mongodb.py:369`) makes and drops | the query it serves: `records/memories.readable` (`memories.py:107`), called by `retrieval.search` (`retrieval.py:224`, sort `('occurred_at','_id')` newest first, limit 4096) and `retrieval.own_thoughts` (limit 2048); the `$or` of (scope, epoch) pairs gets one index branch each and a SORT_MERGE, so the scan stops at the limit |
| B7 revisions index | `store/catalog.py:329` (`state_revisions`) | add `index(entity_key, created_at)`; both fields are declared text | `records/heads.history` (`heads.py:84`): 4 callers, `documents._section_times:311`, `crossing.versions:493` and `crossing.history:513`, `reflection_map.py:58,69`, `context_budget.py:272` (off path) |
| B5 | `memory_pilot.own_items` (`memory_pilot.py:72-78`) | skip the `current_self` lines when the `self` document has sections | 1 caller, `Pilot.sync:251` |
| B6 profile | `tool_watch.py:86-127` (`timed`, `_time`) and `role_tools.tool_recall` (`role_tools.py:1780-1890`) | `tool_watch.part(name)`: a context manager that adds `{name: seconds}` to the in-flight entry of this thread (`entry['thread']` is kept already); `_time` writes `parts` into the `tool.time` payload; `tool_recall` wraps its 7 parts: `context.prepare` (and the errand's second prepare), `read_sections`, `own_thoughts_elsewhere`, `crossing.elsewhere`, `crossing.before`, `headings` + `doc_headings`, `crossing.recalled` | `timed` is entered at the worker's dispatch (1 site per brain); no other handler changes |
| D1 | `memory_tiers.deliver` (`memory_tiers.py:1055-1123`) | a `turn_kind` parameter; when it is in `PROGRAM_TEXT_KINDS`, the two `tiers.surfaced(...)` calls (lines 1107, 1122) are skipped: items still come up, nothing is written (`surfaced_in`, `last_use_at`, no `surfaced_again` moment) | 1 caller, `context.py:554`; the kind is already computed two lines above for the pilot (`turn_kind or event.get('episode_kind') or 'external'`) |
| D7 | `retrieval.search` (`retrieval.py:677-681`, where `selected` is built) | after selection, chunks of one message (same `source_event_ids`, kind `chat_chunk`, `segment_count > 1`) become one entry: bodies joined in `segment_index` order, the first half's `_id`, the manifest's `selected` keeps both ids (the recheck, `in_view` and `touch_salience` are per unit) | `context.py:590` reads the entry's fields as today (`segment_index`, `segment_count` are in `UNVECTORED`, which is everything but the vector) |

`PROGRAM_TEXT_KINDS`, from the 4-day reading (review §3.5): heartbeats (`presence`) 1.8 own items a turn, 3 distinct
rows, the top one in 28 of 29; `self_development` 12 own items, 2 distinct; `settlement` 0; `visit` short program
text (ADR-062 §1.1). `scheduled` turns are her plans' own texts (130 own items, 76 distinct) and `task_feedback` is
the action brain's report: both vary, both count. Proposed: `('presence', 'visit', 'self_development', 'settlement')`.

### 2. Stored state

| State | Create | Use | Discard | Restart |
|---|---|---|---|---|
| the two indexes | `ensure` at worker start, or by hand before the restart (see 5) | every turn (pool), every recall with a query (history) | never; the retired name is dropped by `ensure` | persisted |
| `tool.time.parts` | per recall | the readings | audit retention as today | – |
| `memory_shadow` rows of `current_self` lines (16) | – | – | `Pilot.sync` marks them `gone` at its next run (existing path) | – |

D1 and D7 add no field.

### 3. Tests

Change: `tests/test_tool_watch.py` (5 tests; the payload gains `parts`); the integration module that checks what
`ensure` makes (`integration/conftest.py:94`, the index names of `memory_units`). Go: none. New, earning their place:
- D1: a `presence` turn's surfacing writes no `surfaced_in` and no `last_use_at`, and a second such conversation makes
  no memorable moment (the loop that fed 114 moments and 76 offers; silent).
- D7: two halves of one message selected become one entry holding both texts, in order, and the manifest keeps both
  ids (a dropped half would be silent).
- B5: with a `self` document present, `own_items` indexes no `current_self` line (silent index pollution; one assert).
- B6: a recall's `tool.time` row carries one duration per part (the reading the ADR rests on).

### 4. What she reads

Nothing changes in words. D7: in about 6% of turns one memory entry instead of two for a long message, so a sixth
memory appears (about 300–800 characters more in those turns). D1: heartbeats stop repeating the same three rows (two
of six slots go back to memories). B5, B6, the indexes: nothing.

### 5. Failure modes

- The `memory_units` index (193,609 documents, 2.1 GB) is built when `ensure` runs at the worker's start: minutes of
  disk and CPU on the shared box, during which her start waits. Build it by hand while she is quiet before the
  restart (`createIndex`, then `ensure` finds it); a build that fails leaves no index and the pool falls back to the
  scan plus sort it does today, which the landing's verification checks with one `explain`.
- D7 is in-memory; D1 writes less, not more; B6 adds timing only (a part that hangs is already held by `tool_watch`'s
  limit).

### 6. Her answer

None needed. The program-text kinds are a program decision; she may say whether any plan-fired turn of hers is
templated (then it joins the list).

---

## L2. B3 (tiers bookkeeping incremental) and B8 (chunk watermark)

### 1. Code

B3, in `memory_tiers.py` and its callers:

| Change | Where | Kind | Call sites |
|---|---|---|---|
| no per-turn `sync` | `context._prepare` (`context.py:383`) | remove; `sync` runs once per process at the pilot's start (`memory_pilot.attach`, `memory_pilot.py:131`) and after an import (`persona_data.py:142,172`, the two import sites that pass the gate) | `sync` callers today: `context.py:383` (goes), `memory_tiers.written:490` (stays: a write makes rows), `role_tools.py:2571,2760` (stay) |
| `tick` not every turn | `context.py:384` | at most once per 10 minutes per process (a memo as `Pilot.SYNC_SECONDS`); its read index-bound: place in (随身, 手边), `fact` false | 1 caller |
| index-only reads | `memory_tiers.items` (`memory_tiers.py:207`) and the 8 methods that walk every row: `things:675`, `tick:341`, `deliver:1070`, `headings:1140`, `_carried:366-367`, `week:1014,1022`, `night_list` (goes in L4), `count_days`'s `_Past` (`carried.py:528`) | `store/catalog.py:537`: two indexes on `memory_tiers`, `(persona, row, store, place, doc)` and `(persona, row, doc, sid, place)`; `things` and `_carried` read (store, place, doc) projections covered by the first (about 100 bytes a row instead of 1.2 KB), `deliver` and `headings` read (doc, sid, place) covered by the second; counts stay counts of rows (no counters, nothing to drift) | `Tiers(` is constructed at 31 sites; only the 8 methods change |
| journal and documents not re-read | `Tiers.sync` (`memory_tiers.py:273-296`) | unchanged in body; it simply stops running per turn (today: every document's current revision, 40 of them, and the journal's 1,098 rows with bodies, 3.6 MB) | – |

B8:

| Change | Where | Kind | Call sites |
|---|---|---|---|
| a watermark per scene | new collection `chunk_marks` (owner `records.memories`; `_id` the scene id, `seq` number, `at` text), declared in `store/catalog.py` | `MemoryService.chunk` (`memory.py:206-235`) reads the mark, chunks lines after it (`message_records.said(..., after=)` as `crossing.top_up` reads lines after a seq), writes the mark once at the end of a completed round; it stops saving the message row (`memory.py:234`, the `expected=row['revision']` write that raised 314 conflicts) | `chunk` callers: `memory_indexer.py:55` (every round), `memory.py:170` (on demand in her turn) |
| the word index reads the mark | `crossing.top_up` (`crossing.py:357-366`: `memory_chunk_version == 2`) | "chunked" becomes `scene_seq <= mark`; one read of the 23 marks per top-up | 1 site |
| `memory_chunk_version` | `memory.py:215,234`, `crossing.py:358,361` | no longer written or read; the field stays on old rows, unread (no conversion) | 4 lines |

### 2. Stored state

| State | Create | Use | Discard | Restart |
|---|---|---|---|---|
| `chunk_marks` row per scene | first chunk round of the scene | every round and every top-up | with the scene's data; an erasure bumps the epoch and tombstones the old epoch's chunks, the mark stays valid (seqs only grow) | persisted; a lost mark re-chunks from 0 and skips existing ids (`memory_records.get(key)` at `memory.py:224`): idempotent |
| the two `memory_tiers` indexes | `ensure` | every turn | never | persisted |
| the per-process memos (`synced`, `ticked_at`) | start | – | process end | rebuilt |

### 3. Tests

Change: `integration` index names (`memory_tiers` gains two); `tests/test_record_owners.py` and
`tests/test_store_boundary.py` learn the new collection's owner. Go: none (`sync(`, `tick(` have no test today).
New, earning their place:
- B8: a message row whose revision changes between the read and the end of a chunk round is still chunked and the
  mark advances (the failure that happened 314 times); on the in-memory adapter with a concurrent `save`.
- B3: a section written by her, and one adopted from a seed or an import, has its tier row without any turn having
  run (rows missing would make items undeliverable, silently).

### 4. What she reads

Nothing.

### 5. Failure modes

- A slow or failing mark read delays only that scene's chunk round in the indexer thread, which already pauses and
  retries; the on-demand chunk in her turn (`memory.py:170`) is as today.
- A slow `memory_tiers` read delays only that turn's prepare, as today, with 10× fewer bytes.

### 6. Her answer

None.

---

## L3. D2-A as amended: one ceiling per pair, no refusal, her choice turn then the lapse

### 1. Code

| Change | Where | Kind | Call sites |
|---|---|---|---|
| the gate plans instead of refusing | `carried.gate` (`carried.py:325-353`): today raises `PERSONA_RENDER_OVER_BUDGET` with `over_words`; `render.budget_gate` (`render.py:182`) wraps it; `documents.apply(budget=...)` calls it at `documents.py:605` and `problems` dry-runs it at `:501` | `gate` returns the pairs the write takes over and by how much; `apply` lands the write; `Tiers.written` (`memory_tiers.py:481-545`) applies the overflow per pair | `budget_gate` callers: `role_tools.py:2587,2590-2595` (write_document), `memory_tiers.land:979`, `persona_data.py:142,172`, `documents.adopt_seed:617` |
| overflow by pair, her choice first | `memory_tiers._overflow:380-401` and `overflows:403-428` (today per store by count, `CAPS`, an `over` row per store or document) | per pair: an `over:<persona>:<pair>` row; the first turn after the write lists the choice line (`OVER_LINE` in tokens, with the sections carried in that pair, each with its days unused and about how much it would free); a turn later, still over, lapses in `_lapse_order` until the pair fits (one or several); `CAPS`, `ROOM_WORDS` and the per-store room words in `things` (`:680-688`) go | `_overflow` callers: `written:504,543`; `overflows` caller: `things:697` |
| the lapse order | `_lapse_order` (`memory_tiers.py:369-378`) | key becomes (felt, memorable_at, program score over 30 days ascending, document order); the score from `carried_counts` rows of the candidate sections (one `$in` query; a new index `(persona, section, day)` in `store/catalog.py:569`); a section carried in several pairs is ordered by the over pair's rows | 2 callers (`_overflow`, `overflows`) |
| the tie-break data | `carried.count_days` (`carried.py:532`) writes `program_score` nightly already (5,428 rows in 21 days) | no change | – |
| what the write result says | `role_tools.py:2596-2600` (the result after `apply`) and `carried.room_line` | the lapses made or pending, as `told(move)` lines (exists); the refusal words `OVER_WORDS`, `OVER_PAST`, `OVER_ALSO` go | 1 site |

Out of this landing: the group notes' own per-turn limit and `note_gate` (47 refusals in 22 days, ADR-096 D6 folding),
and the stay lapse (`tick`), which stays as it is.

### 2. Stored state

| State | Create | Use | Discard | Restart |
|---|---|---|---|---|
| `over` rows, new shape (per pair, tokens over, shown_in) | the write that takes a pair over | the next turn of a conversation that reads the pair; the turn after | deleted when the pair fits; the 0 rows of the old shape today | persisted |
| `carried_counts` index | `ensure` | each overflow | never | persisted |
| `move` rows with reason `overflow` | each lapse | told once per conversation (`told_in`) | never (the record) | persisted |
| `CAPS`-derived rows (`over:<persona>:<doc>`) | – | – | none exist (0 `over` rows on 11-05) | – |

### 3. Tests

Change: `tests/test_carried.py` (its one test asserts that the per-pair gate refuses the case `largest` let through,
and that a lifting rewrite is measured before it lands: both become "is planned and lapses in that pair");
`tests/test_tool_budget.py` if the write_document text changes (it need not). Go: none (`_overflow`, `OVER_LINE` and
the 10-18 choice turn have no test today). New, earning their place:
- a write that takes a pair over lands; the next turn lists the choice line; a turn later the stalest, lowest-scored
  section of that pair lapses and the pair fits; a section carried in two pairs frees both (a wrong lapse is silent
  and costly: 6 of 12 came back by hand).
- `carried_counts` missing for a section (a deployment younger than a day) falls back to document order without an
  error (silent otherwise).

### 4. What she reads

- The ceiling refusal (`OVER_WORDS`, a 59-character template with numbers, about 200 characters a time, 125 times
  in 22 days) is gone.
- The choice line when a pair is over: today's `OVER_LINE` (64-character template plus one entry per carried section
  of the store, 300–600 characters) becomes per pair and in tokens; her wording (6).
- `things_from_program.places` loses the per-store room words (about 30 of its 164 characters); `identity_room`
  (per pair, when it changes) stays.
- The moved line and the write result's `told(move)` lines as today.
- Her told text (`memory.tiers_told`, 328 characters, hers) needs no change for this landing: it names no caps.

### 5. Failure modes

- The gate's plan is five composes in the tool body (milliseconds, as today's measurement).
- The `carried_counts` read at overflow: one indexed query; slow, it delays that write only; failing, the order falls
  back to document order and says nothing.
- Nothing new waits in a turn's prepare.

### 6. Her answer

The wording of the token choice line and of the write result's lapse lines (hers, as the room line was under
ADR-096). Whether a lapse should ever take more than one section in one turn, or wait a turn per section (the
design says until the pair fits; her view).

---

## L4. D3-A and D4-A: the stored side left as it is; rows for her log; the write-time line

### 1. Code

Removals (59 occurrences in `memory_tiers.py`, 6 outside):

| What | Where | Outside `memory_tiers.py` |
|---|---|---|
| the gist step: `GIST_CHARS`, `GIST_LIST_ABOVE`, `GIST_NIGHTS`, `DATED`, `GIST_NO_BASIS`, `_gist_rewrite:431`, `gist_refusal:755`, `claim_chars:767`, `detail:1029`, the gist branch of `written:523-530`, `detail_of` | `memory_tiers.py` | `role_tools.py:2540-2543` (the refusal), `role_tools.py:3688-3691` (`detail` in `read_sections`) |
| cooling as a state: the `elif not row.get('fact')` branch of `tick:346-352`, `JOURNAL_COOL_DAYS`, reason `cooled` | `memory_tiers.py` | `context.py:384-385` passes the forgetting numbers to `tick` (drop the arguments) |
| the age bound kept as a filter | `deliver:1083` (`pool`) | a 手边 memory item (not a fact) is in the pool only while its last use or memorable moment is within the bound (30 days for journal rows, the forgetting half-life's step-back for the rest), computed from the row's fields; no row written | – |
| supersession: the `superseded`/`merged` branch of `move:321-322`, `superseded_at`, the correction branches of `placement_after:466-467` and `written:505-508`, reasons `superseded`, `merged`, `gist_skipped` | `memory_tiers.py` | `documents.py`: `OPS:31`, `WRITE_STAGE_OPS:32`, `problems:476,491-495`, `apply:345,569-594` (the `correction` op and `corrects`); `role_tools.py` write_document text (3 mentions); `crossing.before:553` (the `corrected` set from `corrects`: dead once no section can carry one; the line-level correction in `crossing._correction:178` stays); `context_budget.py:77` (off path) |
| the night list: `night_list:813-916`, `NIGHT_ITEMS`, `NIGHT_WHAT`, `NIGHT_HOW`, `NIGHT_WHY`, `NIGHT_NOTE`, `DUPLICATE_SCORE`, `REPEATED_PLACES`, `REPEATED_STAYS`, the `offer` rows of kinds gist, merge, repeated (`week` offers stay) | `memory_tiers.py` | `context.py:1357-1359`, `block_guide.py:62` |
| what stays | `signing`, `has_basis`, `BASIS`, `FACT_AUTHORS`, `JUDGMENT_NOT_FACT`, `confirmed`, `nature`/`from`, `let_go` 手边→收着, `week`, `LOOK_BACK_DAYS` | | |

Additions:

| Change | Where | Kind | Call sites |
|---|---|---|---|
| the write-time line | `memory_pilot.Pilot.like(text, store, scene_id, timeout)`: embeds the new body in the pilot's thread (one request on the memory route, `Retrieval.embed`), compares it with `self.items` of the same store (`_score`, in memory, about 1 ms), returns the best at or above `DUPLICATE_ABOVE` (0.93) or None after `timeout` | `role_tools.py:2596-2600`, after `apply` for `append_section`: the result gains `like: {ref, heading}`; the match sets `confirmed` on both rows when the other is from another conversation or has `from` in `OTHERS_SAID` (today's `night_list:873-880` logic, moved) | 1 new function, 1 call site, 1 result field; `_pairs` (`memory_pilot.py:293`) keeps writing pair rows for the readings |
| her log as rows | `documents.is_journal` (`documents.py:253-255`: `slug in JOURNALS or has entries`) | also `content.get('kind') == 'journal'`, so a document whose kind is set to `journal` by an owner-side revision (author `program`) is imported by `_journal_import` (`documents.py:280-305`) at its next read, as `work_log` was | a one-time owner command (new, `tools/`), or her re-creation (125 appends: too heavy) |

### 2. Stored state

| State | Create | Use | Discard | Restart |
|---|---|---|---|---|
| `gist`, `detail_of`, `superseded_at` on tier rows (6, 6, 0 rows) | – | nothing reads them | unset at install (program fields, not her memory) | – |
| `offer` rows of kinds gist, merge, repeated (128) | – | nothing | deleted at install (telemetry) | – |
| `corrects` on sections | none exist (0 corrections ever landed) | – | – | – |
| `confirmed` | the write-time line | `signing` (her judgment may become a fact) | never | persisted |
| her log's rows: `journal_entries` (125) and `journal_revisions` | the import at first read after the kind flip | as `work_log` | the old document's head is dropped by the import, its revisions stay as history | persisted; the import is idempotent (`if not entry(...)`) |
| `memory_tiers` rows for the 125 new journal items (手边) | the next `sync` (start) or write | `deliver`, `recall` | never | persisted |

### 3. Tests

Change: `tests/test_tool_budget.py` (write_document loses `correction`: about −45 characters of 1,942);
`tests/test_layered_refusal.py` and `tests/test_adr097_keys.py` where they name `correction` (the 已被更正 mark on a
note's past version goes with the op; the line-level mark stays); `tests/test_memory_tiers_told.py` if the core
default told text changes (it mentions only the three places and the absence rule). Go: any test of the gist step
or the night list (none found by name). New, earning their place:
- the write-time line never refuses and is absent when the embedding route is down or slow (a hang here would hold
  her write: costly), with the 1.5 s bound.
- the kind flip imports every section with its first and last times and drops the head (data loss would be silent
  and costly; the phase-0 import has no test today).

### 4. What she reads

- `night_list_from_program` gone: it fired on 22 of 22 nights, up to 5 items with bodies of up to 600 characters
  (about 2,500 characters in a settlement turn) plus `NIGHT_NOTE` (44) in the block guide.
- `write_document`'s declared text: −45 characters (the `correction` sentence and enum value); `GIST_NO_BASIS` (59)
  never again; the `detail` field on recalled sections (6 items) gone.
- New: `like:` on about 3% of appends (journal 32 pairs of 1,098; about one a day), one line of about 60
  characters in the write result.
- `moved` lines never say 很久没用, 被更正替换, 合并了, 两晚没写意思 (none ever did).
- Her told text (328 characters, hers): the sentences 「淡下去不是删掉，原话一直在收着。事实只会被更正替换，不会因为没人用而退；记忆会淡」
  describe mechanisms that go; hers to rewrite before the landing.

### 5. Failure modes

- The write-time embed: one request on the memory route in the pilot's thread, the tool body waits at most 1.5 s
  (the route's client has a 180 s timeout, `evidence.py:68`, so the wait must be the caller's); no line on timeout or
  failure; a pilot thread busy with a sync batch (16 items) also runs out the wait: no line, nothing said.
- The import of her log: 125 rows written at the first read after the flip, inside a turn's prepare (as `work_log`'s
  was); a failure midway resumes at the next read.
- Nothing else does I/O that did not before; the night list's reads at settlement go.

### 6. Her answer

Three: (a) her told text, rewritten by her; (b) the kind flip of her log document (her yes to the owner's one-time
command, or her own re-creation); (c) whether she wants to keep writing gists by hand as a habit (no program step
either way).

---

## L5. D5a as amended: a document per person, sections as items, a 4,000-character budget

### 1. Code

| Change | Where | Kind | Call sites |
|---|---|---|---|
| the store | `memory_tiers.store_of:183` (`person:` slugs → store `person`), `FACTS` (`:54`), `STORE_WORDS` (`:49`), `FIRST_STAY_DAYS` (her view: as persona, 14→28→56) | new store, no count cap | – |
| the document | `documents.py`: `NEW_KINDS` gains `person`, `ALWAYS_KINDS` (a new section carried), default visibility public (the record is read in every place today; owner_private for home-only notes) | kind | – |
| the writer | `memory.MemoryService.commit_understanding:40-100` and `_commit_person:116-142` (today `head_records.mutate` on `relationship:<canonical>|person` with sources) | the person layer becomes `DocumentStore.apply` on `doc:<persona>:person:<canonical>` with the same `_understanding_sources` ids passed as `sources` (`documents._commit` stores `source_ids`: `documents.py:420`), so erasure can taint; the here layer unchanged | `role_tools.tool_understand_person:2764-2838` (1 site) |
| the tool | `role_tools.py:346-358` (`understand_person`, 830 characters declared) | for `layer: person`: `do` (replace_section, append_section, set_tags, let_go), `sid`, `heading`, `body`, `short`; the read-first rule (`:2792-2805`) pins the document's base revision instead of the head's | +about 220 characters: `CHARACTER_TIERED` from 21,139 to about 21,360 |
| the readers | `understanding.layers:588`, `person_view:563`, `entry:614`, `read:666`, `listing:696`, `_everyone:713`, `pins:603` | `layers` reads the document when it exists, else the old head (the transition, one line; removed once her records are moved); `person_view` joins the carried sections (heading and body) under the fixed first line; `entry` adds, beside the short (the fixed section `short`), the carried sections with `from` 别人说的 or her promise word and a line anchor, up to 300 characters; `read` lists every section with its place word; `listing` reads `DocumentStore.slugs('person:')` | `context.py:413-414` (person head), `:688` (person view), `:1111` (manifest `person_revision`, `person_entity_key`: the document's revision id and key), `:1127` (group entries); `memory.py:116-122` (the write rule's key); `native_cognition.py:57` (the write rule); `native_api.py:281` (the memory tab); `role_tools._recall_person:1912-1935` |
| scoping | `memory_pilot.own_items:47-93` and `memory_tiers.deliver:1082` | a person's sections are indexed under a pseudo-scope `person:<canonical>` and are readable only in a turn whose person is that one (`event['person_id']`, or present in a group), so a fact about a person never comes up with someone else | 2 sites |
| the budget | a `person_gate` beside `note_gate` (`context_budget.py`) measuring the carried sections' characters against 4,000; over → L3's overflow (choice turn, then the lapse order), never a refusal | `documents.apply(budget=)` passes it for `person:` slugs | 1 new function, 1 site in the writer |
| the tie-break | `memory_tiers._lapse_order:369` | sections with `from` 别人说的 or her promise word and a `line` anchor order last, after `felt` | – |
| her promise word | `memory_tiers.FROM_NATURE:58` (→ FACT) and `SOURCES`; a neutral core default in `persona_model.CORE_DEFAULTS`, worded by her package as `memory.tiers_told` is | the word is hers (6) | `role_tools.py:2522` validates `from` against `SOURCES` |
| erasure | `privacy._erase_person_layer` (`privacy.py:34-52`) | also walks heads `doc:<persona>:person:` and their revisions' `source_ids`; `point_to`, `drop_head`, `tombstone_revision` work on the same collections | 1 function |
| the identity budget | `carried.IDENTITY` stays (persona, voice, self, core): the person document is outside the ceiling, bounded by its own 4,000 | – | – |

### 2. Stored state

| State | Create | Use | Discard | Restart |
|---|---|---|---|---|
| `doc:<persona>:person:<canonical>` heads and revisions (with `source_ids`) | her first write for that person (her one-time move of each record she chooses; the old head stays readable until then) | every turn with that person (one head and one revision read, as today's `relationship:…|person` costs) | erasure tombstones revisions citing an erased conversation and points the head back, as the old path does | persisted |
| tier rows, store `person` | the write (`written`) | `deliver` in that person's turns, `recall person`, the lapse order | never | persisted |
| `relationship:<canonical>|person` heads (7) | – | read while no document exists for that person | left as history once the document exists (no conversion) | – |
| `memory_shadow` items of store `person` | the pilot's sync | `deliver` (scoped), the write-time line (L4) | `gone` when a section is removed | persisted |
| the here layer (`relationship:…|scene:…`, 28) | unchanged | unchanged | unchanged | – |

### 3. Tests

Change: `tests/test_whose.py` (6 tests build group turns with `people_from_program`; the entry gains `anchored`
when present); `tests/test_tool_budget.py` (+about 220). Go: none (ADR-082's write rule has no behaviour test
today; `understand_person` appears only in the budget test). New, earning their place:
- a person's section never comes up in a turn without that person, in a group or one-to-one (a fence; silent and
  costly).
- an erasure tombstones a person document's revisions that cite the erased conversation and the head falls back
  (privacy; silent and costly; the old path has this behaviour untested).
- the group entry carries anchored sections within 300 characters and never the rest (the hard case's guarantee).

### 4. What she reads

- One-to-one: `relationship.person.text` (2,870 characters at the median at home, the owner's record) becomes the
  carried sections' text: the same characters until she splits or trims; the 4,000 budget is today's cap.
- Groups: the woken person's entry (600 characters at the median) gains up to 300 characters of anchored sections
  when there are any (0 today: the records are bodies).
- `understand_person`: +about 220 characters declared; `recall person` lists sections with place words (about +20
  a section); `doc_refs_from_program` (381 characters at home) gains the person document's refs (about 25 a section).
- `things_from_program.places` gains a 人 store line (about 20 characters).

### 5. Failure modes

- Per turn: one document read replaces one head read (same count, same bytes until she grows the record).
- The budget gate per write: a compose of the carried sections (milliseconds); over the budget, L3's path.
- Erasure walks person documents as it walks person heads (rare, offline).
- Her moving a record: one `append_section` per section she makes; the old head stays readable throughout, so a
  half-moved record shows the document where it exists and the old body otherwise (the transition rule).

### 6. Her answer

Four: (a) the word for her own promises (`from`), hers to name; (b) whether the here layer also becomes items
(recommended: not now; 28 records, median 375 characters); (c) the default visibility of a person's sections
(public, as the record is read everywhere today, with owner_private for home-only notes), and whether a person's
stay is the persona's (14→28→56 days); (d) which of her 7 records she moves and when (hers; the owner's record
first, as D5a says). The 4,000 per person and the 300 in groups are the owner's discipline numbers; her view is
asked, as ADR-096 did for the ceiling.

---

## Across the landings: what cannot be designed without her

1. L5 (a): the promise word. Nothing else in L5 blocks on it (the tie-break can land for anchored 别人说的 first).
2. L4 (a): her told text. The landing can go with the core's neutral default in place until her text is ready, but
   the ADR should not land while her package text contradicts the system.
3. L3: the choice line's wording. The landing can go with the core's neutral line; hers replaces it as ADR-096's did.
4. L4 (b): her log's kind flip. Without it D4-A's rows part waits; the write-time line does not.

Everything else is the program's or the owner's to decide, with her view asked where this page says so.
