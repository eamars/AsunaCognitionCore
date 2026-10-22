# ADR-091: What notes between her conversations cost, and three changes

Status: **Proposed**, 2026-10-22. D1 is a bug fix (Claude builds it on the owner's yes); D2 and D3 change ADR-018's
delivery table and are the owner's decisions. Written at the owner's request after the incident of ADR-090 ("for
incident 2, a full analysis from cost, effectiveness, cache miss impact and other use cases, based on the survey").

## 1. The question

In one group on 2026-10-22 (16:33–18:25 NZDT) six notes went from the group to home and six replies came back. Each
note opened a home turn; each reply opened a group turn told 「这里没有人说话」, and all six spoke in public (three
to nobody; three took in an @ of the owner's that arrived meanwhile). One reply was read in a turn the owner opened and
still opened its own turn. The owner called the exchange with home very inefficient. This ADR measures what notes cost
across their whole record and decides what to change.

How notes work today (ADR-018, ADR-087 §4.4, ADR-088): a `wake` note becomes a turn at the tail of the receiving
conversation's queue, a `next_time` note is shown in its next turn. Rule 1: nothing interrupts a running turn.
Rule 2: a note from outside to home is real time, always `wake`. A home turn opened by an outside note acts with the
outside class (ADR-088 §4.2), and a waiting outside note is not shown in other home turns (§4.4). A note and its
reply, no third hop.

## 2. The survey

By an independent agent, read-only, 2026-10-22: all 476 notes (10-07 12:09 to 10-22 18:42 NZDT; "7 days" is from
10-15 19:55) and all 304 turns they opened, found in the session files by their episode. Notes were classified by
structure only (direction, mode, hop, reply, state, `seen_in`, timing), never by text; from the session files only
event types, step ids, times and usage fields were read. The character brain runs on the local Strata model, which
reports no reasoning tokens, so reasoning cost is not measured. Evidence: §9.

## 3. Volume

| direction | notes | 7 days | mode |
|---|---|---|---|
| outside → home (local chat) | 118 (8 replies; 21 carry the owner's line) | 79 | all `wake` (rule 2) |
| home → group | 113 (69 replies) | 72 | 83 `next_time`, 30 `wake` |
| home → agent line | 97 | 56 | 68 `wake`, 29 `next_time` |
| other home lines → local chat | 90 | 34 | 49 `wake`, 41 `next_time` |
| home → peer line | 39 | 6 | 24 `wake`, 15 `next_time` |
| group errand turn → local chat | 11 | 11 | 7 `wake`, 4 `next_time` |
| home → owner's DM; outside → owner's chat | 7; 1 | 3; 1 | `wake` |
| outside → another group; home → someone's DM | 0 | 0 | — |

In all, 304 `wake` and 172 `next_time`; 148 replies; 2 expired (both `next_time` to an agent line); everything else
was read. `wake` notes per NZ day since 10-07: 7, 11, 4, 10, 26, 16, 10, 18, 18, 21, 17, 12, 25, 25, 34, 50. The
volume is rising.

## 4. Cost

Busy is model time (the sum of step durations); the base is the character brain's 42.9 busy hours and 223.9M new
input tokens over the record (17.2 h and 59.5M in the last 7 days). Cold: the turn's first step read under half its
prompt from cache; extra prefill is that step's new tokens above the warm median.

| turns opened by | turns | busy min | share of busy | new input (share) | cold | extra prefill |
|---|---|---|---|---|---|---|
| all notes, record | 304 | 192.6 | 7.5% | 17.67M (7.9%) | 101 | 14.95M |
| all notes, 7 days | 185 | 99.4 | **9.7%** | 8.29M (**13.9%**) | 46 | 6.62M |
| outside → home (rule 2), record | 118 | 72.0 | 2.8% | 7.65M (3.4%) | 43 | 6.62M |
| outside → home (rule 2), 7 days | 79 | 42.1 | 4.1% | 4.00M (6.7%) | 20 | 3.13M |
| home → agent line, 7 days | 48 | 23.4 | 2.3% | 1.82M (3.1%) | 9 | 1.50M |
| home → group (all), record | 30 | 16.7 | 0.6% | 0.81M | 9 | 0.72M |
| replies, record (the 54 measured apart; 3 peer and errand replies are not) | 54 | 24.4 | 0.9% | 0.82M | 3 | 0.53M |

- A note-opened turn is longer than a person-opened one: median 4 steps vs 3.2 at home, 5 vs 3.3 in groups; in a
  group about three times the wall time (31.8 s vs 10.9 s).
- Replies are cheap and almost never cold: they open right after the turn that sent the note, while that session is
  warm. The cost sits in first notes that land on an idle session: in rule 2's class 87% of all new input is cold
  prefill.

## 5. Cache

| idle gap since the session's last request | 0–5 min | 5–15 min | 15–30 min | 30–60 min | over 1 h |
|---|---|---|---|---|---|
| cold share, all character-brain turns | 8.8% | 30% | 46% | 70% | 95% |

- First-token wait: about 23 s cold, 2.5 s warm.
- **A note turn is not colder than a person's turn at the same idle gap** (0–60 s: 7.7% vs 3.5%; 5–15 min: 18% vs
  29%; over 1 h: 98% vs 96%). Note turns are colder overall (home 31% vs 25%) only because they land later: the median
  gap before a note-opened home turn is 351 s, before a person's 96 s.
- The 14.95M cold prefill tokens are gross: without the note the session would simply have stayed idle.
- After a note turn, the next person turn in the same session within 5 minutes was cold 17.7% of the time, against
  4.7% after a person's turn (11 cases; 6 had another session's requests in between). On the single-slot server a note
  turn evicts other sessions like any request, no more (5–15 min idle: 21% cold with nothing else run, 34% with other
  sessions, 37% with a note turn).

Cold starts follow where a turn lands on the idle-gap curve. No change to notes alone removes them.

## 6. Effectiveness

- **Outside → home turns (118):** 27 had a tool with consequences refused (`plan` 12, `delegate` 8, `write_document`
  8, `ask` 2, `set_policy` 1: the outside class), 25 only length or limit refusals, 66 none. 43 used only
  `think`, `note` or `stay_silent`; beyond that mostly the idea notebook (`ideas` 52, `note_idea` 12); `errand` ran
  twice (notes carrying the owner's line). 28 spoke in the local chat. In the incident, home could not do what the
  group asked (read a skill file, check the activation record) and answered from memory.
- **Replies to groups:** `next_time` replies (53) were read a median of 3 minutes later (longest 4.8 h), none expired,
  45 of 53 first by a turn a person opened. Where the mode was her choice (10-11 to 10-21) she chose `next_time` for
  39 of 42. `next_time` notes in general: median 0.2 h, p90 3.8 h, longest 14.6 h; 2 of 170 expired.
- **Reply-woken group turns since 10-14:** 16; 7 spoke, 9 stayed silent. The 6 outside-class replies of 10-22 all
  spoke.
- **Double answers:** 30 notes (9.9% of `wake` notes, 24 in 7 days) had already been shown in another finished turn
  there, a median of 0.6 min (at most 3.5 min) before their own turn ran; 7 of those second turns spoke (8 lines).
  10 of the 30 were outside → home under the old display, which ADR-088 §4.4 ended (last 10-22 00:43); about 20 in 15
  days remain under today's rules.
- **Refusals:** 237 (0.50 per sent note); 189 (80%) were followed by a note sent in the same turn. `NOTE_TOO_LONG`
  114 (112 retried): outside → home median 347 characters against 300 (p90 492), home → group 329 (p90 390), home →
  home 1,552 against 1,500. Every `NOTE_HOP_LIMIT` (23) and `NOTE_DAY_LIMIT` (4) ended the attempt, as intended.

## 7. Other uses the changes touch

`wake` outside → home 89 first notes; `wake` home → agent line 56; `next_time` home → group 53 replies and 30 first
notes; other home lines → local 90; `next_time` home → agent line 27 (2 expired); home → peer 39; notes carrying
the owner's line 21 (all in the last 7 days); `wake` home → group first notes 14 (2 to a group with no person line in
the previous 24 h); `wake` home → group replies 10 (+6 outside-class); questions 6; owner's chat 1; group → group 0.
ADR-018 §12 chose `wake` for home → group because a note to a resting group could expire unread: in the record 2 notes
went to a resting group, and no `next_time` note to a group ever expired.

## 8. Decisions

### D1: a note is answered once (bug fix)

A note-opened turn whose note was already shown in a finished turn there completes as seen, without a turn, the way an
absorbed line does (`coordinator._absorb`, `chat.py`). A home → group `wake` note is recorded as a visit: an absorbed
one gets its own outcome in `places.outcome` and is left out of `places.today`'s count. An outside note waiting at home
is never marked seen in other home turns, so D1 never skips its turn.

Saves 30 turns over the record (about 20 under today's rules), 10.2 busy minutes, 181k new and 27k output tokens, 8
lines said twice. Costs nothing measurable: the note had been read at most 3.5 minutes earlier.

### D2: a reply to a group arrives there next time (the owner's decision)

A reply from home to a note from a group is delivered `next_time` by default; `wake` stays her choice. Rule 2 is
untouched. `notes.prepare` must know a note is a reply before it fixes the mode. A turn that shows a reply cannot send
a note home in that turn (the hop limit).

Saves 16 turns, 6.4 busy minutes, 42k new and 22k output tokens, 0 cold starts (replies are warm anyway), 12 public
lines (5 with nobody there). Costs reading later: median 7.9 min, p90 34 min, longest 16 h; none would have gone
unread. It returns to what she chose herself 39 times in 42.

**Recommendation: yes.** The saving is small in tokens; what it removes is public speech to nobody, and the turns that
carried the incident forward.

### D3: rule 2, outside → home in real time (the owner's decision)

Rule 2 is the largest single class: 39% of note-opened turns, 4.1% of busy time and 6.7% of new input in the last 7
days, mostly cold prefill; 27 of its 118 turns met a refused action and 43 only thought or wrote a note. Options:

| option | what changes | saves (record) | costs |
|---|---|---|---|
| a. keep | nothing | — | 4.1% of busy, 6.7% of input (7 d), rising with volume |
| b. one turn per burst | outside notes to home within N minutes share one turn | N=10: 28 of 118 turns; N=30: 46 | real time becomes up to N minutes late; gaps between these notes: median 57 min, p25 10.7, p10 3.1 |
| c. let outside → home choose `next_time` | the waiting note is shown in her next home turn | up to 118 turns | reverses ADR-088 §4.4: outside text enters home turns that have home rights; the boundary is the owner's |

**Recommendation: a, keep, and read again on 10-29.** The value of rule 2 is that what happens outside reaches home at
once; b buys little until N is large enough to break that, and c moves the home/public boundary. The cost is real but
modest and mostly the server's cold prefill, which follows idle gaps, not notes. With D1 and D2 in place, read on
10-29: note-opened turns' share of busy time (7 days) and outside → home turns per day. If the share passes 12%, bring
rule 2 back with those numbers.

### Not changed

- The note length limits: 112 of 114 over-long notes were sent in the same turn after a cut, a median 16% over for
  outside → home. The refusal teaches; it costs one step.
- How much she writes and where to: her choices.
- The home turn's outside class (ADR-088 §4.2). What the group needed that day was its own facts and skills; ADR-090
  and her own skill publish put them in the group turn.

## 9. Evidence kept

`.runtime/private/notes-survey/` (124 KB): the survey's scripts (`parse_sessions.py`, `survey_db.py`,
`analyze.py`–`analyze4.py`) and results (`results.txt`, `results2.txt`, `results3.txt`, `results4.txt`; numbers and
masked ids only, no text). The derived data files of the run were not kept.
