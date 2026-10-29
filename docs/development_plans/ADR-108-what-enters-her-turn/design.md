# ADR-108 design: the detail each decision needs to be built

The page is [README.md](README.md); this file holds the layers, the tables and the proofs. Every model-facing text
below is a draft (Chinese, 你, one language) for Xiaoman's reading; code names are as they stand at `5a196e66`.

## 1. The check pipeline (D4b)

### 1.1 Where a call is checked today, and where it moves

DSH runs a call's stages in this order (`dsh-tools` `prepareExecution`): `tools/pre-execute` (async waterfall; ours
asks the worker `session`, `index.js:1232-1245`), then the guards (synchronous: a returned string denies; ours at
`index.js:1217-1231`), then dispatch to the tool's `execute`. `defineTool` wraps `execute` so that DSH's
`validateArgs` runs first and throws `ToolArgsError` (`invalid arguments: …`) on a violation.

| Today | After |
|---|---|
| guard: not in this conversation → refused | unchanged (layer 0; it is synchronous and cannot ask the worker) |
| guard: schema (`argsRefusal`, `tool-args.js`) → refused alone, no audit row | removed from the guard at B4 (kept through B3) |
| `defineTool` wrapper: DSH's own validation against the declared schema (never reached after the guard) | unchanged; it validates the permissive declared schema (§4), so it passes every shape the program repairs and refuses what the program never accepts |
| `execute` → worker `role_tool` | `execute`: repair a copy (§4), `validateArgs` on the copy against the strict schema the program keeps, then worker `role_tool` with `args` (repaired), `given` (as she wrote it, for the record) and `violations` |

Two schemas per tool: the strict one (today's specs, kept in the program beside the repair table and shipped with
`role_tool_specs` for `execute`) and the declared one derived from it by the repair table (fields the table can fill
lose `required`; fields the table parses are declared `json`). One source, so the two cannot drift; a test holds
that every field the declared schema relaxes has a repair entry and a description stating the strict form. R3 (a
supported normalize hook in DSH) would let them be one schema; nothing waits on it.
| worker `RoleTools.call`: first failure raises | worker: layers 0-5 below; one `Refused` whose record keeps every code |

### 1.2 The layers

| Layer | Checks (today's site) | Collected? | Why it stands where it does |
|---|---|---|---|
| 0 | tool in this conversation (guard); args an object; call id not reused; tool exists; retired old name (`role_tools.py:1367-1383`) | stops alone | nothing else is defined without a tool and an object |
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

## 2. Refusal texts (D4c)

### 2.1 Lengths

| Case | Text |
|---|---|
| description, her prose | 「（N 字以内，过了 M 字不收）」 (`LIMIT_WORDS`) |
| description, exact | 「（最多 N 字）」 (`EXACT_WORDS`, unchanged) |
| kept between N and M | 「<字段> L 字，要求 N 字以内，多了 K 字；过了 M 字不收」 (`config.over`) |
| refused past M, prose | 「<字段> 太长了：L 字，过了 M 字的线 J 字（要求 N 字以内）。<为什么有这条线>。精简到 N 字以内再调用；M 字落在第 s 句里（共 t 句）。」 |
| refused past M, a list (plan intent, idea, errand request, note) | the same, ending 「删哪段你自己定；M 字落在第 s 行（共 t 行）」 |
| refused past a safety cap | 「<字段> 太长了：L 字，最多 M 字。」 and what to do (a brief split into a follow-up `task` message) |

The sentence index counts the same sentence ends `config._head` uses (`SENTENCE_ENDS`). Nothing of her text is shown.

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

Applied to a copy in `execute` (layer 1) and recorded in the call's `repairs`; the worker applies the same table, so
both layers read one call. The table is data in `role_tools.py`, shipped with `role_tool_specs`.

| Shape she writes (refusals, 10-18 to 10-29) | Repair | Said in the result |
|---|---|---|
| write_document without `doc` (30) | the one writable document here with a section of that name; in a group outside an errand, `group_notes`; else no repair, a layer-4a problem with the candidates | 「没写 doc：按 section 当作 <doc> 写了」 |
| write_document without `do` (16) | by fields: `heading` and no `section` → `append_section`; `section` and `content` → `replace_section`; `section` with only `tags` / `visibility` / `when_shown` → `set_tags`; anything else no repair | the existing 「没写 do：按你写的字段当作 X 办了。」 |
| write_document `from` outside the enum (21) | none; with D2 she writes `line` instead of 别人说的 / 主人定的 | n/a |
| speak `parts` as a string holding a JSON list (8) | parsed | nothing (format only) |
| speak part without `kind` (6) | the kind whose one field it has (`text`, `name` → sticker, `who` → poke, `face` → react); `artifact_id` alone is picture or file and stays a problem | nothing |
| speak part key that is speak's own (`quote`, `wait`) (part of 7) | lifted to the call when the call has none | nothing |
| delegate without `title` (9) | the brief's first sentence cut to 64 at a sentence end | 「没写 title：用了 brief 的第一句：<title>」 (program-made title, not her prose echoed in a refusal) |
| note `note` for `text` (4), `place` for `to` (3) | renamed | nothing |

In the declared schema (what DSH validates and the model reads) `required` is dropped for `doc`, `do`, delegate
`title` and a part's `kind`, and `parts` is declared `json` so a list written as a string passes DSH's validation and
reaches `execute`. The strict schema inside the program keeps them required and `parts` a list of objects, and
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
in the pointer form (number, speaker, time), without the line's words.

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
| B1 | per step: `user/message` with `source.channel` whose seq lies between the step's last `asuna/stage` and its `assistant/message` (pass: 0); per held receipt: time from receive to write (pass: within its step and 1 s); receipts projected again at a start (pass: no rise) | her session files, home and archive |
| B2 | notices and checkpoints after install that start with their mark (pass: all); program-woken notices with `speaker` (pass: 0); 〔n〕 per checkpoint item (reported) | session files |
| B3 | same-tool different-class second refusals within a turn, as a share of failures (pass: below 2%, from 5.7%); refusals holding 20+ consecutive characters of the call's prose fields (pass: 0, computed by the program); refusals past layer 0 without an audit row (pass: 0) | session files, `role_tool` audit rows |
| B4 | schema refusals of the five shapes (pass: near 0, from 102 in 11 days); cold first steps per conversation after install (pass: one each); 别人说的 / 主人定的 items after install without an anchor (pass: 0) | session files, cache readout (`asuna-cache-readout`), document items |
| B5 | 〔n〕 in new checkpoints whose stored line's speaker differs from the label written beside it | program count over checkpoints and `messages`, numbers only |
