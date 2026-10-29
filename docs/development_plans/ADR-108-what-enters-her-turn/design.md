# ADR-108 design: the detail each decision needs to be built

The page is [README.md](README.md); this file holds the layers, the tables and the proofs. Every model-facing text
below is a draft (Chinese, 你, one language) for Xiaoman's reading. Code names and line numbers were read at
`5a196e66` (some at `fea9e355`); they move, and each is checked again when B0 lands, before a batch builds on it. *(Revision 2: there is no B0; the
builder checks each place before editing it, and §10 was read at `196b6f6`.)*

## 0. Held lines (D1)

`core.held` (`pairing.js`) is a Map in the Host's memory: conversation → the lines held there, each kept once by its
receipt.
- Created: a line that arrives while a step is open (D1; today while a tool call is open) or while a compaction runs.
- Used: written into the conversation, in arrival order, at the next `agent/pre-step` or `agent/turn-stopping`, or
  at `compaction/end` (`release`). B1 adds the release on a step whose request failed, if B0 shows the turn's end
  does not already release it. *(Revision 2, A5: the pinned source shows it does not: `agent/turn-stopping` is not
dispatched after a failed or aborted step; the release is at the `step/end` event, §10.5.)*
- Discarded: `release` deletes the entry. Its size is what arrives during one step in one conversation; it needs no
  cap of its own as long as every step ends in a release, which B1's tests hold.
- Across a restart: it is memory only, and nothing is lost with it. A held line's receipt is acknowledged only after
  the line is written and the conversation flushed (`index.js` `written`), so a stop while it is held leaves the
  receipt unacknowledged, and the worker projects it again at the next start.

Tested today in two halves: `tests/test_native_product.py::test_receipt_is_visible_before_processing_and_replayed_until_native_ack`
(an unacknowledged receipt is projected again at `navigation.ready`, an acknowledged one is not) and, in
`packages/cognition-core/test/navigation.test.js`, the test 'native continuation preserves history and task children
retain their actual execution directory' (a line is held while a compaction runs, a receipt projected again while
held is held once, and it is acknowledged only once written). No test joins the halves; B1 adds one: a stop while a
line is held, then a start, and the line is in the conversation once.
*(Revision 2, A1: `tests/test_native_product.py` was deleted with ADR-104's finish, so the first half no longer
exists; §10.1 replaces this paragraph's tests.)*

Absorbing (README D1): `_absorb` (`coordinator.py:346-356`) marks a line seen during a turn as handled there. From B1
it does so only when the turn has `speak` in that conversation; otherwise the line keeps its own turn.

## 1. The check pipeline (D4b)

### 1.1 Where a call is checked today, and where it moves

DSH runs a call's stages in this order (`dsh-tools` `prepareExecution`): `tools/pre-execute` (async waterfall; ours
asks the worker `session`, `index.js:1232-1245`), then the guards (synchronous: a returned string denies; ours at
`index.js:1217-1231`), then dispatch to the tool's `execute`. `defineTool` wraps `execute` so that DSH's
`validateArgs` runs first and throws `ToolArgsError` (`invalid arguments: …`) on a violation.

| Today | After |
|---|---|
| guard: not in this conversation → refused | unchanged (layer 0; it is synchronous and cannot ask the worker) |
| guard: schema (`argsRefusal`, `tool-args.js`, against the strict declared schema) → refused alone, every violation named, Chinese with DSH's words in brackets, no audit row | kept in layer 0; through B3 against the strict schema, from B4 against the permissive declared one *(Revision 2: one install, so the declared one throughout; §10.6)* |
| `defineTool` wrapper: DSH's own validation against the declared schema, English (`invalid arguments: …`); not reached after the guard (0 on her character brain since 2026-10-18 UTC, §9) | unchanged; the guard checks the same declared schema first, so it stays unreached |
| `execute` → worker `role_tool` | `execute`: repair a copy (§4), `validateArgs` on the copy against the strict schema the program keeps, then worker `role_tool` with `args` (repaired), `given` (as she wrote it, for the record) and `violations` |
| worker `RoleTools.call`: first failure raises | worker: layers 1-5 below; one `Refused` whose record keeps every code |

Two schemas per tool: the strict one (today's specs, kept in the program beside the repair table and shipped with
`role_tool_specs` for `execute`) and the declared one derived from it by the repair table (fields the table can fill
lose `required`; fields the table parses are declared `json`; enums are left out, their values in the field's
description; types stay). One source, so the two cannot
drift; a test holds that every field the declared schema relaxes has a repair entry and a description stating the
strict form. R3 (a supported normalize hook in DSH) would let them be one schema; nothing waits on it.

### 1.2 The layers

