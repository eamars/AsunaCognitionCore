# ADR-077: The current references, analysed and reshaped as interface control documents

Status: **Proposed 2026-10-17** — the owner's request. It starts **after the ADR-076 research study** has reported and
its recommendations are agreed. Claude does the analysis and the work; Xiaoman reviews and gives feedback. **Analysed 2026-10-19** (§9): the shape waits for her review of the samples and the owner's decision.

## 1. Problem

The owner asked why `RUNTIME_API.md` is so wordy, and whether an interface control document (ICD) format would serve
better. Measured on 2026-10-17 (about 16:40 NZDT, `main` at `eae302a4`):

| Document | Characters | Largest paragraph | Table rows | Commits |
| --- | --- | --- | --- | --- |
| `RUNTIME_API.md` | 169,113 | 25,675 | 6 | 252 (122 in the last 7 days) |
| `RUN_ASUNA.md` | 35,422 | 3,088 | 12 | 63 |
| `NATIVE_PLUGIN.md` | 17,209 | 2,059 | 6 | 22 |
| `docs/DEVELOPMENT.md` | 13,557 | 1,838 | 13 | 18 |
| `packages/channels/napcat-qq/README.md` | 10,296 | 6,069 | 0 | 16 |
| `README.md`, `INSTALL.md`, the other package and tool READMEs | 1,000–8,000 each | ≤ 2,737 | few | — |
| `docs/map` (generated) | 249,742 in 12 files | — | — | — |

`RUNTIME_API.md` has 25 headings for 169,000 characters; its ten largest paragraphs hold 65,000. One paragraph, the
one that defines a character turn, is 25,675 characters long. No test reads its content: one test only checks that
it is packed into the core package.

**Why it grew this way.** The rule that a behaviour change updates the current reference in the same change is right,
but each change added a clause to the nearest paragraph and nobody restructured. The rule "present state only, no
history or reasons" removed the why and left dense how. Nothing checks size, shape or agreement with the code, so
nothing pushed back.

**Why it costs.**

- An agent that searches for one fact gets the whole paragraph around it: a lookup in the turn paragraph costs
  thousands of tokens.
- It is packed into her core package, and Xiaoman reads it in self-development turns.
- Prose cannot be checked against code: a limit or a name stated in a sentence drifts silently when the code changes.
  Her 2026-10-17 mix-up of the plugin's `fall` with the worker's `tier.fell` came from that kind of gap between a
  documented name and the real one.
- The same rule appears in several places in different words, so contradictions hide.

## 2. The owner's direction

- Claude analyses **all** the current references after the research study. This is Claude's job.
- Xiaoman reviews and gives feedback: on the analysis and on the shape it proposes, above all for the documents she
  reads herself.

## 3. Scope

The current references named in `AGENTS.md`: `README.md`, `INSTALL.md`, `RUN_ASUNA.md`, `NATIVE_PLUGIN.md`,
`RUNTIME_API.md`, `docs/DEVELOPMENT.md`, and the package and tool READMEs. Plus `docs/map` (generated) and
`docs/articles`, insofar as they repeat or contradict the references. `AGENTS.md` is checked for consistency with
them. `docs/development_plans/**` keeps its role (decisions and history, not authority) and is out of scope, except for
the index.

## 4. Method

1. **Who reads what, for which question.** For each document: its readers (agents writing code, the research agent,
   Xiaoman in self-development, the owner deciding by using), and the questions they actually bring. The questions are
   collected from real lookups: what agents searched for in their sessions, what her self-development turns read, and
   the questions that went wrong (such as `fall`).
2. **Fact by fact.** Every statement is classified as an interface fact (a name, field, type, limit, code, wording,
   endpoint), a behaviour (an order, a lifecycle, a queue rule) or an instruction (how to run or install). Each fact is
   checked against the code. Wrong, stale and duplicated facts are listed, with where else each one appears.
3. **The ADR-076 matrix as a source.** For the turn side (prompts, tools, error messages per scenario class), the
   research study's coverage matrix is the checked source. The ICD uses it; it does not redo it.
4. **The shape** (§5) is proposed from the analysis and decided with the owner, after Xiaoman's review.

## 5. The shape to test (proposal)

- **One entry per interface**, all with the same fields: name; direction (who calls whom); inputs with their types
  and limits; what it returns; every error code with its words and what to do next; a `file:name` anchor to the code.
- **Generated where the code is the source**: her tools and the action tools (names, options, parameters, limits),
  error codes and their words, the context blocks, the HTTP and channel endpoints, record fields. A test fails when the
  code and the ICD disagree, as `docs/map` and `tests/test_tool_budget.py` already work.
