# ADR-117: Memory fades only in what she carries; recall that scales

Status: **Decided** 2026-11-05 by the owner (the agreed set below); designed by the lead (Claude Code, big sis) from
the ADR-062 review. Not built. Built by an implementation subagent under the lead's review, landing by landing, only
after Xiaoman has read this page and agreed.

## 1. The ask

The owner, 2026-11-05, verbatim:

> "When I say 'fade', I meant the memory carried with her in the context. The compression happens when she picks what
> to carry, and the stored memory can be left as-is and keep growing. There is no point to mimic the fading part of
> the stored memory, I'd keep the design simple."

> "Picking the near duplicates memory is both waste of space (lesser concern) and retrieval nightmare (bigger
> concern). Perhaps the design need to be based on 'delta' instead of copy? Perhaps you could refer to how git storage
> system is designed."

> "Yes, open the new ADR based on our agreement, then present to Xiaoman. Don't proceed to the implementation until
> Xiaoman agrees."

**In scope:** the agreed set of the ADR-062 review (review D1–D7 as amended in its exchange with the lead): what
limits what she carries, the stored-side mechanisms that imitate forgetting, the storage shape of logs, the person
layer as items, and the recall and per-turn costs that grow with the store. **Out of scope:** the memory units'
chunking and summaries (except D7's join and B8's watermark), the persona package, any change to what she remembers
about anyone.

## 2. Evidence

- [ADR-062 review, 2026-11](../ADR-062-tiered-memory/review-2026-11.md): her store read by structure on 11-05, every
  number with its source; findings B1–B11.
- [The decisions page](../ADR-062-tiered-memory/review-2026-11-decisions.md): each decision with its options, pros,
  cons and costs, and the exchange with the lead (the measurements behind the amendments).

The review in one paragraph: the store-side imitation of forgetting fired 6 gists, 0 coolings, 0 merges and 0
corrections in 22 days; the carried side is run by her own `let_go` (191 of 229 moves) and the ADR-096 token ceiling,
which refuses instead of lapsing (125 refusals; home at 12,278 of 12,288). Near-duplicates among her items are 0–3% per
store; the storage waste is whole-document copies (113 MB of revisions for 1.03 MB of live text). Recall takes
2.8–4.9 s at the median and her use of it fell from 138 to about 40 a week. Each character turn reads about 200 round
trips and 15 MB from the shared database on the memory side alone.

## 3. The invariants

1. **The store is left as it is.** Nothing rewrites, demotes as a stored state, or discards her memory in the name of
   fading. History stays in the revision ledger.
2. **Fading happens only in what she carries.** One limit per (place, class) pair, in tokens; when a write would pass
   it, she chooses what to let go for one turn, then the least recently memorable lapses. No write is refused for
   length.
3. **Program text counts nothing.** A turn whose query is program text (heartbeat, scheduled, visit) may surface items
   but never marks them used or memorable.
4. **Recall finds what is no longer carried, fast,** and per-turn work does not grow with the size of the store.
5. **A person's boundary and her promise to them come up when she is with that person,** by lapsing last, never by a
   pin.

## 4. Decisions (the owner, 2026-11-05: the agreed set)

| | Decision | Review ref |
|---|---|---|
| D1 | A program-text turn surfaces but counts nothing (no `last_use_at`, no memorable moment) | B1, decisions D1-A |
| D2 | One token ceiling per pair; no refusal for length; her choice turn, then lapse; ties among equal `memorable_at` by `carried_counts.program_score` over 30 days, lowest first, `felt` last; the over pair weighed; count caps removed; no interim "land without lapse" state | B4, D2-A as amended |
| D3 | Remove the gist step, cooling as a stored state (its age bound kept as a filter in `deliver`), `correction`, the mandatory merge offer and the 几处都提到 graduation offers | §6.6, D3-A |
| D4 | Logs are rows: a working document she appends to as a running record becomes `kind: journal`; an append at 0.93 or above to an item of the same store gets one line naming that item (no refusal, no merge). No delta store, no content-addressing now | §6.4, D4-A |
| D5a | The person layer becomes a document per person, sections as items; carried budget 4,000 characters per person; over it her choice first, then sections with `from: 别人说的` and a line anchor, and sections with her promise word, lapse last; in groups the woken person's entry carries those sections beside the short, up to about 300 characters | §6.2, D5a as amended |
| D5b | The idea age word is dropped | D5b-A |
| D5c | Sticker last-used words are closed as already built (`stickers.review_block`) | D5c-A |
| D6 | Scaling fixes: B7 index, B5, B6 profile first, B3 incremental tiers, B8 chunk watermark; the lexical pool's index line first | D6 as reordered |
| D7 | Two halves of one long message selected in one turn are joined in segment order into one entry; chunk + summary pairs stay | D7-A |