| Layer | Checks (today's site) | Collected? | Why it stands where it does |
|---|---|---|---|
| 0 | tool in this conversation (guard); the declared schema (guard, every violation in one text); args an object; call id not reused; tool exists; retired old name (`role_tools.py:1367-1383`) | stops alone; the guard's two have no audit row and are counted from session files by wording | nothing else is defined without a tool and an object that its declared schema accepts |
| 1 | shape repair (§4), `param_names.inbound`, `infer_op`, ADR-098 `written` | n/a (no refusal) | every later check reads the repaired call |
| 2 | usable in this turn (`not_now`), home authority (`OUTSIDE_NEEDS_HOME`), place rules that decide the tool, not its arguments (`DOC_WRITE_REQUIRES_OWNER_PRIVATE`, `GROUP_NOTES_ONLY_IN_ITS_GROUP`) | stops alone, with `INSTEAD` (§2.3) | the fix is another tool or another turn; argument problems beside it lead to a corrected call refused again |
| 3 | schema violations after repair (from `execute`); THINK_FIRST (`role_tools.py:1393-1395`); call cap (`1396-1400`); each text field (`_text`); enums by hand (`_given`); empty fields; field pairs (feel `who` for kind, `pin` outside group notes, `op` validity) | all collected | none depends on another passing; a field that fails here is skipped in layer 4 |
| 4a | state, per field that passed 3: document and section (`named_section`, `missing_section`), feel `ref` (`affect.check`, today inside `ledger.record`), labels (`understanding.resolve`, `watch`), plan id listed, schedule spec, D2 line anchor, sticker refs, task ids | collected across fields | each needs its own field valid, none needs another |
| 4b | on the write's result: carried budget (`carried.py:300-311`, today inside `docs.apply`), group-note size (`context_budget.py:160-170`), signing and gist (`memory_tiers.signing`, `gist_refusal`) | collected among themselves; run only when 3 and 4a passed for their inputs | each needs the target found and the body valid |
| 5 | the effect, and what only the effect can find (a revision race, a store fault, `DocumentError` from the store) | one refusal | it happened, or it did not |

THINK_FIRST is collected, not stopping: she thinks and sends the same call again, so the other problems are what
that call needs. The 24th call is refused with its warning whatever else is wrong (ADR-084), and the warning is one
item of the list.

### 1.3 Splitting a handler

A handler collects only once it is split: its check part reads, appends problems to `self.problems` (`_text`,
`_given` and the state checks append instead of raising while `self.collecting` is set), and ends at
`self.checkpoint()`, which raises the combined refusal when there are problems or when the call is a check only
(layer-3 problems from `execute`). The effect part follows `checkpoint()`. A handler not in the split set raises at
its first failure, as today, and is never run in collecting mode: collecting without a checkpoint before the first
effect would let an invalid call write.

The split set, in build order (character failures by tool from the structural survey, top classes only):

| Tool | Failures named in the survey | Checks to move ahead of the effect |
|---|---|---|
| write_document | THINK_FIRST 87, schema 72, persona over budget 118, op not allowed 42, section not found 30, owner-private 27, note over limit 32 | budget measured on the would-be document before `docs.apply`; doc inference (§4) |
| plan | THINK_FIRST 43, too long 98, schedule spec 49, already done 48, op 32, not in scope 28, id not listed 26 | schedule spec and id with the length |
| think | too long 102 + 128 | none (one field) |
| note | too long 122, undeliverable 67, turn scope, copies others 38, reply ends 17 | deliverability with length |
| feel | schema 13, ref not in index 86, who 38 | `affect.check` before `ledger.record` |
| delegate | THINK_FIRST 74, schema 10, turn scope 25 | title derivation (§4) |
| speak | not sent 151, schema 17 | already collects every part (`role_tools.py:1830-1936`); joins the layers |
| ideas | too long 52, not this turn 27 | |
| task | THINK_FIRST 63 | |

### 1.4 The combined refusal

Form (the codes stay in the record, `WORDS[code]` and the detail reach her, DEVELOPMENT.md "Writing tool errors"):

```
这次调用有 3 处要改，改好一起再调用一次：
1. 先调用 think 写心里话。
2. thought 太长了：……（§2.1）
3. section「…」在 persona 里没有；persona 里有的是：……
```

With one problem the numbering goes and the sentence stands alone. The record: `refused` (the text), `codes` (every
code, in order), `layer` (where it stopped), `repairs` (§4 entries applied).

Length: no problem is ever dropped; each field or part gives at most one problem per layer, so the list is bounded
by the tool's fields and speak's parts. When the text passes `REFUSAL_LONG = 1500` characters, each candidate list
(§2.2) keeps its first three and ends 「还有 N 个」; if it is still longer, it stays as it is.

Best effort, as a mechanism: the problems are those of the layers that ran, up to the one that stopped; a field that
failed in layer 3 is not checked in layer 4, so its layer-4 problem, if any, comes with the next call.

## 2. Refusal texts (D4c)

### 2.1 Lengths

| Case | Text |
|---|---|
| description, her prose | 「（N 字以内，过了 M 字不收）」 (`LIMIT_WORDS`) |
| description, exact | 「（最多 N 字）」 (`EXACT_WORDS`, unchanged) |
| kept between N and M | 「<字段> L 字，要求 N 字以内，多了 K 字；过了 M 字不收」 (`config.over`) |
| refused past M, prose | 「<字段> 太长了：L 字，过了 M 字的线 J 字（要求 N 字以内）。<为什么有这条线>。精简到 N 字以内再调用；M 字之后起是超出部分。」 |
| refused past M, a list (plan intent, idea, errand request, note) | the same, ending 「删哪段你自己定；M 字之后起是超出部分，落在第 s 行（共 t 行）」 |
| refused past a safety cap | 「<字段> 太长了：L 字，最多 M 字。」 and what to do (a brief split into a follow-up `task` message) |

The place is given in characters; no sentence is counted. A line (s of t) counts the field's lines as split on
`\n`, after the trailing blank lines are removed. Nothing of her text is shown.

`<为什么有这条线>` comes from one table per field (`LIMIT_WHY`, versioned). Its phrases are written at build from the
code that carries each text, and each is checked against that code. The one the code states today: think, 心里话会存档：
这个对话里最近三段，下一回合一定看得到 (the `think` description). Shape: 「这一项……，所以有这条线」.

### 2.2 Candidates

A refusal that names a wrong value lists what would pass, from the same predicate that refused:

| Check | Accepting predicate | Listed |
|---|---|---|
| label in a group (`understanding.resolve`, `watch`) | `people.resolve(scene, text)` filtered to the turn's people | the labels of the people that predicate accepts, by one function used for both; today the list is built with `people.speaker` / `ensure_roster` |
| feel `ref` | `affect.check` against `ref_index` | up to 12 (`config.refs_usable`), newest first |
| section | `named_section` on that document | its section ids; with no `doc` given, `文档#section` for each writable document holding that name |
| plan id | the plans she may change here | their ids and intents' first words (program text: the plan's own title) |
| line anchor | `People.line_of` | the last few lines in pointer form (as `line_of` does now) |

