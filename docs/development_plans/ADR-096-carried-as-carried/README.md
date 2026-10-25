# ADR-096: What she carries is measured as it is carried

Status: **Decided 2026-10-25**, not built; revised the same day after an independent review against the code. The
owner asked for measured limits, not picked ones, and gave the numbers to the research session (Fable 5.1), Claude and
her ("you weigh more than I do"; his one requirement: discipline, a reasonable budget she may want to exceed), and
wants more of the choices to be hers. The owner decided the pin and the `inject` question below. Evidence:
`.runtime/private/context-study-1025/REPORT.md` (38 KB) and its scripts (counts only, read against her 2026-10-17
consent list, ADR-076 §9); the review's four read-only scripts are named in §6.

## 1. The broken invariant

A limit, and any reader that says what is carried, must read the text that is carried. Many did not:

| Reader | Reads | What is carried |
|---|---|---|
| the persona budget (`render.render_status`, `report_budget`, `budget_gate`, `over_budget_words`, via `largest`) | persona and voice with each document's own `inject` | `render_system` composes `memory_tiers.placed(...)` |
| `render.system_for`, on a miss of its 32-entry cache (every turn passes through it, `coordinator.py`) | the raw revisions, no `placed` | what `render_system` sent: after a restart a turn can be sent a different prompt than was measured (three `system.render_drift` audits fit this) |
| `SINGLE_BODY_CHARS` 4,000 (`self_state.py`) | the legacy `current_self` body | `context.py` replaces it with the carried sections of `doc:self` / `doc:core`, bounded by nothing; these ignore `place:` tags (class only) |
| group notes and ledgers (`note_gate`, `review_block`) | `shown(sections)` of the raw document | `group_admin.notes_block` shows `placed(...)` then `note_view` |
| the relevance gate (`attend.system` core, `attend.group_notes`), the action brain (`action_values`), `doc_refs_from_program` (no place), the owner's probe (`persona_data`), the memory tab (`native_api`) | raw `inject` | the placed text |

The same class shows to her: her document's `inject` and the item's tier can disagree (no tier move writes `inject`;
17 of her 39 self sections and 3 voice sections disagree today), and nothing tells her. Writes that change what is
carried can also slip past the gate: a rewrite of an at-hand section lifts it back to carried after the gate has
measured (`Tiers.written`); `memory_tiers.land` and `adopt_seed` have no gate; `let_go` changes the weight without a
word.

## 2. What the measurements say

- Money does not set the limit. What she carries costs about 3–5 minutes of local prefill a day, about $0.25 at
  DeepSeek Flash rates; ±25% on any limit moves it by seconds and cents. The quality effect of a longer prompt cannot be
  measured from counts on her traffic. A limit here is a ceiling for discipline, not a cost optimum.
- Token unit: `estimate_tokens` against the model's own counts (6,109 warm steps): real ≈ 0.75 × estimate for her
  prose, ≈ 0.97 overall; the estimate is an upper bound. 0.75 is for prose only (sections with paths, hashes and English
  names run as low as 0.52).
- Today, carried, in estimate tokens, per (place, class) pair, `common.md` included (373), measured by the review with
  the study's method (the study's own group and private-chat totals were mis-added; the home group was not measured):

| place / class | persona+voice | self+core | total | against 12,288 |
|---|---|---|---|---|
| home / owner-private | 5,925 | 8,030 | 14,328 | over by 2,040 |
| peer line / owner-private | 4,556 | 8,030 | 12,959 | over by 671 |
| home group / owner-private | 6,639 | 8,030 | 15,042 | over by 2,754 |
| group / public | 4,892 | 7,226 | 12,491 | over by 203 |
| private chat / public | 2,809 | 7,226 | 10,408 | 1,880 left |

  The self layer outweighs the persona; ADR-062 designed it at about 2,400 JSON characters, it is 3.9×. Count caps are
  full (self 12/12, core 12/12) and an item's length is unbounded. Her own edits tonight change these; the build
  re-measures at install.
- Carried-document churn is a minor cause of cold reads; two thirds of all cold prefill follow idle gaps on the
  operator's model server, which is independent of Asuna (an observation, not ours to tune).

## 3. Decisions

