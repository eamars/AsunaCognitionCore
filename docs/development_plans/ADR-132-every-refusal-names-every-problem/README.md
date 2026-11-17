# ADR-132: Every refusal names every problem, for every tool

Status: **Proposed** 2026-11-16 by big sis (Claude Code), at the owner's ask (The ask). Drafted for the owner and for
her reading; not built. Every count in §3 covers 2026-11-02 18:55 to 2026-11-16 18:55 and was read 2026-11-16 18:30-18:57 from her profile, read-only (session files
through their structure only; audit rows by tool name and code only). Times on this page are local time.

## The ask

The owner, 2026-11-16, after a turn of hers on the vault tool (保险箱, `credential`): "If you could recall, one of the
ADR was to mandate the population of all errors if she called one tool wrong. For example, if she called a tool wrong
while without think first, then all errors will be populated. However this is not the case for 保险箱 ... I would
like you to identify this error, look back on the last ADR on the same matter and perform RCA on why this one is
missed. If this is a legit error then let's draft an ADR to properly fix this failure mode, as well as other possible
failure modes."

What he saw, in program words: a `credential` call without `do` was refused with 「credential 的参数不对：缺 do（做什么
（只能是：keep、drop））。照 credential 的说明改好再调用一次。」; the next call, with `do`, was refused with 「先用 think 写下
这回合的心里话，再做别的……」. One refusal could have named both.

## 1. The rule and how it was built

ADR-108 D4b (the owner's recommendation, binding): one refusal names every problem the program can find, best
effort. A call is checked in layers 0-5; a layer's problems are collected, a later layer runs on what the earlier ones
left valid, and a refusal names every problem of every layer that ran (`role_tools.py` `RoleTools.call`).

It was built as two opt-ins, and a tool that is not listed keeps the old behaviour, stopping at its first problem:

- **Layer 0, the declared schema.** What DSH registers and validates, and what the plugin's guard checks first
  (`index.js` `attachPreset`, `tool-args.js` `argsRefusal`), is derived from the strict schema by
  `tool_schema.declared`: every enum is dropped, but a required field stays required unless it is listed in
  `tool_schema.REQUIRED_FILLED` (three fields: `write_document` `doc` and `do`, `delegate` `title`). A call missing any
  other required field is refused by the guard before it reaches the worker, alone: THINK_FIRST, the call cap and the
  handler's checks never run. 34 required fields in 20 of her 37 tools are on this path, `credential` `do` among them.
- **The handler's own checks.** They collect only for the 10 handlers in `RoleTools.SPLIT` (each split into a check
  part and an effect part). For the other 27, `call()` runs `checkpoint()` before the handler, so a general problem
  (THINK_FIRST, a schema problem) refuses alone and the handler's checks are not reached.

## 2. Why this one was missed (root cause)

- **The rule was written for every tool and built for some.** ADR-108's window (UTC days 10-18 to 10-28) counted
  which tools produced a second refusal, and the build converted those. `credential` (2026-10-07) and `private_words`
  (2026-10-11) existed then and were left out; every tool added since inherits the default. Joining the rule needs a
  list entry, so leaving it needs nothing.
- **It was accepted by an aggregate rate.** ADR-108 named this exact residue: "What still stops alone at layer 0 is
  what the declared schema keeps (a wrong type, a missing field the program cannot infer); it hides the later layers'
  problems behind it", and counted it as the floor of B4's gate, per 1,000 calls. This case is 3 in 14 days (0.19 per
  1,000), inside that floor, so no reading flagged it.
- **The residue had no exit.** Neither the 27 handlers nor the un-inferable required fields had an item that closes.
- **One reason was wrong for one case.** Layer 0 "stops alone: nothing else is defined". That holds for an unknown tool
  or arguments that are not an object. It does not hold for a missing field: THINK_FIRST and the call cap do not
  depend on the arguments at all.

The broken invariant: "a refusal names every problem the program can find" holds only where a per-tool list opts in.
The rule has to be the default, and stopping at the first problem the exception that needs its reason.

## 3. What is known (counts)

Her character brain, 2026-11-02 18:55 to 2026-11-16 18:55: 15,448 tool calls in her character sessions; 12,406
`role_tool` audit rows (the worker's), 1,180 of them refused. The guard's refusals have no audit row (ADR-108: it is
synchronous and cannot ask the worker); they are counted from the session files by their wording.

- Layer 0 (the guard): 40 refusals, 39 a missing field and 1 a wrong type. By tool: `think` 21, `note` 6,
  `private_words` 5, `credential` 3, and `plan`, `understand_person`, `sticker`, `delegate`, `write_document` 1 each.
  Followed in the same turn by a refusal of another class on the same tool: 3, all `credential`, all THINK_FIRST
  (the owner's case among them).
- Unsplit handlers: on the same tool in the same turn, a refusal that named only general codes followed by one that
  named a handler code: `credential` THINK_FIRST then CREDENTIAL_NOTE_INVALID 2, `sticker` 2, `understand_person` 1,
  `note` 1. The second call's arguments were not read, so a changed argument may explain some of these: an upper
  bound on the hidden problems, not a count of them.
- Her action brain, the same window: 17,827 tool calls; 126 refused with DSH's own English argument refusal (`invalid arguments: …`,
  no fix sentence). The guard checks only her character brain's tools (`attachPreset`: `spec` is defined for the
  character lane only).

