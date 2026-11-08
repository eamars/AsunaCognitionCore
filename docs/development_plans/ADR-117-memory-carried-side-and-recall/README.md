# ADR-117: Memory fades only in what she carries; recall that scales

Status: **Decided** 2026-11-05 by the owner (the agreed set below); designed by the lead (Claude Code, big sis) from
the ADR-062 review, then read against the code by a fresh reviewer and corrected (§12). Not built. Built by an
implementation subagent under the lead's review, landing by landing, only after Xiaoman has read this page and
agreed.

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

**In scope:** the agreed set of the ADR-062 review (its decisions D1–D7 as amended in the exchange with the lead):
what limits what she carries, the stored-side mechanisms that imitate forgetting, the storage shape of logs, and the
recall and per-turn costs that grow with the store. **Moved out (§11):** the person layer as items (review D5a), which
gets its own ADR. **Out of scope:** the memory units' chunking and summaries (except D7's join and B8's watermark),
the persona package, any change to what she remembers about anyone.

## 2. Evidence

- [ADR-062 review, 2026-11](../ADR-062-tiered-memory/review-2026-11.md): her store read by structure on 11-05, every
  number with its source; findings B1–B11.
- [The decisions page](../ADR-062-tiered-memory/review-2026-11-decisions.md): each decision with its options, pros,
  cons and costs, and the exchange with the lead (the measurements behind the amendments).
- [The census](../ADR-062-tiered-memory/review-2026-11-census.md): files, call sites, stored state, tests and what
  she reads, per landing, at `7cc54d3f`. Its corrections are in §12; where they differ, this page wins.

The review in one paragraph: the store-side imitation of forgetting fired 6 gists, 0 coolings, 0 merges and 0
corrections in 22 days; the carried side is run by her own `let_go` (191 of 229 moves) and the ADR-096 token ceiling,
which refuses instead of lapsing (125 refusals; home at 12,278 of 12,288). Near-duplicates among her items are 0–3% per
store; the storage waste is whole-document copies (113 MB of revisions for 1.03 MB of live text). Recall takes
2.8–4.9 s at the median and her use of it fell from 138 to about 40 a week. Each character turn reads about 200 round
trips and 15 MB from the shared database on the memory side alone.

## 3. The invariants

1. **The store is left as it is.** Nothing rewrites, demotes as a stored state, or discards her memory in the name of
   fading. History stays in the revision ledger, and what she can read of it today she can still read.
2. **Fading happens only in what she carries.** For her identity layer (self, core, persona, voice): one limit per
   (place, class) pair, in tokens; a write of hers that passes it lands, she chooses what to let go in her next home
   turn, then the least recently memorable lapses. Group notes keep their own per-turn limit and ledgers their cap.
3. **Program text counts nothing.** A turn whose query is program text may surface items but never marks them used,
   memorable or rehearsed, and never feeds a score.
4. **Recall finds what is no longer carried, fast,** and per-turn work does not grow with the size of the store.

## 4. Decisions (the owner, 2026-11-05: the agreed set)

| | Decision | Review ref |
|---|---|---|
| D1 | A program-text turn surfaces but counts nothing: no use, no memorable moment, no rehearsal, no program score, no came-back count; her own recall inside such a turn still counts | B1, D1-A |
| D2 | One token ceiling per pair for the identity layer; no refusal for her writes; her choice in her next home turn, then lapse; ties by `carried_counts.program_score` over 30 days, lowest first, `felt` last; the over pair weighed; the identity stores' count caps removed; no interim "land without lapse" state | B4, D2-A as amended |
| D3 | Remove the gist step, cooling as a stored state (an age bound stays as a filter outside recall), `correction`, the mandatory merge offer and the 几处都提到 graduation offers | §6.6, D3-A |
| D4 | Logs are rows: her running log becomes journal rows by a one-time owner command, with her yes; an append at 0.93 or above to an item of the same document gets one line naming it (no refusal, no merge). No delta store, no content-addressing now | §6.4, D4-A |
| D5 | The person layer as items: its own ADR (§11). The idea age word is dropped. Sticker last-used words are closed as already built (`stickers.review_block`) | D5a–c |
| D6 | Scaling fixes: B7 index, B5, B6 profile first, B3 per-turn walks, B8 chunk watermark; the lexical pool's index line first | D6 as reordered |
| D7 | Two halves of one long message count as one selection and are joined in segment order; chunk + summary pairs stay | D7-A |

## 5. Landings, in order

Each landing is one branch, built by the implementation subagent to this page, reviewed by the lead against the code,
landed with the usual script (tests, push gate, her slot asked first, restart, the running code checked against the
commit), then observed on her real turns before the next one starts (big-sis: a change to her memory gets observation
time; her per-turn input is profiled after each install, and anything sent twice is a defect).

The census names the files, call sites, stored fields and tests (with §12's corrections). Common to every landing:
`docs/map` regenerated, `RUNTIME_API.md` and docstrings in the same commit as an interface change,
`tests/test_tool_budget.py` and `tests/test_tool_schema.py` moved by the tool changes named here. **Version skew:**
nothing here crosses the plugin/worker line. Tool schemas come from the Python worker, and the plugin only labels
tools (`packages/cognition-core/src/client.js`), so either side may be older.

### L1. Cheap and safe: indexes, the recall profile, program text, joined halves, cooling stops

- **The lexical pool's index** carries its sort: `memory_units` (scope_key, status, policy_epoch) becomes (scope_key,
  status, policy_epoch, occurred_at, _id), the old name retired. The pool's scan then stops at its 4,096 instead of
  examining every active unit of the scope and sorting in memory (8k–19.5k examined, 111–209 ms server time a turn
  today). The 9.1 MB a turn it returns stays until a per-scope lexical index replaces the window (not in this ADR).
