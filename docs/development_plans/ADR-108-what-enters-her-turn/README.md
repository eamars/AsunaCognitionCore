# ADR-108: Her tool interface, and what enters her turn

Status: **Proposed** 2026-10-29. Written by the design agent (Claude) from the lead's brief, after two surveys of
the same day (structural and system, section 7). Nothing is built. Next: the lead's review, then the owner, then
Xiaoman once. The detail each decision needs to be built is in [design.md](design.md).

Decision D4a reverses an owner decision of 2026-10-22 (ADR-054, "What she reads names only the ask") and D4c one of
her asks (ADR-054, the offered cut showing what it leaves out). The owner said yes to D4a on 2026-10-29; Xiaoman said
yes to D4c on 2026-10-29, in the form D4c now states (the excess located by characters, not by sentence).

## 1. Context

The numbers below are the surveys' (section 7), read from her session files as they stood at 2026-10-29 00:21 UTC
unless a line says otherwise; how each one is computed is in design.md §9.

Her character brain's calls fail 10.3% of the time (2,702 of 26,218 calls, 10-05 to 10-29; 14.6% on 2026-10-28, a
UTC day: 211 of 1,443). Turns
with three or more failures take 8 steps and 74 s at the median against 3 and 20 s for turns with none. After a
failure, 61.3% of next steps call the same tool with other arguments; an identical failing call again is 0.4%, and
runs of identical consecutive failures are 5 in 2,695. So she does not loop: she corrects one thing at a time, and
the program tells her one thing at a time.

The six findings, each with the invariant it breaks:

| # | Finding (survey numbers) | Invariant broken |
|---|---|---|
| 1 | A line delivered while a request is in flight is appended at once (`navigation.js:84`). In 93% of turns with a mid-turn line (614 of 660: QQ 515 of 550, agent lines 99 of 110) a line was appended while a request was in flight; from that order, inferred and not traced through DSH's surface projection, the response to that request did not carry it. Incident A: after such a line, a later step recorded a sourceless claim attributed to its sender; the order fits more than one reading, and the survey read structure only. | Her conversation's order is the order in which she saw things. |
| 2 | `write_document`'s `from` (别人说的, 主人定的) records a claim as someone's with no check that such a line exists (`memory_tiers.py:56-61`, `727-732`). The identifier in one false claim appears in 17 `compaction/summary` records of her session files (and 17 checkpoint messages; at 2026-10-29 02:39 UTC, a count at one moment that is still growing); this counts records holding the identifier, not summaries holding the claim's sentence. | A record that says someone said something points at what they said; a summary's claim keeps where it came from. |
| 3 | DSH's adapter sends every user-role message as text only and drops `source` (`dsh-llm-pi-ai/lib/index.js:1362-1370`). A live line, a program notice, a checkpoint and the runtime context differ only by text format. | Every message she reads says whose it is. |
| 4 | Limits state a soft number and never the hard one (think: 120 stated, 360 refused); between them "这次照收了". Checks stop at their first failure across two layers; 156 failures were a second refusal of another class for the same tool in the same turn (5.7% of 2,747 failures counted from session files, which include the 206 refused before the worker). In the length refusals (`TEXT_TOO_LONG`, 308), at the median 18% of a refusal's characters are covered by at most four program literals, each counted at its first place; the rest is her text and the program text this measure leaves uncovered (repeated or short literals). The guard's 101 schema refusals (UTC days 10-18 to 10-28, home and archive sessions, one per call id; the system survey counted 102 for the same span, and the 1 was not traced) are interface shape, by shape in design.md §4. | A number she reads is the rule the program applies; a refusal says everything the program knows is wrong; the schema asks only for what the program cannot work out. |
| 5 | Program-woken turns have about 3x the multi-failure rate of person-woken ones (structural survey Q7: 2 or more failures in 11.6% of program-woken turns, against 3.7% for person lines delivered normally); incident A's turn was program-woken (a task result). Every turn's context head carries `speaker`, set from the event's person (`context.py:1340`, `people.relabel`), and on a program wake that person only authorized the turn. | `speaker` names someone who is speaking. |
| 6 | No stored record shows a model step's request; Host report folders keep 5 starts (about 3 hours). | (none: a question of proof) |