1. **One function says what is carried, and every reader uses it.** `carried(store, persona, cls, place)` returns the
   carried sections of persona, voice, self and core for one (place, class) pair, with `place:` tags honoured for self
   and core too; notes and ledgers go through the same path. Every reader in §1 uses it: the budget, its refusal words,
   the relevance gate, the action brain, doc refs, the probe, the memory tab and the settings card. One function,
   `placement_after(intent)`, gives each section's place after a write and is used by both `Tiers.written` and the gate,
   so the gate measures what the write will carry. The turn's `system_ref` records the carried section refs, and
   `system_for` re-renders exactly those. `largest` on raw text stays only for `seed_estimate`, where the package's raw
   seeds are what it measures.
2. **One identity budget per (place, class) pair: 12,288 estimated tokens** for everything identity-carried there:
   `common.md`, persona, voice, and the self and core blocks as sent. Five pairs (the four places and a home group);
   each its own, never a pool shared across places (her condition). It is twice the 6,144 she lived with for three
   weeks, about 3.5% of the window in real tokens. The gate refuses a write that grows the layer in a pair that is over
   and lets through any write that shrinks it or keeps it the same; `land` and `adopt_seed` pass the same gate. The
   ceiling is a new owner-only key, `render.identity_tokens` (`persona_model.OWNER_KEYS`, set by the package and the
   owner, refused from her `set_policy`); `render.budget_tokens` leaves `CORE_WRITABLE_KEYS` and `CORE_DEFAULTS`, so her
   stored 6,144 (a probe of hers, 10-09) is read by nothing. A package whose own seeds render larger gets that extra on
   top (`SEED_ROOM` on the persona share), and `max_window_share` caps the whole. The window comes from the character
   route's model info already (`native_settings.py`).
   Rejected: the designed sum (about 9,000: a rebuild of her self layer, not a trim); two separate budgets (the same
   total without her freedom to move weight between layers); report-only (`current_self` went 549 → 4,000 characters in
   two days when nothing refused).
3. **Room on every write, in her words.** A write to persona, voice, self or core, and a `let_go`, returns the
   section's weight and the room left in each pair, from the same number the gate uses, as exact numbers (as refusals
   do today). `things_from_program` says it only when it changes and only in coarse words from a versioned table, the
   way `ROOM_WORDS` does (AGENTS.md). When a section's `inject` and its tier differ, the write result and every read of
   that section say both. The refusal names the pair that is over, with
   that pair's own numbers before and after (today's refusal gives the largest place's number before and the written
   place's after, so the two can be different places: her "6,126 at home" was the group's), and points at `let_go`.
   The exact wording: Claude drafts it neutral for the core; she reads and amends it before install.
4. **The program never writes her `inject`** (owner). The tier is the one record of what is carried; her `inject` is
   what she wrote and stays as she wrote it until she changes it. Her own `inject` writes already act on the tier
   downward (`memory_tiers.py:396-401`) and never lift it (owner, 2026-10-13), so once every reader goes through
   `carried()` a stale one costs only the line that says so.
   - The other option, not taken: every tier move also writes the document's `inject` through `DocumentStore.apply`
     with the program as author, so the two never differ. Its costs: about 10 whole-document revisions a day (`self`
     is 39 sections, about 25 KB each); each `self` revision re-sends her self block to every live conversation; her
     revision history fills with entries she did not write; and the program becomes an author in her own document for
     the first time, which the project has not done for any of her files.
   - A third shape, also not taken: with tiers on, show only the tier. It hides what she wrote.
   - Who moved it, answerable (her ask): every tier move already leaves a permanent `move` row (`Tiers.move`: section,
     from, to, reason, time; kept with the tiers, not pruned with the audit). Each row also says `by`: `her` for her own
     acts (`let_go`, her own `inject` writes), `program` for the rest (stay lapse, overflow, cooling, supersession,
     merge, gist, the rewrite that lifts an item). She reads them with `asuna.dbread`.