### 2.3 What does the job here (`INSTEAD`)

One table, ability → alternatives in order, each with the words of what it does; a permission refusal adds the first
alternatives that are in the turn's tools: 「这一回合能做这件事的是：<工具>（<它做什么>）」, and when none is, when
the refused one can be used (the existing `NOT_NOW` text). Entries come from what the code already says: `task.answer`
→ `task.message`; `task.message` → `delegate`; `attach_image` → `delegate` (draw first); `errand` → `visit`; `visit` →
`plan`; home-authority writes in an outside-note turn → saying it here (`OUTSIDE_NEEDS_HOME`); a home document in a
group → `write_document` with `group_notes`. A test holds that every entry names an ability that exists.

## 3. Limits, field by field (D4a)

| Field | Today: stated / refused past | Kind | After: description |
|---|---|---|---|
| think `thought` | 120 / 360 | prose | （120 字以内，过了 360 字不收） |
| plan `intent` | 800 / 1,000 (no cut) | prose, list | （800 字以内，过了 1000 字不收） |
| ideas `idea`, `why` | 400 / 500 | prose, list | （400 字以内，过了 500 字不收） |
| note `text` | 240 / 300 outside, 1,200 / 1,500 home to home | prose, list | both pairs, as the description has them now |
| ask `question`, `took`; recall `query`; stay_silent `reason`; set_policy `reason`; restart `why`; await_answer `why`; attach_image `why` | ask at four fifths / line at the limit | prose | aim and line |
| delegate `title` | 64 / 80 | exact | （最多 80 字）; derived when missing (§4) |
| write_document `why` | none stated / 2,000, no soft band | prose | （1600 字以内，过了 2000 字不收）; what is accepted does not change |
| feel `why` | none stated / 500 or 300 | prose | aim and line, per form |
| understand_person `short` | stated / guard only | prose | as it is, with its line |
| delegate `brief`; task `message`, `answer` | none stated / 20,000 | safety cap | not stated; no soft band |
| write_document `content` | none / 1 MiB per revision and the budgets | budget | the budget's room as ADR-096 shows it |
| calls per turn, speak lines | 9 / 24, hers (3) / 6, in results | count | unchanged (ADR-084 step 7) |

## 4. Shape repairs (D4d)

This table is the one list of the shapes; the page's finding 4 and D4d point here. Applied to a copy in `execute`
(layer 1) and recorded in the call's `repairs`; the worker applies the same table, so both layers read one call. The
table is data in `role_tools.py`, shipped with `role_tool_specs`.

The counts are of the guard's 101 schema refusals in UTC days 2026-10-18 to 2026-10-28 (her character preset, home
and archive sessions, one per call id; `q10`, §9), counted by field and kind of violation from DSH's own words that
the guard quotes. One refusal can name several violations, so the counts add up to 106, not 101. An earlier count
of these shapes (30, 16, 21, 8, 6, 7, 9, 4, 3) did not keep its rule, so it is replaced, not reconciled. The words
name the field, not what she wrote instead, so the two `parts` item rows share one count and the note row counts
missing fields.

| Shape she writes (violations, by the count above) | Repair | Said in the result |
|---|---|---|
| write_document without `doc` (22) | the one writable document here with a section of that name; in a group outside an errand, `group_notes`; else no repair, a layer-4a problem with the candidates | 「没写 doc：按 section 当作 <doc> 写了」 |
| write_document without `do` (16) | by fields: `heading` and no `section` → `append_section`; `section` and `content` → `replace_section`; `section` with only `tags` / `visibility` / `when_shown` → `set_tags`; anything else no repair | the existing 「没写 do：按你写的字段当作 X 办了。」 |
| write_document `from` outside the enum (15) | none; with D2 she writes `line` instead of 别人说的 / 主人定的 | n/a |
| speak `parts` as a string holding a JSON list (9: `parts` of the wrong type) | parsed | nothing (format only) |
| speak part without `kind` (with the next row: an undeclared key 6, a value outside an enum 3, a missing field 2) | the kind whose one field it has (`text`, `name` → sticker, `who` → poke, `face` → react); `artifact_id` alone is picture or file and stays a problem | nothing |
| speak part key that is speak's own (`quote`, `wait`) (counted with the row above) | lifted to the call when the call has none | nothing |
| delegate without `title` (8) | the brief's first sentence cut to 64 at a sentence end | 「没写 title：用了 brief 的第一句：<title>」 (program-made title, not her prose echoed in a refusal) |
| note `note` for `text`, `place` for `to` (missing `text` 4, missing `to` 3; whether `note` or `place` was written instead is not in the words) | renamed *(dropped, Revision 2, A8)* | nothing |

