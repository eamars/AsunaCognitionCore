# ADR-131: A turn she can end

Status: **Closed** 2026-11-14 19:0x by proof (§10): installed 18:45 as `2bed5ab29b7d`, read by content, and her
first real turns after it ended by `end_turn`. Proposed 2026-11-14 by big sis (Claude Code), at the owner's
direction (The ask). The owner made it
today's one ADR, ADR-121 next, and asked for it to land as early as she can take it. Read by her 2026-11-14 15:07 at
`1dc8e46cb41f` (agent line 0501): D2 and D4 agreed; D3's wording, D9's words, the time-up turn in D2, a row of §4 and
§8's baseline are hers. Her window for the install: 16:45-18:45, any time before 19:30 (0502). Designed against `main` with ADR-129's exits on top (`8c07e4e02cc2`); every count in
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
usable in every turn but a consult and a time-up turn, the two turns about a running task. A consult's end is
`task_answer`: the action brain is waiting for that answer, and a consult that ends unanswered fails
(`CONSULT_NOT_ANSWERED`). A time-up turn decides its task with `task`'s `more`, `message` or `stop`; an end there
would be leaving without deciding, the shape ADR-128 cured (her 0501). In both, `end_turn` is refused by the gate of
what the turn may use (`NOT_NOW`) with the turn's own words, `CONSULT_ONLY` and `TIME_UP_ONLY` and their twins for
thoughts from the model's thinking, all unchanged: each already names the turn's own end, so `INSTEAD` gets no entry
for it. Never switched off (`switches.KEEP`, beside `think` and `recall`).

