# ADR-084: Mechanical limits on her, removed one at a time

Status: **Open**, 2026-10-20. Decided by the owner and worked through with Claude. Steps 1–6 built the same day. Step 7 (speak lines and tool calls) was agreed by the owner and Claude, put to her 2026-10-20 11:4x NZDT, changed by her in four places, agreed by the owner 12:0x, and built.

Every number below says where it came from, so none is left without a source. A number nobody can trace is recorded as such (§6) and not acted on.

## 1. Direction (owner, 2026-10-20)

- **Gradual.** Program rules that refuse or override her judgement are removed one at a time. Each removal names the limit, shows why it was added, and is put to her (her ask: "show why it was added, not only what it blocks now").
- **The test** (owner, on the night gate: "she already roughly knows the time zone, I don't need a hard limit"): she can see the fact the gate decides on, so the decision is hers.
- **What stays:**
  - the harness's token budget, order and execution, apart from the soft text budget of step 3;
  - the per-turn budget: the most one turn can carry does not grow. More turns, and more frequent turns, are acceptable;
  - the home/public boundary, uncompromised.
- **Hard caps catch only failures:** loops and model failure, deterministic, never reached in normal use (as in the failure-capture design). Below them, reminders replace refusals, because a refusal costs a retry, a lost message, or further refused steps.

## 2. Evidence

- **The inventory:** about 100 limits in six groups (time gates, counts, expiries, length caps, turn and place rules, program overrides). It was made from the code only and spot-checked by Claude. File: `.runtime/private/limits/mechanical-limits.md`, about 25 KB, local, never committed.
- **The survey:** how often each limit actually stopped her. It counted audit records and DSH session-log tool errors only; nothing she wrote was read. Span: audit records from 2026-09-20 to 10-19, role-tool records from 10-05. The counts used are quoted where they apply.

## 3. Built

| step | limit | change | numbers behind it | commit, record |
|---|---|---|---|---|
| 1 | Night gate on visits and wake-notes (「那边这会儿是夜里」) | removed | stopped her 9 times (6 in the last 7 days) | 29085a22; ADR-012 §12 |
| 2 | Visit gap after her own visit (`heartbeat.after_own_min`, doubled when nobody answered), the wait for quiet before starting a topic (`heartbeat.quiet_min`), and the "last visit still running" guard | removed; both keys deleted; counts per day and per beat stay | gap: 12 stops; quiet: 0. She had set the gap to its minimum, 30 | 0e301001; ADR-012 §12 |
| 3 | Length limits on her prose fields | **hard limits unchanged**; she is asked for **0.8×** of each, and the description states both numbers; text in between is kept and its result says by how much; a refusal shows what its cut leaves out; silent cuts are marked | refused: notes 81, plan intents 53, ideas 44, other short fields 13. **0.8** is the owner's number, chosen 2026-10-20 ("0.8 is my made-up number"). Both numbers on the page: her ask | 3441eeb4; ADR-054 §Soft text budget |
| 4 | `speak` line cap counted lines that never left | counted from the turn's own outgoing messages; failed, cancelled and taken-back parts give their lines back; UNKNOWN counts | 3 failed parts of 1,893; of 12 turns refused at the cap, 0 had lost a line first. She later wrote that her stated reason had been her own mistake | 08edbbb8; ADR-064 |
| 5 | 随身 room was visible only once a store was over its cap | each capped store says how much room is left | that day: self, core and the fullest group notes full; persona 2 left; voice 1 | 13090b88; ADR-062 |
| 6 | Audit retention left no trace when it deleted nothing | every run is recorded; `by` per rule; totals; the latest record kept; `dbread.aggregate` says when it cuts | her own study and her five points | 13cf32b8; ADR-074 |

**Her reading of step 3, in her own measurement.** The soft receipt saves retries; it does not change how she writes. Her first plan intent after the change took six refusals: 1269 → 1216 → 1123 → 1074 → 1033 → 1005 → 999 characters, accepted with the 「超了 199 字」 line. She cut to avoid the refusal, not because she saw the target. Judge the feature by retries saved, not by shorter text.

