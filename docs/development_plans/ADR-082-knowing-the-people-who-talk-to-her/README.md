# ADR-082: Knowing the people who talk to her

Status: **Proposed** 2026-10-19: the owner's design, worked through with Claude and tested on her model; under
independent review; then the owner's decision; then her review. Not built.
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

- **D1 — Short line on address, once per session context.** When a person explicitly addresses her, their short line
  enters her turn, unless her session still shows it. Explicit: an @ of her or a reply to her line in a group
  (`wake_reason` `mentioned_account` or `reply_to_character`), any line in a private chat, at home, on an agent line or
  on the peer line. A line the relevance gate let through (her name without an @, a proactive turn, someone she
  watches, an awaited answer…) injects nothing.
- **D2 — Discarded at compaction.** A compaction takes the entry off her surface for good: it is not restored, and the
  checkpoint does not carry it. It comes back the next time that person addresses her.
- **D3 — The full layers on demand.** She reads them herself; nothing shows them automatically.
- **D4 — Nothing written, nothing done.** No entry, no line, no error, no log. The owner encourages her to write often;
  that is said to her, not added to a turn.
- **D5 — One rule everywhere**: groups, private chats, home, agent and peer lines.
- **D6 — She may write about anyone present**, in any turn where their own lines are in front of her, visits to a
  group included.
- **D7 — Mistakes are hers to make and to correct.** No edit tool for the owner or agents; every change goes through
  her (she rewrites when someone corrects her). What matters is that the correction path works (§6).
- **D8 — She writes the short line herself, in the same call as the body** (option A; §5 measured it against a
  summary call, option B).
- Out of scope, owner: a line of reply-length statistics (how someone talks belongs to his understanding); reading the
  ideas notebook in note-woken turns, reply-note caps and speak's line count stay as they are.

## 3. Design

### 3.1 The record

A revision's content becomes `{body, short}`: `short` is one line, who the person is to her and how to talk with
them, written by her in the same call as the body. Body and short are one revision, so they cannot drift apart.
`state.Store.mutate` allows `short` beside `body`. Records without a short (the 16 existing ones, persona seeds) show
nothing (D4) until she next writes them; no migration.

### 3.2 The entry

`people_from_program`, a list block at the turn's tail, one item per person who addressed her among the turn's new
inputs (the trigger first, then absorbed lines in order; at most 8):

```
{ who: <label as the conversation shows it>, familiarity: <tier words>,
  short: <person-layer short>?, here: <this conversation's here-layer short>?, written_at: <timestamp field> }
```

An item without either short is not made (D4); a block without items is not sent. Every field is stable from turn to
turn (no relative times), so ADR-056 delivery folds an item the session still shows; a changed short has a new digest
and is sent again. Her system prompt says once (block guide, in place of today's `understanding_update_from_program`
line): what the block is, that the later copy of a person holds, that the full text comes with `recall`'s `person`.

### 3.3 The tools

Shape chosen by experiment (§6, E2): one tool that both read and wrote could not require `layer` for writes only, and
she left it out in 41 of 108 runs. Reading a person is remembering them, so it moves to `recall`:

- **`recall` gains `person`**: the label as shown in this conversation. It returns that person's person layer (with
  the fixed line that it is only part of them, and how many here layers exist elsewhere) and this conversation's here
  layer; "还没写过" when there is none. It pins the revisions it showed to the episode (`understanding_seen[person]`).
  The program resolves the label among the people whose lines are in this turn, and at home among those she has
  written, by their roster entry with its send time (ADR-029), never by guessing.
- **`understand_person` stays write-only** and requires `layer`, `content` and `short`; `person` is optional (default:
  the person the turn is about). A write is accepted only against a revision this turn showed (a `recall`, or none
  existing); one against an unread or moved record is refused **with the current text**, so the refusal is the read.
  Once per person and layer per turn. Sources: this turn's monologue and the shown lines/summaries that cover that
  person (`summary_attribution.covers_person`), as today.
- **A long `short` is kept, not refused**: the result says how many characters over 80. Her rule for `think`
  (2026-10-14): a refusal costs a whole retry. Measured lengths: median 46, max 93.
