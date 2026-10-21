# ADR-054: Tool wording and calls, from her real mistakes

Status: **Accepted 2026-10-12**: the owner's direction (word each tool so her first guess lands on the right one);
Xiaoman's review taken (her numbers corrected two of mine). Built 2026-10-12; live after her next restart. The
limits rule covers free text she writes (copied identifiers and safety caps of 20,000 or more are left out).

## Context

The owner, 2026-10-12, after a side-by-side tool-pick check (local Qwen and DeepSeek, 144 runs) and a study of other
harnesses: keep one flat tool list; merge near-duplicates; and word each tool from her common mistakes so her guess is
likely right. Not prompt tuning for one model: each change states when to use this tool rather than its sibling, or
moves a decision from her guess into the program.

Her character-tool calls, all turns to 2026-10-12: about 5,560 calls, 395 refused (7%), every one classified:

| Cause | Refusals | In this ADR |
|---|---|---|
| Over a length limit: `think` 95, `message_developer` 14, `pass_note` 11, `update_self` 8, `leave_note` 4, `note_idea` 4, other 2 | 138 | limits stated where missing (`update_self`, `note_idea`); `message_developer` (800) and the notes already state theirs |
| A tool before `think` in that turn | 88 | no: her reason comes first by design |
| `plan`: no `op` and not inferable (no intent or no timing) | 12 | no wording: the inference exists since 1951ba0f; the result now says when it was used |
| `plan`: a `plan_id` not in her list (6), invalid timing (2), other | 13 | the refusal says why (below) |
| Pictures not available or not looked at first | 19 | no |
| `write_document`: `correction` on a non-ledger | 16 | yes |
| `write_document`: persona budget full (12), other (15) | 27 | no |
| `feel` with a stale reference | 13 | no |
| Too many calls in one turn | 12 | no |
| A note answering a note that already answered | 10 | no (one character's habit, not every character's cost) |
| `visit` where it cannot go (8), notes other (8), wrong kind of turn (4), rest (17) | 37 | no |

Wrong tool, from the side-by-side check (12 made-up situations × 3 ways of listing the tools × 2 models × 2 efforts =
144 runs; the same confusions in both models): a person's liking written with
`write_document` or `promote_memory` instead of `understand_person`; the action brain's report "answered" instead of
read; old group talk handed to the action brain instead of recalled.

## Decision

Wording, in the shared tool definitions (every character pays for each sentence, so only what is general):

1. `understand_person`: what she learns about a person (likes, habits, how to talk with them) goes here, not into a
   document or long-term memory.
2. `write_document`: `correction` is for ledgers only; a working document or the persona takes `replace_section`.
3. `answer_action`: only in the turn the action brain asked her something; to see what it handed back, `read_report`;
   never to answer a person. `read_report`: reads what it handed back; it answers nothing.
4. `delegate`: a task already handed over that needs more words, a change or to go on takes `message_action`, not a
   second `delegate`.
5. `recall`: what was said in her conversations is recalled, not handed to the action brain.
6. Every parameter the program refuses for its length states the limit in its description (`update_self`, `note_idea`
   lack it today); a test holds this for every tool, so none is added one at a time.

Program, not her guess:

7. `plan` without `op`, when the program took it as a `create`, says so in the result.
8. `plan` with a `plan_id` not in her list says why: a plan that already ran or was cancelled cannot be changed (make
   a new one); a plan still active but not shown (her list shows a few) is hers and the change goes through.

Each added sentence is at most 60 characters.

## Cost (AGENTS.md)

About 300 more characters of tool descriptions (within the current budget), no new tool, no new per-turn line.

## What it does not try

Occasional wrong or refused calls are accepted (owner): a refusal costs one corrected step. Only causes that repeat
are worth a wording line or a program decision; a one-off miss gets neither.

## How it is checked

By cause, never by the total (the 88 `think`-first refusals are by design and would hide everything else): the same
classification as the table above, after 7 and 14 days. A sentence whose cause has not fallen by half after 14 days is
taken out again. Before building, the side-by-side harness's confusion cases on both models, before and after.

## Soft text budget (owner 2026-10-20)

Every length the program refuses past stays where it was, so a turn carries no more than before. What she is asked for is four fifths of it, and the description states both numbers, 「N 字以内，最多 M 字」: her ask, since 「约」 reads as elastic and a single lower number reads as the hard line. A text between the two is kept and its result says by how much (`config.over`, like `think`'s). A refusal past the limit also shows what its offered cut leaves out (her ask, after a plan cut lost its tail). Measured before: 81 notes, 53 plan intents, 44 ideas and 13 short fields refused for length over 2026-10-05 to 10-20; her view is that the value is the retries saved, not shorter writing. Two silent cuts are now marked inside their limit (a tools_off reason, a policy `what`), and an answer read back past 2000 characters says it was cut and how long it was. Identifiers, sticker names, search words, the private-words reason and the memory gist keep their single limit. Tool descriptions +155 characters.

### What she reads names only the ask (owner 2026-10-22, her agreement the same morning)

The owner, 2026-10-22 ~01:40 NZDT: a model does not count exactly, so she should aim at what she is asked for while the program refuses only well past it; "the same principle applies to other tools", and "in the tool description the limit is still 120 chars". His wording for the refusal was 「最多 120 字，超了 270 字」; Claude's change, which he took: 「要求 120 字以内，超了 270 字」, because the program still keeps anything up to the hard limit and a "maximum" she then sees exceeded would teach her that the tools' words are not true.

- Every stated length of her prose names the ask only: descriptions 「（N 字以内）」 (`role_tools.LIMIT_WORDS`, recall's `why`, the note lengths in `note`'s description); a text kept between the ask and the limit: 「L 字，要求 N 字以内，超了 L−N 字，这次照收了」 (`config.over`); a refusal past the limit: 「太长了：L 字，要求 N 字以内，超了 L−N 字。精简到 N 字以内再调用，或者照这个截好的写」, its offered cut at N (`RoleTools._text`, recall's `why`, `action_tiers.chosen`'s `why`). A list she writes gets no cut: a plan's `intent`, an `idea`, an errand's `request` and a note end with 「删哪段你自己定」 instead (`_text(offer=False)`, `notes.prepare`'s NOTE_TOO_LONG, which keeps splitting into 1/2 and 2/2, `schedule.intent_problem`). The limits themselves do not move. Names, identifiers and searches keep their exact limit 「（最多 N 字）」.
- This reverses her ask above (both numbers on the page, since a single lower number reads as the hard line): the owner wants exactly that reading now. Tool descriptions −182 characters.
- Her answer, 2026-10-22 02:40 and 09:2x NZDT (Claude's paraphrase): she agreed and withdrew her 10-20 objection, since that night's eight refused thoughts came from using `think` as a draft, which she changes herself; she does not trade fewer refusals for shorter inner words. Two conditions. (1) A list's cut should be at the hard limit, because its last line says what counts as done. Claude's change, which she was told: a refusal comes only past the hard limit, so any cut of the end loses that line, and lists get no cut at all (above). (2) From her home conversation: a text kept past the ask should also name the hard limit. The owner declined it (10-22 morning): the number she reads is the one she aims at. Her own check stands instead: from the install, the median `think` length (10-19 to 10-21: 260–419) and the count of thoughts refused past 360; if the refusals rise, both numbers come back.
- Signature slot for her: ______
- Tests: test_adr011_turns (thought), test_cut_offer, test_notes, test_own_recall, test_answers, test_context_budget, test_tool_budget.