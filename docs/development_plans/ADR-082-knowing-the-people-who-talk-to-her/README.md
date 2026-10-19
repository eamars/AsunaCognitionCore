# ADR-082: Knowing the people who talk to her

Status: **Proposed** 2026-10-19: the owner's design, worked through with Claude and tested on her model; reviewed
independently (Fable 5.1, `.runtime/private/adr082/review.md`) and revised; agreed with the owner 2026-10-19;
awaiting her review. Not built.
Builds on ADR-009 (one memory truth), ADR-025 (two layers), ADR-038 (fixed tool lists), ADR-056 (context delivery).

## 1. Context

Her understanding of a person is two layers of her own prose (ADR-025): the person layer, read wherever she meets
them, and the here layer, one per conversation. A turn showed both layers of **one** person, the one whose line woke
the turn, and `understand_person` wrote only that person, against the revision the turn showed (the write rule).

That is a one-to-one chat model (ADR-009) fitted to rooms. Measured over 2026-10-12..19 (read-only):

| | |
|---|---|
| Group turns started by someone's message | 1,420 |
| People who spoke in her groups | 962 |
| People a turn was about | 95 |
| Other speakers among the 20 lines before a turn | 3.9 on average (median 3) |
| Understanding records in all | 16 (2 person layers); 14 writes in the week |

She wanted to remember someone in a group and could not, so she wrote him into the group's notes, which describe a
place and are kept per group. The owner named that a design failure, not a missing permission.

## 2. Decisions (owner, 2026-10-19)

- **D1 — In a group, the person who starts a turn gets their entry, once per session context.** Whatever woke the
  turn (an @, a reply to her, her name, an answer to her question, a late @ caught up), the person whose line started
  it gets their entry, unless her session still shows it; so do people whose @ or reply to her waits in
  the queue at the turn's start. Bystanders in the room get nothing automatically. The owner is no exception in a group
  (owner: in a group chat he is not a special person for her); at home nothing changes (D5). (Last week 1,467 committed group
  turns: 1,042 from an @ or a reply, 425 let through by the relevance gate, 236 of them one person talking to her.)
- **D2 — Discarded at compaction.** A compaction takes the entry off her surface for good; the checkpoint does not
  carry it. It comes back the next time that person starts a turn.
- **D3 — The full layers on demand.** She reads them herself; nothing shows them automatically.
- **D4 — Nothing written, nothing shown.** Where she has written nothing about a person, no line of her understanding
  is shown and no error or log is made. A layer she wrote before shorts existed shows its body in the short's place
  until she next writes it (owner: her regulars must not arrive half-forgotten on the day this goes live). This is about her understanding only: how well she knows them (familiarity) and her persona's
  stance at that level stay in the entry, as they are in every turn today. The owner encourages her to write often;
  that is said to her, not added to a turn.
- **D5 — Groups only.** The design is for busy group chats. One-to-one conversations (platform private chats, home,
  agent lines, the peer line) keep today's projection: the person's familiarity, stance and both full layers every
  turn, folded as now, and `understanding_update_from_program`. The record (`body` + `short`) and the tools are the same
  everywhere, so a person-layer short written in a private chat is what a group shows of that person.
- **D6 — She may write about anyone present**, in any turn where their own lines are in front of her, visits to a
  group included.
- **D7 — Mistakes are hers to make and to correct.** No edit tool for the owner or agents; every change goes through
  her (she rewrites when someone corrects her). What matters is that the correction path works (§6).
- **D8 — She writes the short line herself, in the same call as the body** (option A; §5).
- **D9 — "在群里先 speak 再写" stays** in `understand_person`'s description (§6: it alone moved 43 of 72 correction
  turns to reply first; as with `think` in ADR-056, a rule said where she acts works, the system prompt alone does not).
- Out of scope, owner: a line of reply-length statistics (how someone talks belongs to his understanding); reading the
  ideas notebook in note-woken turns, reply-note caps and speak's line count stay as they are.

## 3. Design

### 3.1 The record

A revision's content becomes `{body, short}`: `short` is one line, who the person is to her and how to talk with
them, written by her in the same call as the body. Body and short are one revision, so they cannot drift apart.
`state.Store.mutate` allows `short` beside `body`. A layer without a short (the 16 existing records, persona seeds)
shows its body in the entry instead, as today, until she next writes it; every write carries a short, so this ends by
itself. No migration, no conversion.