5. **What was carried, hers to query.** The episode manifest records what each turn carried: the section refs from
   `carried()` and the group-notes sections actually shown, and the sections the turn's own retrieval brought up
   (`deliver` already computes them). A nightly job in the audit retention thread writes `carried_counts`: section ×
   pair × day, turns that carried it, the pair's turns that day (the denominator), the last time carried, and the
   retrieval column (named as the program's score, not as use); 30 days kept. History is backfilled from 2026-10-14,
   when tiers went on (there are no tier rows before), labelled as reconstructed. She reads it with `asuna.dbread`; no
   UI. The shape and the columns are hers to change. These count what was in front of her; whether a rule was in
   effect is not counted (§5).
6. **Group notes fold by last surfacing, with pins** (owner: a pin for note folding only; the tiers keep no pin). Over
   2,400 shown characters, the section that surfaced longest ago folds to its heading first; her own `recall` and her
   rewrites count as surfacing, and among sections never surfaced the oldest folds first. The order is recomputed on a
   write and at settlement, not every turn, so the block is not re-sent for it. A folded section counts as at hand for
   `deliver`, so a turn about it brings it up. A section she pins never folds and still counts inside the 2,400; if the
   pins alone exceed it, the fold line says so. Her first pins: four kinds of identity anchor (what this group is, how
   she talks here, who is a bot, who is the same person). A pin does not stop a tier's stay lapse or the 10-item cap; she is told
   so. Which sections she pins, and the field's name, are hers. 4,800 hard stays.
   The other option, not taken: no pin. Simpler and consistent with the tiers; its cost is that the anchors she named
   (what this group is, how she talks here, who is a bot, who is the same person) surface rarely by nature and would
   fold first.
7. **Unchanged:** the person layer (4,000 characters, report only), the work log (not carried), count caps.
8. **The ADR-062 shadow pilot is closed.** Its floor and slot numbers are written into ADR-062; `SHADOW_PILOT` goes
   off (the tiers keep their item index, which starts with the tiers); turn rows older than 30 days are deleted by the
   retention thread; the pilot's docstring stops calling the collection harmless to drop. Decision 5's score comes from
   the manifest. Voice joins the item index, so a stored voice section is found by `recall` like any other.
9. **Persona wording leaves the core:** `self_review.EXCHANGES_NOTE`, `dice.HINTS['idle']` and `memory_tiers.TOLD`
   become persona-model keys with neutral `CORE_DEFAULTS` (the mechanism `people.familiarity` uses), set by her package,
   not her writable keys. `TOLD` says no pins today; her package text will say what is true after decision 6.

## 4. Her choices (she is told these are hers)

The wording of the room line, the tier line and the refusal; how she splits the 12,288 in each pair; which sections she
pins and what the field is called; the columns of `carried_counts` and how long within 30 days; how and when she trims
(no deadline from us); whether, when and how the "in effect" study runs (§5). Not hers: the ceiling and the per-pair
gate (the owner's discipline).

## 5. Cost, proof, readings

- Cost: no tool added. Write results grow by one line when a carried document changes; `things_from_program` by a
  coarse word when it changes; the manifest by about 1 KB a turn; `carried_counts` about 150 rows a day. The gate's
  work per write: five composes of carried text plus the self/core JSON per class, a few milliseconds. Prompt text
  changes only where the program now honours what she wrote: self/core `place:` tags (one section at home today) and the
  notes' fold order; `system_for` stops re-rendering a different prompt after a restart.
- Tests: every reader in §1 reads `carried()`; a section let go no longer counts; the per-pair gate refuses the case
  `largest` let through (home over, a group-only edit pushing the group over); a stored legacy `render.budget_tokens`
  does not bind; a rewrite that lifts a section is measured before it lands; `land` and `adopt_seed` are gated; the room
  line, the tier line and the refusal's pair; pins never fold and count; `carried_counts` matches a replay; voice is
  recallable; the three wordings come from the package. Existing tests that assert 6,144 change with it.
- Docs in the same commit: RUNTIME_API.md (`render.budget_tokens`, `max_window_share`, places, notes) and its packaged
  copy, docs/DEVELOPMENT.md, docs/map, the module docstrings. Her `asuna-render-budget-per-place` skill reads the old
  ruler: it is hers, she is told, it is not edited for her.
- Re-measured at install, with her check on her first writes: the room line is there, the five pairs and the gate give
  one number, a tier/`inject` difference is said.
- Later, outside this build: whether a carried rule was in effect in a reply, on her four bounds (2026-10-25): only her
  delivered lines; mechanical matching (line → rule → record id), never a characterisation; Claude and she first read
  the same 20 lines each and compare, no third agent; only a hit table goes back to her, the verdicts are hers.

## 6. Evidence

The study: `.runtime/private/context-study-1025/` (REPORT.md and seven scripts with outputs, about 120 KB, counts only).
The review's scripts (`combos.py`, `drift.py`, `pol.py`, `shadow.py`, counts only) are copied there as `review/`.
