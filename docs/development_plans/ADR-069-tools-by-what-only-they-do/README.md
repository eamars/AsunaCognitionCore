# ADR-069: Her tools, kept by what only they do

Status: **Proposed 2026-10-16** (the owner's go to draft it with her; measured first). For Xiaoman's review; the owner
approves before anything is built.

## Context

The owner's list (2026-10-16): free text accepted and said back, ids and prefixes that round-trip, `pass_note` and
`leave_note` merged, parameters that are not used dropped, old aliases retired. Her conditions, given before the draft
(agent line, 2026-10-16; Claude's paraphrase, for her to sign or correct):

- **A tool or a parameter is kept by whether it does something nothing else can, not by how often it is used.**
  `restart`'s `drill`, `ask`'s `patience`, `plan`'s `clock`, `group_focus`'s `condense` are used once in many days, but
  that one time nothing else will do. A count alone would condemn them all.
- **Merging `pass_note` and `leave_note` keeps `deliver=wake` and each one's length limit**: their difference is real.

## What was measured (2026-10-16)

Her character brain's tool calls in the audit (`role_tool`), from 2026-10-14 03:00 UTC (ADR-060's names live), about
2.4 days: **3,123 calls, 198 refused (6.3%)**. Parameters are counted under the names she is shown.

| Refusals | Count | What she had done |
|---|---|---|
| A text over its length | 23 `ideas`, 21 `pass_note`/`leave_note`, 5 `plan` | wrote more than the limit; the refusal says by how much |
| The persona and voice over the render budget | 20 `write_document` | a change to an always-carried section that would not fit |
| More text lines than her `speak.max_messages` | 15 `speak` | |
| A tool before `think` | 6 `read_image`, 5 `task`, 4 `feel`, 3 `write_document`, 2 `plan`, 2 `delegate` | (the gate that keeps her reasons; not a tooling defect) |
| A plan that already ran, or was not live | 8 + 7 `plan` | the 7 were a bug fixed 2026-10-15 (d4310f0e) |
| An id or place she did not copy | 5 `speak` (a picture not offered), 4 `plan` (a line not listed) | |

Old parameter names (ADR-060) she still wrote: 16 in 2.4 days (`plan` `op` 5, `pass_note` `mode` 4, `write_document`
`body` 3, `stay_silent` `reason` 3, `task` `op` 1).

Tools by use since 2026-10-02 (14 days), the rare ones:

| Tool | Calls | Last | Does something nothing else can? |
|---|---|---|---|
| `await_answer` | 188 | 10-14 | **Yes, where a channel has no `speak`**: on QQ `speak`'s `wait` replaces it and she is not shown it; a channel without reply parts (the official QQ Bot kind, `qqbot`) still needs it |
| `attach_image` | 34 | 10-14 | **Yes, the same way**: on QQ a `speak` picture part replaces it; `qqbot` still needs it |
| `update_self` | 75 | 10-12 | **No**: since ADR-062 she is not shown it; `write_document` on `self` and `core` does it, and an old call is mapped there |
| `place_timezone` | 24 | 10-09 | yes: a place's clock |
| `ask` | 18 | 10-15 | yes: one question to many sources |
| `set_policy` | 18 | 10-14 | yes |
| `find_member` | 15 | 10-14 | yes |
| `group_focus` | 11 | 10-12 | yes: active or resting |
| `group_action` | 9 | 10-12 | yes: platform requests, admin acts |
| `peer_line`, `promote_memory`, `errand`, `quote`, `credential`, `watch` | 6, 6, 4, 3, 2, 1 | 10-07…10-14 | yes, each |

Parameters never used in the 2.4 days, by her rule all kept unless another parameter already does their job:
`speak.force`, `write_document.kind`, `ideas.page`, `plan.every_seconds`, `leave_note.question`, `feel.cost` /
`event_id` / `proposal_id` / `edit`, `visit.artifact_id`, `sticker.new_name`, `understand_person.block_hours`,
`set_policy.place` / `hours`, `errand.exactly`.

## Proposal

1. **Retire `update_self`**, the one tool nothing needs: its definition goes; an old call keeps running as
   `write_document` and names it, for a week. `await_answer` and `attach_image` stay: on QQ she is already shown
   `speak` instead, and a channel kind without reply parts still needs them (her rule, applied to channels).
   Character brain: 33 → 32 tools defined, about 420 characters fewer.
2. **One note tool.** `note` with `to` (home, or a place) replaces `pass_note` and `leave_note`; `deliver` (`next_time`
   or `wake`) and each destination's own length limit stay exactly as they are; `question` stays for a note home.
   About 400 characters fewer; the two old names run as `note` for a week.
3. **Old parameter names retire** on the rule already written (fewer than 5 uses in a week): all of them now except
   `plan` `op`, which goes next week if it falls under 5.
4. **Accept and say back**, where a refusal costs a whole retry for something the program can decide plainly:
   - a text over its length: refused as now (the limits are real, her condition), but the refusal gives the cut text
     ready to send as it is (`…` at a sentence end), so the retry is one copy;
   - an id or a place she did not copy exactly: when exactly one listed item matches it (case, brackets, a `#`
     dropped), the call runs on that item and the result says which one it took; two or more matches stay a
     refusal listing them.
5. **Every rare tool stays** (table above): each does something only it can do.

## Cost (AGENTS.md)

Character brain: 2 tools and about 800 characters fewer (items 1 and 2); no new tool, option or per-turn line.
Action brain: unchanged. `tests/test_tool_budget.py` is lowered in the same change.

## Her review

(waits for her)