## 4. Failure modes of the class (a refusal that leaves out a problem the program could name)

| # | Failure | Here |
| --- | --- | --- |
| F1 | A missing required field stops at layer 0 and hides the turn's checks and the handler's | D1 |
| F2 | A handler outside `SPLIT` stops at the first problem; a general problem hides all of its checks | D2 |
| F3 | A tool added later falls back to F1 and F2, as `credential` and `private_words` did | D3 |
| F4 | A wrong type stops at layer 0 (1 in 14 days) | kept: DSH validates types against the declared schema before our code runs; its count is the sentinel |
| F5 | Layer 2 (NOT_NOW, not usable in this turn) stops alone | kept, ADR-108 D4c: the fix is another tool or turn, and argument problems listed beside it lead to a corrected call that is refused again |
| F6 | A layer-4 problem that needs a field fixed first (a section in a document not yet named) | kept: best effort by nature; it cannot be named before the field it depends on |
| F7 | The action brain's argument refusals are DSH's English line with no fix | not this ADR: a separate decision for the owner (§7) |
| F8 | `task`, `ideas` or `ask` with a `do` that cannot be read stops alone (found at the build, §8) | kept, the named exception: each has a read option, so whether a thought is needed is not known; not a regression |

## 5. Decisions (proposed)

**D1. The declared schema requires nothing.** `tool_schema.declared` drops `required` from every field, as it already
drops every enum. The strict schema keeps it, and the worker's layer 3 names a missing field together with THINK_FIRST,
the call cap and the handler's problems. Layer 0 then refuses only a call that cannot be read (an unknown tool,
arguments that are not an object, a reused call id) and a wrong type (F4). The model still needs to know which fields
are required: each required field's description says so in words, derived in `declared()` the way enum values are
listed today. Her words (agent line 0526, F8), the same string on every such field:
「（必填。不写＝这次不执行；缺哪几项一次全说）」. Her three conditions: at the end of the description, in its brackets, never a
heading of its own; no English `required`; and only on a field the program cannot fill in: a field with a default the
program infers (`write_document` `doc` and `do`, `delegate` `title`, the `do` of an op tool) does not carry it. The
program's inference does not change: those fields are filled exactly as today (`tool_schema.REQUIRED_FILLED`,
`infer_op`); D1 changes only the layer that names a missing field and what it is named with (her 0528). Cost: every
tool spec with a required field changes, which means one cold request per open conversation at the install. Her tool
budget, computed 2026-11-16 19:31 on today's specs with D1's rule applied (the budget test's own count,
`tests/test_tool_budget.py`): 34 marks; 20,513 -> 20,668 characters (+155: her mark adds 748, the `required` flags it
replaces take 593 off), 33,800 -> 35,451 bytes (+1,651). Measured again at the build and given to her (her 0528). The schema this changes is her character brain's only: it is built by
`role_tool_specs` for her role sessions (`native_worker.py`, `attachRole`); the action brain's tools are DSH's own,
registered for its task, and `tool_schema` never declares them (her 0526 question).

**D2. Every handler collects.** `SPLIT` goes. Every handler gets a check part that ends with `self.checkpoint()` before
its first effect, and `_found` always collects. The dispatcher no longer refuses before a handler runs. The 27 handlers
are read one by one; most have one or two checks and then one write. What goes is the list, not the behaviour: the 10
handlers that collect today keep doing so unchanged (her 0526).

**D3. The default is the rule.** Three tests, because a regression here is silent:
- over `all_specs()`: no declared field has `required` or `enum`; every field the strict schema requires and the
  program cannot fill in carries her string once, at the end of its description; a field the program fills carries it
  0 times (her 0526: the test counts the string);
