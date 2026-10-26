# ADR-099: Her thoughts can come from the model's own thinking

Status: **Designed 2026-10-26** by the owner and Claude; failure modes reviewed the same evening (§4). Building. The
default deployment is unchanged (§3.2).

## 1. Why

On Claude models every character-brain request is stopped before any output (`stop_reason: "refusal"`, category
`reasoning_extraction`; [MODELS.md §4](../../MODELS.md#4-claude-models-warnings), Sonnet 5.5, 33 of 33 turns that
reached the model). The design asks the model, as the first step of every turn, to write what it noticed, felt and
plans into the `think` tool, and refuses its actions until it has. That is the shape the check stops.

The stage exists for one purpose (owner, 2026-10-26): to keep what she thought at the moment the input reached her, so
it comes back with what it led to. It is not there to extract reasoning. A Claude model already thinks before it
answers, and the API returns a summary of that thinking (`display: "summarized"`, which DSH's provider sends; DSH keeps
it in the session record). The record can be filled from that summary instead of a tool call. Anthropic's own guidance
is the same: read the thinking blocks rather than prompt for reasoning in the response; such a request "may be refused
with `stop_details.category: "reasoning_extraction"`" on Fable 5.1, Opus 5.5, Opus 5, Sonnet 5.5 and Fable 5
([Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking#summarized-thinking), read 2026-10-26;
Haiku 5.5 is not in that list, so the probe runs it in both modes).

What the summary is, from the same page: "a summary of Claude's full thinking process rather than the raw chain of
thought"; "Summarization is processed by a different model from the one you target"; billed at the full thinking
tokens; its behaviour "subject to change". So a recorded thought in this mode is another model's account of her
thinking, not her words, and not all of it.

Removing the stage is a change of design, not a rewording: nothing in the request asks for her thoughts any more. A
version that still asked for the same content under another name would be the work-around MODELS.md §4 rules out.
That the stage is the cause is not yet shown; the refusal probe decides it (§5 step 2).

## 2. The invariant

In `thinking` mode no request of the character brain asks the model to write out its thoughts: no `think` tool, no
step, notice, hand-back or tool description that asks for 心里话, in new conversations and in ones that began in the
other mode. Her 心里话 record, and everything that reads it, keeps working, filled from the model's own thinking.

## 3. Decision

A deployment setting `thoughts` on the Cognition Core settings card:

| Value | 心里话 come from | Who |
|---|---|---|
| `tool` (default) | her `think` call, first step of every turn, as today | every deployment unless set |
| `thinking` | the summary of the model's first thinking in the turn, recorded by the program | deployments whose character brain runs on a model that refuses the stage |

- **Applied between turns.** The setting goes through the existing settings path: refused while a turn or task runs
  (`ASUNA_BUSY`), then the worker restarts and each conversation reopens at its next idle stage.
- **A conversation is carried when its mode changes.** DSH's provider keeps a session's first tools and system text as
  the head of every request and appends later changes, so an open session would keep offering `think` and its turn
  steps. Each session records the mode it was opened in; a session in the other mode is carried to a successor
  (ADR-028) at its next turn. One cold cache per conversation, once.
- **One predicate.** Whether a turn asks for a thought is `'think' in ep.turn_tools`, computed each run from the same
  config as her tool specs. Every check reads it; no mode is stored on the turn, so a turn resumed after a restart in
  the other mode, or one from before the setting, needs nothing.
- **The route must think.** In `thinking` mode the settings refuse a character route, or its group effort, without a
  thinking level: with none, DSH sends thinking disabled and there would never be a thought, silently.

### 3.1 What `thinking` mode changes

1. **Nothing asks for the stage.** `think` leaves her tool list in every place; the turn notice drops
   「这一回合第一步先调用 think 写心里话。」; the turn steps (`turn.md`, `turn_consult.md`) have a version per mode; the
   wordings that name `think` or tell her to write 心里话 first (consult-only note, stay_silent) get a `thinking`-mode
   version; `tool` mode keeps its words.
2. **No check waits for a thought.** Actions refused before a thought (`role_tools`), the speak-only hand-back
   (`coordinator`, `no_thought`) and the body-text check (`answers.speech_problem`) read the predicate and are off.
3. **Capture.** When her first tool call of a turn arrives, the reasoning of the model response that made it is
   already in the DSH session (the agent loop appends the response before it runs a tool). The plugin hands that
   reasoning with the call; the worker records it before it runs the call: the same `monologue` memory unit, marked
   `source: thinking`, stored whole (contracted as her writing is, ADR-098), so each action's link to its reason
   works as today. Every action of the turn is linked to that first thought, also those made after later
   responses that thought again: in `tool` mode she may think again mid-turn and later actions link to the newer
   thought, so the two modes are not equivalent here. A turn with no tool call is captured once at its end. Repair requests (`:fix-N`) are not captured;
   a resumed turn is. Redacted and empty thinking blocks are skipped. A capture that fails is audited and the call
   runs without a thought; it never fails her action. A turn whose model did not think leaves none, and nothing
   waits for one, but it leaves an audit row (`thought.none`, with why: no thinking, redacted, capture failed), so
   "did not think" and "not recorded" can be told apart and counted. Gate, appraiser, summary and title requests make no role-tool calls and are never captured.
4. **Projection is short.** Wherever a recorded summary comes back — the last three in a conversation, her thoughts
   seen from home, the thought behind a quoted line, plan, task or night item, the self-review — it is cut at 120
   characters with the excerpt mark (owner, 2026-10-26); one helper decides by the unit's source. `recall` gives the
   longer text (up to its usual 1,200 characters). Thoughts she wrote with `think` keep today's lengths, including
   the self-review's 360 (her ask).
5. **Honest label, per item.** A summary is not her own writing, nor all of her thinking, and another model wrote
   it. Each recorded summary is marked where it comes back, briefly: 「你此前想法的摘要，别的模型写的」 (owner:
   honest, but short). A block that holds both kinds labels each.
6. **A view of a person without a thought.** `understand_person` takes this turn's thought as its source; in a turn
   without one, the source is the chat chunk of the line she answers (made on demand); failing that, a refusal in
   words, never a raw code.

### 3.2 Not changed

- `tool` mode, and every deployment that does not set `thoughts`: the same tools, wordings, checks and lengths.
- The relevance gate's short reason, edit reasons on her tools (why a memory changed, why she stays quiet): decisions,
  not reasoning.
- What the model thinks: thinking effort stays the route's.
- Readings stay per mode: every recorded thought carries its `source`, `thought.none` exists only in `thinking` mode,
  and a readout that counts thoughts (her weekly think counts, refusals before a thought) reads one mode, never both
  in one table. Tests are named per mode; `tool`-mode tests stay as they are, the guard for §3.2.

## 4. Failure modes

Reviewed against the code on 2026-10-26 (an adversarial read by a second Claude Opus 5.5 instance). Each row is
answered in §3.

| # | Failure | Trigger | Effect | Answer | Test |
|---|---|---|---|---|---|
| 1 | Open sessions keep the stage | the mode changes on a live conversation | `think` and the old turn steps stay at the head of every request; refusals go on while a fresh-session probe passes | session records its mode; mismatch carries the conversation | switch a running conversation; the next request has no `think` and no old steps |
| 2 | Actions lose their reason | any `thinking` turn | the reason lookups find only `think` calls: plans, tasks and night items lose `your_thought_then`, the thought loses what it led to | lookups read `ep.monologue_refs` and the call the thought is anchored to; old records by the old scan | thinking turn → plan → the fired plan shows the thought; the thought lists the plan |
| 3 | No thinking at all | character route or group effort without a level | thinking disabled; no thought ever, no error | settings refuse it in `thinking` mode; turns without a thought are counted | settings test |
| 4 | A redacted or empty block stored | `redacted_thinking`, a signature-only block | she reads "[Reasoning redacted]" or nothing as her thought | only non-redacted blocks with text | extractor test |
| 5 | A turn resumed in the other mode | restart between prepare and resume | `think` offered on Claude: refused at every resume; or a gate with no `think`: wedged | the predicate is the turn's tool list, recomputed each run | crash matrix: prepared in one mode, resumed in the other |
| 6 | One check left on | any site not reading the predicate | actions refused, speak-only turns silent, body-text turns failing | the gate, notice, hand-back, `speech_problem` and capture read the predicate | every turn kind × both modes |
| 7 | A repair's thinking recorded | `no_thought` / unsent hand-back | the thought is about the program's note | `:fix-N` not captured | repair test |
| 8 | A summary is not in her voice | summaries in English, about "the user", the tools | breaks 你/我 and one language; agent talk comes back as her thought | the label; content judged by the owner from the soak's sample | soak readout |
| 9 | "Whole" on recall is false | a summary over 1,200 characters | recall cuts at 1,200 | stated as "longer", not "whole" | recall of a long unit |
| 10 | A projection site misses the cut | any of the sites in §3.1-4 | 2,000 characters a thought, three a turn | one helper by source | snapshot per site |
| 11 | Mixed labels | old `think` thoughts and summaries in one block | her own writing labelled a summary | label per item | mixed-unit context test |
| 12 | No source for a view of a person | a turn without thinking | raw `MUTATION_REQUIRES_SOURCES` | the answered line's chunk, else words | private-chat turn without reasoning |
| 13 | Thinking edited on replay | ADR-098 contraction, inbox splices | the provider drops the mismatched block (or a 400 on a route without binding controls) | capture stored contracted; the soak counts drops and 400s | soak |
| 14 | `think` calls in a history where it is gone | — | unknown to the API | covered by #1: the successor session starts clean | — |
| 15 | Cache | a mode change | one cold start per conversation | accepted | cache readout after a switch |

## 5. Order

1. The switch, the predicate and the three checks (§3.1 items 1–2), the session carry (#1), the settings check (#3),
   and `--thoughts thinking` on the refusal probe.
2. The refusal probe on the existing Anthropic key, Haiku 5.5 at effort high: the go/no-go. A FAIL means the stage
   was not the cause; the build stops there and goes back to the owner.
3. Capture, reason lookups, projection, labels and the person-view source (§3.1 items 3–6).
4. A multi-turn soak on Claude: drops and 400s from preserved thinking, turns without a thought, and a sample of the
   recorded summaries (synthetic conversations only) for the owner to judge their language and person.
5. Current references (RUNTIME_API.md settings, MODELS.md).