Her steps read 92.2% of their input from cache. A change to tool specs or the system prompt costs one cold request
per open conversation (median 89-130 k tokens re-read, 3-6x the request time); marks on new messages cost nothing;
anything that differs per turn in the prefix costs on every turn. Every decision below is priced in those terms.

## 2. Decisions

### D1. A line that arrives during her turn joins the conversation at the next step boundary

Once a turn is headed, her conversation changes only at a step boundary: a line that arrives while a step is open
(from `step/start` until that step ends) is held, as lines are already held while a tool call is open or a
compaction runs (`pairing.js`), and released at the next `agent/pre-step` or at `agent/turn-stopping`. The open tool
call is a part of the open step, so the one rule replaces `toolCallOpen` in the hold condition. The line keeps its
label line (speaker, local time, number) and gets no other mark: in true order it sits after her last call and its
result, which is where a new line is.

A held line that joins a turn opened by the program is seen in that turn, and today the coordinator then gives it no
turn of its own (`_absorb`, `coordinator.py:346-356`: a line that first came into her view during a turn is hers
there, answered or let pass). That stays where the turn can answer it, a turn with `speak` in that conversation: she
saw the line at a step boundary and could reply. A turn without `speak` there cannot, so a line released into it is
not absorbed and keeps its own turn, which opens after this one. The held lines' lifecycle (memory only, emptied at
every release, recovered at a start from the receipt that is acknowledged only after the line is written) and the
tests that hold it are in design.md §0.

Reasons: it restores the invariant instead of describing its breakage; the hold path and its acknowledgement exist
(their tests, and the one B1 adds, are in design.md §0); the worker's `seen_inputs` rule (`seq < lastRequest`)
becomes exact, since nothing is written between a step's `asuna/stage` mark and its response. Cost: no prefix cost (new suffix either
way); a line waits at most one request (median 3.3-10.7 s at high cache share, up to about 28 s cold).

Not chosen:
- **Append at once, marked as new** (「回合中到的」 with time): the order stays false, the mark describes it, and the
  mark is program-computed state needing a versioned table. A mark cannot make a call that did not see the line look
  as if it had.
- **Hold to the next turn** (as the local Web chat does): her turn could not take a correction that arrives while she
  works; in QQ 21.8% of turns have a mid-turn line.

### D2. A claim that someone said something points at the line that said it

`write_document` takes `line`: the number of the line the item rests on (the 〔n〕 at the end of its label line) or
「这条」, the one form every pointer has (ADR-079 §9.4, `People.line_of`). When `line` is given, the program resolves
it in this conversation and sets `from` itself: 主人定的 when the line is the owner's, 别人说的 when it is another
person's. A program line (`asuna:internal`) is nobody's and anchors nothing (ADR-089). The result names the line in
the pointer form (`People.pointed`: number, speaker, time, first words), so she sees at write time what the claim
now rests on. The anchor is stored with the item and shown with it wherever the item is shown.

When 别人说的 or 主人定的 is given without a line, or the line does not resolve, the write goes through recorded as
我自己的判断, and the result says so and how to anchor it (a later `replace_section` with `line`). 查过的 and
我自己的判断 are unchanged (`memory_tiers.signing`).

So that every line can be pointed at, every line shows its number, in every conversation (today only where the
channel carries quotes, `capabilities.numbered`; ADR-079 §9.2). `speak`'s `quote` stays only where the channel
carries it.