- **"在群里先 speak 再写"** in `understand_person`'s description (static text): open for the owner (§9).
- `block_hours` keeps blocking only the person the turn is about, never at home (unchanged).

## 4. Every path

### 4.1 Turns: entry, read, write

| Turn | Entry injected | `recall` person | write about |
|---|---|---|---|
| Group, @ or reply to her | the addresser, plus absorbed addressers | yes | addresser; anyone whose lines are in the turn |
| Group, passed by the relevance gate | none | yes | anyone whose lines are in the turn |
| Private chat (platform) | the person | yes | the person |
| Home: owner, agent line, peer line | the speaker | yes (anyone she has written) | the speaker |
| Task result (`task_feedback`) | none (no one addressed her) | yes | the requester |
| Plan due (`scheduled`) | none | yes | none (no one's lines) |
| Visit to a group (an errand's visit too) | none | yes | anyone whose lines the visit shows (**newly open**) |
| Heartbeat, night, self-improvement | none | yes (home) | none |
| Note-woken | none | as `recall` is there today | none (nothing with consequences, ADR-018) |
| Action brain asking her (`consult`) | none | as `recall` is there today | none |
| Relevance gate (attend) | its question shows the speaker's **short lines** instead of today's 400-character cut of the bodies | — | — |

Mid-turn lines: an @ absorbed into a running turn (`coordinator._absorb`) never starts its own turn; its sender gets
an entry only if the line was among the turn's inputs at its start. One that joins later has none in that turn and
comes at that person's next own address. Accepted as degraded. **To verify in review:** which absorbed lines a turn
lists at its start.

### 4.2 Sessions: when an entry leaves

| Event | What happens to entries and `recall` results |
|---|---|
| Next turn, same session | still visible: folded, nothing sent |
| Her write changes a short | new digest: sent at that person's next address; the old copy may stay visible above (the later holds) |
| Compaction (DSH threshold) and the quiet-group condense (ADR-049) | off the surface; `restoreContext` skips `people_from_program` and the person `recall` results; the checkpoint instruction's existing rule on program data names the block (E4) |
| New session (rotation, one-shot errand or reflection session) | empty surface: injected at the first address |
| Person blocked (ADR-052) | no turns, so no entries |

### 4.3 Every reader and writer of the records

| Module | Today | After |
|---|---|---|
| `context.py` turn projection | both full layers of the turn's person, every turn | `people_from_program` (§3.2); full layers only by `recall` |
| `attend.speaker_understanding` | first 400 characters of both bodies | the two short lines |
| `memory.commit_understanding` / `_commit_person`, `state.mutate` | `body`, the turn's person | `body` + `short`, any person present; per-person pins |
| `role_tools.tool_understand_person` / `tool_recall` | write, current speaker / no people | write with `person` / `person` read |
| `native_cognition` used/older marks | the turn's pinned revisions | also recalled and injected revisions |
| `native_api` (owner's read-only memory page) | body per layer | body and short, read-only (no edit, D7) |
| `reflection_map` (her self-review) | changed person layers, 1,200 characters | unchanged (a review wants the body) |
| `familiarity` | a record exists → known | unchanged |
| `privacy._erase_person_layer` | takes back revisions citing an erased conversation | unchanged: the short is in the revision |
| identity (`canonical_person_id`, linked scopes) | person layer on the canonical id | unchanged; recycled accounts resolved by send time (ADR-029) |
| compaction instruction (`compaction.js`) | program data list | names `people_from_program` |
| block guide | `understanding_update_from_program` line | `people_from_program` line |

## 5. Who writes the short line: A or B

Run 2026-10-19 on her live character model (`qwen38-next-uncensored-strata-vision`, group effort medium, B's summary
call low), no persona, one request at a time while she was quiet. 60 synthetic people × 5 runs (stopped at 290 rows
per arm, after the verdict was clear). Planted facts checked by program; every flag and 110 of A's other lines read by
Claude.

| | A: with the body, one call | B: summary call after |
|---|---|---|
| Real mistakes in the short | 2 in 110 read (an unconfirmed guess stated: 回成都了 → 成都人) | 3 (a correction lost twice, one muddled guess) |
| Inference stated as fact (planted) | 0 of 90 mentions | 0 |
| Old fact kept after a change | 0 (13 flags, all false) | 2 |
| Over 80 characters | 4 | 3 |
| Seconds per write | 5.0 | 9.3 |
| Completion tokens per write | 657 | 1,429 |

A detail true in one group only went into the person layer's **body** in about 60% of the cases that offered one,
alike in both arms (70 and 65 of ~117); A's short then carried it more often (62 vs 21). The owner accepts these:
people make that mistake too (ADR-025 D1); what matters is that a mistake can be corrected (§6). **Verdict: A.**

## 6. The life cycle on her model

What the model must do at each step, and what showed it. Program steps (injection, folding, discard, re-sending,
refusals) are verified by contract tests (§8).

| Step | Shown by | Result |
|---|---|---|
| Write body and short | §5 | ~2% mild mistakes |
| Start by herself, with nothing telling her to write | E2: a real group turn (core guide, shipped `think`/`recall`/`speak`), 36 cases × 3 | wrote in 72 of 72 corrections, 34 of 36 first meetings |
| Read before rewriting | E2 | 70 of 72; the other 3 refused with the current text, then wrote correctly |
| Correct the mistake when told | E2 | the mistake still stated in **0 of 72** (every flag read: each names it as corrected) |
| Same with the §3.3 shape (`recall` person, required fields, "先 speak 再写") | E2 re-run, corrections, 24 × 3 | 0 of 72 still stated; refusals for a missing `layer` 35 → **0**; tool calls per turn 6.1 → **4.75**; wrote before speaking 72 → 29 |
| Compaction leaves entries out | E4: the shipped checkpoint instruction naming the block, 10 transcripts × 3, each short with a fact said nowhere else | **0 of 30** checkpoints carried one |

The correction path, end to end: (1) she sees the mistake, because the short is in front of her whenever that
person addresses her, after every compaction anew; (2) the person corrects her; (3) she reads and rewrites body and
short in one write. Nothing else edits her records (D7); the operator `rollback` CLI is maintenance, used only with
her agreement.

Evidence: the scripts, cases and raw rows in `.runtime/private/adr082/` (synthetic people only, 1.2 MB), kept until
this ADR is decided, then reduced to the scores.

## 7. Cost

| | Today | After |
|---|---|---|
| Tool descriptions | — | about +250 characters (`recall` `person`; `understand_person` `person`, `short`, the read and order clauses); budget raised in the same change |
| Per session context, per person who addresses her | both full bodies (group here layers 250–600 characters; at home up to ~4,000) | one entry, at most ~200 characters |
| Relevance gate question | up to 400 characters | up to 160 |
| A correction | one write | `recall` + write: 4.75 tool calls per turn on her model |
| Cache | — | entries at the tail, append-only: no prefix change |

Upper bound measured: 350 (group, day, speaker) appearances a day; with a short for every one of them, about 35k
characters a day across all groups. With 16 records today it is near zero.

## 8. A model with a longer context

- Compactions are rarer, so entries live longer and are sent less often; an old copy beside a new one stays visible
  longer, which "the later holds" covers.
- The design is a disclosure choice, not tuning: who is shown, when, and at what depth. A stronger model with cheap
  cached context could be given the full layers on address; that is one switch in `people_from_program`, not a
  redesign. The 8-person cap is the only number in the program; 80 characters is a word in a description.
- An API model's prefix cache is untouched (tail only), whichever model.
- The experiments ran on today's local model only (owner); a model switch reruns E2 and E4 before it goes live.

## 9. Open for the owner

- "在群里先 speak 再写": with it, 29 of 72 correction turns still wrote first. It is a static clause, but a reminder
  in kind. Keep it, or accept a write before the reply (about 2–3 seconds more before her words go out).

## 10. Verification before it ships

- Contract tests per row of §4: entry only on explicit address; folded while visible; skipped silently without a
  short; not restored after compaction; re-sent after a change; `recall` pins; write refused with the current text;
  write about a present person with its sources; visit writes; the gate's short lines; the block named in the
  checkpoint instruction.
- Live, on her agent line with her agreement: she writes a short line about Claude; Claude addresses her in a new
  session and she shows she knows it; after a compaction it comes back on the next address.
- Her review of this ADR before it is built.
