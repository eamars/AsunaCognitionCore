# ADR-131: A turn she can end

Status: **Proposed** 2026-11-14 by big sis (Claude Code), at the owner's direction (The ask). The owner made it
today's one ADR, ADR-121 next. Designed against `main` with ADR-129's exits on top (`8c07e4e02cc2`); every count in
§1 was read 2026-11-14 14:20-14:45 from her database and one QQ group's role session. Times on this page are local
time.

## The ask

The owner, 2026-11-14, after a look at one QQ group: "I suspect there are some side effect from removing the tool,
that it appears that she cannot properly terminate a turn without the tool. I need you to read the code carefully
before making any conclusion." After §1 and §2 were put to him, his direction (verbatim): "Perhaps a dedicated
end_turn tool (to replace the original stay_silent)? And you need to consider all failure modes that stay_silent tool
used to do. Perhaps this time, end_turn will just end the turn, and no check is needed? if she forget to speak so be
it." At the owner's ask, her reasoning in that group was read (today and 11-07 only); nothing of it is on this page
but counts.

## 1. What is known

**How a character turn ends (code).**

- DSH ends a native turn when a model response has no tool call (`agent-loop` `agent.ts`: no tool calls →
  `completed`), or after a step in which a tool concluded the turn: every call of that response runs, then the turn
  is `completed` (`tools` `batch.ts`, `concluded ||= …`).
