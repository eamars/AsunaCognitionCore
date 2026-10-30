# ADR-108: Her tool interface, and what enters her turn

Status: **Proposed** 2026-10-29. Written by the design agent (Claude) from the lead's brief, after two surveys of
the same day (structural and system, section 7). Built in one pass on the branch `claude/keen-turing-nylmyr`
(section 9); not landed. Next: the lead integrates it, Xiaoman reads section 8 and the finished words once, one
landing. The detail each decision needs to be built is in [design.md](design.md).

Decision D4a reverses an owner decision of 2026-10-22 (ADR-054, "What she reads names only the ask") and D4c one of
her asks (ADR-054, the offered cut showing what it leaves out). The owner said yes to D4a on 2026-10-29; Xiaoman said
yes to D4c on 2026-10-29, in the form D4c now states (the excess located by characters, not by sentence).

Revision 2 (2026-10-29, Claude, [section 8](#8-revision-2-2026-10-29)) closes the gaps a check against the code and
the pinned DSH source found, and fixes how the work is built and signed: in one pass, as one product (the owner's
requirement of the same day). It changes no decision D1 to D6. Xiaoman's signature at
`bdbac55c952c` covers sections 1 to 7 as they stood; section 8 is new and she has not read it. Text it replaces is
marked where it stands and kept as it was designed.

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

*(Revision 2, 8.4 item 7: in this section and the next, "B1" to "B4" name rows of section 5, and "from B3", "through
B3", "waits for B4", "B4's one cold request", "before B2 installs" and "the next batch" mean the one build and its one
install.)*

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
*(Revision 2: in the local Web chat the number goes into the turn's notice, not onto the line (A3); the anchor's
whole lifecycle is A7.)*

### D3. What Asuna writes into her conversation carries its source at the front

Within what Asuna writes, every user-role message that is not a person's line starts with a fixed mark from one
versioned table (design.md §5): the stage notice, the restore notice and every repair notice start with 〔程序〕;
a checkpoint body starts with a fixed line marked 〔摘要〕 that says the compactor wrote it from an earlier stretch of
this conversation, that a 〔n〕 names the line an item came from, and that an item without one is the compactor's
account. A person's line keeps its label line, which is its mark. The marks are written when the message is written,
so they are in the session file and the Web page as she reads them. The mark is the message's own first line, so a
stage notice's body (a JSON object, `index.js:812`) starts on the next line; B0 runs a real notice through every
reader of that text before B2 installs it. *(Revision 2, A4: the readers were read in the code and none parses the
text; there is no B0.)* A platform notice inside a line (`notices.MARK`, 「（平台通知）」, after
its label line) is a different thing: a line the platform relayed, which keeps its label line and that mark; the
table of design.md §5.1 lists both so they are versioned together.
*(Revision 2, A4: the character lane only, and the mark is added in the two places that build her notices, not per
kind.)*

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
  table shipped with the specs. *(Dropped, Revision 2, A8.)*

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
*(Revision 2, A10: both are settled from DSH's source (8.2) and held by tests of the product; there is no B0.)*

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
| R1 (the owner takes it, 2026-10-29) | The checkpoint preamble can be the engine's own | `frameSummary` reads the preamble from the engine (`this.constructor.CHECKPOINT_PREAMBLE`, a static field of `BasicCompactionEngine`), so `RoleCompactionEngine` sets it *(shape corrected, Revision 2, A9)* | Today every checkpoint opens in English with "treat as established background", which presents the compactor's account as confirmed, the opposite of D3's line, and is outside the one-language rule |
| R2 (closed by us in the build, Revision 2 A11; was: decided after B0) | Runtime-context snapshots are not added to a lane that suppresses the runtime context | `suppressRuntimeContext()` also stops the snapshot messages (`working-directory`, `approval`/`sandbox` policy) | 959 such messages in her workspaces' session folders (action-brain sessions included), 276 right after her own TURN notices; deployment details do not belong in her context (AGENTS.md). Conditional on B0 showing they reach her requests |
| R3 (dropped by the owner, 2026-10-29) | A tool can normalize its arguments before DSH validates them | a `defineTool` option `normalizeArgs(args)` run before `validate` | Not needed by any batch: D4b works with a permissive declared schema and a strict one kept inside the program. With this hook the two schemas could be one, declared and strict |

Not requested: `source` reaching the model as data (D3 writes it into the text), the role mapping, the `Error: `
prefix on tool errors, what `request/header` records (D6), the surface order of appended messages (D1 holds instead).

## 5. Build plan

Each batch has one builder, goes to review on its own, and is read on her real turns 7 days after its install. A
verdict is pass or fail; a fail is looked at before the next batch builds on it.
*(Replaced, Revision 2, 8.4: one build, one landing, one acceptance, one sign-off. The batch names below are the rows of
what the build contains. B0 is not built (A10); B5 is not in the build.)*

| Batch | What | Prefix cost | Proves, and how |
|---|---|---|---|
| B0 | Facts, on an isolated demo profile with synthetic inference: `step/start` precedes `agent/request`; a line held over an open step lands after the step's result; DSH's validation passes a call in each widened shape against the permissive declared schema, still refuses one outside it, and our `execute` receives the passed call as she wrote it; whether runtime-context snapshots reach a character request; whether `source` is on the messages at `llm/stream`; whether a held line is released when its step's request fails; a real stage notice with its 〔程序〕 first line read by every reader of a notice's text (the Web client, compaction, the restore path) | none (no live change) | each a yes or no, recorded in this ADR; R2 is sent or dropped on it |
| B1 | D1: hold over an open step (`navigation.js`, `pairing.js`); release on a failed step; no absorbing into a turn without `speak` there | none | in her session files after install: channel lines between a step's `asuna/stage` mark and its assistant message, 0 (today in 93% of turns with a mid-turn line); every held receipt acknowledged; hold time at most its step plus a second; the test that joins a stop while held to the next start (design.md §0) |
| B2 | D3 marks and the checkpoint head line; D5 `woken_by_program`; every line numbered, and the compaction instruction's line numbers (D2, summary part) | none | notices, repairs and checkpoints written after install all start with their mark; no program-woken notice carries `speaker`; share of new checkpoint items that carry a 〔n〕 (counted by the program, numbers only) |
| B3 | D4b layers and D4c texts: the check in her tools' execute, the worker's collected layers, the split of the nine handlers, `INSTEAD`, one predicate for listed values | none (tool results only) | same-tool second refusals of another class in the same turn below 2% of failures (5.7% today, same base); no refusal holds 20 or more consecutive characters of the call's prose (program check, numbers only); every refusal past layer 0 has an audit row with codes; layer-0 refusals counted from session files by wording, and DSH's English refusal still 0 on her character brain |
| B4 | Every spec change in one install: D4a wording, the permissive declared schemas with D4d's repairs (and the guard checking them), D2 `line`, the turn instruction's clause for `woken_by_program` | one cold request per open conversation | the guard's schema refusals by the shapes of design.md §4, per 1,000 calls, from 7.4 (101 in UTC days 10-18 to 10-28) to at most 1.5, against a floor of 1.0 (the 14 that B4 leaves refused: missing fields the program cannot infer; the system survey counted 102 for the same span, and the 1 was not traced); schema refusals followed in the same turn by a refusal of another class on the same tool, per 1,000 calls, from 1.5 (20 in 13,588 calls) to at most 0.4, with the count beside it (at most 5 in 11 days) and its floor (4: what B4 leaves stopping alone), window and counting rule in design.md §8; D4a's condition: length refusals per field no higher than the week before; cache readout shows one cold first step per conversation, then the usual share; every 别人说的 / 主人定的 written after install resolves to a line, and the unanchored ones are recorded as hers with the result line |
| B5 | Only if B2's count warrants it: the program checks each 〔n〕 in a new checkpoint against the stored line's speaker and notes mismatches under the checkpoint | none | built or dropped on the measured mismatch rate |

B1 and B2 can install together on one restart; B3 needs nothing from DSH. Through B3 the guard checks the strict
schema, as today: while the declared schemas are strict, a call that fails them would otherwise meet DSH's own
English refusal before our `execute`. B4 widens the declared schemas and points the guard at them in the same
install, so the problems the strict schema adds join the one refusal from B4 on. B4 is the only batch with a prefix
cost and carries every spec change at once.

*(Revision 2 replaces this plan's stages with one build (8.4), drops B0 and replaces B4's anchor condition (A10), and
changes what B1, B2 and B4 build (A1 to A8, A11). With one install there is no "through B3": from the install the guard
checks the declared schema and the strict one runs in `execute`.)*

## 6. Open questions

1. Settled by the owner on 2026-10-29: think keeps 120/360 (3x room) while every other prose field has 1.25x; D4a
   changes only what she reads.
2. Lines from another conversation: D2 anchors only in the conversation where the line was said; a claim heard
   elsewhere is recorded as hers until a handle across conversations exists (recall could return one).
3. The local Web chat: the owner's typed lines enter without a label line, so only 「这条」 can point at them today;
   whether Web lines get a label line is open. *(Closed, Revision 2, A3: the number goes into the notice.)*
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

## 8. Revision 2 (2026-10-29)

Written by Claude (the lead) after checking sections 1 to 7 against the code at `196b6f6` and against the pinned DSH
source (`4000a552`, `tools/dsh-inline/source.json`; the DSH paths below are in that repository). It changes no
decision D1 to D6. It closes gaps in how they are built, and it fixes how they are built and signed. Xiaoman's
signature at `bdbac55c952c` covers sections 1 to 7 as they stood; this section is new and she has not read it. The
detail is in [design.md](design.md) section 10.

The owner's requirement (2026-10-29), in his words:

> This plan will be built in one pass. There will be no staged build artifact or test. The system will be sign off as a
> full product, not at each stage.

### 8.1 Why a revision

- The page was pinned at `5a196e66`. ADR-104's finish landed after it and deleted the unit tests that needed a
  database (`34150388103f`), among them the ones the page names for D1 and D5.
- A census of the consumers of one predicate and of the messages Asuna writes found uses the page did not count.
- The pinned DSH source answers every question B0 was to answer that the design still needs, and shows that
  `agent/turn-stopping` is not where a failed step's held line can be released.
- The owner's requirement above makes the batch plan of section 5 a list of what one build contains, and leaves no stage
  in which a wrong assumption could be shown before the whole is installed. What a stage would have shown has to be
  settled by reading, or held by a test of the product, before the build starts (8.2, 8.4).

### 8.2 What the pinned DSH source answers

| Question | Answer | Where |
|---|---|---|
| The order inside a step | `agent/pre-step` (Asuna releases held lines) → `step/start` → `step()`: `agent/request`, then the claimed messages (the stage notice) appended, then the request built from the surface, the stream, `assistant/message`, the tool calls and their results → `step/end`, appended in a `finally` | `core/agent-loop/src/agent.ts:275, 331, 358, 427, 551, 594` |
| Where a failed or aborted step ends | The step's error leaves the loop; `step/end` and then `turn/end` are still appended; `agent/turn-stopping` is dispatched only after a step that returned. A held line is released at `step/end`, not at `turn-stopping` | `agent.ts:344-362, 368-387` |
| A retried request | Rebuilt from the surface (`continue`): a line appended during the failed attempt is in the retry; a held one stays held | `agent.ts:526` |
| A hung request | The stream idle watchdog ends a stalled stream at `streamIdleTimeoutMs`, 300,000 ms by default, as a `TIMEOUT` error into the request-error waterfall. No behaviour below depends on the profile's value | `llm/llm-pi-ai/src/config.ts:47`, `adapter.ts:391`; `llm/llm-deepseek/src/defaults.ts:4` |
| `source` at the adapter | Dropped: each message that is not a tool result is sent as `{role: 'user', content: text}` (finding 3 holds) | `llm/llm-pi-ai/src/context.ts:254, 371` |
| Validation | `defineTool` validates before the tool's `execute`, throws `ToolArgsError`, and passes `args` to `execute` unchanged. A missing `required` property is a violation; an undeclared key is one only where `additionalProperties: false` is declared, and the parameter root is open; `integer` and `string` are strict (`"3"` is not an integer); `json` takes any lossless JSON value, a string included. So the permissive declared schema of D4b is supported as designed. The order pre-execute, guard, dispatch is `prepareExecution` | `core/tools/src/schema.ts:597-599`, `json-schema.ts:560-640`; `core/tools/src/index.ts:1501-1543` |
| Runtime-context snapshots (R2) | `suppressRuntimeContext()` removes optional contexts (`approval:policy`, `sandbox:policy`) and keeps required ones; `working-directory:current` is registered `required: true` and is restored at every step, so `Current working directory: "…"` reaches a lane that suppresses. A context registered through the agent's own scope shadows a global one by name (DSH's own error text says so), and an empty snapshot is not projected on a session that never had one | `session/working-directory/src/index.ts:90-95`; `interaction/user-approval/src/index.ts:163`; `core/system-prompt/src/index.ts:408-413, 582-602`; `agent-loop/src/runtime-context.ts:152-163` |
| The checkpoint preamble | A module constant used by a free function, `frameSummary(summary)`, called once; there is no engine field to set (A9) | `compaction/compaction-basic/src/summarizer.ts:70, 188`; `region.ts:417` |

### 8.3 Amendments

**A1. The tests D1 and D5 name are gone.** `tests/test_native_product.py` and the two tests of
`test_author_is_who_wrote.py` were deleted (`34150388103f`). D1 is proved by JS tests on synthetic session events and one
worker test on the in-memory adapter; D5 by a new unit test that carries the two assertions that died (the turn still
reads `person_id` and `session_class`). No test needs a server (design.md §10.1).

**A2. `capabilities.numbered` is two questions.** It answers "do lines here show their number" and "can she quote by
it". The first is true whenever a row has a `scene_seq` (every input row has one); the second keeps the old body as
`can_quote` and gates only the quote hint at `context.py:1283`, which would otherwise tell her to write a number in a
`quote` field that her `speak` does not have on agent and peer lines (design.md §10.2).

**A3. The local Web chat (open question 3 closed).** The owner's Web line is DSH's native message and Asuna writes no
label line for it. Its number goes into the turn's notice (`event.line`), which stays on the surface; 「这条」 works as
before. So every line can be pointed at in every conversation, and the compaction instruction says where a Web line's
number is (design.md §10.3).

**A4. D3 as built.** The character lane only. The 〔程序〕 line is added in the two places that build her notices
(`message()` and `restored()` in `index.js`), not per kind; the action brain's notices and `relay()` stay as they are.
The checkpoint's 〔摘要〕 line is added once, to the final summary, and a copy of it in the model's output is removed
first. Nothing parses a notice's text (`visibleCarried` reads `source.carried`) (design.md §10.4).

**A5. D1 as built.** A line is held while a step is open (`step/start` to `step/end`) or a compaction runs;
`toolCallOpen` leaves the condition because a tool call lives inside a step. Release is at `agent/pre-step` and
`agent/turn-stopping` as now and at the `step/end` event, the one point every step passes, failed and aborted ones
included. A stalled request ends at DSH's idle watchdog (300 s by default, per attempt, with its retries); a step that
is still open when the worker's fence (`workflow_timeout_seconds`, 1,800 s by default) fires is cancelled by the host,
and `step/end` releases the line. We add no timer of our own (design.md §10.5).

**A6. Two sides at different versions.** *(Superseded by A12: the build adds no field between the two sides, so there
is nothing to skew.)*

**A7. D2's anchor, its whole lifecycle.** `line: {scene, seq}` on the item row beside `from`, no copy of the author;
it exists exactly while `from` is 别人说的 or 主人定的; a rewrite that restates neither keeps both; it shows as a
pointer in its own conversation and as 「出自别处的一行」 elsewhere; it is read at show time, so an erased line shows as
gone (design.md §10.7).

**A8. D4d's note synonyms are dropped.** They were never evidenced (the refusal words do not say what was written
instead) and cannot be reached (the guard refuses a missing `text` or `to` before `execute` could rename it); the
counts of section 5 already treat those refusals as the floor.

**A9. R1's smallest form, corrected.** `frameSummary(summary, preamble = CHECKPOINT_PREAMBLE)`, and its one call site
(`region.ts:417`) passing a value the engine holds (a `Config` field or an overridable method). It is the owner's, and
the build does not wait for it: until it lands, the checkpoint's English preamble stands beside the 〔摘要〕 line as
section 2 says.

**A10. No B0, and an acceptance that can fail.** B0 is not built: its facts are in 8.2, and the product's own tests hold
the assumptions that depend on DSH (design.md §10.9). B4's anchor condition ("without an anchor: 0") cannot fail,
because an unanchored write is recorded as hers; it is replaced by a check that every anchor resolves to a line of the
right author, with the share of writes that fell back to hers reported (design.md §10.8).

**A11. R2 is closed by us, in the build.** In her lanes other than the action brain's, the plugin registers through the
agent's own scope an empty context named `working-directory:current` (required, the same order), as it already blanks
DSH's developer sections by name. No request to the owner, no DSH change. A session that already holds a snapshot gets
DSH's one-time "Current runtime context: none" message after its history, and, for a session that had a snapshot before
the install, DSH's empty-snapshot line again after each later compaction (design.md §10.11).

**A12. The strict check runs in the worker, and no new field crosses between the sides.** The worker ships each tool's
declared (permissive) schema in `role_tool_specs`; DSH validates the call against it and the guard (`tool-args.js`)
checks it. The call reaches the worker's `RoleTools.call`, which repairs a copy of it, checks the copy against the strict
schema the program keeps (`tool_schema.py`), and joins every violation with the other layers' problems into one
numbered refusal. The JS sends the call as DSH passed it; it has no `strict` flag and sends no `given` or `violations`.
So an old guard with a new worker, and a new guard with an old worker, each do what they did before (design.md §10.6).

**A13. What the build does not do, and said so.** Each is a limit of this build, not an open decision:

- Layer 4a (state checks) is collected for the handlers that were split: think, delegate, the task answer, message and
  stop, the ideas note, feel, plan (making a plan, with its timing), write_document and speak. A plan's update and
  cancel, and `note` (the tool that sends a note), stop at their first failure as they did; `note`'s destination checks
  were not separated from its effect.
- A body rewrite of an item keeps its anchor: the anchor is where the item came from, and says nothing for the new text.
- An item written as 别人说的 or 主人定的 before the install stays as it is: no history is converted.
- An item's source is shown where the ledgers, the night list, her own-notes block and a group's notes are shown. The
  system-prompt blocks of the persona and the voice show none.
- A line erased after an anchor was set shows as gone, not as the line.

### 8.4 One build, one sign-off

The owner's requirement decides how the work runs:

1. **One build.** One builder, one branch (`claude/keen-turing-nylmyr`), one pass over [design.md](design.md). The rows
   B1 to B4 of section 5 name what the build contains; they are not stages. B1 to B3 have no prefix cost and B4 has one, so
   the install costs one cold request per open conversation. A fresh reviewer read the finished diff against the code
   before it was handed over, and what it found is fixed (section 9). B5 is not in the build: it is decided after
   acceptance, on the mismatch rate B2's count gives, and is its own work.
2. **No staged artifact or test.** Nothing is installed, probed or signed for a stage: no probe, no interim install, no
   per-batch gate. The product's tests ([design.md](design.md) §10.1) are written with the code; the builder runs them as
   it writes, as its own checks and not as gates, and the landing runs them again once with the checks already in the
   repository (§10.10).
3. **One landing.** The lead's landing script runs the tests and the push gate, fast-forwards and restarts once, while
   she is quiet and after telling her, and checks that the running code is the commit's.
4. **Her readings, and one sign-off.** Before the landing she reads this section once (one message from the lead, the
   changed parts only). The words the build writes from code (`LIMIT_WHY`, `WORDS[code]`, `INSTEAD`, `WAKE_WORDS`, the
   marks and the compaction rules) are in the build, finished; she reads them once at a frozen commit, before the
   landing. If she asks for other words, they change in those tables only (each table is one file, with a version
   constant that is raised with the text), as a text change on the same branch before the landing; no mechanism changes
   with a word, and she reads only what changed. That reading and her check by content after the landing are her part of
   one sign-off, of the product; it is recorded once, after acceptance.
5. **One acceptance.** Section 5's "Proves, and how" column and [design.md](design.md) section 8 are one table, read once,
   7 days after the install. The batch labels in it name rows, not stages. A fail is a defect of the product: it is fixed on
   a new branch and landed as a fix, and the product is not signed until the table passes or the owner accepts a stated
   residual.
6. **Because nothing is shown in between,** the design carries what a stage would have caught: the facts of 8.2 are read
   from source; each assumption that depends on DSH has a test of the product (§10.9); the builder stops at the first gap
   and goes back to design rather than guess. And the way back is one revert commit, landed by the same script: her
   self-development commits are made in the same checkout under her own name, so the branch is never reset. What the
   new code wrote stays harmless to the old (an item row's `line` is an extra field the catalog stores and returns
   unchanged; marks, numbers, `event.line`, `woken_by_program` and the 〔摘要〕 line are text in session files). The tool
   specs return to the strict ones, which costs one more cold request. No history is converted.
7. **Reading the staged words.** Where sections 2 to 7 and design.md say "from B3", "through B3", "waits for B4", "B4's
   one cold request", "before B2 installs", "the next batch" or "when B0 lands", they mean the one build and its one
   install, as the notes at section 2 and section 5 say; the rows B1 to B4 are the same rows of one acceptance table.

What stays open after this revision is what the page already lists: Xiaoman's reading of the finished words (open
question 5, item 4 above), B3's 2% threshold (open question 7), and the program-woken multi-failure rate beyond who is
speaking (open question 6).

