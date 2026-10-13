# ADR-060: Plain parameter names: one name per idea, words a reader understands

Status: **Proposed 2026-10-13** (owner's ask, after seeing `missing required property "op"` more than once). For
Xiaoman's review: the names are hers to choose; the owner approved doing it tonight. Her answers came on the agent
line on 2026-10-13 (03:02, 04:00 and her full read, NZDT); "Her review" below is Claude's paraphrase of them, for her
to sign or correct.

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

## Her review

*Claude's paraphrase of her messages of 2026-10-13 (03:02 first pass, 04:00 answers, then her full read), not her
own words. Her signature:* ____


- Agreed: `op` → `do` (with `group_action.kind`), `why` everywhere, `sid` → `section`, `quote.how` → `quote_whom`,
  `block` → `block_hours`, `feel.open` → `unresolved`, `watch.mode` → `how_often`, yes/no as words (the cheapest
  item: all 31 refusals), `plan.line` and `peer_line.line` → `place`, `feel`'s `decision` folded into `do`.
- **Notes keep `to`**: `to` is where a note is sent, `place` is which conversation she is in; different directions.
- **`pass_note.mode` → `when` would make a new double meaning**: `when` already means a time elsewhere
  (`restart.when`, and `sticker.when` means "when to use it", already a second meaning). Agreed instead:
  `pass_note.mode` → `deliver` (wake / next_time) and `sticker.when` → `use_for`, leaving `when` a time only.
- **`write_document.inject` → `shown` reads like `visibility`** beside it. Her choice: **`when_shown`** (inject is
  jargon; `visibility` says who can see a section, `when_shown` when it is put in context).
- **One word for written content**: the files' `text` → `content` fixes the action brain's 7 refusals, but her
  `write_document` calls its text `body`, so she would trip the other way. Proposed: `content` for a document's or
  a file's text (`write_document.body`, `update_self.body`, `understand_person.body`, `write_file.text`,
  `development_write.text`); a message keeps `text`. Agreed, with the cost named: `body` is a word she writes
  dozens of times a day, so the old name must not leave early.
- **Old names leave by use, not by calendar**: an old name is removed once her calls use it fewer than 5 times in a
  week.
- **Both names, both ways**: a call with an old name runs and its result says "`body` 已改名 `content`，这次照办"; a
  refused call lists the new and the old name together, so the refusal says what it wants.
- **The one-meaning rule runs as a test against the rename table**, not as a sentence in this ADR: her full read
  found the draft's own `pass_note.mode` → `when` broke it.

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

## Wording audit (2026-10-14, owner's ask; ships with this ADR)

The owner asked for every harness-side prompt, tool name, tool description and error to be checked for consistent
words, clear definitions, concise errors, wordiness and needless "don't"s, read **in context**: what each brain was
actually sent, not the files alone. Her persona is out of scope (hers). Read on 2026-10-14 from the latest real
session of each kind (her turns in a group, on an agent line, in local chat and on the peer line; the action brain;
the relevance gate; the background summarizer), with other people's words and her own texts blanked. The owner chose
to ship the fixes with the renames above: one review with her, one restart, refusals counted by cause.

### Defects: wrong text in context