The other violations in the same 101: enum values (write_document `kind` 5, `nature` 2, ideas `decision` 2, visit
`intent` 1), which move to layer 3 with B4, and missing fields the program cannot infer (write_document `why` 2,
private_words `do` 2, promote_memory `why` 2, think `thought` 2), which stay refused at layer 0.

In the declared schema (what DSH validates and the model reads) `required` is dropped for `doc`, `do`, delegate
`title` and a part's `kind`, `parts` is declared `json` so a list written as a string passes DSH's validation and
reaches `execute`, and no field declares an enum (each enum field's description lists its values). The strict
schema inside the program keeps them required and `parts` a list of objects, and
`execute` validates the repaired copy against it. Each relaxed field's description states the strict form and what
the program uses when the field is missing, because the model reads only the declared schema. This change is a spec
change: it rides on B4's one cold request.

## 5. Marks and wake words (D3, D5)

### 5.1 Source marks, `MARKS_VERSION = 1`

| Message | First line |
|---|---|
| stage notice, restore notice (`index.js` `message`, `restored`) | 〔程序〕 |
| repair notice (unsent text, speech problems, missing thought: `coordinator.py` REPAIR) | 〔程序〕 |
| checkpoint body (prepended by `RoleCompactionEngine.summarize`, after the section check) | 〔摘要〕下面是压缩器把这个对话较早的一段整理成的检查点：条目末尾的〔编号〕是它出自的那一行，没有编号的是压缩器的转述。 |
| a person's line | its label line (`People.transcript`), unchanged |
| a platform notice inside a line (someone recalled a message, and the like) | its label line, then `notices.MARK` 「（平台通知）」, unchanged: a line the platform relayed, not a message Asuna wrote |

Each mark is the message's own first line, followed by a line break; a stage notice's JSON body (`index.js:812`)
starts on the second line. B0 runs a real stage notice, mark included, through every reader of a notice's text and
records which of them reads past the first line. *(Revision 2, A4: the readers were read in the code and none parses
the text, so nothing needs to run this; §10.4.)*

### 5.2 `woken_by_program`, `WAKE_VERSION = 1`

| Episode kind | Words |
|---|---|
| task_feedback | 你交给行动脑的事交回了结果；event 里是行动脑写的 |
| consult | 行动脑做事时有话问你；event 里是行动脑写的 |
| scheduled | 你自己定的计划到点了 |
| visit | 你自己出门来这里看看 |
| presence | 心跳到了 |
| self_development | 自我改进的时候到了 |
| settlement | 夜里的沉淀 |
| note | 你在<地方>写的便条到了 |

`external` (a person's line) keeps `speaker`. The block is in the notice, so it is new suffix; `_from_program` is
already explained in turn.md.

## 6. Line anchors (D2)

Resolution, in order: `line` given → `People.line_of(scene, episode, line)`; no row → recorded as 我自己的判断, the
result says 「〔n〕 不是这里的一行」 with the recent lines (as `line_of` lists them); a program row → the same, 「程序的行
不算谁说的」; the owner's row → `from` 主人定的; another person's → 别人说的; her own row → 我自己的判断. A `from` she
gave that differs from the line's author is replaced by the line's, and the result says so. The item stores `line:
{scene, scene_seq, author}`; wherever the item is shown (carried sections, recall, the night list), its source shows
in the pointer form (number, speaker, time), without the line's words. *(Revision 2, A7: no `author` is stored, and
the pointer form is for the anchor's own conversation only; §10.7.)*

Results: 「记成 <from>，出自 <pointer>」, or 「记成你自己的判断：没有指到哪一行；要记成他说的，用 replace_section 加 line」.

`capabilities.numbered` becomes true for every scene whose lines have a `scene_seq`; `speak_spec` keeps `quote` only
where `carries(…, 'quote')`.

## 7. The compaction instruction (D2)

Rules added to `ROLE_COMPACTION_INSTRUCTION` (drafts; the summarizer is not her and writes of 角色 in the third person
as today):

- 写谁说了、定了、答应了或更正了什么的条目，末尾写它出自的那一行的〔编号〕，照抄那一行标签行末尾的编号；说不出出自哪一行的，写成「（转述）」。
- 合并时，旧检查点条目的〔编号〕原样带过来。
- The existing 「（凭：谁在什么时候说的或做的那一句）」 becomes 「（凭〔编号〕）」.

The instruction is the last user message of the compaction request, so the change leaves the summary request's
prefix as it is.

## 8. Proofs, per batch

All counts are structure only: event types, seqs, times, codes, lengths. No text is read out.

| Batch | Count | Source |
|---|---|---|
| B0 | yes/no per fact, on the demo profile's session file and its synthetic provider's received requests | demo profile, deleted after export |
| B1 | per step: `user/message` with `source.channel` whose seq lies between the step's last `asuna/stage` and its `assistant/message` (pass: 0); per held receipt: time from receive to write (pass: within its step and 1 s); receipts projected again at a start (pass: no rise); lines absorbed into a turn without `speak` there (pass: 0) | her session files, home and archive; `input.absorbed` audit rows |
| B2 | notices and checkpoints after install that start with their mark (pass: all); program-woken notices with `speaker` (pass: 0); 〔n〕 per checkpoint item (reported) | session files |
| B3 | same-tool different-class second refusals within a turn, as a share of failures counted from session files with the pre-worker layer included, as the 5.7% was (pass: below 2%); refusals holding 20+ consecutive characters of the call's prose fields (pass: 0, computed by the program); refusals past layer 0 without an audit row (pass: 0); layer-0 refusals by wording (reported), DSH's English refusal on her character brain (pass: 0) | session files, `role_tool` audit rows |
| B4 | the guard's schema refusals, by the shapes of §4 (pass: at most 1.5 per 1,000 calls, from 7.4, which is 101 in UTC days 10-18 to 10-28; the system survey counted 102 for the same span, and the 1 was not traced; floor 1.0, from the 14 that B4 leaves refused); chains, below (pass: at most 0.4 per 1,000 calls, from 1.5; count at most 5; floor 4); length refusals per field against the week before (pass: no higher; D4a's condition); cold first steps per conversation after install (pass: one each); 别人说的 / 主人定的 items after install without an anchor (pass: 0) | session files, cache readout (`asuna-cache-readout`), document items |
| B5 | 〔n〕 in new checkpoints whose stored line's speaker differs from the label written beside it | program count over checkpoints and `messages`, numbers only |

*(Revision 2, A10: there is no B0; B4's last count, items without an anchor, is replaced by §10.8; B1's proof also
counts lines written at `step/end` after a failed or aborted step; the table is read once, 7 days after the one install
(README 8.4).)*

B4's chains. A chain is a schema refusal (layer 0, told by its wording) whose tool's next call in the same turn is
refused with another class. The window is 11 whole UTC days; the sessions are her character preset's, home and
archive, one row per call id; the rate is chains per 1,000 of her character brain's calls in the window. Baseline,
UTC days 2026-10-18 to 2026-10-28: 101 schema refusals, 20 chains, 13,588 calls, so 1.5 per 1,000 (`q10`, §9). Of
the 20, by what B4 leaves of each refusal: 9 are repaired or relaxed away (missing `doc` 3, missing `do` 3, missing
delegate `title` 2, `parts` as a string 1); 7 are enum values, which join the combined refusal; 4 still stop alone,
being a missing field the program cannot infer (note `to`, note `text` and `to`, write_document `why`,
promote_memory `why`). Those 4 are the floor: B4 does not move them, so at today's rate they are about 0.3 per
1,000 calls and a count of 4. When the gate is red, the floor tells which: a reading near 0.3 is the part B4 does
not touch, grown; one well above it is a repair that did not take. The share of chains in the window's schema refusals (20 of 101 today) is reported, not gated: after B4 the
schema refusals left are the uninferable kind, whose share of chains is higher (4 of 14 today), so that share rises
with no change in her calls.

B4's schema refusals, in the same window and counting: 101 today, 7.4 per 1,000 calls. By what B4 leaves of each:
60 repaired or relaxed away, 27 enum values that move to layer 3, 14 still refused at layer 0 (missing fields the
program cannot infer). So the gate is at most 1.5 per 1,000 calls, against a floor of 1.0 (the 14).

## 9. How the page's numbers are computed

The scripts are in `.runtime/private/tool-failures/scripts/` (README section 7), so each number can be computed
again; they read her session files and print counts only. Session files are those of the home and archive session
folders; a call is counted once by its call id (seeded sessions repeat records).

| Number | Formula | Script, output |
|---|---|---|
| 10.3% (2,702 of 26,218) | character-lane calls (session kind `asuna-role`) whose `tool/result` has `isError`, over all such calls, 10-05 to the read at 2026-10-29 00:21 UTC | `parse.py` then `analysis.py`; `survey-out-1029.txt` |
| 14.6% (211 of 1,443) | the same, for calls whose time falls on 2026-10-28 as a UTC day (`iso(time)[:10]`, `timezone.utc`); recomputed from the same 00:21 UTC read | `analysis.py`; `survey-days-1029.txt` |
| 18% (median, length refusals) | per refusal text of the `TEXT_TOO_LONG` family (the `Error: ` prefix removed, cut to 3,000 characters): the characters covered when up to four program literals are chosen greedily, each marking only its first place in the text and chosen only while it adds at least 5 characters, over the text's length; the median over the family's 308 | `errclass.py` (`cover`), `q3stats.py`; `survey-q3stats-1029.txt` |
| 17 `compaction/summary` records | records in her session files whose line holds the one identifier of the false claim, counted by record type; not a count of summaries holding the claim's sentence | `q8.py`; `survey-q8-1029.txt` (rerun 2026-10-29 02:39 UTC: still 17) |
| 0 English schema refusals | failed `tool/result`s of her character preset whose text (the `Error: ` prefix removed) starts with `invalid arguments`, per UTC day, against those holding the guard's 「原话：invalid arguments」; home and archive sessions, one per call id; 0 from 2026-10-18, when the guard's first appears | `q9_dsh_layer.py`; `survey-q9-1029.txt` |
| 101 schema refusals, 20 chains, 13,588 calls (B4's baseline, §8) | her character preset's calls in UTC days 2026-10-18 to 2026-10-28, home and archive sessions, one per call id; a schema refusal told by the same wording as q9; a chain is one whose tool's next call in the same turn fails with any other failure; violations counted by field and kind (enum, type, required, undeclared) from DSH's words the guard quotes, one refusal giving several; what B4 leaves of a refusal by the relaxed fields of §4 and the enums leaving the declared schema | `q10_after_schema.py`; `survey-q10-1029.txt` |
| 156 (5.7% of 2,747), 1,062 unclassed, 44-156 | the system survey's serial counts: for each failed call, the next call of the same tool in the same turn, classed by the program wording of both refusals; the base includes the 206 refused before the worker | computed by the system survey's agent; its script was not kept, so these stand as the survey states them (`system-survey-1029.md`, "Serial counts") |

## 10. Revision 2: what each amendment builds

Code names and line numbers below were read at `196b6f6` (JS and Python) and at DSH `4000a552`. They move; the builder
reads the named place again before editing it. Every model-facing text is a draft for Xiaoman's reading (Chinese, 你, one
language), like the tables above. The build is one pass (README 8.4): the sub-sections are areas of one product, not
stages, and the batch labels B1 to B4 in the rest of this file name rows of its tables.

### 10.1 The product's tests (A1)

No test below needs a server. Each is listed with the failure it guards; a test with no failure to name is not written.
They are written with the code and run once, at the landing.

D1, JS (`packages/cognition-core/test/`, `node:test`, on synthetic session events with the fixture of
`navigation.test.js`):

1. A line arriving between a `step/start` and its `step/end` is held and is not in the log. Guards: the wrong order
   (finding 1).
2. At the `step/end` event it is written once, after the step's last `tool/result`, and its receipt is acknowledged
   only after the flush. Guards: order, and loss.
3. A step that ends in an error or an abort (events `step/start`, `step/end`, `turn/end`, no `agent/turn-stopping`)
   releases it. Guards: a line stuck in memory until a restart, which the DSH source shows can happen.
4. A line arriving while no step is open (after `step/end`, before the next `step/start`) is written at once. Guards:
   needless waiting.
5. A log whose last `step/start` is older than a `session/end-seed` holds nothing. Guards: a reopened conversation that
   never takes a line again.
6. A compaction that ends while a step is open does not release it; `step/end` does. Guards: a line written inside a
   step.

D1, worker (`tests/`, the `store` fixture): a receipt that was stored and not acknowledged is projected again by
`navigation.ready`; after `channel_input.ack` it is not. The builder reads `navigation.ready` (`native_worker.py:1131`)
and `channel_input.ack` (`:1146`) and writes the smallest test that calls them. If they cannot run on the in-memory
adapter, that is a gap to report to the lead; it is not a reason to move the test into `integration/`, which checks an
adapter's promises and not the program. And `_absorb`: a line seen in a turn whose `turn_tools` hold `speak` is marked
`absorbed_by`; in a turn without `speak` it is not. Guards: a line nobody answers.

D5 (`tests/test_woken_by_program.py`): for each of the eight episode kinds the stage context has `woken_by_program`
with the table's words and no `speaker`; for `external` it has `speaker` and no `woken_by_program`; for a
`task_feedback` and a `scheduled` turn `ep['person_id']` and `ep['manifest']['session_class']` still read the person who
authorized it; for a person's line from the local chat the `event` block carries `line` (A3). Guards: incident A's
shape, and the authority assertions that went with the deleted tests.

A2: in a scene whose channel carries no quote, a label line and a pointer show the number and the context has no
`quote` hint; in a scene that carries quotes both show.

D3, JS: `message()` and `restored()` on the character lane start with 〔程序〕 and a line break, on the executor lane they
do not; `summarize` adds the head once, removes a copy the model wrote, and an interim `inSteps` summary carries none.

D2, `tests/`: §6's resolution table row by row (a number here, 「这条」, a number that is not here, a program row, the
owner's row, another person's, her own); §10.7's lifecycle (set, replaced by a new `line`, dropped by another `from`,
kept by a rewrite that restates neither, shown in another conversation, row gone).