## 9. As built

Built by Claude in the cloud, on the branch `claude/keen-turing-nylmyr`, in one pass; the commits after Revision 2
(`160968c`) are one build and are landed as one. The owner's pattern: the builder does everything that can be done
without her, then the lead integrates the build and talks to Xiaoman (a cloud session cannot reach her).

| Decision | Built in | Held by |
|---|---|---|
| D1 | `pairing.js` (`stepOpen`, `mustHold`, `releaseAtBoundary`), `navigation.js`; `coordinator._absorb` | `pairing.test.js`, `navigation.test.js` on a real DSH session with a step open; `test_woken_by_program.py`'s absorb cases |
| D2 | `role_tools.py` (`line`, `_anchored`, `_resolve`), `memory_tiers.py` (the anchor and its lifecycle), `people.py` (`source_of`), `carried.py`, `group_admin.py`; the compaction rules in `compaction.js` | `test_line_anchor.py` |
| D3 | `marks.js`, `index.js` (`message`, `restored`), `compaction.js` (`withCheckpointHead`) | `marks.test.js` |
| D4a to D4d | `tool_schema.py`, `role_tools.py` (the layered `call`, the nine splits, `INSTEAD`), `config.py` (`too_long`), `documents.py` (`problems`), `affect.py` (`record_problems`), `native_worker.py` (`role_tool_specs`) | `test_tool_schema.py`, `test_layered_refusal.py`, `test_length_refusal.py`, `test_tool_budget.py`, `test_declared_specs_dsh.py` (the specs the worker ships, registered and called through DSH's own `defineTool` and `validateArgs`), `tool-args.test.js` |
| D5 | `wake_words.py`, `context.py` (`CONTEXT_HEAD`, `local_line`), `context-delivery.js`, `turn.md`, `turn_thinking.md` | `test_woken_by_program.py`, `context-delivery.test.js` |
| D6 | nothing is added | |
| A2, A3 | `capabilities.can_quote`; every line shows its number; `event.line` | `test_adr079_pointers.py`, `test_woken_by_program.py` |
| A11 | `contexts.js`, `index.js` | `marks.test.js`, `native-loop.test.js` (through DSH's own `agentPresets.mount`) |

Checks run in the build container (Linux, the in-memory adapter): `pytest tests` 811 passed, 9 skipped (the skips are
the personal-words list, the private-words scene tests and the voice model, none present there); `npm run test:native`
276 passed and 8 failed, the same 8 that fail on `160968c`: four turn-end compaction tests that need the fork's
engine, three ADR-098 root tests with Windows path fixtures, and the working-copy test. A reviewer who had not seen
the build read the diff against the code; its findings (the dedup list in `context-delivery.js` dropping
`woken_by_program`, a test that contradicted itself, two more) are fixed, each with a test that fails without the fix.

Merged with main at `48e20f7` (ADR-109: the data child and the timing of every tool call). Two files conflicted: the
index of this folder (both rows kept) and `runtime-manifest.json` (regenerated); `docs/map/` came out up to date. The
two meet in three places, each read and held by a test:

- ADR-109 times a character call where the worker dispatches it (`NativeLane.wait`), outside `RoleTools.call`, and counts
  a `Refused` as a failed call. A layered refusal passes it unchanged, with every code, and the timing row holds no
  text of hers (`test_layered_refusal.py`, last test, which fails when the dispatch stops counting `Refused`).
- The data child runs history search and the discussion digest. They label people through `People.row_head` and
  `label`, which this build did not change, and not through the lines' numbers or `pointed`.
- Each ADR has its own restart (ADR-109 section 7); the lead lands them in the order they are ready.

On the merged tree `npm run test:native` gives the same 276 passed and 8 failed as before the merge, and
`pytest integration` ran against a throwaway MongoDB 8.3 (Atlas Local in a container, removed afterwards, no test database
left): 114 passed, and 19 vector-index cases did not pass: the 18 of `test_store_contract.py` TestN (the server answers
`"mappings" is required` to the search-index definition) and one in `test_schema_and_vectors.py`. The same 19 fail the same
way on `origin/main` alone against that server, so they say something about the test server and not about either branch.

Not run, and for the lead:

- `tools/check_prepared_start.py`.
- The private-words list: `tools/check_staged_secrets.py` (both modes) and `tools/publication_scan.py` over the 59 files
  the build changed found nothing, but the machine has no private-words list, so that part is unchecked, not clean.
- The ADR-098 root tests and the four compaction tests, on Windows and with the fork.
- The survey numbers of section 1, which need her session files.
- Xiaoman's reading: section 8 once, and the finished words once, at the frozen commit (8.4 item 4).
- A look at the Web page for a notice that begins with the mark (design.md §10.4), after the landing.
- Removing the scratch `config/local.json` the build container created (it is ignored by git).