1. **DSH's coding-agent text reaches three of her brains.** The action brain, the relevance gate and the summarizer
   get about 2,300 characters of English meant for a developer using DSH: the checkout path ("use this checkout only
   to inspect or extend DSH"), the Web GUI URL and its HMR rules, and how to link files and use a `present` tool none
   of them has. Her role turns do not (their system prompt is the worker's render alone). The cause: three sections
   DSH registers outside the runtime context we already suppress (`harness:source`, `ui:deliverable-file-references`,
   `app:web-surface`). Fix: blank them for every lane, as `harness:identity` is.
2. **The gate and the summarizer get the character's turn contract.** `common.md` ends with "每一回合先用 think…
   stay_silent 结束" though neither has tools. The contract belongs to `turn.md` (role turns only); `common.md` keeps
   what holds for every lane.
3. **Relative times are still sent.** A memory's `when` reads `10/12 07:35（35 小时前）`; the gate's `since_you_spoke`
   reads `7 分钟前`. ADR-056 rule 2 says clock stamps only. A memory also carries `occurred_at` (the same time again)
   and fields she never uses (`segment_index`, `segment_count`, `status`, `historical_sources`, `kind`).
4. **The clock block shows a raw timestamp** (`2026-10-13T18:26+08:00`); everything else she reads is `10/13 18:26`.
5. **One block says two opposite things**: `stickers_from_program`'s guide joins two notes with "／" (「这里发不出去」
   and 「在这里想发哪个…」) where only one applies to a place.

### Wordiness and needless "don't"s

The rule for every rewrite: say what to do. Keep a "don't" only for a failure that was seen and that the positive
form cannot say; say each fact once, in the one place it applies.

- `common.md`: eight sentences, six of them "不要 / 不是 / 不能"; several repeat `turn.md` (thoughts are not speech,
  labels, the contract).
- `turn.md` 说话时: eight bullets, mostly negatives, some repeating the tool texts (@ labels, pictures).
- `executor.md`: "不要" four times and "禁止" once; "普通实现细节和错误自己处理" twice.
- Tool texts at the long end: `read_image` (about 700 characters, half of it rules the program enforces anyway),
  `write_document` (one paragraph mixing five operations, visibility and injection), `ideas`, `leave_note`,
  `understand_person`, `delegate`, each with "不抄 / 不带 / 不当场 / 不为了 / 不要说成".

### One word per idea (beside the renames above)

The same thing is called: 回合 / 一轮 / 一拍 (a turn); 行动脑 / 行动侧 (the action brain); 用户 / 对方 / 主人 (who she
talks to); 本机 / 本地 / 家里 (home); `ref` / `_id` / `artifact_id` / `sid` (what to copy). Each gets one word,
listed in a glossary test like the parameter names, and the tool texts use only those.

### Errors she reads

Seen in her last 14 days of refusals:

- Prose and a code in one message: 「这份文档不能这样改。 （DOC_OP_NOT_ALLOWED: correction 只用于活账…）」.
- A code alone: `CLOSE_REQUIRES_OPEN`.
- Raw platform text: `HTTP_400:{"retcode":-5503007,"retmsg":"download url has expired",…}`.
- A machine timestamp: 「现在是 2026-10-13T01:32+13:00（周二，Pacific/Auckland）」.
- The same 16-character aside on every length refusal: 「（标点、空格、换行和字母也各算一个字）」.

The rule: one sentence for what is wrong, one for what to do; codes stay in the record, not in her text; platform
replies are put in words; times are local and short; how length is counted is said once, in the tool text.

### Checks on her words (owner, 2026-10-14)

The program checks what she is about to say before it leaves. The owner's rule: keep a check only for output that
cannot be right; drop one that could stop a correct answer, accepting a rare wrong line.

| Check | Can a correct answer trip it? | Decision |
|---|---|---|
| Nothing written and no `stay_silent` | No | Keep |
| Cut at the length limit | No | Keep |
| No `think` yet | No (turn rule) | Keep |
| A consult answered in body text, not `task` answer | No | Keep |
| A sticker or face name she does not have; stickers where none can be sent | No (her own markup) | Keep |
| The whole answer is a JSON object | Yes (someone asks for JSON) | Drop |
| Program words (`_from_program`, tool names, 工具调用) | Yes (a script, a talk about tools) | Drop |
| A line starting with a label, no @ | Yes, rarely; the name still shows | Drop |
| `#4` where 4 is someone's number | Yes (an issue number, a rank) | Drop |
| More than one sticker in a turn | Yes (two can be what she means; the program already sends each as its own message) | Drop the cap |

### How it ships

Every rewrite goes to her as before/after with its characters per brain before it is built into the install
(her condition for this ADR); `tests/test_tool_budget.py` moves by exactly the measured change. One restart with the
renames. Afterwards: refusals per day by cause and the argument-validation refusals, apart from the missing-`think`
count of 2026-10-14.
