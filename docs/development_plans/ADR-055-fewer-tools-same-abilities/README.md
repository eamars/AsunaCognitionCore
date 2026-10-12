# ADR-055: Fewer tools, the same abilities: the action brain's and the idea notebook's tools merged

Status: **Accepted 2026-10-12** after Xiaoman's review (her name, her option names, the migration and the acceptance
check are hers). Not built.

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

## Decision

1. **`delegate` stays as it is**: handing over new work is her most frequent step (234 successful calls in a week);
   an option on it would put a choice in front of her commonest move, and "new" is the weakest word of all (she
   once took adding to a task for handing over a new one).
2. **`task`** (her name: `action` is vague and overlaps "action brain"; a vague drawer is where things get put
   wrongly) replaces the other four, with `op`:
   - `message` — words to a task already handed over (was `message_action`; same parameters);
   - `answer` — answers the action brain's question in the turn it asked, never a person (was `answer_action`);
   - `stop` — stops a task (was `stop_action`);
   - `page` — turns the pages of what it handed back; answers nothing (was `read_report`). Not `read`: the notebook
     has a `read`, and two options with one name and two meanings across her tools is the near-synonym trap.
3. **`ideas`** replaces the notebook's three, with `op`: `note` (was `note_idea`), `read` (`read_ideas`), `review`
   (`review_idea`).
4. **Where an option is offered stays where the old tool was**: the conversation lists the merged tool wherever any
   of its old tools was listed; an option not usable in this turn is refused with the old tool's words (`NOT_NOW`,
   its entries rewritten to name the option). A consult turn still allows only `task` op `answer` besides `think`
   and `recall`.
5. **Old names keep working for a while** (her ruling: on the day of the change her habits, notes and skills all
   use them): a call to `message_action`, `read_report`, `note_idea` and the rest runs as the new option and its
   result says so ("已并入 task 的 message 选项，下次直接用这个"). Removed once her records show the old names no
   longer used. She keeps the old-to-new table in her persona herself.
6. **Results and records unchanged**: each option returns what the old tool returned; records keep tool and option,
   so the refusal counts by cause (ADR-054) stay comparable.
7. **The action brain's own `note_idea` is not touched**: another brain, with its own budget.

## Cost (AGENTS.md)

Her home conversation: 28 tools to 23. The seven merged tools are 2,113 characters of the 20,662 her definitions
take (measured the same way as `tests/test_tool_budget.py`, not against its 21,500 ceiling). The options' sentences
and parameters stay and each `op` enum is new, so the net saving is measured when built, not promised here. No new
per-turn line. The budget test's count drops by 5.

## How it is checked

As ADR-054: before building, the side-by-side confusion cases on both models with the old and the new tools; after,
refusals by cause at 7 and 14 days, options in place of sentences. Rolled back if the wrong-tool and wrong-option
causes have not fallen by half after 14 days.