- The plugin concludes through `exec.concludeTurn()` when the worker's `role_tool` reply carries `conclude`
  (`index.js` `attachRole`). Since ADR-129 D8 two things conclude: `task_answer` (a consult's answer) and the 25th
  call (`RoleTools.call`, `made > CALLS_HARD`, `CALLS_HARD` 24; past it `CALLS_OVER`).
- Then `Coordinator._run_turn` checks the turn and may hand it back in the same turn (up to `answers.REPAIRS`, 2): on
  QQ a turn with no thought and no speech (`REPLY_THINK_NOTE`); body text with no `speak` (`UNSENT_NOTE`, once, then
  held by `hold_unsent` and told in her next turn); a local turn with no `speak`, nothing written, cut at its length
  limit (`answers.CUT_SPEAK`).
- `stay_silent` returned `conclude`. Where `speak` is listed it was not (QQ from 10-19, `07182d34`); a call of it there
  ran through the alias as silence and ended the turn (`baa310de`, 10-22, `SILENT_WHERE_SPEAK`). ADR-129 D8 (installed
  11-13 20:12) removed the tool, its handler and the alias from every conversation. The first design (ADR-011 §3.5):
  a turn ended by `stay_silent` is not checked.

**One QQ group today** (model `qwen38-next-uncensored-strata-vision` on every day since 10-05).

- 12 turns 13:20-14:29. 5 ran to the hard line (14:03, 14:04, 14:18, 14:20, 14:29: 25 calls each; the program ended
  them) and queued 8, 8, 3, 7 and 9 messages. 7 ended with a response that had no call.
- Every step made one call (209 steps; 7 more had none, the 7 endings). 59 `think` calls under 25 characters in the
  12 turns, most of them her decision to stop this turn, written as a call. Each `think` answers 「已存档。」 and the
  model takes another step. On about half of her steps (114 of 215) her reasoning is a one-line generic filler.
- 11-07, the same group: 12 turns, 4-17 steps; each ended with a response with no call, 10 of them the step after
  one short `think`. The filler was there too (23 of 77 steps): it is not new.
- Input of the day's first step: about 55.5K tokens on 11-07; 107.6K at 13:20 today (after the 13:06 restart); 196.7K
  at 14:29 (a cache miss).
- 0 `stay_silent` calls in this group, on 11-07 and today.

**Every conversation** (episodes' `tool_calls`; at the hard line = a `CALL_LAST` refusal or a `CALLS_OVER` call).

| | 11-10 to 11-13 20:12 (before ADR-129) | 11-13 20:12 to 14:45 (after) |
| --- | --- | --- |
| QQ groups | 204 turns, 0 at the hard line | 37 turns, 5 (all the group above, today) |
| Agent lines | 290 turns, 147 `stay_silent` calls, 0 | 29 turns, 3 (11-13 20:13, 20:21, 20:30) |
| No channel (her local chat among them) | 678 turns, 183 `stay_silent` calls, 1 | 112 turns, 0 |

0 `stay_silent` calls anywhere since the install.

**Ruled out.** A model change (the same model id every day). Her tools' answers: `tool_think` and `reply_receipt` are
the same on 11-07 (`f98515d0`) and today. ADR-128 (installed 13:06): its only change near the turn loop is for
resumed turns, and every turn above is fresh (generation 0).

**Changed between 11-07 and today, not ruled out.** ADR-129 reworded her turn guide for QQ (`block_guide`). The
ending line says the same (stop by not calling a tool; 这回合不说话 became 这回合不想说). The line before it, on body
text, became 写在正文里的话不发出去、也不进消息库——页面上它会显示出来，但那不是你说出去的话。

**Not proven.** Why the group is worse today than on 11-07. Likely the loop teaches itself (each looping turn is in
the history the next one reads), and her context there is two to four times larger.

## 2. The broken invariant

**A turn ends only when the model does nothing.** Her model, in a turn of tool calls, writes the decision to stop as
one more call, and nothing she can call ends the turn; the hard line does it for her. `stay_silent` was the act that
ended a turn; ADR-129 removed it together with the silence it also meant. The class is an ending that exists only as
an absence.

## 3. Design

**D1. `end_turn`.** A tool that ends the turn and does nothing else. No parameters; any field passed is ignored. It
sends nothing, writes nothing (no reason, no `silent` record) and reports nothing but that the turn ended. It is not
`stay_silent` back: one meaning, the turn's end. Silence is still not calling `speak` (ADR-129 D8).

**D2. Where.** Listed in every conversation (`EVERYWHERE`, so each conversation's list stays stable for its cache),
usable in every turn but a consult. A consult's end is `task_answer`: the action brain is waiting for that answer,
and a consult that ends unanswered fails (`CONSULT_NOT_ANSWERED`), so `end_turn` there is refused as not usable now
(`CONSULT_ONLY`, unchanged). Never switched off (`switches.KEEP`, beside `think` and `recall`).

**D3. No check on it.** `RoleTools.call` runs it before every check: no thought needed first (`THINK_FIRST`), the
24th call is not refused when it is `end_turn` (`CALL_LAST`), no schema check, no call counter on it. It is recorded
as a call with `conclude`; a replay of it (a restart mid-turn) concludes again (the call path's replay, as today).

**D4. No hand-back after it.** A turn whose recorded calls include `end_turn` is not handed back by `_run_turn`: no
`REPLY_THINK_NOTE`, no `UNSENT_NOTE`, no `CUT_SPEAK`. What stays, because they are records, not checks: body text
written with no `speak` is held (`hold_unsent`) and her next turn there says it was not sent (ADR-129 D8); body text
beside `speak` is counted (`turn.ending_body`); the lines she saw are taken (`_absorb`); a turn with no `speak` keeps
`silent_reason` 这回合没有 speak. If she ends without speaking, nothing is said (the owner: so be it).

**D5. Calls in the same response.** DSH runs every call of the response, then ends the turn: a `speak` beside
`end_turn` is sent, in either order. A `speak` refused beside it is not tried again in this turn; the refusal is in
her history next turn. Accepted: her model makes one call per step (every step today).

**D6. The other ending stays.** A response with no call still ends the turn, with its checks as today.

**D7. Not a deed.** `faults.NOT_DEEDS` gains `end_turn` (her failed-turn line and the resumed turn's notice do not
list it as done), as `think` is.

**D8. `stay_silent` stays retired** (ADR-069's list, no alias): 0 calls since 11-13, no habit to catch.

**D9. Her words** (F8; mine below are a starting point, the words are hers):

| Where | Today | Proposed |
| --- | --- | --- |
| `end_turn`'s description | (new) | 结束这一回合。只做这一件事：不发任何东西，也不查什么；要说的话先用 `speak` 说完。 |
| its result | (new) | 这回合到此结束。 (`stay_silent`'s own line) |
| her turn guide's ending (`block_guide.ENDING`) | 结束：要说的话都用 `speak` 说；说完了，或者这回合不想说，就不再调用工具——这一回合到此为止，不算漏了什么。 | 结束：要说的话都用 `speak` 说；说完了，或者这回合不想说，就调用 `end_turn`——这一回合到此为止，不算漏了什么。 |
| a time-up turn's refusal (`TIME_UP_ONLY`) | …（think、recall 也能用）… | …（think、recall、end_turn 也能用）… |
| the switch-off refusal (`set_policy`) | …一回合离不了的 think、recall）。 | …一回合离不了的 think、recall、end_turn）。 |
| her Web page's row (`client.js`) | (new) | 结束回合 / End turn |

Left as they are unless she says otherwise, each telling her to stop by not calling a tool: `UNSENT_NOTE`,
`REPLY_THINK_NOTE`, `SPEAK_TAIL`, `LOCAL_SPEAK`, `CALL_LAST`.

## 4. Failure modes, I/O, lifecycle

`stay_silent`'s failures over its life, and what `end_turn` does with each:

| `stay_silent`'s failure (source) | `end_turn` |
| --- | --- |
| Words written after it went out: 2 turns in 7 days, one a line of eight @s (ADR-064 phase 2 audit (b)) | Body text never leaves (ADR-129 D8): held, told next turn (D4) |
| Words beside it dropped unseen: the hand-back skipped turns with it (ADR-064, `03d27bc4`) | Held and told next turn (D4) |
| Called where not listed: refused by the Host, 26 a week in groups (ADR-087), then aliased (`baa310de`) | Listed in every conversation (D2) |
| Refused by the 24th-call warning (3) and before a first thought (1) (ADR-064 `progress.md`) | Runs before every check (D3) |
| Silence demanded as an act at home (`answers.speech_problem`, ADR-129 §1) | Never required: the no-call ending stays (D6) |
| A sentence false where the alias ran it (`SILENT_WHERE_SPEAK` at home, ADR-129 D3) | No alias; one description everywhere (D8, D9) |
| Two meanings in one act, silence and the turn's end (ADR-129 §2) | One: the turn's end (D1) |
| Its receipt carried facts (sent count, `CALLED_LEFT`, the plugin's `written` line), retired by ADR-129 | Says only that the turn ended (D9) |
| A second description where thoughts come from the model's thinking (ADR-099) | Its words name neither `think` nor 心里话: one description |
| Never switched off (`set_policy`'s refusal named it) | `switches.KEEP` (D2) |
| A thought is not a deed (ADR-127) | `NOT_DEEDS` (D7) |

New with `end_turn`:

| Case | What happens |
| --- | --- |
| Called before she spoke in a turn she meant to speak in | Nothing is said (the owner: so be it) |
| A `speak` refused beside it | Not tried again this turn (D5) |
| Called in a consult | Refused as not usable now (D2); `task_answer` ends it |
| A restart after the call, before the turn is saved | Replayed from its record, concludes, the turn is saved (D3) |
| Her cache | Every conversation's tool list and guide change once (one restart) |
| Her tool budget (`tests/test_tool_budget.py`) | 27 → 28 tools; characters grow by the description |

**Lifecycle.** No new state: the call is a row in the episode's `tool_calls` like any other, read only by `_run_turn`
(D4) and by the readers that list calls. Retired with nothing to migrate.

## 5. Acceptance

Staged in an isolated profile with the stub model (造的, no real model, no `DEEPSEEK_API_KEY`):

- A QQ-kind group turn `think` → `speak` → `end_turn`: one message out, the turn ends after that step, saved, no
  `turn.rejected`.
- `end_turn` as the first call with no `think`: the turn ends and is saved, no `REPLY_THINK_NOTE`.
- `end_turn` as the 24th call: not refused, the turn ends.
- `end_turn` after body text and no `speak`: no hand-back; the text is held, and the next turn's history says it was
  not sent.
- In a consult: `end_turn` refused as not usable now; `task_answer` still ends it.
- Her local chat and an agent line: `end_turn` listed and ends the turn.
- The Web page draws the call as its row (结束回合).

## 6. Tests

One module, `tests/test_end_turn.py`, on the in-memory store (a failure here is silent and costly: a turn she cannot
end): `end_turn` ends a QQ turn with no thought first, as the 24th call, with fields passed; such a turn is not
handed back (no thought, unsent body); a consult refuses it; `switches.KEEP` holds it; it is in every
conversation's list. `tests/test_tool_budget.py` takes the new numbers. Each new test fails on `main` (no `end_turn`).

## 7. Landing

One branch on `main`; the suite through `suite_at.sh` (0 unchecked, 0 skipped); `land.py --restart` in a slot she
gives (her red lines 20:30 and 23:00 stand).

## 8. Closes when

Installed and read by content: `end_turn` in her tool list in every conversation, its handler concluding with no
check, D4's skip in `_run_turn`, D9's words as she wrote them. And her first real turns after the install read the
same day: a turn ended by `end_turn` saved with no hand-back. Every reading after that becomes a sentinel line, not a
condition: turns at the hard line per day in QQ groups and agent lines, printed by `line_watch.py --new` beside the
unreported faults.