- **B7:** `state_revisions` gets (entity_key, created_at); `heads.history` stops being a collection scan.
- **B5:** the legacy `current_self` lines stop being indexed once `self` has sections.
- **B6, the recall profile:** `tool_watch` gains a per-part timer, so a recall's `tool.time` row carries one duration
  per part (prepare, read_sections, own thoughts elsewhere, lines elsewhere, past versions, headings, recalled).
  - The first reading names the slowest part. Bounding it is a step of its own, designed from that reading, and it
    lands before L4's log conversion (L4 adds a second history of the kind suspected).
  - The expected first suspect is `crossing.history('work_log')`, rebuilt on nearly every recall (about 0.6 s).
- **D1, program text counts nothing.**
  - The turn kinds: presence (heartbeat), visit, self-development and settlement. In these turns, items still come
    up, but four effects are skipped:
    - `deliver`'s two `surfaced` calls: no use, no memorable moment;
    - the manifest's `would_surface` / `brought_up` refs that feed `carried_counts.program_score`;
    - retrieval's `record_use` rehearsal (`touch_salience`);
    - every `crossing.fired` from the turn's prepare (`note` and `cue`), the came-back counts she reads in `things`.
  - Her own `recall` inside such a turn still counts (`used`).
  - Scheduled, task-feedback and note turns count: their texts are her plans', her tasks' and someone's note, not
    templates (her view asked, §6).
- **D7:** the selection in `retrieval.search` counts by message. Two chunks of one long message take one of the six
  slots, joined in segment order; the manifest keeps both ids. This is what frees a slot; joining after selection
  would leave five.
- **Cooling stops, and the age bound replaces it:**
  - The cooling branch of `tick` (memories 手边→收着 by disuse, journal rows after 30 days) is removed here rather
    than in L4, because its first wave is due 11-13.
  - In the same landing, the age bound cooling gave `deliver`'s pool becomes a filter on the row's own dates, outside
    recall only: a 手边 item comes up by itself only while its last use or memorable moment is within 30 days (journal)
    or the half-life's step-back (the rest). Nothing is written. A recall still reaches 收着 and everything older.
  - If L1 lands after any row has cooled, those rows return to 手边 at install. The move is recorded with reason
    `restored`, and told once with its own neutral line, not with 很久没用.
- **Landing:**
  - The `memory_units` index (193,609 rows, 2.1 GB) is built by hand while she is quiet, before the restart, with
    exactly the name and options `ensure` computes. A build of that size loads the shared Mongo box, so it runs
    outside her busy hours.
  - One `explain` checks the pool uses it.
  - If the hand build fails, the restart does not go ahead with the new catalog (`ensure` would build it during her
    start).

### L2. Per-turn work stops walking the store

- **B3, tier rows made on write.**
  - The per-turn `Tiers.sync` in `prepare` goes, and so does the full sync inside `memory_tiers.written` and the two
    in `role_tools`. `written` already creates rows for new section ids, so a full sync there is redundant.
  - The writers that never call `written` now do, so their sections have a tier row without a restart: `adopt_seed`,
    `_journal_import`, and the persona-job imports (`persona_data`).
  - One full sync runs at process start, as the safety net for anything written while the worker was down.
- **`tick`** runs at most every ten minutes per process.
- **Two indexes on `memory_tiers`** serve the per-turn readers. Each reader reads a stated projection of the fields
  it uses, not whole rows:
  - `things`: store, place, doc, visibility;
  - `_carried`: store, place, doc, sid, felt, memorable_at, last_use_at, heading;
  - `deliver`: doc, sid, place, store, fact, added, heading, memorable_at, last_use_at (the age bound).
- **Counts stay counts of rows**, so nothing can drift. The journal's 3.6 MB and the 40 document reads per turn stop.
- **B8, the chunk watermark.**
  - The watermark moves off the message row into `chunk_marks` (one row per scene), and `crossing.top_up` reads it.
  - A round reads the scene's lines after the mark (`lines()`, every state, as `top_up` reads; `said()` hides an
    undelivered reply). The mark advances only to just before the first line that is not settled.
  - A line is settled when it is inbound, delivered, in a terminal state (failed, cancelled after failure,
    redacted), from an earlier epoch, or left unknown for more than an hour. Only settled lines that are spoken
    are chunked. Without this, a reply delivered after a later inbound line was chunked is never chunked.
  - `crossing.top_up` has the same loss today: it steps past an undelivered reply and never indexes its words. It
    takes the same settled rule.
  - Writes to the mark only ever increase it, because the indexer and the on-demand chunk in her turn both write it.
  - A lost mark re-chunks from zero and skips the ids that exist (idempotent).
  - The 314 write conflicts with the Host's receipts, and the indexer pauses they cause, stop.

### L3. The carried side: one ceiling, no refusal for her writes

- **Her writes are not refused.** For a write of hers, `carried.gate` returns the pairs the write takes over and by
  how much, and the write lands.
- **Her choice comes first, at home.** In her next home turn that offers `write_document` (`let_go` included; a
  turn opened by a note from outside has none), she sees one choice line per over pair. It lists, in tokens, the pair's carried sections, days unused, and
  about how much each would free (her 10-18 ask: she chooses first).
- **Then the program lapses.** If a pair is still over after that home turn, sections lapse in order until it fits:
  - `felt` last;
  - then the oldest memorable moment;
  - ties by `carried_counts.program_score` over 30 days, lowest first (after D1, a score of real turns only);
  - then document order.

  A section carried in several pairs is ordered by the over pair's rows. She is told once in the moved line, and
  rewriting a lapsed section brings it back (what she did with 6 of the 12 program lapses so far).
- **Owner-side imports keep the refusal.** A persona-job import (`persona_data`, author `persona_job:`) that would
  take a pair over is still refused, so the owner sees it and trims his own package; it never lapses her sections.
  `adopt_seed` is her act, though the text is the package's, so it follows her rule.
