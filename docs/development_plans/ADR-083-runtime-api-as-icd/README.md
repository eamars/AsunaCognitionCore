# ADR-083: RUNTIME_API.md as an interface control document

Status: **Open** since 2026-10-20: decided by the owner, worked through with Claude, and built the same night (`RUNTIME_API.md` 189,317 → 63,596 characters, largest paragraph 691, 50 tables; `packages/cognition-core/DSH_API.md`). Waiting: the owner's read, the reviewer's spot check, her review (§5). Replaces ADR-077, whose plan was under-thought
and grew into code (generators, an agreement test, a commit hook) for what is a documentation job. ADR-077's analysis
(its §9 and `.runtime/private/adr077/`) is the evidence this ADR builds on.

## 1. Problem

`RUNTIME_API.md` is 189,317 characters in 570 lines under 25 headings (2026-10-20). Paragraphs run to tens of
thousands of characters, so a reader who searches for one fact gets a wall of text, and a reader who reads it whole
(her action brain does, up to 93,842 characters in one task) pays for all of it. ADR-077's check found about one checked
row in seven wrong or stale.

It grew because agents were told to describe every behaviour change in it, in the same change. Each change added a
clause to the nearest paragraph, so the document became a second copy of the code, kept by hand, drifting from it.
The most frequent lookup in the records was an agent looking for where to update it.

## 2. Decisions (owner, 2026-10-20)

- **No information is better than false information.** A line that can mislead costs more than reading the code.
- **`RUNTIME_API.md` stays at the root and is reorganised in place as an ICD** for what is useful, stable and usable
  for secondary development: a contents list, one section per interface, tables for fixed facts (endpoints, fields,
  outcomes, codes, config keys, package contracts), short notes for behaviour that crosses the boundary, each fact
  stated once and linked from elsewhere. It keeps its name and stays packed in the core package.
- **Kept separate:** `packages/cognition-core/DSH_API.md`, the DSH services, hooks, events and file formats Asuna
  relies on, next to the plugin that uses them (for the owner, who keeps Asuna compatible with DSH). A sub-module gets
  its own document only when its section is too large to navigate; the channel packages keep their READMEs.
- **Her tools are a pointer only.** They are API, but their source is already a readable table that is never out of
  date (`src/asuna/role_tools.py`: `TOOLS`, where each is offered in `EVERYWHERE`, `AT_HOME`, `IN_GROUPS` and
  `_turn_rules`, refusal words in `not_now` and `words`). A copy would serve no reader the code does not serve better,
  and would drift first.
- **No code changes.** No generator, no new test, no hook. The one rule left (AGENTS.md, `f40e8d2b`): a change to an
  interface updates its entry.
- **Agent instructions that told agents how to work were removed** from AGENTS.md and docs/MODELS.md (`f40e8d2b`).

## 3. How the current text is sorted

Each paragraph of today's document goes one of four ways, using ADR-077's facts tables (statement class and verdict)
as the inventory:

| What it is | Where it goes |
|---|---|
| An interface fact (a name, field, endpoint, code, limit an outside reader relies on) | a table row in its section, checked against the code as it is moved |
| How an operator installs, configures or runs it | `RUN_ASUNA.md` or `INSTALL.md`, if not already there |
| Internal behaviour (how her turn runs, every hint, every internal limit) | cut; the code is the authority. One overview line stays where it helps a reader find the code |
| History, reasons, dates | cut (ADRs keep them) |

A fact that cannot be checked against the code when it is moved is cut, not carried.

## 4. Readers

- **Agents** changing the code: find the interface, its entry and its code anchor.
- **Her action brain** in self-development: reads it whole; her skills anchor into it, and she updates those anchors
  herself once the new document is in place (she is told after the owner has seen it).
- **Adapter and package authors:** the channel API and the package contracts.
- **The owner:** `DSH_API.md` at DSH upgrades.

## 5. Sign-off

- The owner reads the result by using it.
- No paragraph over about 1,500 characters; every section is in the contents list.
- A spot check by the independent reviewer (the same one as ADR-076/082) finds no entry that contradicts the code.
- She has reviewed it and updated her skills' anchors.

## 6. Cost

One hand-kept document still drifts when an interface changes and its entry is not updated. The surface is much
smaller than today's (interfaces only, no behaviour copy), which is what makes that rule cheap to keep.
