# ADR-099: Her thoughts can come from the model's own thinking

Status: **Designed 2026-10-26** by the owner and Claude; the owner asked for it so a persona can run its character
brain on Claude models. Not built. The default deployment is unchanged (§3).

## 1. Why

On Claude models every character-brain request is stopped before any output (`stop_reason: "refusal"`, category
`reasoning_extraction`; [MODELS.md §4](../../MODELS.md#4-claude-models-warnings), Sonnet 5.5, 33 of 33 turns that
reached the model). The design asks the model, as the first step of every turn, to write what it noticed, felt and
plans into the `think` tool, and refuses its actions until it has. That is the shape the check stops.

The stage exists for one purpose (owner, 2026-10-26): to keep what she thought at the moment the input reached her, so
it comes back with what it led to. It is not there to extract reasoning. A Claude model already thinks before it
answers, and the API returns a summary of that thinking (`display: "summarized"`, which DSH's provider sends; DSH keeps
it in the session record). The record can be filled from that summary instead of a tool call.

Removing the stage is a change of design, not a rewording: nothing in the request asks for her thoughts any more. A
version that still asked for the same content under another name would be the work-around MODELS.md §4 rules out.

## 2. The invariant

In `thinking` mode no request of the character brain asks the model to write out its thoughts: no `think` tool, no
step, notice, hand-back or tool description that asks for 心里话. Her 心里话 record, and everything that reads it, keeps
working, filled from the model's own thinking.

## 3. Decision

A deployment setting `thoughts` on the Cognition Core settings card:

| Value | 心里话 come from | Who |
|---|---|---|
| `tool` (default) | her `think` call, first step of every turn, as today | every deployment unless set |
| `thinking` | the summary of the model's first thinking in the turn, recorded by the program | deployments whose character brain runs on a model that refuses the stage |

- **Applied between turns.** The setting goes through the existing settings path: refused while a turn or task runs
  (`ASUNA_BUSY`), then the worker restarts and each conversation reopens at its next idle stage.
- **One mode per turn.** A turn records the mode it was prepared in (`ep.thoughts`); every check, notice and the
  capture read that, never the live setting. A turn resumed after a restart keeps its mode.

### 3.1 What `thinking` mode changes

1. **Nothing asks for the stage.** `think` leaves her tool list in every place; the turn notice drops
   「这一回合第一步先调用 think 写心里话。」; the turn steps (`turn.md`, `turn_consult.md`) have a version per mode; the
   wordings that name `think` or tell her to write 心里话 first (consult-only note, stay_silent) are neutral in both
   modes.
2. **No check waits for a thought.** The three places that hold a turn until she has thought — actions refused before
   a thought (`role_tools`), the speak-only hand-back (`coordinator`, `no_thought`), the body-text check
   (`answers.speech_problem`) — read one predicate of the turn's mode and are off in `thinking` mode.
3. **Capture.** The first model response of a character-brain turn that carries thinking text is recorded as that
   turn's 心里话: the same `monologue` memory unit, marked `source: thinking`, stored whole, written before that
   response's tool calls run, so each action's link to its reason (`reason_ref`) works as today. Later responses in
   the turn are her working steps and are not recorded. A turn whose model did not think leaves none, and nothing
   waits for one.
4. **Projection is short.** Wherever a thought comes back — the last three in a conversation, the thought behind a
   quoted line, plan, task or night item, the self-review, the exchanges — a recorded summary is cut at 120 characters
   with the excerpt mark (owner, 2026-10-26). `recall` returns it whole, when she asks.
5. **Honest label.** A summary is not her own writing. In `thinking` mode the notes say so, briefly:
   「你此前想法的自动摘要（最近的在最后）」 (owner: honest, but short).

### 3.2 Not changed

- `tool` mode, and every deployment that does not set `thoughts`.
- The relevance gate's short reason, edit reasons on her tools (why a memory changed, why she stays quiet): decisions,
  not reasoning.
- What the model thinks: thinking effort stays the route's.

## 4. Failure modes

(Reviewed before the build; §4 is filled from that review.)

## 5. Order

1. The switch and the three checks (§3.1 items 1–2), and `--thoughts thinking` on the refusal probe.
2. The refusal probe on the existing Anthropic key, Haiku 5.5 at effort high: the go/no-go. A FAIL means the stage
   was not the cause; the build stops there and goes back to the owner.
3. Capture, projection and label (§3.1 items 3–5).
4. A multi-turn soak on Claude: preserved thinking refuses a replayed history that was edited (400 "invalid
   signature"), and her lanes edit history in places (inbox splices, compaction, the ADR-098 rewrite must give the
   same bytes each request).
5. Current references (RUNTIME_API.md settings, MODELS.md).
