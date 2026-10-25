# ADR-097: What she learned comes back when it comes up

Status: **Open: problem stated 2026-10-25, design not chosen.** The owner asked whether anything like `recall`
brings back a group's slang or something she learned recently at the right moment, and suspected the cycle from
writing it down to having it again is not closed. This record states the problem, how it fails today and what we want.
A deep dive of the whole save and recall cycle (a Fable 5.1 research session with Claude) comes next; then a design,
to her first, then the owner. Evidence: §6.

## 1. The broken invariant

What she wrote down about a place comes back when its subject comes up there again, without her having to remember
that she wrote it. Today that holds only while the item is carried (随身). Once it is at hand (手边), the way back
depends on a meaning match of one incoming message against a whole section, and the exact word that names the subject
cannot bring it back on its own.

People do not have this problem: her understanding of a person travels with that person into each turn they are in
(`relationship` in 84% of turns, `members` and `people` in groups, ADR-082). Things she learned have no such anchor.

## 2. The cycle today

| Stage | Where | What happens |
|---|---|---|
| Write | `write_document` to a group's notes (`group_admin`), a ledger, `self`, `core`, the journal; `promote_memory` | Her own words, in sections. A group's notes are facts (`memory_tiers.FACTS`) and readable only in that group. |
| Carry | `memory_tiers.Tiers`, `carried.py` (ADR-096) | Up to 10 sections per group's notes carried there (`CAPS`); over 2,400 characters they fold by last surfacing. She trims with `let_go`; a rewrite lifts a section back. |
| Come back by itself | `context.prepare` → `memory_tiers.deliver` → `memory_pilot.rank` / `admitted` | The turn's query is the incoming message (`event['text']`). An at-hand item is admitted only if its vector score, (1 + cosine) / 2, is at least `FLOOR` 0.83; at most 2 of the 6 memory slots. The lexical rank is fused into the order but never admits an item. |
| Come back when asked | `recall` (`role_tools.tool_recall`) | The same `deliver` with `recall=True` (put-away items too), the same floor; plus `headings`, which lists at-hand and put-away headings sharing at least two terms with the query; and `sections`, which reads a section she names. |
| Notice a miss | none | Nothing records that something she wrote was relevant and did not come back. |

Chat memories (chat chunks, summaries, her thoughts) take the other four slots by `retrieval.search`: vector and
lexical ranks fused, no absolute floor, forgetting by `memory.forgetting`.

## 3. What the records show (2026-10-25, counts only)

| Reading | Number |
|---|---|
| Group-notes sections | 161 in 18 groups (153 written in the last 14 days); per group 1 to 26 |
| Where they are | carried 60, at hand 99, put away 2 |
| How the at-hand ones got there | 77 moved down by her `let_go`; 30 written at hand; 7 lifted back by a rewrite |
| Not carried (101): ever brought up by a turn by itself | 14 |
| Not carried: ever returned by `recall` | 3 |
| Journal rows, for comparison: ever brought up by itself | 363 of 679 |
| `recall` in 14 days | 203 (home 94, the peer line 50, groups 59); 121 with a query |
| Recalls with a query that returned one of her own items | 3, all journal; group notes 0 |
| Automatic memory searches in 3 days: coverage `sufficient` | 1,422 of 1,422 (`memory.coverage_floor` 0, her package leaves it unset) |
| Of those, the lexical pool at its 4,096-unit cap | 805 |
| Active memory units | chat chunks 99,437; monologue 8,012; dialogue summaries 7,679; promoted 6 |
| Group-notes sections embedded whole / by their opening 400 characters | 156 / 5; length median 517, p90 1,279 |
| Turns since ADR-096's install (16:16) with one of her items brought up | 8 of 33 |

## 4. Failure modes

- **F1. Admission by meaning only.** A message that uses a term (a group's slang, a nickname, a coined word, a game's
  name) shares the word with her note about it, not its meaning; a whole message rarely scores 0.83 against a section
  that explains the term. The exact word is counted (lexical rank) but cannot admit. Journal rows, long narrative much
  like the talk itself, come back (53%); group notes, short facts, rarely do (14% of those not carried).
- **F2. One vector per section of several ideas.** Group-notes sections hold a few ideas each (median 517 characters).
  A term in the middle is a small part of the section's single vector. ADR-062 §1.1 already found that items of one idea
  retrieve better than sections of many.
- **F3. Asking does not reach them either.** `recall` uses the same floor, so a short query rarely admits a section; the
  headings path needs two shared terms with the heading, which a term in the body never gives. In 14 days her queries
  brought back a group-notes section 0 times; she finds one only by naming it.
- **F4. No miss is visible.** Chat chunks always fill the slots, so coverage is always `sufficient` and no recall comes
  back empty. Neither she nor we can count the times something she wrote was relevant and did not come.
- **F5. Her discipline feeds the hole.** ADR-096 and the group-notes limit ask her to keep what is carried small; she
  does (77 sections let go in two weeks). Each one she lets go depends on F1 to return, so the better she trims, the
  more she loses.
- **F6. Older chat by meaning only.** In 57% of automatic searches the lexical pool is the newest 4,096 units of the
  place, so a term explained in chat long ago, and never written down, comes back only by vector.

Not failures: a group's notes are not read in another group (state about a place stays with the place); a section she
carries is in front of her already. Not measured: real misses in conversation, which needs reading the talk and her
notes. Her own examples (a time she knows she should have remembered something) are the honest first test.

## 5. What we want

- **W1.** Something she wrote comes back when its subject comes up again in the place it belongs to, without her
  searching.
- **W2.** The exact word she chose for it (slang, a name, a coined term) is enough to bring it back; a meaning match
  stays a way in too.
- **W3.** Bounded: within her two own-item slots; no flood in visits, heartbeats or busy groups (ADR-062's pilot test).
- **W4.** One rule for both ways back: what a turn brings up by itself and what `recall` finds.
- **W5.** Visible to her, in words: what came back and how often, and what has not come back for a long time, so she
  decides what to keep, merge, carry or drop (more of the choices are hers, owner 2026-10-25).
- **W6.** A miss is countable from records, without reading anyone's words: for example a recall that returns an
  at-hand item the same turn's automatic pass did not bring.
- **W7.** No model call on the reply path; no conversion of her existing notes by the program; the core stays
  persona-agnostic; she writes through categorical choices the program maps.

## 6. Evidence and next

Scripts (counts only; no text, headings, queries or ids printed): `.runtime/private/recall-cycle-1025/`,
`recall_survey.py` (5,661 B), `recall_survey2.py` (1,852 B), `recall_survey3.py` (1,293 B).

Next: the deep dive with a Fable 5.1 research session (the whole cycle against the code and her real records, with
F1-F6 to confirm or refute); her examples of misses; then options with their costs, to her first. Ideas already on the
table, none decided: words she gives a section that bring it up when a message contains one (as character-chat
lorebooks do); one idea per item; letting a rare exact term admit; a lower floor for group notes (cheapest, but ADR-062's
floor table shows more items per turn, and it does nothing for F2-F4).
