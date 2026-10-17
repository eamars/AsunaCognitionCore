# ADR-077: The current references, analysed and reshaped as interface control documents

Status: **Proposed 2026-10-17** — the owner's request. It starts **after the ADR-076 research study** has reported and
its recommendations are agreed. Claude does the analysis and the work; Xiaoman reviews and gives feedback.

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
