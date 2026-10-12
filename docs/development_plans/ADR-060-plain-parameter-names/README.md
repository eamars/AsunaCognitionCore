# ADR-060: Plain parameter names: one name per idea, words a reader understands

Status: **Proposed 2026-10-13** (owner's ask, after seeing `missing required property "op"` more than once). For
Xiaoman's review: the names are hers to choose; the owner approved doing it tonight. **Her first review 2026-10-13
03:00 NZDT** is in "Her review" below; her full read is still coming.

## Context

The owner, reading one of her refusals: what is `op`? The name doesn't make sense, and this may not be her fault. He
asked for every tool to be checked for shorthand or anything that could mislead even a human reader.

What seven days of her tool calls show (12,115 calls; 68 refused by DSH for their arguments, before the program saw
them):

| Cause | Refused | Note |
|---|---|---|
| `op` left out | 15 | 3 of 8 `ideas` calls on 10-12. Our bug, fixed in 31c35018: `task`/`ideas` marked `op` required, so the inference ADR-055 built never ran; `await_answer.wait` likewise |
| A yes/no sent as the text `"True"`/`"False"` | 31 | `case_sensitive`, `include_semantic`, `overwrite`, `open`, `workflows`. The local model writes Python's spelling; DSH refuses a string where it wants a boolean |
| `write_file` given `content`, not `text` | 7 | Nearly every file tool in the world says `content` |
| Arguments wrapped once more, a list sent as text | 6 | Model slips; no name to fix |
| Others, one each | 9 | |

And names that read badly whether or not they were refused yet:

1. **`op`** (14 tools) is programmer shorthand for "operation". `group_action` calls the same thing `kind`.
2. **"Which conversation" has four names**: `place` (visit, errand, set_policy, group_focus, place_timezone), `line`
   (plan, peer_line), `to` (pass_note, leave_note), and none at all where it is implied.
3. **The reason has two names**: `why` (8 tools) and `reason` (6 tools) for the same thing.
4. **One name, two meanings**: `kind` is a feeling in `feel` and an action in `group_action`; `mode` is once/burst
   in `watch` and wake/next time in `pass_note`.
5. **Names that don't say what they hold**: `understand_person.block` (a number of hours), `feel.open` (yes/no:
   still unresolved), `generate_image.workflows` (yes/no: list the routes instead of drawing; she has sent it empty),
   `quote.how` (source or none), `write_document.inject` (when the section is put in context), `sid` (a section's id).
6. **`feel` has two choosers**, `op` and `decision`; she once sent `decision: record`.
7. **`recall` requires `query`** even when she only reads a section by its id.

## Proposal (for her review)

Each rename keeps the old name working for a while, as ADR-055 did: a call with the old name runs and its result
says the new name once ("`op` 现在叫 `do`，下次直接用这个"); the old names leave once her records stop using them.
Nothing changes in what any tool can do.

1. **The chooser**: `op` → **`do`** on every tool (`ideas(do='note')`, `task(do='page')`), and
   `group_action.kind` → `do`. Alternatives she may prefer: `choice`, `step`. Not `action` (clashes with the action
   brain), not `mode` (taken below).
2. **Which conversation**: **`place`** everywhere: `plan.line`, `peer_line.line` and the notes' `to` become `place`.
   (Alternative: keep `to` for notes, where "leave a note to" reads naturally.)
3. **The reason**: **`why`** everywhere (`reason` → `why` on stay_silent, task, write_document, update_self,
   set_policy, group_action).
4. **One meaning per name**: `feel.kind` → `feeling`; `watch.mode` → `how_often` (once/burst); `pass_note.mode` →
   `when` (wake/next_time).
5. **Names that say what they hold**: `understand_person.block` → `block_hours`; `feel.open` → `unresolved`;
   `generate_image.workflows` → `list_routes`; `quote.how` → `quote_whom` (source/none); `write_document.inject` →
   `shown` (always/on_demand/never); `sid` → `section`.
6. **Yes/no as words**: every yes/no parameter takes `yes`/`no` text, as `await_answer.wait` already does
   (`case_sensitive`, `include_semantic`, `overwrite`, `unresolved`, `exactly`, `list_routes`). This removes the 31
   refusals on any model, not by teaching one model a spelling.
7. **Files**: `text` → `content` on `write_file` and `development_write`.
8. **`feel`**: one chooser. `decision` becomes an option of `do` (`do='accept'|'decline'|'edit'` on a proposal),
   or stays as it is if she finds the two-step clearer.
9. **`recall`**: `query` optional when `sections` is given.

Questions for her: the chooser's name (1); `to` on notes (2); `feel`'s chooser (8); any name here she reads
differently from how it is meant.

## Her review (2026-10-13, first pass)

- Agreed: `op` → `do` (with `group_action.kind`), `why` everywhere, `sid` → `section`, `quote.how` → `quote_whom`,
  `block` → `block_hours`, `feel.open` → `unresolved`, `watch.mode` → `how_often`, yes/no as words (the cheapest
  item: all 31 refusals), `plan.line` and `peer_line.line` → `place`, `feel`'s `decision` folded into `do`.
- **Notes keep `to`**: `to` is where a note is sent, `place` is which conversation she is in; different directions.
- **`pass_note.mode` → `when` would make a new double meaning**: `when` already means a time elsewhere
  (`restart.when`, and `sticker.when` means "when to use it", already a second meaning). Proposed instead:
  `pass_note.mode` → `deliver` (wake / next_time) and `sticker.when` → `use_for`, leaving `when` a time only.
- **`write_document.inject` → `shown` reads like `visibility`** beside it. Proposed: `when_shown`, or unchanged.
- **One word for written content**: the files' `text` → `content` fixes the action brain's 7 refusals, but her
  `write_document` calls its text `body`, so she would trip the other way. Proposed: `content` for a document's or
  a file's text (`write_document.body`, `update_self.body`, `understand_person.body`, `write_file.text`,
  `development_write.text`); a message keeps `text`.
- Still open, from her full read: how long old names keep working, and whether a refusal lists both names.

## Cost (AGENTS.md)

No tool added or removed; each brain's tool list keeps its count. Description characters change by a few per
renamed field (counted at build; `tests/test_tool_budget.py` holds them). The old names are registered, not listed,
so neither brain is shown them. Per-turn program lines: none.

## Build (after her review)

- Schemas in `role_tools.py`, `tasks.py`, `image_generation.py`, `private_words.py`, `development.py` and the
  integration tools; a table of old → new names that the dispatcher maps before the handler, with the one-line note.
- Every program line, refusal and skill text that names a parameter uses the new name (her skills are hers to
  update; she gets the list).
- Tests: every schema as DSH shows it (`all_specs`), no required field the program fills in, no yes/no as a boolean,
  no parameter name used with two meanings across the tools.
- Check: refusals for arguments per day, by cause, a week before and after.