## 5. Landings, in order

Each landing is one branch, built by the implementation subagent to this page, reviewed by the lead against the code,
landed with the usual script (tests, push gate, her slot asked first, restart, the running code checked against the
commit), then observed on her real turns before the next one starts (big-sis: a change to her memory gets observation
time; her per-turn input is profiled after each install, and anything sent twice is a defect).

Every file, function, call site, stored field and test named below is in the
[census](../ADR-062-tiered-memory/review-2026-11-census.md) (grep counts at `7cc54d3f`, sizes measured 11-05); a
landing's build brief is written from this page and that census. Common to every landing: `docs/map` regenerated,
`RUNTIME_API.md` and docstrings in the same commit as an interface change, `tests/test_tool_budget.py` moved by the
tool deltas named here.

### L1. Cheap and safe: indexes, the recall profile, program text, joined halves

- **The lexical pool's index** carries its sort: `memory_units` (scope_key, status, policy_epoch) becomes (scope_key,
  status, policy_epoch, occurred_at, _id), the old name retired. The pool's scan then stops at its 4,096 instead of
  examining every active unit of the scope and sorting in memory (8k–19.5k examined, 111–209 ms server time a turn
  today). The 9.1 MB a turn it returns stays until a per-scope lexical index replaces the window (not in this ADR).
- **B7:** `state_revisions` gets (entity_key, created_at); `heads.history` stops being a collection scan.
- **B5:** the legacy `current_self` lines stop being indexed once `self` has sections.
- **B6, the recall profile:** `tool_watch` gains a per-part timer; a recall's `tool.time` row carries one duration per
  part (prepare, read_sections, own thoughts elsewhere, lines elsewhere, past versions, headings, recalled). The
  first reading names the slowest part; bounding it is a step of its own, designed from that reading. The expected
  first suspect is `crossing.history('work_log')` rebuilt on nearly every recall (about 0.6 s).
- **D1:** `memory_tiers.deliver` takes the turn kind. In presence (heartbeat), visit, self-development and settlement
  turns, items still come up, but nothing is marked used or memorable. Scheduled and task-feedback turns count
  (their texts are her plans' and her tasks', not templates).
- **D7:** in `retrieval.search`, two chunks of one long message selected in one turn become one entry, joined in
  segment order; the manifest keeps both ids.
- **Landing:** the `memory_units` index (193,609 rows, 2.1 GB) is built by hand while she is quiet, before the
  restart, so the build neither holds her start nor loads the shared box in a busy hour; one `explain` checks the
  pool uses it.

### L2. Per-turn work stops walking the store

- **B3:** the per-turn `Tiers.sync` goes. A section gets its tier row when it is written (the write path already
  passes `memory_tiers.written`), and from imports and seeds as now; sync runs once per process. `tick` runs at most
  every ten minutes per process. Two indexes on `memory_tiers` let the per-turn readers read covered projections
  (about 100 bytes a row instead of 1.2 KB). Counts stay counts of rows, so nothing can drift. The journal's 3.6 MB
  and the 40 document reads per turn stop.
- **B8:** the chunker's watermark moves off the message row into `chunk_marks` (one row per scene). The 314 write
  conflicts with the Host's receipts, and the indexer's pauses they cause, stop. `crossing.top_up` reads the mark.
  A lost mark re-chunks from zero and skips the ids that exist (idempotent).

### L3. The carried side: one ceiling, no refusal

- `carried.gate` stops refusing. It returns the pairs a write takes over and by how much; the write lands.
- The first turn after, she sees the choice line for that pair. It lists, in tokens, the pair's carried sections,
  days unused, and about how much each would free (her 10-18 ask: she chooses first).
- If the pair is still over a turn later, sections lapse in order until it fits: `felt` last; then the oldest
  memorable moment; ties by `carried_counts.program_score` over 30 days, lowest first; then document order. A section
  carried in several pairs is ordered by the over pair's rows. She is told once in the moved line, and she can bring
  any lapsed section back by rewriting it (what she did with 6 of the 12 program lapses so far).