**D3. No check on it but the gate.** `end_turn` is still under the gate of what this turn may use (`NOT_NOW`,
D2); nothing else checks it: no thought needed first (`THINK_FIRST`), no refusal by the call count (it still takes a
call number, like any call), the 24th call is not refused when it is `end_turn` (`CALL_LAST`), no schema, its
fields ignored. It is recorded as a call with `conclude`; a
replay of it (a restart mid-turn) concludes again (the call path's replay, as today). A turn ended with `end_turn`
may have no thought in it: that is the design, not an omission (her 0503: otherwise stopping takes two calls, the
shape this page cures). When something matters she writes a thought first herself; that is hers, not the code's.

**D4. No hand-back after it.** A turn whose recorded calls include `end_turn` is not handed back by `_run_turn`: no
`REPLY_THINK_NOTE`, no `UNSENT_NOTE`, no `CUT_SPEAK`. What stays, because they are records, not checks: body text
written with no `speak` is held (`hold_unsent`), and her next turn in that conversation is told it was not sent, once,
in the block `unsent_from_program`: 没发出去：「…」 with the first 40 characters of it (`context`, ADR-129 D8); the
hold is cleared when that turn is saved. Body text beside `speak` is counted (`turn.ending_body`); the lines she saw are taken (`_absorb`); a turn with no `speak` keeps
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
| `end_turn`'s description | (new) | 结束这一回合。除此之外什么都不做：不发话、不查东西；要说的话先用 `speak` 说完再调它。 |
| its result | (new) | 这一回合结束了。 (not `stay_silent`'s old 这回合到此结束。, the line her model has seen: her 0501) |
| her turn guide's ending (`block_guide.ENDING`, in every turn) | 结束：要说的话都用 `speak` 说；说完了，或者这回合不想说，就不再调用工具——这一回合到此为止，不算漏了什么。 | 结束：要说的话都用 `speak` 说；说完了、或者这回合不想说，就调用 `end_turn`，也可以什么都不调用——这一回合到此为止，不算漏了什么。 (both ends stay) |
| a time-up turn's refusal (`TIME_UP_ONLY`) | …（think、recall 也能用）… | unchanged: not usable there (D2) |
| the switch-off refusal (`set_policy`) | …一回合离不了的 think、recall）。 | …一回合离不了的 think、recall、end_turn）。 |
| her Web page's row (`client.js`) | (new) | 结束回合 / End turn; icon `IconPauseOutlineRegular` (`stop_action`'s); no entry in the summary table (no fields) |

All words here are hers (0501).

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
| Called in a consult or a time-up turn | Refused as not usable now (D2); `task` ends it |
| A turn she ends without speaking | From outside nothing is said, the same as if she had dropped off: by design, not a fault of `end_turn` (her 0501; she keeps it in her own records since 11-13) |
| A restart after the call, before the turn is saved | Replayed from its record, concludes, the turn is saved (D3) |
| Her cache | Every conversation's tool list and guide change once (one restart) |
| Her tool budget (`tests/test_tool_budget.py`) | 27 → 28 tools; 20,427 → 20,513 characters declared (+86: its entry 84 characters, 160 bytes, and the list's separator); hers to count again |

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
- In a consult and in a time-up turn: `end_turn` refused as not usable now, with that turn's own words.
- Her local chat and an agent line: `end_turn` listed and ends the turn.
- The Web page draws the call as its row (结束回合).

## 6. Tests

One module, `tests/test_end_turn.py`, on the in-memory store (a failure here is silent and costly: a turn she cannot
end): `end_turn` ends a turn with no thought first, with fields passed, and as the 24th call; after `speak` the parts
are out; a turn it ended is not handed back (no thought where QQ asks for one, words left unsent) and her next turn
still says the words were not sent; a consult and a time-up turn refuse it; `switches.KEEP` and `NOT_DEEDS` hold it;
it is in every conversation's list; its result is 这一回合结束了。 word for word and her turn guide's ending, with
both ends, is in the prompt a turn is sent (her 0504). `tests/test_tool_budget.py` takes the new numbers. Each new test fails on `main` (no `end_turn`).

## 7. Landing

One branch on `main`; the suite through `suite_at.sh` (0 unchecked, 0 skipped); `land.py --restart` in a slot she
gives (her red lines 20:30 and 23:00 stand).

## 8. Closes when

Installed and read by content: `end_turn` in her tool list in every conversation, its handler concluding with no
check, D4's skip in `_run_turn`, D9's words as she wrote them. And her first real turns after the install read the
same day: a turn ended by `end_turn` saved with no hand-back. A reading with no such turn says "no sample", never
"no problem" (her 0504); she reads her own use again the next day. Every reading after that becomes a sentinel line, not a
condition: turns at the hard line per day and where, printed by `line_watch.py --new` beside the unreported faults.
Its baseline before the install (her 0501): 11-13 3 on agent lines (20:13, 20:21, 20:30); 11-14 5 in one QQ group
(14:03, 14:04, 14:18, 14:20, 14:29; 8, 8, 3, 7 and 9 messages queued); before ADR-129, 1 in 1,175 turns
(11-10 to 11-13 20:12).

## 9. The build (2026-11-14)

On `main` after ADR-129's close (`b029cd0d7a3e`): the page (`63f1568dd934`; she read it as `1dc8e46cb41f` before a
rebase that changed only a context line of the index), her verdict 0501 on it (`736b8345898f`), the code
(`80126a3f87b0`), her 0503 sentence on D3 (`ca61724cbd1b`), the project map (`17b844f41353`, generated) and her 0504
asks (`2bed5ab29b7d`: tests that pin her result word for word and her guide's ending in the prompt a turn is sent,
the consult refusal recorded as `NOT_NOW`; the page's call number and "no sample"). Her verdict: install, nothing in
the way (0504 on the code; 0508 moved it to `2bed5ab29b7d`, whose changes after the code are docs and tests only).

- The suite on `2bed5ab29b7d`: Python 1055 passed (1047 and `tests/test_end_turn.py`'s 8), JS 328, 0 skipped,
  0 unchecked. `tests/test_cache_readout.py`, red in her sandbox (an ACL on temp files), passed outside it.
- Her tool budget, counted by her too: 28 tools, 20,513 characters declared (+86), 33,800 bytes (+162).

**Shown (2026-11-14 18:33-18:37, 造的).** An isolated profile and database (`asuna_v2_demo_adr131`, dropped after),
the demo persona, one agent line, every route on a stub model, the Host started with no model key; installed from
the build. Read from the demo's database and the stub's request log:
- `think` → `speak` → `end_turn`: the message reached the line; the turn saved after three model requests, none after
  `end_turn`; no hand-back.
- `end_turn` alone, no thought, with an old `reason` field: saved, no hand-back.
- 23 `think` calls, then `end_turn` as the 24th: not refused; the turn ended.
- `think`, then `end_turn` with body text in the same response and no `speak`: saved, not handed back, nothing sent;
  the next turn's prepared context carried 没发出去：「…」 once.
- A `speak` refused for its shape, then `end_turn`: the turn ended with nothing sent (D5's accepted case).
- Not shown: the page's row 结束回合 (the demo page stayed behind DSH's own preview notice). Unchecked, not passed.

## 10. Installed and closed (2026-11-14)

Installed 18:45 (`back_at` 18:45:56, about 50 s down) as `2bed5ab29b7d` at her word (0509; her window 16:45-19:30).
`loaded.commit` `2bed5ab2`; the 169 installed files the same as the commit; the QQ adapter back by itself; core
package `126a5f610a18`, hers unchanged (`f62358557927`). Read by content in her profile's installed copy: the
description and result in her words, her guide's ending with both ends, `KEEP` and `NOT_DEEDS` with `end_turn`, the
skip in `_run_turn`; 28 tools. From her side (0510) she read the launcher's block (`2bed5ab2`, the package
ids) and `end_turn` in her own tool list.

§8's readings, her first real turns after the install (counts and program words only):
- Her agent line, 18:47: `think` → `speak` (2 parts) → `write_document` → `end_turn`; saved after one delivery, no
  hand-back.
- The QQ group of §1, 19:03: `think` → `speak` (1 part) → `end_turn`; three model steps, saved after one delivery in
  20 s, no hand-back, no short thought to stop. The same group's turns earlier that day: 5 of 12 at the hard line.
- Turns at the hard line from the install to 19:04: none (the sentinel's line has only the baseline's).

Unchecked by both of us, said as such: the page's row (§9), and why `selections.xiaoman`'s candidate id changed at
ADR-129's install. From here the sentinel is the reading; she reads her own use again 11-15 15:30.
