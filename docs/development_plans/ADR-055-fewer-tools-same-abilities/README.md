# ADR-055: Fewer tools, the same abilities: the action brain's and the idea notebook's tools merged

Status: **Accepted 2026-10-12** after Xiaoman's review (her name, her option names, the migration and the acceptance
check are hers). **Built 2026-10-12** (see Build).

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

## Build (2026-10-12)

- **Checked before building** (scratchpad harness, her real descriptions and parameters, 18 made-up home moments: the
  12 of ADR-054 and 6 on the merged families): 28 tools 61/72 right, 23 tools 64/72; local model at medium and high
  effort 30/36 against 31/36, DeepSeek at low and high 31/36 against 33/36. Misses common to both: naming `think`
  (the harness asks for one tool; hers says think comes first) and reading the notebook before reviewing it when the
  moment gives no id. One new kind: DeepSeek at low effort twice named `ideas` without an option.
- Hence one addition, as ADR-054 did for `plan`: a call without `op` whose fields name exactly one option is that
  option (`role_tools.OP_FIELDS`; `task`'s message, answer, reason, page; `ideas`' idea, id or decision, search or
  page), and its result says so. Fields naming none or several are refused with the options.
- `review` takes the idea's `id` (its old `idea` was the id while `note`'s `idea` is the text: one name, two
  meanings); an old `review_idea` call's `idea` arrives as `id`.
- What a conversation lists and a turn allows is kept by option (`task.message`, `role_tools.abilities`); the model is
  shown the tools (`toolbox`). The old names are registered with the merged tool's parameters but never listed; the
  plugin's guard lets one through where its tool is listed, and its result carries `renamed`. Records keep the tool,
  its `op` and `called_as`, and the readers (reasons, the night summary) read an old record as its option.
- Cost as measured by `tests/test_tool_budget.py`: her character brain 37 tools defined to 32, 21,474 description
  characters to 20,861; the seven merged tools 2,290 to 1,677; her home list 15,816 to 15,203. The budget is lowered
  to 32 tools and 20,900 characters. No per-turn line added.
- Her persona's own skill `asuna-bot-or-person` names old tools in her words; hers to update (old names keep
  working meanwhile).