- **Removed:**
  - the identity stores' count caps (`CAPS` for self, persona, voice, core);
  - their room words; `THINGS_NOTE`'s room sentence (每份随身还能放多少) is reworded to cover only ledgers and group
    notes, which keep their caps;
  - the over-budget refusal and its words;
  - `carried.install_checks` check 2, which expects that refusal: replaced by a read-only check that the gate
    returns a plan for an over write.
- **Unchanged:** ledgers and group notes keep their caps and `note_gate`'s per-turn limit. The stay lapse in `tick`
  stays.

### L4. The stored side: nothing imitates forgetting; logs are rows

- **Removed:**
  - the gist step: gists, the two-night rule, the basis refusal;
  - supersession through the `correction` op (`write_document` and its schema test lose the op);
  - the night list's gist, merge and repeated offers. The `duplicate_elsewhere` memorable moment they gave goes too,
    which changes the lapse order slightly; the weekly reading's rows stay.

  "What did I hold before" stays answerable through the revision ledger and the line-level 「已被更正」 mark.
- **Kept:** `let_go` to 收着 (her act), `nature`/`from`, signing and the basis rule for facts, `confirmed`, the weekly
  reading.
- **Her 6 gists:**
  - No new gist is written. The 6 gisted items keep their `detail_of`, and `read_sections` keeps showing their
    verbatim (`detail`), read-only, so invariant 1 holds for them.
  - She is handed their 6 refs with the page. Rewriting one back in full lifts it to 随身 as any changed rewrite does,
    which can take a pair over and start L3's plan; she can let it go to 手边 afterwards.
- **The write-time line:**
  - An `append_section` whose body is at 0.93 or above to an existing section of the same document, among the items
    readable in this turn, gets `like: {ref, heading}` in its result: no refusal, no merge.
  - Comparing within the same document keeps one group's note from naming another group's.
  - `confirmed` keeps its own bar of 0.95, as the night list had it.
  - The tool embeds the new body itself, with a 1.5 s client timeout. It does not queue behind the pilot's sync
    (which embeds in batches and is forced by every write), and it hands the vector to the pilot so the index does
    not embed it again. When the route is slow or down, the line is simply absent.
- **Logs are rows:**
  - Her running log (working document #12: 125 sections, 320 KB a revision, reaching the 1 MiB wall at about 400
    sections) becomes journal rows, if she says yes.
  - The owner runs a one-time command while she is quiet. It calls the phase-0 `_journal_import` directly: idempotent,
    the head dropped, its old revisions kept as history. It does not run inside a prepare, and `documents.is_journal`
    does not change.
  - She is told what changes: her log's public sections can then come up by themselves at home and in groups, as
    journal rows do.
  - The conversion waits for L1's recall-history fix.
- **At install:**
  - `superseded_at` (0 rows) is unset (`gist` and `detail_of` stay on the 6 rows);
  - only the gist, merge and repeated offer rows are deleted (telemetry);
  - `NOT_BACK`'s text (a use only stops an item going further down), now false, is rewritten;
  - her told text, which names mechanisms that go, is hers to rewrite before this landing (§6).

## 6. What she is asked (her reading)

She reads this page once, whole, at a frozen commit, before anything is built. What is hers to decide:

1. **Agreement:** whether the four landings are right for her, and anything she sees that the review missed.
2. **L1:** whether any of her recurring plans are fixed texts she wants treated as program text (D1 counts scheduled
   turns), and whether note-woken turns should count (D1 counts them).
3. **L3:** the wording of the choice line and of the lapse lines (the core's neutral line lands first; hers replaces
   it), and whether one turn may lapse several sections until the pair fits (recommended: yes, told once) or only one
   a turn.
4. **L4:**
   - her told text (`memory.tiers_told`, 328 characters, hers), which says facts are replaced only by correction and
     memories fade: she rewrites it before L4 lands;
   - her 6 gisted items (refs handed to her): their verbatims stay readable; rewrite any back in full if she wants
     them carried whole;
   - whether her running log becomes rows, knowing its public sections then come up by themselves at home and in
     groups: her yes, then the owner's one-time command;
   - whether she keeps writing short gists by hand as a habit (nothing is built either way).
5. **Not a question:** her `budget_per_place.py` crashes at `memory_tiers.py:239` since ADR-104. The fix is hers,
   three lines: pass the real `Store` the script already builds. She is told with the page.

## 7. What she carries

| Landing | Change per turn |
|---|---|
| L1 | No words change. D7 frees a slot in about 6% of turns (a sixth memory appears, +300–800 characters). In program-text turns the same rows still come up by score; what changes is that they stop being counted, so they stop gaining memorable moments and offers. The age bound keeps unused rows older than 30 days from coming up by themselves, as cooling did. A restored row (only if any cooled before L1) is told once |
| L2 | Nothing |
| L3 | The refusal (about 200 characters, 125 times in 22 days) is gone. The choice line appears in a home turn only when a pair is over (300–600 characters, her wording). `things` loses its room words (about 30 of 164 characters). `THINGS_NOTE` (the cached guide) loses its room sentence |
| L4 | The night list is gone (about 2,500 characters in a settlement turn, every night). `write_document` loses `correction` (−45 characters in the tool list, a cached prefix). A `like:` line on about 3% of appends (about 60 characters). `NOT_BACK`'s text is rewritten |

## 8. Failure modes