D4, `tests/` and JS: one refusal carries the problems of layers 3 and 4a together, and layers 0 and 2 stop alone; no
refusal holds 20 consecutive characters of the call's prose (the program check the acceptance counts on, run on
synthetic calls); every field the declared schema relaxes has a repair entry and a description stating the strict form
(promised in §1.1); every `INSTEAD` entry names an existing ability (promised in §2.3); §10.6's two directions for one
tool.

The declared schema, JS, with DSH's real `defineTool` and `validateArgs`: for each repair-table entry the shape she writes
passes the declared schema and `execute` receives it unchanged (an absent `doc`, `do`, `title` or a part's `kind`;
`parts` as a string, as an array, as an array with a key the strict schema does not declare; a `from` outside any list),
and what the declared schema keeps is refused, by DSH and by `argsRefusal` (a required field missing, `"3"` for an
integer). Guards: a repair the guard would refuse before `execute` ran, which is what made the note synonyms
unreachable (A8).

R2 (A11), JS, with the real `SystemPrompt` and a context registered the way the working-directory service registers its
own (`required: true`): a character-lane request carries no `Current working directory`; an executor-lane request does.
Guards: deployment details in her requests.

Not tested: wording, the words of the tables, the counts of section 5.

### 10.2 `numbered` (A2)