- **Short prose only for behaviour** with no table shape (ordering, lifecycles, how queues and restarts behave), one
  section per subsystem.
- **One home per fact.** Other documents link to it instead of restating it.
- The current-reference rules stay: present state only; no personal data; updated in the same change as the
  behaviour. The ICD makes that rule cheaper to keep, because the generated parts update themselves.

Options to decide after the analysis:

- **A (recommended):** the generated ICD for the parts that are tables, plus short prose for behaviour, with the
  agreement test.
- **B:** the same structure written by hand, with no generation. Faster to start, but it drifts again.
- **C:** split the largest paragraphs and add headings only. Cheap; it fixes the lookup cost but not the drift.

## 6. Her review

Xiaoman reads `RUNTIME_API.md` from her package and keeps her own map of the project (`docs/map`) and her skills,
which anchor into the code. Before the shape is decided, she reviews the analysis and a sample of the new entries:
whether they answer the questions she brings, and what she would miss. Her feedback is recorded here as Claude's
paraphrase, with the time and a signature slot. Where a change touches her skills' anchors, she updates her skills
herself.

### Her first feedback (2026-10-17, about 18:30 NZDT)

Claude's paraphrase of her message on the agent line:

- **A stale document must turn red and block the commit by itself.** Today's red test (Claude forgot to regenerate
  the project map) shows that now a document out of step with the code stops no one; it depends on someone remembering
  to regenerate. If ADR-077 does not change that, the format changes and the defect stays.
- **The agreement test must run both ways.** "Documented but not in the code" is the easy direction; "in the code but
  not documented" is the one that is missed, and the one that has misled her most.
- **Generated files say they must not be edited by hand, and where to edit instead.** Her two tests: is it tracked,
  and does something overwrite it. The packed copy under `packages/cognition-core/python/asuna` misled her once: an
  edit there is overwritten at the next pack.
- **She reads by turn, not by module:** in this kind of turn, which tools she has, their limits, what is refused, and
  whether a refusal gives her the next step. She will pick the sample entries by turn kind, not by chapter.

Signature: ____

## 7. Sign-off

- **Real lookups.** A set of real questions collected in §4.1, each answered from the new documents. Each answer is
  correct against the code and reached with far fewer characters read than before; the before and after counts are
  both recorded.
- **Agreement with the code, both ways.** The agreement test passes; it fails on a deliberately broken limit or name,
  and on an interface present in the code but missing from the document. A stale document blocks the commit.
- **No fact lost.** Every interface fact of the old documents is in the new ones or listed as removed, with the reason
  (wrong, stale or duplicated).
- **Her review** is in §6, and the owner has read the result by using it.

## 8. Order

After the ADR-076 report and the owner's and Xiaoman's decisions on its recommendations, because those may change
behaviour the documents describe. It is built in small batches, one document family at a time, each verified before
the next.

## 9. The analysis (2026-10-19, Claude)

### 9.1 How it was run

Every current reference was checked statement by statement against the code (§4 step 2), by helpers working in
parallel under one brief (`.runtime/private/adr077/brief-facts.md`): `RUNTIME_API.md` in six slices, the other
references in one, and the real lookups (§4 step 1) in one. Each statement got a class (interface, behaviour,
instruction), a verdict (correct, wrong, stale, unverifiable, history) with its `file:line` evidence, and where else the
same fact is stated; each slice also lists interfaces in the code that no reference mentions. Read only, no model
calls. Evidence: `.runtime/private/adr077/` (the per-slice tables, `lookups.md`), about 0.55 MB, kept until this ADR
is closed.

| Slice | Statements | Wrong | Stale | History | Undocumented in the code |
|---|---|---|---|---|---|
| `RUNTIME_API.md` 1–41 (responsibilities, configuration) | 187 | 32 | 1 | 2 | 55 |
| 42–264 (channel API) | ≈190 | 17 | 3 | 8 | 26 |
| 265–306 (action capabilities, history, what a turn carries) | 258 | 27 | 3 | 3 | 80 |
| 307–349 (people, her place in a group) | 84 | 7 | 2 | 1 | 33 |
| 350–465 (tiered memory, media, attach and stickers) | 99 | 17 | 1 | 8 | 43 |
| 466–570 (schedules, integration, self-development) | ≈154 | ≈35 | 1 | 3 | ≈58 |
| The other references | 396 | 56 | 11 | 11 | 62 |
| **Total** | **≈1,370** | **≈190** | **22** | **36** | **≈360** |

### 9.2 Who reads, for which question