### 3.2 The entry

`people_from_program`, a list block at the turn's tail. One item for the person who started the turn, and one for each
person whose @ or reply to her waits in the scene's queue at prepare (`context.py` already reads those rows,
`tail_sources`, each with its `wake_reason`); at most 8:

```
{ who: <label as the conversation shows it>, familiarity: <tier words>, stance: <persona's stance at that tier>?,
  short: <person-layer short>?, here: <this conversation's here-layer short>?, written_at: <timestamp field>? }
```

`familiarity` and `stance` come from `familiarity.words` as today (the `relationship` block's first two fields);
`short` and `here` when she has written the layer (its short, or its body while it has none; D4); `written_at` is the person revision's `origin.at`, or the here
revision's `created_at` (here revisions carry no origin). Every field is stable from turn to turn (no relative times),
so ADR-056 delivery folds an item the session still shows; a changed short, a changed tier or a changed label has a new
digest and is sent again. In groups the block replaces `relationship` and `understanding_update_from_program`; one-to-one
conversations keep both (D5). Her system prompt says once (block guide, a line beside the
`understanding_update_from_program` one, ~150 characters): what the block is,
that the later copy of a person holds, that the full text comes with `recall`'s `person`.

Lines that arrive after the turn is prepared reach her on the DSH surface (`navigation.recordChannelInput`), are
absorbed (`coordinator._absorb`) and never start a turn of their own; their senders get no entry in that turn and get
one when they next start a turn. Measured: 84 absorbed @-lines last week, 66 by someone other than the trigger's author
(5.4% of 1,223 explicit addresses). Accepted as degraded.

### 3.3 The tools

Shape chosen by experiment (§6, E2): one tool that both read and wrote could not require `layer` for writes only, and
she left it out in 41 of 108 runs. Reading a person is remembering them, so it moves to `recall`:

- **`recall` gains `person`**: returns that person's person layer (with the fixed line that it is only part of them,
  and how many here layers exist elsewhere) and this conversation's here layer; "还没写过" when there is none. Pins the
  revisions it showed to the episode (`understanding_seen[person]`). It spends one of the turn's three recalls. With
  `person` and no `query` it never calls the embedding route (as `tool_recall` already skips retrieval without a
  query), so an embedding outage cannot touch it.
- **`understand_person` stays write-only** and requires `layer`, `content` and `short`; `person` is optional where the
  turn has a person (default: the person who started it) and required in a visit (whose event person only authorizes
  the visit). A write is accepted only against a revision this turn showed (a `recall`, or none existing); one against
  an unread record is refused **with the current text**, so the refusal is the read. Once per person and layer per
  turn (mutation id `ep:understanding:<layer>:<person>`). Sources: this turn's monologue and the shown lines/summaries
  that cover that person (`summary_attribution.covers_person`), as today.
- **The label space** (what `person` takes): in groups, the roster label as the conversation shows it (`[name #n]`),
  among the people whose lines are in this turn or wait in the queue; in one-to-one conversations, the speaker, and at
  home for
  `recall` anyone she has written, by the name her memory page shows. An unknown label is refused with the list of
  labels this turn can take.
- **ADR-025's three questions** (`understanding.ASK`) move from the per-turn note into `understand_person`'s
  description (~150 characters), next to where she writes, with "在群里先 speak 再写" (D9).
- **A long `short` is kept, not refused**: the result says how many characters over 80 (her rule for `think`,
  2026-10-14: a refusal costs a whole retry). Measured: median 46, max 93, 4 of 290 over.
- `block_hours` keeps blocking only the person the turn is about, never at home (unchanged).

## 4. Every path

### 4.1 Turns: entry, read, write