`capabilities.numbered` has five places at `196b6f6`, and one body that answers two questions:

| Place | It asks | After |
|---|---|---|
| `people.py:518` `pointed` | show the number? | when the row has a `scene_seq` |
| `people.py:582` `transcript` | show the number? | the same |
| `role_tools.py:1962` the `speak` receipt (`reply_receipt`) | show the number? | the same |
| `context.py:1283` the `AMBIGUOUS` hint (`:62`: 「要引哪条就在 quote 写它的编号」) | can she quote by it? | `can_quote(store, scene)` |
| `capabilities.py:157` `numbered` | | renamed `can_quote`, body unchanged (`carries(…, 'quote', 'quote_in')`) |

`speak_spec` is already gated by `carries(…, 'quote')` (`role_tools.py:667-687`). Every row has a `scene_seq`: inputs
take it in `persist_input` (`ingress.py:67, 72`), her own lines in `coordinator.py:430, 459`.

### 10.3 The local Web chat (A3)

`ContextBuilder.prepare` builds the turn's `event` block (`context.py:683`). When the event has no `channel` (the test
the file already uses at `:812`) and the turn's trigger is a person's line (`external`), the block gains
`'line': '〔n〕'`, n the input row's `scene_seq`, in the form of a label line's number. A program-woken turn has no
calling line and gets none. The event stays in the notice (the notice keeps the turn's trigger), so an earlier Web line
is pointable by the number in its own notice while that notice is on the surface. The compaction instruction gains
「网页里主人的话没有标签行，它的编号在紧跟着的程序通知里（event 的 line）。」 Cost: about 12 characters on a Web turn's
notice, new suffix, no prefix cost. Every input row has a `scene_seq` (`persist_input`, `ingress.py:67, 72`), the Web
chat's included.

### 10.4 D3 as built (A4)

- `packages/cognition-core/src/marks.js` holds `MARKS_VERSION = 1` and the two words of §5.1. `message(stage, …)`
  (`index.js:805`), when `stage.lane === 'character'`, makes the text `〔程序〕` + a line break + the text, after the
  ceiling has been applied (the mark is a fixed five characters outside it). `restored()` (`:828`) does the same. Stage,
  repair and restore notices all reach her through these two, so one edit each covers them.
- Not marked: the executor lane's notices (the same `message()`, a different `stage.lane`), `relay()` (`:845`, a note
  into the action brain's own conversation), and the interim summary message `inSteps` builds (`compaction.js:488`),
  which only the summarizer reads.
- The checkpoint head: `RoleCompactionEngine.summarize` (`compaction.js:322`) wraps its two return paths. The result's
  `summary` blocks get the 〔摘要〕 text block first, after a leading 〔摘要〕 line in the model's first block is
  removed. `inSteps` runs inside it, so only the final result carries the head. DSH frames it as English preamble,
  `<compacted-summary>`, head, body, closing tag (`region.ts:417`).
- The compaction instruction gains three rules (drafts): §7's 〔n〕 rules; 「已有检查点开头那行〔摘要〕是程序写的，
  不要抄进来。」; §10.3's Web clause.
- Readers of a notice's text: none parses it. `grep JSON.parse` over `packages/cognition-core/src` finds forms, files and
  settings; `visibleCarried` reads `source.carried`; the Web client titles a turn from `source.summary`. After the
  landing, the lead looks once at the Web page for a notice that begins with the mark.

### 10.5 D1 as built (A5)

In `pairing.js`:

- `stepOpen(events)`: scanning back, the latest of `step/start`, `step/end`, `turn/start`, `turn/end` and
  `session/end-seed` is a `step/start`.
- The hold condition at `navigation.js:83` becomes `headed(events) && (agent && stepOpen(events) || compactionOpen(events))`.
  `toolCallOpen` has no other caller (`navigation.js:5, 83` and `pairing.js:69`) and is removed.
- `releaseAfterCompaction` becomes `releaseAtBoundary`: on the `compaction/end` and `step/end` session events, by
  `queueMicrotask` (DSH refuses an append from inside a session observer), it writes the held lines when no step, tool
  call or compaction is open, then flushes.
- The `agent/pre-step` and `agent/turn-stopping` handlers (`index.js:1326, 1344`) stay as they are.

The waits, as the discipline asks. Who waits: the lines of that one conversation only (the map is per conversation). A
slow step: until its `step/end` (median 3.3 to 10.7 s at high cache share, about 28 s cold). A failing step:
`step/end` is appended in a `finally` (`agent.ts:358`), so the release comes with it. A hung step: DSH's idle watchdog
ends a stalled stream at `streamIdleTimeoutMs` (300 s by default, per attempt, with `llm-retry`'s retries), the step
ends, the line is released; a hung tool is bounded by its own `timeoutMs`, as a tool-open hold is today. We add no
timer. A Host stop: the memory map is lost, the receipts stay unacknowledged and are projected again at the next
start (§0).

### 10.6 Two sides at different versions (A6)

The build ships both sides together (`tools/check_prepared_start.py` checks the installed core against the commit), so
skew lasts across one restart only. The rules make it harmless anyway, by interface:

| Interface | Old JS, new worker | New JS, old worker |
|---|---|---|
| Held lines and `_absorb` | A line she saw in a turn without `speak` gets one more turn of its own (it is also in her history) | The line is absorbed as today |
| Marks, numbers, `event.line`, `woken_by_program` | None of the new text; nothing breaks | The same; `can_quote` is Python only |
| `role_tool` fields `given`, `violations` | The worker reads them with `.get`: absent, it checks as before | The JS sends them and an old worker ignores unknown fields; an old worker's specs carry no `strict` and its declared schema is the strict one, so the guard has already refused anything invalid |
| `role_tool_specs` with `strict` | The old guard checks the permissive declared schema and sends unrepaired arguments; the worker applies the same repair table itself and its handlers' own checks stand | Specs without `strict`: the JS takes declared for strict, does not validate in `execute` and sends no `violations`, because an old worker would run an invalid call; with `strict` it validates and sends |

A test holds the last row's two directions for one tool.

### 10.7 The anchor's lifecycle (A7)

Stored on the item row (`memory_tiers.Tiers.rows`, set with `from` and `nature` in `written`) as
`line: {scene, seq}`. Nothing else: the author and the time are the row's.

- Created: a `write_document` with a `line` that resolves (§6).
- The rule: the anchor exists exactly while `from` is 别人说的 or 主人定的. A write that sets another `from` removes it;
  one with a new `line` replaces it; a rewrite that restates neither keeps both, as `from` is kept today (the night
  list's gist rewrite must not lose an item's provenance).
- Shown wherever the item's `from` is shown. In the anchor's own conversation: the pointer form without the words
  (`People.pointed` minus the words). In another conversation: 「出自别处的一行（<time>）」, because a speaker label of
  another scene would mislead. The row is read at show time: a row that is gone or marked erased shows
  「出自的那一行已不在」 and nothing else (ADR-105: whatever reads an erased row says so).
- Discarded: with the item row. Put away or moved: it stays.
- Restart and compaction: a durable record, independent of both. A summary's 〔n〕 is a number in the same scene,
  resolved by `line` against the stored row and never by the summary.
- Not done here: copies of an item into another, and a line from another conversation (open question 2).

### 10.8 The acceptance condition for anchors (A10)

It replaces "items after install without an anchor (pass: 0)", which cannot fail because an unanchored write is
recorded as hers. Pass: every item with `from` 别人说的 or 主人定的 written after install has an anchor whose row
exists in that conversation and whose author is the owner exactly when `from` is 主人定的. Reported: the share of
`write_document` calls that gave 别人说的 or 主人定的 and were recorded as hers. Counts, from the audit rows and the item
rows.

### 10.9 What a stage would have shown, and where it is settled now (A10)

| Assumption | Settled by | Held by |
|---|---|---|
| The order inside a step, and the release at `step/end` after a failure | DSH source (README 8.2) | D1 JS tests 1 to 6 |
| `source` is dropped, so marks go in the text | DSH source | D3 JS test |
| DSH's validation passes the widened shapes and refuses what is kept | DSH source | the declared-schema test |
| The working-directory snapshot reaches her, and a scoped blank removes it | DSH source | the R2 test |
| Nothing parses a notice's text | the code (`grep JSON.parse`) | D3 JS test; the lead's look at the Web page after the landing |
| A Web line has a `scene_seq` | the code (`persist_input`) | D5 test (`event.line`) |
| A hung request is bounded | DSH source | none needed: we add no timer, and every wait is DSH's |

Where a test of the product fails against a row above, the builder stops and returns the row to design (README 8.4,
item 6); it does not change the test to pass.

### 10.10 The one landing

At the landing, once: `pytest tests`, `pytest integration` (a throwaway database), `npm run test:native`,
`tools/check_prepared_start.py --commit <sha>`, `tools/check_staged_secrets.py --personal`, and
`tools/publication_scan.py` on the changed files; `tools/project_map.py` regenerates `docs/map/` (`tests/test_project_map.py`
fails while it is stale). The lead's landing script runs them, fast-forwards and restarts once, while she is quiet and
after telling her, and checks the installed commit by `loaded.commit`.

Reference docs changed in the same commit as the behaviour (`AGENTS.md`): `RUNTIME_API.md` "What she carries" (every line
shows its number, `event.line`, `woken_by_program` in place of `speaker` on program-woken turns, the marks) and "Her
tools"; `docs/DEVELOPMENT.md` "Writing tool errors" (a refusal lists every problem, numbered, and repeats none of her text)
and its guard paragraph (the schema check moves into `execute`; the guard checks the declared schema);
`prompts/turn.md` and `turn_thinking.md` (the clause for `woken_by_program`, which rides on the one cold request);
`docs/map/`. A builder works in a worktree on its own branch, removed when it is merged. The way back is in README 8.4,
item 6.

### 10.11 R2 (A11)

`index.js:1256` suppresses the runtime context in every lane, which removes `approval:policy` and `sandbox:policy` (both
optional) and keeps `working-directory:current` (registered `required: true`). Right after it, for `lane !== 'executor'`
(as DSH's developer sections are blanked at `:1262`), the plugin registers through the same scope
`context({ name: 'working-directory:current', order: getContextOrder('WORKING_DIRECTORY'), required: true,
interpolate: false, text: '' })`.

One detail the builder must not miss. The working-directory service also rewrites that contribution's text in its own
`system-prompt/assemble` hook (`session/working-directory/src/index.ts:97-110`). The runtime-context message that is
appended at a step is built from `refreshContext` (`agent.ts:411-413`), which resolves the registered provider, so the
blank is what the model sees; the R2 test (§10.1) is the proof. If it fails, R2 goes back to the owner as a DSH request
and the build does not carry it.

A session that already holds a snapshot gets DSH's one-time "Current runtime context: none. Earlier runtime-context
snapshots no longer apply." message after its history (`runtime-context.ts:152-163`); a session that never had one gets
nothing.