Summaries: the compaction instruction (ours, `compaction.js`) asks that every item saying who said, decided, promised
or corrected something end with the 〔n〕 of the line it rests on, copied from the label line, that an item carried
from an earlier checkpoint keep its 〔n〕, and that an item with no line be written as the summarizer's account. The
existing 「（凭：谁在什么时候说的或做的那一句）」 becomes that 〔n〕. The program puts one fixed line at the head of
every checkpoint body saying what it is (D3). A claim in a summary can then become someone's only through D2's
anchor, which resolves against the stored line, not against the summary.

Reasons: refusing an unanchored write costs a retry and invites any number to make it pass; recording it as hers
keeps the write and makes the record true; the resolution is mechanical, in a store the program owns. The program
still cannot check that a line says what she claims; the result shows her the line's opening words so the check is
in front of her when she writes (her habit is writing first and checking later).

Not chosen:
- **Refuse an unanchored 别人说的** (the brief's other option): see above.
- **Accept it flagged unverified**: two kinds of 别人说的 that a reader cannot tell apart, and the flagged one still
  reads as theirs.
- **Anchor by speaker only** (the speaker has a line in this conversation): incident A's sender had a real line; this
  check would pass the sourceless claim.

Cost: the spec change (a field, its sentence) rides on B4's one cold request; ~30 characters on an anchored write's
result; about 6 characters on each new line in the conversations that showed no number (agent lines, peer lines, the
local Web chat), no prefix cost. The numbers come with B2, together with the compaction instruction that asks for
them, so a summary has a number to copy in every conversation; `line` itself, a spec change, waits for B4.

### D3. What Asuna writes into her conversation carries its source at the front

Within what Asuna writes, every user-role message that is not a person's line starts with a fixed mark from one
versioned table (design.md §5): the stage notice, the restore notice and every repair notice start with 〔程序〕;
a checkpoint body starts with a fixed line marked 〔摘要〕 that says the compactor wrote it from an earlier stretch of
this conversation, that a 〔n〕 names the line an item came from, and that an item without one is the compactor's
account. A person's line keeps its label line, which is its mark. The marks are written when the message is written,
so they are in the session file and the Web page as she reads them. The mark is the message's own first line, so a
stage notice's body (a JSON object, `index.js:812`) starts on the next line; B0 runs a real notice through every
reader of that text before B2 installs it. A platform notice inside a line (`notices.MARK`, 「（平台通知）」, after
its label line) is a different thing: a line the platform relayed, which keeps its label line and that mark; the
table of design.md §5.1 lists both so they are versioned together.

Reasons: the marks are new suffix (no prefix cost); one table; the session file shows what the model read. 〔程序〕
says itself, so the marks need no system-prompt change.

What Asuna cannot write: DSH's English checkpoint preamble, which frames every checkpoint as established background
(`dsh-compaction-basic/lib/index.js:280`), and DSH's runtime-context snapshots. Both are requests to the owner (R1, R2).

Not chosen:
- **Marks rendered at request time** from `source` in the `llm/stream` waterfall (where ADR-098 contracts roots):
  it would cover DSH's two kinds without a DSH change, but the request would differ from the stored conversation,
  replacing DSH's preamble in flight depends on its exact string across upgrades, and introducing it costs one cold
  request per conversation.
- **Re-rendering old messages** with marks: one full re-read per conversation for messages compaction folds anyway.
- **A role other than user** for program messages: DSH's mapping; a mid-conversation system message is not something
  every chat template accepts.

### D4. The tool interface

**D4a. One rule per kind of limit, stated where she reads it.** Four kinds (design.md §3):
- *Her prose* (think, plan intent, ideas, notes, ask, stay_silent, set_policy, restart, feel and write_document
  reasons, understanding text): an aim and a line, both stated in the description: 「（N 字以内，过了 M 字不收）」. A
  text between is kept and its result says the fact without leniency: 「L 字，要求 N 字以内，多了 K 字；过了 M 字不收」
  ("这次照收了" goes). Past M it is refused (D4c). The numbers do not move: think keeps 120/360 (ADR-087 §4.1); the
  rest keep four fifths (`config.soft`). Fields with a line but no stated number today (write_document `why` 2,000,
  feel `why`) join this kind.
- *Exact* (names, identifiers, searches, sticker names): one number 「（最多 N 字）」, unchanged.
- *Safety caps* (20,000 and over: delegate `brief`, task `message` and `answer`): a failure catch, not in the
  description (ADR-054), no aim, no soft band; the refusal states it.
- *Counts and budgets that depend on state* (calls and speak lines per turn, carried budget, group notes): already
  stated as aim and line where she reads them (ADR-084 step 7: 「提醒线 9，硬线 24」, 「你平时 3 行以内，硬线 6」;
  ADR-096 room on every write); their refusals take D4c's form.

Reasons: the house already states both numbers for counts, on her evidence that numbers move her and judgement words
do not (ADR-084 §4, her change 3); prose is the one kind that hides its line, and the kind with the most length
refusals (308 + 128 + 165). This is her 10-22 condition (2) in ADR-054, which the owner declined that morning with the
rule that both numbers come back if the refusals rise; whether that reading has fired was not measured by the
surveys. **The owner said yes on 2026-10-29.** That rule becomes D4a's acceptance condition: in B4's reading, length
refusals per field are no higher than in the week before the install; if they are higher, D4a is looked at again
before the next batch. Cost: description wording, in B4's one cold request.

Not chosen: one number that is the line (a model that does not count would be refused near it, and carried length
drifts toward the stated number, as thoughts grew after 10-14, ADR-087 §3); keeping the hidden line (the inconsistency
she named).

**D4b. One refusal names every problem the program can find, best effort** (the owner's recommendation, binding).
The checks run in six layers, 0 to 5; a layer's problems are collected, and a later layer runs only on what the
earlier ones left valid (design.md §1). Best effort means: a refusal names every problem of every layer that ran, up
to the layer that stopped; it does not predict what a later layer would find on fields that failed earlier, and
those problems come with the next call. Where it applies: layer 3's general checks for every tool from B3; a
handler's own checks only for the tools in the split set (design.md §1.3), each from its split on; a tool outside
that set reports its own first failure, as today. The list has no cap on problems, since each field or part gives
at most one per layer; when the refusal passes 1,500 characters, each candidate list keeps its first three and adds
「还有 N 个」, and no problem is dropped (a dropped problem is the extra call this decision removes). The layers:

0. The call can be read: the tool exists in this conversation, the arguments are an object, the call id is not
   reused, and the arguments meet the declared schema (the guard checks it before DSH's own check would, and names
   every violation at once). Stops alone: nothing else is defined.
1. Shape repair, no state (D4d).
2. Permission: the tool or option is usable in this turn and place (`not_now`, home authority, owner-private
   documents). Stops alone, naming what does the job here (D4c): the fix is another tool or another turn, so argument
   problems listed beside it lead to a corrected call that is refused again.
3. Every argument and the turn, collected: schema after repair, THINK_FIRST, the call cap, lengths, enums, empty
   fields, field pairs (`who` on a mood that takes none, `pin` outside group notes).
4. State, collected for the fields layer 3 passed: section, ref, label, plan id, schedule spec, line anchor; then the
   checks on the write's result (carried budget, group-note size, signing, gist), which need their target found.
5. The effect. A failure here (a race, a store fault) is one refusal, as today.

The strict schema check moves out of the guard, which is synchronous and runs after `tools/pre-execute` (dsh-tools
`prepareExecution`), into her tools' own `execute`, which is async and ours (`index.js:1414-1445`). DSH's `defineTool`
wraps that `execute` in its own validation against the declared schema, and the pinned DSH is built on as it is
(AGENTS.md), so the work is split between two schemas:
- **The declared schema** (what DSH registers, validates and shows the model) is permissive: `required` only for what
  the program cannot infer, and types widened to the shapes she writes that the program repairs (`parts` declared
  `json`, which DSH's subset already has, as set_policy's `value`; `doc`, `do`, delegate `title` and a part's `kind`
  optional); no field declares an enum, and each enum field's description lists its values. The guard's check of
  it, and DSH's own behind it, then pass every shape the program repairs and every enum value, and still refuse
  what the declared schema keeps: a value of the wrong type, or a missing field the program cannot infer.
- **The strict schema** stays inside the program, beside the repair table. Our `execute` repairs a copy of the
  arguments, validates the copy fully against it (DSH's `validateArgs`, or our own), and hands the repaired arguments
  and every violation to the worker, which adds the other layers' problems and builds the one refusal.

The guard keeps layer 0: "not in this conversation", and from B4 the declared-schema check (through B3 it checks
the strict schema, as today). Its refusals stop alone and have no audit row, because a guard is synchronous and
cannot ask the worker; they are counted from the session files by their wording. DSH's own English refusal behind
the guard is not reached (none on her character brain since 2026-10-18 UTC, design.md §9). From B3 on, every refusal
past layer 0 has a `role_tool` audit row with its codes; today the 206 refused before the worker have none. Cost: the
declared-schema change is a spec change and rides on B4's one cold request, with the other spec changes.

The risk this leaves: the model reads the declared schema, so a permissive declared schema must still say what the
program wants. Each widened field's description carries the strict form (「parts：一个列表，每条一个对象」;
「doc：文档名；不写时按 section 找」), each enum field's description lists its values, and the guard's schema
refusals by the shapes of design.md §4 in B4's reading show whether the descriptions carry it.

The worker's general checks (layers 2-3) apply to every tool from B3; a handler's own checks collect
only once that handler is split into a check part and an effect part (the tools with most failures first:
write_document, plan, think, note, feel, delegate, speak, ideas, task). A handler not yet split runs as today when
the general layers pass. The survey's estimate of what this saves is 44-156 failures (1.6-5.7% of the 2,747 counted
from session files, the pre-worker layer included), same-tool chains only.

**D4c. Refusal texts carry the program's knowledge, not her text.**
- No refusal repeats her prose. A short value of hers that is an identifier (a ref, a label, an enum value she wrote)
  may be named; nothing longer. The length refusal stops offering the cut (`cut_offer`, her ask of 10-20; **she said
  yes on 2026-10-29**): the offered cut is the text she just sent with the excess removed, which does not tell her
  where the line is and does not judge for her which part to drop. It says instead where the excess starts, by
  characters: 「360 字之后起是超出部分」; a list field (plan intent, idea, errand request, note) also gives the line it
  falls in: 「第 s 行（共 t 行）」. Sentences are not counted (the program has no sentence splitter, and her prose often
  has no sentence end).
- A length refusal says the line, by how much she went over, the aim, and where the line comes from, from one table
  of reasons per field (design.md §2): what that text is carried into.
- Where a candidate exists, the refusal gives it ready to copy (section ids, refs, labels, plan ids, documents
  holding a section of that name), the most likely first, at most 12 (`config.refs_usable`).
- What a refusal lists as allowed is produced by the same predicate that accepts. Today `understanding.resolve` and
  `watch` match with `people.resolve` but list with `people.speaker` / `ensure_roster`, so a refusal can list the
  value it refused (`understanding.py:268-276`, `role_tools.py:2558-2565`).
- A permission refusal ends with what does this job in this turn, from one table of alternatives per ability
  (`INSTEAD`, design.md §2) intersected with the turn's tools; when none, when it can be done.
- The combined refusal lists its problems numbered, THINK_FIRST first when present; the record keeps every code, so
  readings classify by code, not wording (1,062 of 2,747 refusals were unclassed by wording; 2,747 is the serial
  count's base, and the survey's count by layer gives 2,746 by another deduplication rule).

**D4d. The schema asks only for what the program cannot work out.** Where her habit is reasonable, the shape takes it.
The shapes, their counts and their repairs are listed once, in design.md §4; this list is their summary:
- write_document without `doc`: the document holding a section of that name among those she may write here, when
  exactly one does; in a group outside an errand, `group_notes`. Otherwise a layer-4 problem listing the candidates.
- write_document without `do`: inferred from the fields, as task, ideas and ask already are (`infer_op`): `heading`
  without `section` is `append_section`; `section` with `content` is `replace_section`; `section` with only tag fields
  is `set_tags`. The result says the inferred `do`, as today for the others.
- `from` outside its four values: largely gone with D2's `line`. The declared schema declares no enum, so a value
  outside it reaches the strict schema and is a layer-3 problem combined with the rest. What still stops alone at
  layer 0 is what the declared schema keeps (a wrong type, a missing field the program cannot infer); it hides the
  later layers' problems behind it, and in UTC days 10-18 to 10-28, 4 of the 20 schema refusals followed by a
  refusal of another class were of that kind (design.md §8, the floor of B4's gate).
- `speak` `parts` written as a JSON list in a string: parsed. A part with no `kind` and exactly one kind's field:
  that kind. A part key that is one of speak's own fields (`quote`, `wait`): lifted. Anything else: a problem.
- delegate without `title`: the brief's first sentence, cut to the aim (64), named in the result.
- Field synonyms seen in refused calls (`note` for `text`, `place` for `to` on note): accepted, from one declared
  table shipped with the specs.

In the declared schema `required` leaves `doc`, `do`, `title` and a part's `kind`, and `parts` is declared `json`
(D4b); the strict schema inside the program keeps them as they are. Cost: B4's one cold request.

### D5. A program-woken turn says what woke her and whose words its event holds

A turn opened by the program carries no `speaker`. It carries `woken_by_program`, from one versioned table by episode
kind (design.md §5), saying what woke her and who wrote the event's text: the action brain for a task result or a
question; her own plan, visit, heartbeat, self-development or night settlement; her own note from another
conversation. The person who authorized the turn stays on the episode for authority, as today; it is not shown as
someone speaking. A person's line that arrives during the turn comes as a line (D1). A person-woken turn keeps
`speaker` as it is.

Reasons: on a task result today the head names the person who asked for the task beside the action brain's text,
the precondition for attributing that text to the person (incident A's shape). Cost: notice content, new suffix; a
few tens of characters per program-woken notice, less the `speaker` it drops.

What changes with it: `tests/test_author_is_who_wrote.py:62` and `:81` assert that a task-result and a due-plan turn
carry the person's `speaker`. B2's builder changes them to assert no `speaker` and the table's words, and keeps their
assertions that authorization still reads the person (`person_id`, the session class). The turn instruction's line on
`_from_program` (`turn.md:2`, and the same line of `turn_thinking.md`) gets a clause for `woken_by_program`; it is in
her system prompt (`block_guide.guide`), so it rides on B4's one cold request, and until then the key's own words say
what it is.

Not chosen: `speaker: 程序` (the program is never a person, ADR-089); leaving the key out with nothing in its place (an
empty speaker slot is one a model fills, system survey §4).

### D6. No request record is added

The fixes are proven from records that exist: D1 by the order of events in the session files (no channel line
between a step's `asuna/stage` mark and its assistant message); D3 by the message text itself; D4 by the tool
results and the `role_tool` audit rows with their codes; D2 by the stored items and their anchors; D5 by the notice.
Two facts the design rests on need a sight of a real request once (whether DSH's runtime-context snapshots reach her
lanes, and that a held line lands after the step's result): B0 shows both on an isolated demo profile with synthetic
inference, which writes nothing on her data and calls no model. So there is no new state and no lifecycle to keep.

If a later finding needs real requests, the smallest form is an owner-switched capture of the next N requests of one
conversation into `<data>/private/`, read by the owner only (her context is private), removed when its evidence is
exported; it would get its own ADR.

## 3. Consequences

- Her conversation's order is true; a mid-turn line waits up to one request.
- A record of someone's word points at their line or is hers; summaries carry line numbers; every line shows its
  number.
- Program text she reads is marked as the program's; checkpoints say what they are, in Chinese, beside DSH's English
  preamble until R1.
- One refusal per call says everything the program found, without her words; the schema takes the shapes she writes.
- Program-woken turns say who wrote their event.
- Cache: one cold request per open conversation at B4's install (tool specs); nothing else touches the prefix.
- Reversed: ADR-054 "What she reads names only the ask" (owner) and the offered cut (her ask); ADR-079 §9.2 numbers
  only where quotes are carried. Changed: the strict schema check moves from the guard (tool-args.js) into her tools'
  execute, against a strict schema the program keeps; the declared schemas become permissive, and the guard checks
  them.

## 4. Requests to the owner for DSH

DSH is the owner's (pinned, `tools/dsh-inline/source.json`); none of these blocks a batch.

| | What | Smallest form | Why |
|---|---|---|---|
| R1 (the owner takes it, 2026-10-29) | The checkpoint preamble can be the engine's own | `frameSummary` reads the preamble from the engine (`this.constructor.CHECKPOINT_PREAMBLE`, a static field of `BasicCompactionEngine`), so `RoleCompactionEngine` sets it | Today every checkpoint opens in English with "treat as established background", which presents the compactor's account as confirmed, the opposite of D3's line, and is outside the one-language rule |
| R2 (decided after B0) | Runtime-context snapshots are not added to a lane that suppresses the runtime context | `suppressRuntimeContext()` also stops the snapshot messages (`working-directory`, `approval`/`sandbox` policy) | 959 such messages in her workspaces' session folders (action-brain sessions included), 276 right after her own TURN notices; deployment details do not belong in her context (AGENTS.md). Conditional on B0 showing they reach her requests |
| R3 (dropped by the owner, 2026-10-29) | A tool can normalize its arguments before DSH validates them | a `defineTool` option `normalizeArgs(args)` run before `validate` | Not needed by any batch: D4b works with a permissive declared schema and a strict one kept inside the program. With this hook the two schemas could be one, declared and strict |

Not requested: `source` reaching the model as data (D3 writes it into the text), the role mapping, the `Error: `
prefix on tool errors, what `request/header` records (D6), the surface order of appended messages (D1 holds instead).

## 5. Build plan

Each batch has one builder, goes to review on its own, and is read on her real turns 7 days after its install. A
verdict is pass or fail; a fail is looked at before the next batch builds on it.

| Batch | What | Prefix cost | Proves, and how |
|---|---|---|---|
| B0 | Facts, on an isolated demo profile with synthetic inference: `step/start` precedes `agent/request`; a line held over an open step lands after the step's result; DSH's validation passes a call in each widened shape against the permissive declared schema, still refuses one outside it, and our `execute` receives the passed call as she wrote it; whether runtime-context snapshots reach a character request; whether `source` is on the messages at `llm/stream`; whether a held line is released when its step's request fails; a real stage notice with its 〔程序〕 first line read by every reader of a notice's text (the Web client, compaction, the restore path) | none (no live change) | each a yes or no, recorded in this ADR; R2 is sent or dropped on it |
| B1 | D1: hold over an open step (`navigation.js`, `pairing.js`); release on a failed step; no absorbing into a turn without `speak` there | none | in her session files after install: channel lines between a step's `asuna/stage` mark and its assistant message, 0 (today in 93% of turns with a mid-turn line); every held receipt acknowledged; hold time at most its step plus a second; the test that joins a stop while held to the next start (design.md §0) |
| B2 | D3 marks and the checkpoint head line; D5 `woken_by_program`; every line numbered, and the compaction instruction's line numbers (D2, summary part) | none | notices, repairs and checkpoints written after install all start with their mark; no program-woken notice carries `speaker`; share of new checkpoint items that carry a 〔n〕 (counted by the program, numbers only) |
| B3 | D4b layers and D4c texts: the check in her tools' execute, the worker's collected layers, the split of the nine handlers, `INSTEAD`, one predicate for listed values | none (tool results only) | same-tool second refusals of another class in the same turn below 2% of failures (5.7% today, same base); no refusal holds 20 or more consecutive characters of the call's prose (program check, numbers only); every refusal past layer 0 has an audit row with codes; layer-0 refusals counted from session files by wording, and DSH's English refusal still 0 on her character brain |
| B4 | Every spec change in one install: D4a wording, the permissive declared schemas with D4d's repairs (and the guard checking them), D2 `line`, the turn instruction's clause for `woken_by_program` | one cold request per open conversation | the guard's schema refusals by the shapes of design.md §4, per 1,000 calls, from 7.4 (101 in UTC days 10-18 to 10-28) to at most 1.5, against a floor of 1.0 (the 14 that B4 leaves refused: missing fields the program cannot infer); schema refusals followed in the same turn by a refusal of another class on the same tool, per 1,000 calls, from 1.5 (20 in 13,588 calls) to at most 0.4, with the count beside it (at most 5 in 11 days) and its floor (4: what B4 leaves stopping alone), window and counting rule in design.md §8; D4a's condition: length refusals per field no higher than the week before; cache readout shows one cold first step per conversation, then the usual share; every 别人说的 / 主人定的 written after install resolves to a line, and the unanchored ones are recorded as hers with the result line |
| B5 | Only if B2's count warrants it: the program checks each 〔n〕 in a new checkpoint against the stored line's speaker and notes mismatches under the checkpoint | none | built or dropped on the measured mismatch rate |

B1 and B2 can install together on one restart; B3 needs nothing from DSH. Through B3 the guard checks the strict
schema, as today: while the declared schemas are strict, a call that fails them would otherwise meet DSH's own
English refusal before our `execute`. B4 widens the declared schemas and points the guard at them in the same
install, so the problems the strict schema adds join the one refusal from B4 on. B4 is the only batch with a prefix
cost and carries every spec change at once.

## 6. Open questions

1. Settled by the owner on 2026-10-29: think keeps 120/360 (3x room) while every other prose field has 1.25x; D4a
   changes only what she reads.
2. Lines from another conversation: D2 anchors only in the conversation where the line was said; a claim heard
   elsewhere is recorded as hers until a handle across conversations exists (recall could return one).
3. The local Web chat: the owner's typed lines enter without a label line, so only 「这条」 can point at them today;
   whether Web lines get a label line is open.
4. Whether `understand_person`'s "他说的 / 你推的" split should take the same anchor; not in this ADR.
5. The wording of every table in design.md is a draft for Xiaoman's reading. The reasons per field (§2.1
   `LIMIT_WHY`) and the words per code (`WORDS[code]`, §1.4) are written at build from the code that carries each
   text, checked against it, and go to Xiaoman to read before they are installed.
6. The about 3x multi-failure rate of program-woken turns (structural survey Q7: 11.6% against 3.7%); D5 addresses who is speaking, not the rest
   of that rate (turn rules, D4c's alternatives may cover some).
7. B3's 2% threshold is an engineering guess from the survey's split (44 pure-argument chains of 156); it may move
   once B3's codes give a clean count.

## 7. Evidence

`.runtime/private/tool-failures/` (local, never committed): `survey-out-1029.txt` (structural survey, Q1-Q5),
`survey-q67-1029.txt` (its Q6-Q7: incident turns and wake classes), `survey-days-1029.txt` (per UTC day),
`survey-q3stats-1029.txt` (refusal families and literal shares), `survey-q8-1029.txt` and `survey-q9-1029.txt` (the
identifier count and the refusals by who wrote them), `survey-q10-1029.txt` (what follows a schema refusal: B4's
baseline), `system-survey-1029.md` (system survey), the briefs, and
`scripts/` (the survey scripts that compute every number here, about 110 KB; their formulas are in design.md §9). No
text of hers or anyone's is quoted here; numbers are the surveys', texts are the program's own from source.