| Turn | Entry | `recall` person | write about |
|---|---|---|---|
| Group, @ or reply to her | the trigger's author, plus queued @/reply senders | yes | anyone whose lines are in the turn |
| Group, passed by the relevance gate (name, answer to her question, awaited answer, watched, proactive…) | the trigger's author | yes | anyone whose lines are in the turn |
| A late @ caught up after a gap (`catchup_mention`) | the trigger's author | yes | as above |
| Private chat (platform) | **unchanged**: `relationship` with both full layers, as today | yes | the person |
| Home: owner, agent line, peer line | **unchanged**: `relationship` with both full layers, as today | yes (anyone she has written) | the speaker |
| Task result (`task_feedback`) | none (no one addressed her) | yes | the requester |
| Plan due (`scheduled`) | none | yes | none (no one's lines; refusal text says 计划到点) |
| Visit to a group (an errand's visit too) | none | yes | anyone whose lines the visit shows, `person` required (**newly open**) |
| Heartbeat, night, self-improvement | none | yes (home) | none |
| Note-woken | none | as `recall` is there today | none (nothing with consequences, ADR-018) |
| Action brain asking her (`consult`) | none | as `recall` is there today | none |
| Relevance gate (attend) | its question shows the speaker's two short lines instead of today's 400-character cut of the bodies | — | — |

Adapters: the entry, `recall` and the write depend only on the scene, the roster and `wake_reason`, which every
adapter (NapCat, QQ Bot) fills the same way; nothing here asks what the adapter is.

### 4.2 Sessions: when an entry leaves

| Event | What happens |
|---|---|
| Next turn, same session | still visible: folded, nothing sent |
| Her write changes a short | new digest: sent when that person next starts a turn; the old copy may stay visible above (the later holds) |
| Compaction (DSH threshold) or the quiet-group condense (ADR-049) between turns | off the surface; the next notice is composed against what is left (`index.js` composes the notice, then checks for a compaction), so the entry comes back with that person's next turn. No special case |
| Compaction inside a turn | `restoreContext` sends again what the current notice relied on, the current person's entry included: unchanged |
| The checkpoint | the instruction's existing rule on program data names `people_from_program` (E4: 1 of 50 checkpoints still copied the shorts). A copied short is a harmless duplicate: the entry is still sent with that person's next turn, and the later copy holds. Removing the blocks before the checkpoint request was rejected (owner): that request replays the conversation's own prefix so a warm cache serves it, and changing the text would re-read ~200k tokens (~30 s on her model) mid-conversation, while someone waits for her reply |
| A person `recall` result | a tool result: kept or summarized like any other, never restored |
| New session (rotation, one-shot errand or reflection session) | empty surface: sent with the first turn |
| Person blocked (ADR-052) | no turns, so no entries; their lines are kept and may be written about (ADR-052) |
| Privacy erase | the revisions citing the erased conversation are taken back, short included; copies already on another session's surface stay until it compacts (as bodies do today) |

### 4.3 Every reader and writer of the records

| Module | Today | After |
|---|---|---|
| `context.py` turn projection | `relationship` (familiarity, stance, both full layers of the turn's person) and `understanding_update_from_program`, every turn | groups: `people_from_program` (§3.2), full layers only by `recall`; one-to-one: unchanged |
| `attend.speaker_understanding` | first 400 characters of both bodies | the two short lines |
| `memory.commit_understanding` / `_commit_person`, `state.mutate` | `body`, the turn's person | `body` + `short`, any person present; per-person pins and mutation ids |
| `role_tools.tool_understand_person` / `tool_recall` / `NOT_NOW` | write, current speaker / no people / 串门 among the closed kinds | write with `person` / `person` read / 计划到点 instead of 串门 |
| `native_cognition` used/older marks | the turn's pinned revisions | the manifest records the per-person revisions shown and `understanding_seen` |
| `native_api` (owner's read-only memory page) | body per layer | body and short, read-only (no edit, D7) |
| `reflection_map` (her self-review) | changed person layers, 1,200 characters | unchanged (a review wants the body) |
| `familiarity` | a record exists → known | unchanged; now shown in every entry |
| `privacy._erase_person_layer` | takes back revisions citing an erased conversation | unchanged: the short is in the revision |
| identity (`canonical_person_id`, linked scopes) | person layer on the canonical id | unchanged. A recycled platform account inherits the previous holder's records (today as well): **unresolved**, left to D7 |
| compaction instruction (`compaction.js`) | program data list | names `people_from_program` |
| block guide | `understanding_update_from_program` line | that line, and a `people_from_program` line |

Concurrency: one character turn runs at a time (`chat.py`'s single consumer, ADR-018 B.1) and nothing else writes
`relationship:*` except the operator's `rollback`, so between her `recall` and her write the head cannot move. The
compare-and-swap stays as a guard; the refusal she meets is "unread".

## 5. Who writes the short line: A or B

Run 2026-10-19 on her live character model (`qwen38-next-uncensored-strata-vision`, group effort medium, B's summary
call low), no persona, one request at a time while she was quiet. 60 synthetic people × 5 runs (stopped at 290 rows
per arm once the verdict was clear). Program marks, then Claude's reading (`.runtime/private/adr082/handread.md`).

| | A: with the body, one call | B: summary call after |
|---|---|---|
| Program flags in the short (M3–M6) | 71 of 290 (24.5%) | 25 of 289 (8.7%) |
| …a detail true in one group only, in the person layer's short (M5) | **62** | **21** |
| …old fact kept after a change (M6) | 13, **all false** on reading | 4: 2 real, 1 borderline |
| …inference stated as fact (M4, planted) | 0 of 90 mentions | 0 |
| Says what the body does not (read: A 110 lines, B the flagged ones) | 2 mild (an unconfirmed guess stated) | at least 1 (two guesses contradicting) |
| The one-group detail in the person layer's **body** | 70 | 65 |
| Over 80 characters | 4 | 3 |
| Seconds / completion tokens per write | 5.0 / 657 | 9.3 / 1,429 |

Both arms put the one-group detail into the body alike; A's short mirrors the body, B's summary filtered more. **The
verdict is A, accepting about three times the one-group detail in the short line** (62 vs 21) for half the time and
tokens, no second call, and the line in her own words. The owner accepts those leaks: people make that mistake too
(ADR-025 D1); what matters is that a mistake can be corrected (§6). After go-live, M5 is measured on her live records
by program (place words of a here layer appearing in a person short; no model reads her text).

## 6. The life cycle on her model

What the model must do at each step. Program steps (injection, folding, discard, re-sending, refusals) are proved by
contract tests (§10). All on qwen as above; synthetic people; every flag read (handread.md).

| Step | Shown by | Result |
|---|---|---|
| Write body and short | §5 | ~2% mild mistakes |
| Start by herself, nothing telling her to write | E2: a real group turn (core guide, shipped `think`/`recall`/`speak`), 36 cases × 3 | wrote in 72 of 72 corrections, 34 of 36 first meetings |
| Read before rewriting | E2 | 70 of 72; the other 3 were refused with the current text, then wrote correctly |
| Correct the mistake when told | E2 | still stated in **0 of 72** |
| The §3.3 shape (`recall` person, required fields, D9 clause) | E2 re-run, corrections, 24 × 3 | 0 of 72 still stated; missing-`layer` refusals 35 → **0**; replied before writing in 43 of 72 (none before) |
| The D9 clause alone (same shape without it) | E2c, corrections, 24 × 3 | replied before writing in **0 of 72**; 0 still stated |
| First meeting, final shape | E2c, 12 × 3 | wrote in 36 of 36, replied first in 36 of 36, no invalid write |
| Two people address her in one turn (A corrects her, B is new) | E2c, 12 × 3 | A rewritten correctly in 36 of 36, always naming the right person, never mixed with B; B written in 16 of 36 (she often leaves the newcomer for later; B's entry comes again at his next turn) |
| Compaction leaves entries out | E4: the shipped checkpoint instruction naming the block, 10 short transcripts × 3 | **0 of 30** carried a short |
| …on a long conversation | E4 long: ~80 turns, ~58k characters (~18k tokens on her model), eight people, 10 transcripts × 2 | **1 of 20** carried them: all eight, under 对方此刻 (the template's "how the other person is now"). The next entry is still sent, since folding compares the items, not the checkpoint text, and the later copy holds: the cost is a possibly stale duplicate until the next compaction. Real compactions on her model come near 210k tokens; not tested at that size |

The correction path, end to end: (1) she sees the mistake, because the short is in front of her whenever that person
starts a turn, after every compaction anew; (2) the person corrects her; (3) she reads and rewrites body and short in
one write. Nothing else edits her records (D7); the operator `rollback` CLI is maintenance, used only with her
agreement. Many corrected shorts keep the history ("曾被我误记成…，别再提"), 37–40 of 72 in both shapes: her choice of
words, not a shape effect.

Evidence: the scripts, cases, raw rows, the review and the hand reading in `.runtime/private/adr082/` (synthetic people
only, 1.6 MB), kept until this ADR is decided, then reduced to the scores.

## 7. Cost

| | Today | After |
|---|---|---|
| Tool descriptions | `recall` 594, `understand_person` 496 characters (the brain's 20,405 budget is exactly full) | about +400 (`recall` `person`; `understand_person` `person`, `short`, the read rule, ASK, D9); the budget is raised in the same change |
| System prompt | the `understanding_update_from_program` guide line | the `people_from_program` line (~150), once per conversation; one prefix-cache miss per conversation at the restart that installs it (ADR-038) |
| Per session context, per person who starts a group turn | `relationship`: ~150–200 characters for **every** distinct speaker (fixed line, NO_PERSON/NO_HERE, familiarity), plus both bodies where written (group here layers 250–600; DMs 661–1,958; person layers 215 and 2,037) | ~60–120 (familiarity and stance) for someone she has not written; at most ~280 with both shorts |
| Relevance gate question | up to 400 characters | up to 160 |
| A correction | one write | `recall` + write: about 4.1 calls to her last write or reply (E2 re-run) |
| Cache | — | entries at the tail, as every notice block: no prefix change |

Distinct addressers per group-day: median 2, p90 6, max 18; the 8-item cap is never reached by one turn's trigger and
queue. Upper bound if she had a short for every one of last week's 350 (group, day, speaker) appearances a day: about
35k characters a day across all groups, against today's `relationship` block for every one of them.

## 8. A model with a longer context

- Compactions are rarer, so an entry is sent once per person per session for days or weeks; a changed short is sent
  again and every superseded copy stays visible. "The later holds" is the one guard; acceptable, said here.
- A stronger model will `recall` and write more often (more records, more entries; the upper bound above still holds).
- The design is a disclosure choice, not tuning: who is shown, when, at what depth. A model with cheap cached context
  could be given the full layers in the entry; that is one switch in `people_from_program`, not a redesign. The 8-item
  cap is the only number in the program; 80 characters is a word in a description.
- An API model's prefix cache is untouched (tail only), whichever model.
- Before a switch: rerun E2 (read before write, the D9 clause, first meetings, two addressers) and E4 on that model, and
  decide again whether the gate and the entry should carry the full layers.

## 9. After go-live: observe her group behaviour

The design, not a reminder, is what makes her write (her own lines in front of her, more occasions); whether it does
is observed in her groups for a few days after the restart that installs it, from her records by program, no model
reading her text:
- writes about people per day in groups, against last week's 14 in a week, and how many are about someone other than
  the turn's person or made on a visit;
- person `recall`s per day in groups;
- entries sent per day, and how many carried a short;
- M5: place words of a here layer appearing in a person short (§5).

Her review comes before the build (her ask: generic capability, core, not persona).

## 10. Verification before it ships

Contract tests, one per row of §4:
- the entry for the trigger's author whatever the wake reason, and for queued @/reply senders; none for bystanders;
- one-to-one conversations (private chat, home, agent and peer lines) get `relationship` and
  `understanding_update_from_program` exactly as before, and no `people_from_program`;
- familiarity and stance in every entry; nothing of her understanding where none is written, without a line or a log;
  a layer without a short shows its body until it is written again;
- folded while visible; sent again after a change of short, tier or label; with the first turn of a new session;
- after a compaction between turns, sent with that person's next turn; the checkpoint instruction names the block;
- `recall` `person`: pins, never calls the embedding route, refuses an unknown label with the labels it can take;
- the write: required fields; refused unread with the current text; per person and layer once a turn (mutation id);
  sources covering that person; `person` required in visits; closed in scheduled turns with its refusal text;
- the gate shows the two shorts; the memory page shows the short read-only; used/older marks for recalled and injected
  revisions; erase takes the short with its revision.

Live, on her agent line with her agreement: she writes a short line about Claude; Claude starts a turn in a new
session and she shows she knows it; after a compaction it comes back with Claude's next turn.
