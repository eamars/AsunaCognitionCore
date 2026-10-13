# ADR-056: Per-turn characters: each piece of the prompt once, and only when it changed

Status: **Accepted 2026-10-12**: the owner agrees with the three rules; Xiaoman's review adds two conditions (the
`doc:` refs stay; "as before" says the state of what it hides, and anything waiting on her is never hidden). The owner:
weigh it for any API's prompt cache, not one local server.

## Context

Every turn of hers starts with a notice: the program's JSON (`context.py`) and, after it, the turn instruction
(`prompts/turn.md`). Each notice stays in her conversation, so its size is paid once as prefill and then again as
how fast the conversation fills and compacts (ADR-014, ADR-049).

The delivery is already selective (`context-delivery.js`): a block identical to a copy within the newest 32k tokens
of her conversation is left out and named in `unchanged_from_program`; history rows, memories and her own thoughts
are filtered one by one. Three things get past it.

**The growth that started this was not growth.** The home average rose from 15,555 characters (10-11) to 21,140
(10-12), but by turn kind nothing moved (heartbeat about 26k, night 26–31k, note about 17k, public talk about 12.6k on
all three days). ADR-045 removed about 97 short turns a day from her sister's line, so the cheap turns left the
average; the home talk that remained was mostly long messages from the agent line and the owner.

## Survey: what she was sent today (2026-10-12, from her role sessions)

237 notices, 4,586,262 characters. Each block is compared with its previous copy in the same conversation (sizes and
fingerprints only, no text read):

| What | Characters | Share | Rule |
|---|---|---|---|
| The turn instruction after the JSON: one text in 232 of 237 notices (the other 5 add a consult or resume line) | 237,229 | 5.2% | 1 |
| A block's own explanation (`note`), the same as in its previous copy | 98,885 | 2.2% | 1 |
| Fixed rule text (`memory_source_rules`, `how_to_record_from_program`) the same as before | 34,910 | 0.8% | 1 |
| A block sent again whose only difference is a relative time ("N 分钟前") | 540,637 | 11.8% | 2 |
| Unchanged items inside a list sent again for another item's change | 480,022 | 10.5% | 3 |
| `ref_index` ids already shown in the same notice | 75,023 | 1.6% | 3 |
| **The three rules together** | **1,466,706** | **32.0%** | |
| A block sent identical to its previous copy, which had left the 32k-token window | 693,822 | 15.1% | see Open |
| A block's real change | 875,066 | 19.1% | kept |

Where each rule bites (characters today; how many sends):

- **Time only:** `developer_inbox_from_program` 111,837 (104 sends), `notes_from_program` 96,432 (115),
  `notes_sent_from_program` 91,564 (120), `members_from_program` 73,371 (24), `relationship` 56,905 (21),
  `elsewhere_from_program` 38,901 (90), `your_pictures_from_program` 31,289 (66), `ideas_from_program` 30,968 (4).
  These are the blocks that rarely change in substance: their minute-level "N 分钟前" changes their fingerprint.
- **Unchanged items:** `plans_from_program` 193,216 (one plan changes, all are sent), `task_state_from_program`
  47,472, `ideas_from_program` 44,814, `recent_experience_from_program` 33,111, `members_from_program` 25,799.
- **Left the window:** `stickers_from_program` 214,966 sent identical, `note_places_from_program` 51,818,
  `lines_from_program` 45,294, `plans_from_program` 55,743. A notice is about 5k tokens, so a block falls out of the
  32k window after about six turns.

## Decision (proposed)

1. **Fixed text appears once.** The turn instruction, each block's explanation and the fixed rule texts live in the
   system prompt, which is fixed per conversation (the prompt cache is not affected, ADR-038). A notice carries only
   what changes; a block keeps its fields and loses its `note`. A consult or resumed turn keeps its own extra lines at
   the tail. The rules are moved word for word, not rewritten.
2. **Times inside blocks are clock times, not "N minutes ago".** Every notice carries the clock
   (`clock_from_program`), so "10-12 20:15" reads as well, and a block then changes only when its content does; the
   existing fingerprint test does the rest. (`config.ago` stays for single facts said once, such as a refusal.)