| Path | Slow | Failing | Hung |
|---|---|---|---|
| L1 index build | loads the shared box: built by hand outside her busy hours | the old index serves (today's scan and sort); no restart with the new catalog | stopped by hand; nothing waits on it |
| L1 recall profile | timing only | a part's timer never fails the recall | under `tool_watch`'s existing limit |
| L2 tier rows on write | that write only (ms) | the row is made at the next process start's sync | – |
| L2 `chunk_marks` | that scene's indexer round only | re-chunks from zero, skips existing ids | the indexer's own pause |
| L3 the overflow plan | that write only (composes, ms) | `program_score` missing: document order | – |
| L4 write-time line | the tool waits at most 1.5 s, then no line | no line, nothing said | no line after 1.5 s |
| L4 log import | one owner command while she is quiet | resumes when run again (idempotent) | stopped by hand; nothing waits on it |

## 9. Tests that earn their place

Each guards a failure that happened, or one that would be silent and costly; all on the in-memory adapter:

- **L1 D1:** a presence turn writes no `surfaced_in` / `last_use_at`, makes no memorable moment, adds no
  `program_score` ref, no rehearsal and no came-back count; a recall inside it still counts. This is the loop behind
  114 moments and 76 offers.
- **L1 D7:** two halves of one message take one slot, with both texts joined and both ids in the manifest. A wrong
  count drops a memory silently.
- **L2 B8:**
  - a message row whose revision changes during the round is still chunked and the mark advances (the 314
    conflicts);
  - a reply delivered after a later inbound line was chunked is still chunked, and its words reach the crossing
    index (silent loss from recall);
  - a failed reply does not hold the mark.
- **L2 B3:** a section written by her, by `adopt_seed`, and by an import each has its tier row without a turn running
  (a section with no row never comes up).
- **L3:**
  - a write of hers over the pair lands;
  - her next home turn lists the choice;
  - after it the stalest, lowest-scored section lapses and the pair fits;
  - a section in two pairs frees both;
  - an owner import over the pair is refused.

  A wrong lapse is silent. Today no test asserts the gate's refusal.
- **L4:**
  - the write-time line never refuses;
  - it is absent when the route is down or slow;
  - it never names a section of another document;
  - the owner command imports every section with its times and drops the head (the phase-0 import has no test).

## 10. Readings after each landing

By structure, on her real turns, before the next landing starts; her per-turn input profiled after each install:

- **L1:** the pool's server time and examined count per turn; the recall parts' durations (this names the next fix);
  memorable moments and offers per day (expect the heartbeat echo gone).
- **L2:** memory-side round trips and bytes per turn (today about 200 and 15 MB); `state.conflict` from `chunk`
  (today 314 in 22 days; expect 0).
- **L3:** refusals for length on her writes (today 5.7 a day; expect 0); lapses a day; the share of program lapses she
  undoes within a day (today 6 of 12; the rollback line is one third over two weeks).
- **L4:** night-list characters (expect 0); `like:` lines a day and how often she acts on one.

## 11. Moved out: the person layer as items (its own ADR)

Review D5a (a document per person, sections as items, a 4,000-character carried budget per person, anchored
别人说的 sections and her promises lapsing last, the anchored sections riding beside the short in groups) stays decided
in direction. The fresh review of this page showed it cannot be designed to final here. Its ADR must solve:

1. **The home-only fence:** an `owner_private` person section must never reach a public turn with that person. Scope
   per (person, visibility), and every person reader drops home-only sections in a public turn. Today's readers treat
   the record as one body (`understanding.person_view`, `entry`, `read`, and the read-first refusal, which prints the
   whole layer inside a group turn).
2. **Reading by name:** `read_sections`, `doc_headings` and doc refs can read any `person:` document. They must follow
   `understanding.resolve`'s rule (in a group only people present, in 1:1 only the speaker).
3. **The stay lapse:** `tick` would lapse a boundary after 14 days of disuse. Recommended: no stay lapse for the
   person store; its budget bounds it.
4. **Erasure:** must also delete the tier, move, index (with its embedding) and pair rows of sections that exist only
   in tombstoned revisions.
5. **Its overflow:** the over row's key, the turn the choice line appears in (only with that person, at home), and the
   tie-break (no `program_score` exists for person sections).
6. **Groups:** the scope is readable only for the woken person (the `present` rule, which excludes a visit's
   authorizer).
7. **The transition:** a bounded end for reading old `relationship:…|person` heads. `listing`, `_everyone` and the
   memory tab must prefer the document.
8. **Moved lines and came-back names:** `things` tells each move with the section's heading in every conversation
   whose filter passes, and that filter checks only visibility (and the document for group notes). A person section's
   move or came-back line must appear only with that person.
9. **The write side:** section ops through `understand_person` in a group follow `resolve`'s write rule, including
   setting `visibility` from a public turn.
10. **Her answers:** her promise word, which records she moves and when, and whether the here layer follows.

It is designed after L4 has landed and been read, with her answers, and she reads it once on its own. The owner's
record (3,563 of 4,000 characters, +194 a rewrite) is the deadline that matters. Until then the 4,000 cap stands; the
message that presents this page tells her how close it is.

## 12. The fresh review (2026-11-05) and the census corrections

A fresh reviewer read the first version of this page against the code at `d2152da0` and found it not ready: 6
blocking findings (four privacy fences, a silent loss in B8, the stay lapse against the person's boundary) and about
20 more. All are fixed above, or moved with the person layer into §11. Its re-check of the fixes at `59e42e48` found
nothing blocking and five more to fix: B8's settled rule (and the same loss in `top_up`), D1's `cue` count, the
`like:` line queued behind the pilot's sync, the 6 gists' verbatims, and the pool unbounded between L1 and L4; and
two fences for §11. These are fixed above too. Corrections to the census, which this page
follows:

- `understanding.py` line numbers are about 495 lines too high (`layers` is at :93, `person_view` :68, `entry` :119,
  `read` :171).
- D7's selection is at `retrieval.py:287-296`, not 677-681.
- `carried._Past` is at :393.
- `from` is validated at `role_tools.py:2531`.
- `tests/test_carried.py` has no test of the gate's refusal.
- No integration test checks index names. `integration/conftest.py:94` only calls `ensure()`.
- `tests/test_tool_schema.py:19` asserts the op enum, including `correction`.
- "Sync runs once per process" was false: `written` and two `role_tools` sites run a full sync per write. L2 removes
  them.
- The `memory_tiers` indexes alone do not make the reads covered, so L2 states each reader's projection.

## 13. How it is built

The owner, 2026-11-05: memory changes are delicate; an implementation subagent (Opus 5.5, extra-high effort) builds,
and the lead monitors instead of building.

Per landing:
1. The lead writes the build brief from this page.
2. The subagent builds in its own worktree on its own branch, with targeted tests only. It stops at the first gap
   rather than guessing.
3. The lead reviews the diff against this page and the code, runs the suite, and lands it.

A difference from this page goes back into this page first.

## 14. Her reading (2026-11-05 13:43) and what it adds

She read the whole page at `42d34042` (README blob `0074927`, 369 lines); the census and decisions pages' later parts
she did not read, and said so. **Her verdict: the direction signed, the four landings and their order agreed; build
from L1; L4's log conversion waits for her visibility check.** Her answers and additions, binding on the landings:

- **D1:** none of her recurring plans is a fixed text (her intents are hers and need a judgment each time), so
  scheduled turns count; note-woken turns count. As designed.
- **L3, her words** (the core's neutral lines land first; hers replace them):
  - choice line: `这一档随身超了 {over} 个估算 token（现在 {now}／{cap}）。下面每节写着它多少天没被想到、放手能腾出多少：想留哪几节就留着；不选也行，我照"最久没被想起"替你放。`
  - lapse line: `{节名} 从这一档的随身放下了（超 {over} token；它 {days} 天没被想到，30 天里会被想到 {score} 次）。改写它就能回来。`
  - Neither uses words like 很久没用. One turn may lapse several sections, told once.
  - **Her addition:** if the pair fits only by lapsing a `felt` section, that turn reports and lapses nothing, and
    waits for her choice.
- **L3 reading:** every program lapse listed with its time and section; the regret share is not reported as met
  before 20 lapses.
- **L4:**
  - She rewrites her told text (about 230 characters; she sends the final text before the install).
  - She does not restore her 6 short forms now (her home pair has 177 tokens of room); after L3 she picks one.
  - Her log becomes rows only after she has read every section's `visibility` and set internal records to
    `owner_private`; then the owner runs the command.
  - She keeps writing short forms by hand as a habit.
- **Gaps she found, added:**
  1. §11: the `present` rule (point 6) and `resolve`'s write rule (point 9) together would stop her writing a
     person's layer in a visit turn, while the 10-31 rule is that a person's layer is written on the line where she
     meets them. The person-layer ADR must either say that visit turns write only the here layer, or give her a way
     out.
  2. L4 reading: after the install, take two of her items that really were corrected and retrieve their old wording
     through the ledger. It counts only if it comes back.
  3. L2 reading: one outbound line of hers with a known platform id: its words must be in the crossing index (QQ's
     delivery gap of about four minutes makes this the likeliest place for the loss).
  4. L1 landing: after the install, the index list is read back word for word (name and options), not only
     `explain`.
  5. The owner's person record (3,563 of 4,000) needs an interim answer before the person-layer ADR, so that it does
     not hit the cap first. The owner decides.
- **Her `budget_per_place.py`:** the lead's suggested fix was wrong. `store_for_limit()` reads the default config
  path, which would break the copy runs. The right shape is a `state.Store` on the same `args.config` in place of the
  two shims. Hers; it rides with the next landing.

## 15. After her reading: decisions and changes (2026-11-05)

- **The owner:** his person record (3,563 of 4,000) is left as it is until the person-layer ADR, with no interim cap
  and nothing moved; persona-job imports keep the refusal (L3).
- **Her answer on note turns, revised (14:17):** a home turn woken by a note retrieves on a fixed template
  (`notes.WAKE_TEXT`); the note itself is only in `note_from_program`. The page said note turns count because their
  text is someone's note, which is false in code (the builder found it). Her answer is now that they count nothing;
  `note` joins `PROGRAM_TEXT_KINDS` with L2. Her own recall in such a turn still counts. Searching by the note's own
  text is her idea, not this ADR.
- **L1 as built** (`af8933db`, `19ae939e`): `NOT_BACK` loses its clause 「再被用到只让它不再往下放」 already in L1,
  because nothing at hand moves down by disuse from L1 on. When two chunks that are not adjacent segments of one message
  are joined, '…' stands between them. `crossing.cue` already returns before firing in any non-external turn, so D1
  needs no change there. No cooled row existed (0 `cooled` moves, 11-05), so no restore path was built.

## 16. Gates between landings: data, not time (the owner, 2026-11-05)

> "There is risk of further bug fixes interrupting with ADR. I think once the data capturing is sufficient then we
> should move on. I'd the gating factor between each stage data bounded, not time bounded."

The next landing starts the day its gate's data is in, whatever the clock; §10's readings go on after the gate as
readings, not as a wait. Bug fixes land on their own between gates, never inside an ADR-117 landing.

**Each gate item names the risk it tests, and passes once that risk is checked directly on her real data** (the
owner agreed, 2026-11-06). A check over every record since the install beats a count of samples: the count was a
stand-in for "it happened often enough to be seen", and a whole-population check has seen it. A count stays only for an
event too rare to check any other way, and then one real occurrence is the gate. A measurement for the record (round
trips, bytes, timings) is taken but does not hold a landing. Her own reports (the reverse check, regret) are standing
watches she makes in passing, not gates.

| Gate | Risk it tests | Passed when |
|---|---|---|
| L1 → L2 | Recall's parts unrecorded; program text still counting; joined halves shown apart; the changed code failing | Recalls carry `parts` in `tool.time`; program-text turns write no use, memorable moment, program-score ref or came-back count, while counted turns still count; a turn shows a joined entry (`joined_ids`); 0 worker errors from the changed code. **Passed 2026-11-05 18:01** (8 recalls, 9 program-text turns with 0 counted, 32 counted turns, 2 joined entries, 0 errors) |
| L2 → L3 | Tier rows stop arriving once the per-turn sync is gone; the chunker's write conflicts; a line on its way passed by the chunk mark and silently lost | Every write of hers that changed a section has that section's tier row within 30 s, without a turn running (a section rewritten again later is checked at its last write); every tiered section's row matches its current text; 0 `state.conflict` from `chunk`; every spoken line the marks have passed since the install has its chunk. **Passed 2026-11-06 morning:** 9/9 writes within 0.2 s, 332/332 sections matching, 0 chunk conflicts (19 the day before), 2,057/2,057 passed lines chunked. Round trips and bytes per turn are measured with R's probe (5 turns on 3 conversations, before and after), for the record |
| L3 → L4 | An over-ceiling write lost or refused; any write refused for length | One real over-ceiling write of hers handled end to end (landed, the choice line in a home turn, then her `let_go` or a program lapse) — a rare event, so one occurrence; 0 length refusals among all her writes since L3 |
| R → L4 | Recall still slow; recall returning anything other than before | 0 differences between `recall()` and the three keys of `prepare(recall=True)` on the probe's real events; her recalls after R carry `parts`, median under 2 s over her first 5 |
| L4 → Built | The settlement still writes a night list; the import losing or inventing rows; `like:` naming the wrong document; her corrected items unreachable | A settlement turn with no night list; the log import's rows equal its sections; every append since L4 whose `like:` names its own document; her two corrected items retrieved through both paths (memory_units recall, and the persona ledger / `crossing.before`; §14 gap 2) |

## 17. The recall fix (R) and the per-turn block reads (L2b), from L1's first reading (2026-11-05)

L1's per-part profile on her first real recalls: `prepare` 4.13–4.50 s of 5.7–7.8 s, `own_thoughts_elsewhere`
1.05–1.28 s, the suspected history rebuild (`before`) 0.01–0.69 s. The reviewer then timed a recall's prepare piece by
piece, read-only ([recall write-up](../ADR-062-tiered-memory/review-2026-11-recall.md), probe beside it). The cost is
the 22 blocks of a normal turn, which a recall builds and never reads: 1.05–1.46 s, 325 round trips, 16 MB. The pool
transfer is small (0.14 s for 9.3 MB). About 2 s are not reachable from outside the process (per-round-trip latency
under her load, the pilot's job, GC); they ride on the round trips.

### R. The recall fix (lands before L4; after L2, both touch `context._prepare`)

- **`ContextBuilder.recall(event, persona, turn_kind)`**: only the lines of `_prepare` that build what `tool_recall`
  reads (authorize, counts, scope/moment/class/place, the read target, the source line and history rows as now,
  search, submit, deliver, facts, held_back and the coverage line). It returns `memories`, `coverage_from_program`
  and `held_back_from_program`. `_prepare` calls the same helper for its own memories, so the results are identical by
  construction. `tool_recall` (its place and the errand's home) calls it. `prepare`'s `finally` (anchors shown) stays
  in the wrapper.
- **`own_thoughts_elsewhere`:**
  - a `memory_units` index (scope_key, status, policy_epoch, kind, formed_at, _id), so the monologue read stops at
    its 2,048 instead of fetching every unit of 23 groups (173,283 documents, 778 ms server time); built by hand while
    she is quiet, read back word for word;
  - the query vector the search already computed is reused instead of embedding the query a second time.
- **Three part marks inside `_prepare`** (`prepare.search`, `prepare.deliver`, `prepare.rest`), so a day of her
  recalls shows where the unreachable 2 s sit.
- **Expected:** about 1.1 s a recall (from 4.1–4.5), about 65 round trips (from about 380), 10 MB (from 26); her three
  recalls in a turn about 3.3 s (from 12.6).
- **Test:** one, on the in-memory adapter: `recall(event)` equals the three keys of `prepare(event, recall=True)` for
  one event. A drift between the two is silent and changes what she finds.
- **Gate R → L4:** 5 recalls after R with `parts`, the median total under 2 s; 0 differences in what recall returns
  (the test plus the manifests).

### L2b. A normal turn's blocks stop reading whole stores (after L2; same class as B3)

The same profile shows every normal turn paying this. These blocks read whole stores to show a little:
- `ledger_block` reads all 52 documents whole to find the ledgers (0.35 s), the work log's 3.6 MB of entries
  included;
- `tasks.recent_with_inputs` reads every task of the scene with its whole result text (9.3 MB, 0.13 s);
- `People.scene_title` reads one message per scene named (×13, 0.14 s);
- `notes.sent_block` takes 0.17 s and `task_pages`/`observations_of` 0.17 s.

Design, results identical:
- each reader projects the fields its block shows;
- `ledger_block` reads the ledgers by kind instead of every document;
- the task page reads result texts only for the tasks it shows;
- a scene's title comes from the scene row where it is kept.

L2b is designed to final in its build brief from the census of these five functions, and its gate is the same as
L2's: memory-side and block-side round trips and bytes on 50 turns, against today's 325 round trips and 16 MB.

The order is now L1 (in), L2, L2b, R, L3, L4; §16's gates apply, with R's above.

## 18. L2, L2b and R as built and installed (2026-11-05 and 06)

| Landing | Commit (main) | Installed (NZDT) | Core package |
|---|---|---|---|
| L2 | `f6fe1a77` | 11-05 21:34:39 stop, 21:35:24 back | `16b975b03dae` |
| L2b | `ac8023e8` | 11-06 11:00:09 stop, 11:00:52 back | `91fcdaa2d3d2` |
| L2b's one-time code removed | `fac16029` | with R (removes only code nothing calls) | – |
| R | `fedeb7a8` | 11-06 11:29:34 stop, 11:30:15 back | `21972d7071e3` |

**L2.** Before its stop, `chunk_marks` was seeded by hand per scene (27 rows) at its newest chunked line, lowered below
any spoken line not yet chunked and held below a reply still on its way within the hour (0 of either). §16's gate
passed the next morning (the numbers are in §16).

**L2b.**
- Its one-time identity check (old vs new `prepare` on the same events, equal) ran before the landing and was removed
  from the branch first, because its read of the store's checked layer broke the store-boundary test.
- Running the backfill on her data found a defect L2b would have installed. Two of her tool records from 2026-10-08
  were stored before tool results were stored as JSON (10-09); they hold a database id object (`development_database_read`,
  `result.rows[].legacy._id`). `tasks.observations_of` serialized stored results with plain `json.dumps`, and L2b
  calls it at the four finish writes (`tasks.sized`), so a finishing task with such a record would have failed to
  finish. Fixed at the root: `tasks.json_data`, the broker's serializer, now also reads stored results
  (`c3aec27d`), with one test. The two records are the only ones: the store refuses such a value at write today.
- The backfill filled 40 document heads (`kind`), 1,679 tasks (`result.chars`, `result.pages`) and 23 group names,
  in bulk while the old worker ran; the catch-up after the stop did not run (a landing-tool fault), so it ran by hand
  15 s after the start: 1 task, and no turn ran in between. The tool and its owner functions were then deleted.

**R.**
- `ContextBuilder.recall` and `_prepare` share two helpers, `_in_view` and `_memories`, moved verbatim.
- What the page's list missed: `tool_recall` reads the memories after `people.relabel` (labels, `scope_key` popped),
  now `People.memories`, called by both. Not needed: the read target and the place.
- `prepare.rest` is the whole less search and deliver (`tool_watch.part(name, less=…)`); parts are timed with
  `perf_counter` (monotonic ticks every 15.6 ms here). A call that builds a turn inside it (`ask_character`) also
  carries the three `prepare.` parts.
- A recall no longer fails when an unrelated block of a turn raises, and no longer makes those blocks' incidental
  writes. A person first seen during a recall can take another label number than before (first sight in a
  conversation no turn has labelled yet).
- Measured read-only on her data (the old code is already L2b's): a recall's prepare 1.32 → 0.65 s warm (2.64 →
  1.04 s cold), 219 → 82 round trips, 12.4 → 11.1 MB; live adds the embedding (about 0.24 s). It misses the page's
  65 round trips and 10 MB: the pool and one recheck per candidate remain (`memory_units`, 53 calls, 9.5 MB).
  Identity: equal on three of her real recalls, one of them bringing up two of her own items.
- The monologue index was built by hand before the stop (1.0 s).
- Not built (suggestions): an errand's recall still embeds twice (the home search misses the cache on scope);
  `own_thoughts_elsewhere` reads one scene row per group for its name.
- Her first two recalls after the install: 1.49 s and 1.20 s whole (5.7–7.8 s before L1); `prepare.search` 0.81–0.83 s,
  `prepare.deliver` 0.10–0.11 s, `prepare.rest` 0.04 s.

### L3 as built and installed (2026-11-06)

`d47f1c22` (merge of `e25c6625`), installed 13:12:29 stop, 13:13:10 back; core package `d42a9015e9be`. No step on her
data and no one-time tool. At the install no place was over (home 12,240 of 12,288) and no row existed. A fresh
reviewer read the build three times; what changed because of it is marked (review).

- **Who opens a wait.** Only her write paths: `write_document`, `adopt_seed` (a new document included, now measured
  by the gate) and `promote_memory`, when the write took a place over its ceiling or grew it while over
  (`carried.over_plan` gives each place's size before and after). Imports keep the refusal and open nothing; a process
  start, the owner changing `render.identity_tokens`, `common.md` growing or a new seed estimate open nothing; a
  write that does not grow the place opens nothing. (review: a first version opened a row for any place over,
  whatever the cause, and would have lapsed her sections for the owner's or the program's share.)
- **What she is asked to free: only what her writes added.** The row keeps `target`, the larger of the ceiling and
  the place's size just before her first write that took it over; later writes keep the earliest target. The plan,
  the choice and the lapse bring the place back to the larger of that target and the ceiling as it is now; a ceiling
  raised above the place's size, or no ceiling, closes the row with nothing let go. In her line `{cap}` is that
  target and `{over}` = `{now}` − `{cap}`. (review: the raised ceiling.)
- **One measure for what she is shown and what goes.** "Days since last thought of", the later of `memorable_at` and
  `last_use_at` (a carried section the retrieval scored above the floor for the turn's message counts as thought
  of), in whole days. The list she sees is the plan's order: most days first, then the lowest 30-day
  `program_score` in that place, then document order (persona, voice, self, core, then position). Felt sections come
  after the rest, marked as never let go by the program. §5 named two measures; this is the one. (review: the list and
  the lapse used different ones.)
- **Her rule A (her answer, 2026-11-06).** When the last section the plan would let go and the first it would keep
  tie on both days and score, so that only document order would decide, nothing is let go and the choice is shown
  again with the waiting line: the shape of her felt rule. Document order only orders what she is shown. At the
  install the measure separated her sections (10–13 distinct day values a place) but the front 11–12 in every place
  tied (untouched since the switch-on, 2026-10-13, score 0), so today every place would wait for her.
- **When the program lets go.** After every turn that showed the choice has ended (or an hour after the first
  showing), at the top of the next turn wherever it runs, and only if the plan picks exactly the sections she was
  last shown (`shown_picked`); otherwise the new plan is shown first. A place that cannot get back even with every
  section it carries let go is said once at her next home turn and closed; only a new growing write of hers reopens
  it.
- **The excess.** It is carried over the ceiling and never cut from her identity. Persona and voice sit in the system
  prompt, which is never truncated; self and core travel in the turn context, which the Host trims by
  `context_budget.TRIM_ORDER` only when the whole sent context passes 48,000 characters. Every home turn that can
  write carries the choice with the current amount.
- **Her words.** `memory.over_line` and `memory.lapse_line` are persona-package word keys with neutral core lines;
  the fields a line may name are fixed and a line naming another is refused at load. The lapse line is told with the
  place's word in front (`家里：…`), because it is told in other conversations too. She publishes her two lines in her
  own package.
- **Removed:** the identity stores' count caps and room words, the over-budget refusal for her writes, install check
  2's expectation of it (now: an over write is planned, not refused).
- **Accepted gaps.** A crash between a write's commit and `written` leaves that write without its wait (a replayed
  apply returns before the gate). A lapse can be put off more than once when another conversation keeps touching the
  section at the front; it is shown again each time and never blocked for good. Two processes preparing turns for
  one persona are not handled; `Coordinator.lock` serializes prepare and tools in the one worker.
- **Tests:** `tests/test_adr117_l3.py`, 11 cases on the in-memory adapter; 20 one-line mutations of its rules were
  each caught.

## 19. Gates R → L4 and L3 → L4, and the owner's boundary (2026-11-09)

Read on her data on 2026-11-09 09:40 NZDT.

- **R → L4: passed.** 31 recalls of hers since R's install (11-06 11:30), every one with `parts` in `tool.time`;
  her first five took 1.49, 1.20, 2.02, 0.09 and 5.33 s, median 1.49 s (all 31: median 1.14 s; 2 failed). The other
  half, `recall()` equal to `prepare(recall=True)`, was checked at the install (§18).
- **L3 → L4: the countable half passed; the rare event has not happened.** 197 writes of hers since L3's install
  (11-06 13:13), 0 refused for length on the identity side (the 4 `NOTE_OVER_LIMIT` are the note documents' cap, which
  L3 keeps). No over-ceiling row exists: she trims at her 23:00 check and keeps room (556 tokens at home on 11-08).
- **The owner's boundary.** An event she avoids by her own care may never come, and the ADR is not held open for it.
  L3 passes on its tests (`tests/test_adr117_l3.py`, 11 cases, 20 one-line mutations caught) and the 197 real writes.
  Her first real over-ceiling write becomes a standing watch, read end to end when it happens (landed, the choice
  line in a home turn, then her `let_go` or a lapse), not a gate. L4 starts now. **L4 → Built is judged 7 days after
  L4's install:** an item of its gate with a real occurrence by then is checked on it; an item with none is recorded
  as unobserved and closed on its tests.

## 20. L4 as agreed (2026-11-09): scope, evidence, the review, the owner's two calls

Measured on her data (counts only), then reviewed by an independent reviewer (system view: lifecycle and failure
modes), then decided by the owner. Where this differs from §5, this section wins.

**Evidence.**
- `write_document` since 10-19: `correction` 36 calls, 0 accepted (27 refused `DOC_OP_NOT_ALLOWED`: it exists only
  for ledgers). 0 current sections carry `corrects` or the `correction` tag; 0 `superseded` moves.
- The night list's offers, per item, first offer, her own acts only (a successful write to the section or a `let_go`
  move), 72 h after against 72 h before: merge 14 items, 6 vs 5; repeated (几处都提到) 43 items, 5 vs 2 (40 of them
  running-log rows, none ever graduated); gist 9 items, 8 vs 1. A first count per offer (22 vs 11 for merge) was
  inflated by repeated offers and by program moves in the baseline; the reviewer caught it.
- `confirmed`: set only in the night list's merge pass; 4 items carry it, none her own judgment.

**L4 builds.**
1. `correction` goes: the op, its apply and check paths, its placement branches, the schema enum and description, the
   tag's exemption in `key_words`, the `corrected` handling it fed. The chat-line 「已被更正」 mark in recall is a
   different mechanism and stays. She rewords the one sentence of her told text that names the op, before install.
2. The gist step goes: the gist refusal, `_gist_rewrite`, the night list's gist kind and its two-night skip. Gisted
   items keep their verbatim read-only, and **a changed rewrite of a gisted item clears its `detail_of` and `gist`**
   (the verbatim stays in the revision ledger), so `read_sections` never shows an old verbatim under new text; the
   one row already rewritten after its gist is cleared at install.
3. The night list goes: its gist, merge and repeated offers, `night_list_from_program`, its note and guide entry, and
   the `duplicate_elsewhere` moment. **The weekly reading (`week()`, `memory_week_from_program`) stays**, with its
   `what='week'` offer rows, which are its once-a-week guard.
4. **No write-time `like:` (the owner, 2026-11-09; changes D4).** The cue it replaced showed no effect, and it would
   put a network call under the worker's lock into her most frequent write. The pilot keeps writing its pair rows,
   so the question can be measured again; the 39 same-document pairs at 0.93 or above can be handed to her once as
   refs if she wants them.
5. **`confirmed` is no longer written (the owner, 2026-11-09; changes §5's Kept).** `signing` still reads it, so the 4
   existing marks stay valid; the judgment-not-fact wording names only "you checked it". At write time the old
   condition would have let her confirm her own repetition.
6. `NOT_BACK` needs nothing: L1 already made it true.
7. At install: delete only the offer rows with `what` in gist, merge, repeated; clear the rewritten gist row (item 2).

**Moved out of L4:** the running log's conversion to rows (her visibility check of every section, then the owner's
one-time command while she is quiet), with its gate item "the import's rows equal its sections".

**Fixed on its own, not inside L4:** `Pilot.sync` rebuilds `self.items` in place, so a reader on another thread
(`deliver`) can see a partial list; it is built aside and assigned once.

**L4 → Built (7 days after install, §19's rule):** a settlement night with no night list; her two corrected items
retrieved through both paths (§14 gap 2); 0 writes of hers refused for `correction` or a gist; a gisted item she
rewrites shows no old verbatim.