- one refusal names a missing field and THINK_FIRST together (`credential` without `do` and with no thought: the
  owner's case);
- every handler, called with no thought first and an argument its own checks refuse, on the in-memory store, is
  refused with both THINK_FIRST and its own code, and writes nothing. Its last part covers D2's real risk: an effect
  run while a problem is still pending.

**D4. Nothing else she reads changes.** The refusal texts are the ones she has (`combined()` already numbers several
problems); only her required mark in each such description is new.

## 6. Closes when

- In an isolated profile on a stub model (造的): a `credential` call with no `do` and no thought gets one refusal
  naming both; a `credential` call with a bad `note` and no thought gets one refusal naming THINK_FIRST and
  CREDENTIAL_NOTE_INVALID; D3's tests pass for every handler.
- Installed and read by content: no declared field requires anything, so a missing field cannot be refused at layer 0.
- Real traffic, by count and not by date (her 0528; the owner's rule of 2026-11-09): read once her character brain
  has made 2,000 calls after the install. Passes when (a) every refusal that names a missing field, in a turn whose
  thought was not yet written at that call (no accepted `think` before it in the audit rows), also names THINK_FIRST
  (§3: 3 calls where they came apart); (b) missing-field refusals number at most 10 (twice §3's rate
  of 2.5 per 1,000: D1 takes `required` out of what the model reads); (c) layer-0 refusals for a missing field are 0.
  Read before 2,000 calls, it is reported as not enough, never as a pass, and the count is never moved later. At
  2,000 calls the reading closes it, pass or fail: no new decision then (her 0531). F4's count is written down as the
  sentinel.

## 7. For the owner

- **F7** is a separate ADR if he wants it: the guard would check the action brain's tools too and refuse in Chinese
  with a fix, as ADR-076 R3 did for her character brain. DSH's English line already lists every schema problem at once,
  so the gap there is the wording and the missing fix, not completeness.
- The order: today's ADR is ADR-121, and five ADRs are open (120, 121, 122, 123, 125). This page waits for his word on
  where it goes.

## 8. Built and staged (2026-11-18)

Built on this branch after the signed page (`b392f0390d5c`). Times are local.

- **D1, measured.** 36 fields carry her mark, not 34: §5 counted the top level only, and two nested fields are
  required too (`recall`'s `sections[].doc`, `plan`'s `clock.time`). Her tools as sent: 20,513 -> 20,676 characters
  (+163; §5 computed +155) and 33,800 -> 35,547 bytes (+1,747; computed +1,651). `tests/test_tool_budget.py` is
  raised to 20,676. A missing field's refusal now comes from the worker. It says the field's values when it has a
  list of them, as the guard's refusal did, in one bracket (her 0551): 「缺 do（做什么；只能是：keep、drop）」 (added after
  the staging below; the unit tests hold it).
- **D2, how.** `SPLIT` is gone. Every handler runs with the general problems pending (`RoleTools._handle`).
  - A check that stops before the handler's checkpoint is one problem, named with the pending ones. A missing-field
    code that the strict schema has already named is not named twice.
  - A failure reading a value already found wrong leaves the refusal to the problems found.
  - Each handler ends its check part before its first effect. Where a module checks and writes in one call, it takes a
    `ready` hook that runs between the two: `credentials` (keep names all its own problems, `credentials.problems`),
    `watches`, `switches`, `group_admin`, `notices`, `questions.close`, the five sticker writes, `received_files` and
    `promote`. A note's own checks (`notes.prepare`) run with the rest.
  - Still after the checkpoint, best effort as F6: the checks inside the scheduler's visit, errand and note send,
    `restart`'s `when`, `group_focus`'s focus change, a sticker found already kept after its bytes are fetched, and
    `read_image`'s and `received_file`'s reads. They stop alone only when nothing else is pending.
- **F8, found at the build, kept: the named exception.** `task`, `ideas` and `ask`, called with a `do` that cannot be
  read (missing and not inferable, or not one of its options), are refused for that alone. Each of them has a read
  option, so whether a thought is needed is not known, and its other checks depend on the option. **Such a refusal
  standing alone is not a regression** of ADR-108 or of this ADR (her 0551).
- **D3.** `tests/test_every_refusal.py`:
  - the declared schema walked at every depth;
  - the owner's case;
  - §6's note case;
  - all 38 tools and options called with no thought, with no arguments and with every required one filled in: each is
    refused with what is pending, and nothing is written;
  - a valid vault call with THINK_FIRST pending does not reach the vault.

  Not held by a test, said here so nobody takes it as held (her 0553): a missing **nested** required field
  (`recall`'s `sections[].doc`, `plan`'s `clock.time`). An empty call never reaches them; the 34 top-level fields
  were each named missing by an empty call when read on 2026-11-18, a reading and not an assertion of the test.
  ADR-108's structural test now covers every handler. DSH's validator test: `speak {}`, `write_document` without `why`
  and `think {}` now pass DSH and are named by the worker; `think` with a number stays refused.
- **Suite** on `9f7e92025916` (the staged code): Python 1133 passed, JS 328, 0 skipped, 0 unchecked.
- **Staged (造的), 10:39-10:42.** An isolated profile `asuna-demo132` on the stub model, without DEEPSEEK_API_KEY, with
  its own database.
  - On the agent line `credential` is not offered (DSH answered that the line has no such tool), so the demo
    persona's home chat on its Web page was used instead.
  - `credential` with no `do` and no thought: one refusal, 「这次调用有 2 处要改」, 1. THINK_FIRST, 2. 「缺 do（做什么）」.
  - `credential` keep with an empty note and no thought: one refusal, THINK_FIRST and CREDENTIAL_NOTE_INVALID. Nothing
    reached the vault.
  - Both were read from the demo's audit rows. Torn down at 10:42: database dropped; profile, config and launch entry
    removed.
- **Not shown yet:** §6's second and third readings (installed and read by content; 2,000 of her real calls).
