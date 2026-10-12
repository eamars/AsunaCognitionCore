# ADR-055: Fewer tools, the same abilities: the action brain's and the idea notebook's tools merged

Status: **Draft 2026-10-12**: the owner's direction (her character brain has too many tools); her agreement in
principle given, this concrete shape awaits her review. Not built.

## Context

Her home conversation lists 28 tools. A local model picks worse among many tools (ADR-054's side-by-side check,
other harnesses' findings: merging overlapping tools is the best-supported fix). Two families do one job each with
several names:

- The action brain: `delegate`, `message_action`, `answer_action`, `stop_action`, `read_report` (five).
- The idea notebook: `note_idea`, `read_ideas`, `review_idea` (three).

Her review (2026-10-12): merge both; keep `errand`, `watch`, `credential` and `quote` (each the only way to do what
it does); `read_report` is heavily used (46 successful calls in a week), not rare; the merged option that answers
the action brain must say it answers the action brain, never a person; count successes and refusals apart before
retiring anything.

## Proposal

1. **`delegate` stays as it is**: handing over new work is the step she takes most and should not need an option.
2. **`action`** replaces the other four, with `op`:
   - `message` — words to a task already handed over (was `message_action`; same parameters);
   - `answer` — answers the action brain's question in the turn it asked, never a person (was `answer_action`);
   - `stop` — stops a task (was `stop_action`);
   - `read` — turns the pages of what it handed back; answers nothing (was `read_report`).
3. **`ideas`** replaces the notebook's three, with `op`: `note` (was `note_idea`), `read` (`read_ideas`), `review`
   (`review_idea`).
4. **Where an option is offered stays where the old tool was**: the conversation lists the merged tool wherever any
   of its old tools was listed; an option not usable in this turn is refused with the same words the old tool's
   refusal used (`NOT_NOW`), naming the option. A consult turn (the action brain asked her) still allows only
   `action` op `answer` besides `think` and `recall`.
5. **Results and records unchanged**: each option returns what the old tool returned; her records keep the tool
   and option, so the refusal counts by cause (ADR-054) stay comparable.

## Cost (AGENTS.md)

Her home conversation: 28 tools to 23. Description characters: the merged descriptions keep each option's sentence,
so the saving is the repeated names and preambles, roughly 600 of about 21,000 characters; the parameters stay
(each option keeps its own). No new per-turn line. The budget test's count drops by 5.

## Open for her

- `delegate` separate, or an `action` option too (`op: new`)? Proposal: separate.
- Names: `action` and `ideas`, or words she would reach for first?