77 distinct questions from the records (`lookups.md`): 262 Claude Code transcripts, 7 Codex sessions, 87 of her
action-brain tasks that read references (271 reads).

- **Agents mostly ask where a fact lives, not what it is.** The most frequent question, about 137 lookups: "where
  does the document describe X, so I can update it?"; then whole-document reads to get oriented (about 57) and "does
  anything still mention the removed name Y?" (about 33). That is the cost of a fact living in several places.
- **She reads whole files and checks them against the code.** Five of her tasks read more than 58,000 characters (the
  largest 93,842). Her questions follow her four turn questions (which tools in this turn, their limits, what is
  refused, whether a refusal gives the next step).
- **One grep can return a whole paragraph**: 17,236 characters for one refusal's wording.
- **Five copies of `RUNTIME_API.md` were read**: the root, the packed copy, the channel copy, the installed copy and
  the public GitHub copy. One (a channel package's ignored copy from 10-14) was stale and has been deleted.
- **Readers went wrong** nine ways on record, among them: her usage readout said a field did not exist that does
  (`tasks.tier.fell`); the reference contradicted itself on an image cap and on a turn rule; a security review relied
  on "ids never reach her model", which the code did not hold; the owner swapped two relevance-gate rules spread over
  several paragraphs.

### 9.3 What it found

- **About one statement in six is wrong or stale.** Most are exact facts a reader acts on: a parameter name that is
  now refused (`kind`, `reason`, `inject`, `op` in four tools), a limit or default that changed, a list missing a member
  (the die's seven faces, the fifth rhythm task, the `raw` fields the Host keeps).
- **The code-to-document direction is the larger gap**, as her first feedback said. 415 refusal codes are raised in
  `src/asuna`; 43 of them (10%) appear in `RUNTIME_API.md`. Context blocks, audit events, HTTP outcomes and record fields
  are missing in the same way.
- **One fact, many homes, each drifting alone.** The DSH version is stated in nine places; the persona and channel
  contracts in four; within `RUNTIME_API.md` several rules are stated two or three times and disagree (the image cap,
  the effort settings, where pictures may go).
- **History in current references**: reasons, dates and "as before" in about 40 places (AGENTS.md says none).
- **Some errors were the program's, not the document's.** The check found them and they were fixed and installed the
  same evening (main `130e4e71`, her restart 20:15): a credential's values written into the audit in plain text; her
  `plan` tool able to cancel her rhythms; four hints that taught calls the program refuses (`kind 写 accept`,
  `[表情包:名字]` in text, `affect_adopt`, visibility `private`); the persona-model schema refusing four keys the core
  declares. Two more were found and fixed the same night (on main, installed at her next
  restart): the settings card said night stages skip while a publication waits for a restart, and the code (by design)
  runs them; her `when_shown` hint said an item comes back to 随身 when it is used again or corrected, and by ADR-062
  (§4.2 step 7) and the code only a rewrite that changes it does.
- **The way a 收着 item comes back by surprise (ADR-062 §4.2) is not built**: `memorable(…, 'surprise')` has no
  caller, and a correction supersedes the item it corrects (moves it down). That is ADR-062's to decide, not this one's.
- **A test is not an ICD.** The two existing agreement tests (`docs/map`, `tests/test_tool_budget.py`) stop drift where
  they reach; nothing reaches the prose of `RUNTIME_API.md`.

### 9.4 What it means for the shape (§5)

The analysis supports option A, and says which parts to generate first:

1. **Her tools, by turn** (her reading order): for each place and turn kind, the tools she has, each with its
   parameters as she is shown them, their limits, when it is not available and the words she then reads, and the words
   of every refusal, marked where a refusal gives no next step. Generated from `role_tools`.
2. **Refusal codes**: every code with its words, who reads it (her, the action brain, an adapter, the operator) and
   where it is raised. Generated from the source.
3. **Context blocks**: each `_from_program` block, when it comes, its fields, and the guide line she reads for it.
4. **The channel API**: endpoints, envelopes, outcomes and codes (adapters' agents read it).
5. **Short prose for behaviour**, one section per subsystem, each fact stated once; other documents link to it.

The agreement test runs both ways and blocks the commit: a generated page that is not what the generator writes now
fails; prose that names a code, tool, option or block the code does not have fails; a code, tool or block the code has
and no page lists fails. Generated pages say at the top that they are generated and where to edit instead.

Samples for her review (§6), built from the code: `.runtime/private/adr077/samples/` — `tools-group.md` and
`tools-home.md` (her tools in a group and at home, with their refusals; 10 and 11 refusals flagged as giving no next
step) and `errors.md` (113 codes with their words, by module). The final version is one page per turn kind.