## 4. Step 7: speak lines and tool calls

**Speak lines, data from 2026-10-14 to 10-20 (reply-part platforms):**

| lines in a turn | turns |
|---|---|
| 1 | 696 |
| 2 | 387 |
| 3 (the cap) | 116 |

- 24 refusals at the cap. They wanted 4 lines (15 times), 5 lines (8 times) and 6 lines (once). She has never asked for more than 6.
- Each refusal dropped the whole call.

**Tool calls, data from 5,180 turns:**

| calls in a turn | turns |
|---|---|
| 1–3 | 3,930 |
| 4–6 | 1,093 |
| 7–9 | 123 |
| 10–12 | 20 |
| more than 12 | 14 |

- 14 turns reached the cap of 12. They went on to 13–18 records: she kept calling and was refused, so the refusal did not stop the turn.

**The design as proposed by the owner and Claude:**
- **Usual:** her own lines setting, and 9 calls.
- **Past the usual:** a reminder to wrap up, not a refusal.
- **Hard caps:** 10 lines and 24 calls.

**Her four changes, all taken by the owner:**
1. **Line hard cap 6, not 10.** Her highest ever is 6, so 6 covers her whole record; at 10, the lines in between would have only a weak hint watching them.
2. **At 24 calls, warn once, then end.** The 24th call is refused with the warning, the 25th still runs, and the turn ends after it. A straight cut could fall between a hand-off and its result, or a written document and its report.
3. **Numbers, not judgement, in the reminders.** Her evidence is the six retries of §3: phrasing like 「该收尾了」 she slides past, numbers she acts on.
4. **The verdict split by setting.** Her agent line and home turns run longer by nature, and would read as "she talks more" if mixed with group turns.

**As built:**

| | speak lines | tool calls |
|---|---|---|
| usual | her `speak.max_messages` (3; hers to set, 1–5) | 9 calls (99.3% of turns stay at or below) |
| reminder | every `speak` that sent text: 「这回合已说 N 行（你平时 3 行以内，硬线 6）」 | from the 10th call, each result: 「这回合第 N 次工具调用（提醒线 9，硬线 24，还剩 M 次）」, and with 3 or fewer left: 「先想清楚哪一步不做」 |
| hard cap (failures) | 6 lines in a turn: the call is refused | the 24th call is refused with the warning that the next one is the last; the 25th runs and the turn ends after it |
| her real maximum | 6 | 18 records |

- **Key name:** `speak.max_messages` keeps its name. It is declared in her persona package, which is hers; she updates its description there.
- **Cost:** a worst-case turn grows from 12 to 25 model steps, only where it would otherwise have been refused repeatedly. The context ceiling (48,000 characters) still bounds every step.
- **Verdict:** 7 days from the restart that installs it, the same counts again, split by setting. The thresholds apply to QQ group and DM turns. Home and agent-line turns are reported but not judged.
  - Fail, and we look again: more than 10% of speaking turns over her usual lines, more than 2% of turns reaching the call reminder, or any turn at either hard cap.
  - Pass: otherwise, it stands.

## 5. Not removed, and why

- **The home/public boundary:** E1 and E2, the trust rules for notes, and the copied-text rule for notes from outside.
- **Data-integrity rules:** `think` first, a judgement not signed as a fact, output checks.
- **Harness wake decisions:** P5 holds, the chain-wake night hold, heartbeat skips. These decide whether the program wakes her, not what she does.
- **Cost guards she sees and can tune:** visits per day and per beat, and lines per turn until step 7.

## 6. The untraced "60"

On 2026-10-20 the owner recalled a "~60 character budget" for `think` as an earlier recommendation of Claude's. It is not in the code, the survey or Claude's memory, so it was not acted on. `think` asks for 300 and keeps any length (her decision, 2026-10-14). If the number is found later, it comes back here with its source.

## 7. Open, each its own task

- Done 2026-10-20: a restart receipt's `qq_adapter` line read as down while its health record lagged behind the restart; it now says the record is from before the restart and either may be true (her ask).