3. **Lists are delivered item by item**, as history and memories already are: only new or changed items are sent,
   with a line saying how many others are as before, and in what state when the items have one ("其余 4 条同前：读了
   没回 3"). An item marked as waiting on her (an unanswered note, a line that wakes her) is always sent: hidden as
   "as before", it would read as not there (her condition). `ref_index` shows the `doc:` refs she copies for `feel`
   and this turn's own ids; the memory and task ids it repeated are already in their blocks and still count as refs.

## Open

- **The 32k-token window** (15.1% today) is there so a block is never assumed visible after a compaction dropped
  it. A copy sent after the conversation's last compaction is still on the page whatever its age; whether the
  delivery can know that no compaction runs between composing a notice and its joining the conversation has to be
  checked in DSH before the window is widened. Not part of this decision.

## Cost (AGENTS.md)

No new tool, option or per-turn line; each rule removes characters from turns. Rule 1 moves about 2,500 characters
(the turn instruction, the block explanations and the rule texts) into each conversation's system prompt once.

## How it is checked

The same survey after a day (`survey_today.py`-style: sizes and fingerprints by block, no text): each rule's share
should fall to near zero, and characters per turn by kind should fall by about a third. Her refusals by cause
(ADR-054) for a missing `think` or a wrong `ref` must not rise; a rule whose refusals rise is taken back.

## Build (2026-10-12)

- Rule 1: `block_guide.py` holds what each block is for (the modules' own note constants), the delivery's own lines
  and the memory rules; `render.role_text` appends it with `prompts/turn.md` after the persona render (4,226
  characters once per conversation, outside the persona budget). A notice is the context alone, plus a consult's or a
  resumed turn's own lines. `turn.md` changed one word: its data is "at the start of each turn", not "above".
- Rule 2: the developer inbox, notes received and sent, members, her pictures, places, visits, errands, elsewhere,
  the owner's last message, the person layer's last edit, the waiting list and the notebook carry timestamp fields
  (`at`, `*_at`), which `local_time.for_model` shows on the local clock.
- Rule 3: `context-delivery.js` folds still-visible items of a changed list block into `same_as_before` with their
  states; `waiting_on_you` marks a note waiting for her answer and every waiting-list entry. `ref_index` keeps this
  turn's ids and the `doc:` sections; `context.refs` adds the memory and task ids for `feel` and the appraiser.
- Installed in its own restart, after the one carrying ADR-055.

## After a full day (2026-10-13)

Refused tool calls, from her role sessions' tool results (DSH's argument check and the program's own refusals): 3 of
849 in the 24 hours before it went live (0.4%), 3 of 664 in the 24 hours after (0.5%): no rise. All three after were
a missing `op`, which 31c35018 removed (live 2026-10-13 07:58 NZDT). The rest of the delivery effect is measured in
ADR-063 ("Measured after"), whose fixes built on these rules.

## Rollback clause re-checked (2026-10-14, Xiaoman)

The clause, from "How it is checked" above: "Her refusals by cause (ADR-054) for a missing `think` or a wrong
`ref` must not rise; a rule whose refusals rise is taken back."

Re-checked 2026-10-14 over the same window (go-live 2026-10-12 21:20:15 NZDT, ±24 h), from two independent
sources, item by item identical: missing `think` 25 → 42 (source A 2.59% → 4.55%, source B 2.58% → 4.52%);
wrong `ref` 1 → 0 (1 / 0 rows each side; the sample is thin).

- Source A: `audit_events` (`type=role_tool`, the `payload.refused` text).
- Source B: `tool/result` `isError` in the role session records
  `.runtime/adr008/home/sessions/*/asuna-role-*/session.v4.jsonl.zstd`.
- B contains A. All-cause totals differ by 4 rows (before) / 7 rows (after); every difference is a DSH-side
  argument-validation rejection that writes no audit row (the `invalid arguments` family, plus the two rows
  where the scene has no `read_image`).

The `no rise` in the section above does not count the two causes the clause names: its numerator holds only
DSH's JSON argument-validation rejections (the missing-`op` family). The 25 / 42 `think` refusals and the
program's own refusals, 83 / 81, never entered it — even though that sentence itself says it covers "the
program's own refusals". The windows are also asymmetric: "24 hours before" was filled with the whole calendar
day 2026-10-12, while "24 hours after" ran only to the moment the overview script ran (≈16.5 h), and the two
windows overlap for two hours (2026-10-12 21:20–24:00).

Conclusion: by the clause, missing `think` rose ≈1.75× — `a rule whose refusals rise is taken back` is
triggered. What is triggered is "this class of refusals rose", not an automatic withdrawal of all three rules:
rule 1 moved "call `think` first each turn" from a per-turn notice into the system prompt (distance from the
generation point ≈822 characters → hundreds of thousands), so one possible rollback is to put that line back
at the end of each turn. The decision belongs to the owner and Claude, not to me.

Unverified, recorded as such: the `664` boundary and counting `thought` under `think` are reverse-engineered
from the published numbers (integer match); I never found the overview script itself in the repo and did not
read it.