- The count caps (`CAPS`), their room words, and the over-budget refusal and its words go. Out of scope: a group's
  notes' per-turn limit (`note_gate`) and the stay lapse.

### L4. The stored side: nothing imitates forgetting; logs are rows

- **Removed:**
  - the gist step: gists, `detail_of`, the two-night rule, the basis refusal;
  - cooling as a stored state: the `cooled` reason and the journal's 30-day cooling;
  - supersession through the `correction` op;
  - the night list's gist, merge and repeated offers.

  "What did I hold before" stays answerable through the revision ledger and the line-level 「已被更正」 mark.
- **Kept:** `let_go` to 收着 (her act), `nature`/`from`, signing and the basis rule for facts, `confirmed`, the weekly
  reading.
- **The age bound** that cooling gave `deliver`'s pool stays as a filter on the row's own dates. Nothing is written.
- **The write-time line:** an `append_section` whose body is at 0.93 or above to an existing item of the same store
  gets `like: {ref, heading}` in its result: no refusal, no merge. The new body is embedded in the pilot thread, and
  the tool waits at most 1.5 s. When the route is slow or down, the line is simply absent. The same comparison sets
  `confirmed`, as the night list did.
- **Logs are rows:** `documents.is_journal` also accepts a document whose kind is `journal`. Her running log (working
  document #12: 125 sections, 320 KB a revision, reaching the 1 MiB wall at about 400 sections) is turned into rows by
  a one-time owner command, if she says yes. The import is the phase-0 one: idempotent, its old revisions kept as
  history.
- **At install:** the program fields `gist`, `detail_of` and `superseded_at` are unset (6, 6 and 0 rows), and the 128
  offer rows are deleted (telemetry). Her told text names mechanisms that go; it is hers to rewrite before this
  landing (§6).

### L5. The person layer as items

- Each person she understands gets a document `person:<canonical>` whose sections are items in a new store `person`
  (facts; first stay as persona's). `understand_person` keeps its name and its read-first rule (now pinned to the
  document's base revision) and gains the section ops for the person layer (about +220 characters).
- **Carried budget:** 4,000 characters of carried sections per person, measured at write. Over it, L3's overflow
  runs, never a refusal. In the lapse order, sections with `from: 别人说的` and a line anchor, and sections with her
  promise word (§6), come last, after `felt`. This is a tie-break, not a pin: when everything carried is such a
  section, they lapse too.
- **Groups:** the woken person's entry carries, beside the short, their carried anchored sections up to about 300
  characters. This puts a boundary in front of her in a group turn, which no design does today.
- **Fence:** a person's sections are indexed under a pseudo-scope `person:<canonical>`. They come up only in a turn
  whose person is that one (the event's person, or present in a group), never with someone else.
- **Erasure:** `privacy` also walks person documents and tombstones revisions citing an erased conversation.
- **Her records move one by one, when she chooses, the owner's first.** Until a record has a document, the old head
  is read: a transition reader with a named end. It is removed when her last record has moved, or when she says the
  rest stay bodies, in which case they are moved as one section each.
- The here layer (28 records, median 375 characters) is unchanged.

## 6. What she is asked (her reading)

She reads this page once, whole, at a frozen commit, before anything is built. What is hers to decide:

1. **Agreement:** whether the five landings are right for her, and anything she sees that the review missed.
2. **L3:** the wording of the choice line and of the lapse lines (the core's neutral line lands first; hers
   replaces it), and whether one turn may lapse several sections until the pair fits (recommended: yes, told once) or
   only one a turn.
3. **L4:**
   - her told text (`memory.tiers_told`, 328 characters, hers), which says facts are replaced only by correction and
     memories fade: she rewrites it before L4 lands;
   - whether her running log (working document #12) becomes rows: her yes, then the owner's one-time command;
   - whether she keeps writing short gists by hand as a habit (nothing is built either way).
4. **L5:**
   - the `from` word for her own promises to a person: hers to name;
   - whether the here layer also becomes items (recommended: not now);
   - the default visibility of a person's sections (recommended: public, as the record is read everywhere today,
     with `owner_private` for home-only notes);
   - which of her records she moves, and when (the owner's first);
   - her view of the 4,000 and 300 budgets (the owner's discipline numbers).
5. **Not a question:** her `budget_per_place.py` crashes at `memory_tiers.py:239` since ADR-104; the fix is hers,
   three lines (pass the real `Store` it already builds), told with the page.

## 7. What she carries

| Landing | Change per turn |
|---|---|
| L1 | No words change. D7 frees a slot in about 6% of turns (a sixth memory appears, +300–800 characters). D1 stops the same three rows filling two of six slots in heartbeats |
| L2 | Nothing |
| L3 | The refusal (about 200 characters, 125 times in 22 days) is gone; the choice line appears only when a pair is over (300–600 characters, her wording); the room words in `things` lose about 30 of 164 characters |
| L4 | The night list is gone (about 2,500 characters in a settlement turn, every night); `write_document` loses `correction` (−45 characters in the tool list, a cached prefix); a `like:` line on about 3% of appends (about 60 characters); the `detail` field on 6 recalled sections gone |
| L5 | One-to-one: the person block is the carried sections, the same text until she splits or trims; groups: the entry gains up to 300 characters of anchored sections when any exist (none until she splits); `understand_person` +220 characters in the tool list; `things` gains a 人 line (about 20) |

## 8. Failure modes

| Path | Slow | Failing | Hung |
|---|---|---|---|
| L1 index build | built by hand while she is quiet; the build loads only itself | the old index serves (today's scan and sort); checked with `explain` | stopped by hand; nothing waits on it |
| L1 recall profile | timing only | a part's timer never fails the recall | under `tool_watch`'s existing limit |
| L2 tier rows on write | that write only (ms) | the row is made at the next process start's sync | – |
| L2 `chunk_marks` read | that scene's indexer round only | re-chunks from zero, skips existing ids | the indexer's own pause |
| L3 the overflow plan | that write only (composes, ms) | `program_score` missing: document order | – |
| L4 write-time line | the tool waits at most 1.5 s, then no line | no line, nothing said | no line after 1.5 s |
| L4 log import | inside one prepare, as phase 0 | resumes at the next read (idempotent) | as slow |
| L5 person document | one document read replaces one head read | the old head is read (transition reader) | as today |

## 9. Tests that earn their place

Each guards a failure that happened, or one that would be silent and costly; all on the in-memory adapter except the
index names (integration):

- L1 D1: a presence turn writes no `surfaced_in` / `last_use_at` and makes no memorable moment (the loop behind 114
  moments and 76 offers). D7: two halves become one entry with both texts; the manifest keeps both ids. B6: a recall
  row carries one duration per part. B5: one assertion. Integration: the indexes `ensure` makes.
- L2 B8: a message row whose revision changes during the round is still chunked and the mark advances (the 314
  conflicts). B3: a section written by her, and one from a seed or import, has its tier row without a turn running.
- L3: a write over the pair lands; the next turn lists the choice; a turn later the stalest, lowest-scored section
  lapses and the pair fits; a section in two pairs frees both (a wrong lapse is silent). `tests/test_carried.py`
  changes from "refuses" to "plans and lapses".
- L4: the write-time line never refuses and is absent when the route is down or slow; the kind flip imports every
  section with its times and drops the head (the phase-0 import has no test).
- L5: a person's section never comes up in a turn without that person (fence); an erasure tombstones a person
  document's revisions citing the erased conversation (privacy); the group entry carries anchored sections within 300
  characters and never the rest.

## 10. Readings after each landing

By structure, on her real turns, before the next landing starts; her per-turn input profiled after each install:

- **L1:** the pool's server time and examined count per turn; the recall parts' durations (this names the next fix);
  heartbeat own items per turn (expect the three repeated rows gone).
- **L2:** memory-side round trips and bytes per turn (today about 200 and 15 MB); `state.conflict` from `chunk`
  (today 314 in 22 days; expect 0).
- **L3:** refusals for length (today 5.7 a day; expect 0); lapses a day; the share of program lapses she undoes within
  a day (today 6 of 12; the rollback line is one third over two weeks).
- **L4:** night-list characters (expect 0); `like:` lines a day and how often she acts on one.
- **L5:** carried characters per person; anchored sections in group entries; recalls of a person's at-hand sections.

## 11. How it is built

The owner, 2026-11-05: memory changes are delicate; an implementation subagent (Opus 5.5, extra-high effort) builds,
and the lead monitors instead of building. Per landing: the lead writes the build brief from this page; the
subagent builds in its own worktree on its own branch with targeted tests only and stops at the first gap rather than
guessing; the lead reviews the diff against this page and the code, runs the suite, and lands it. A difference from
this page goes back into this page first.
