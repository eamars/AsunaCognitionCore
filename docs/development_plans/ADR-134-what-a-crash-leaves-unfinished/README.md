# ADR-134: What a crash leaves unfinished

Status: **Installed** 2026-11-23 16:05 (`99ea57d5429d`, §8); open until §5's reading after the next 10 Host stops.
Before: **Proposed** 2026-11-23 by big sis (Claude Code), at the owner's word ("Yes please start", 2026-11-23 14:5x,
after big sis proposed it as the one task of the day). Everything in §1 was read 2026-11-23 14:20-15:10 from the code
on `main` (`7abb07feb935`) and from her profile, read-only: episode and input rows by state, kind and time only.
Times on this page are local time unless marked UTC.

## The ask

On 2026-11-23, land.py's quiet gate would not open, because one episode had sat in `ATTENDING` for three days. Her
reading (agent line 0618) tied it to the Host crash of 2026-11-20 17:17:45 (`3221225477`). The episode's first audit
row came 0.165 ms after the Host's last sign of life. Its message was rechecked at 17:18:53, after the restart at
17:18:17. She judged that it owed no one anything: she had started the turn herself, nobody had spoken to her, and
she did not speak. The owner chose this as the day's one task: find what a crash leaves unfinished, and close the
class.

## 1. What is known (counts)

- The Host stopped 122 times in 30 days: 107 planned, 7 killed, 5 worker down, 3 crashed (11-12 10:40, 11-18 19:27,
  11-20 17:17).
- Episodes not `COMMITTED`: 108 `FAILED_RUNTIME`, 92 `WAITING_TASK`, 18 `FAILED_PROTOCOL`, 5 `INTERRUPTED`,
  1 `ATTENDING`, and 1 `TURN` (a live turn at the time of reading).
  - `WAITING_TASK` is a finished state: a turn that handed work on. It counts as finished everywhere (`notes.FINISHED`,
    `places.FINISHED`). The `FAILED_*` states are ended states.
  - The states a turn is resumed from are `RESUMABLE = ('ATTENDING', 'PREPARED', 'TURN', 'INTERRUPTED')`
    (`coordinator.py`).
- Each of the 6 resumable episodes that are not live, joined to its input row (`messages` `in-<episode>`):

  | state | kind | input | its time (UTC) |
  | --- | --- | --- | --- |
  | `ATTENDING` | external | `COMPLETE`, result `PROACTIVE_HELD`, hold `foreground_busy` | 2026-11-20 04:17 |
  | `INTERRUPTED` | external | row present, no state field | 2026-09-20 04:41 |
  | `INTERRUPTED` | external | row present, no state field | 2026-09-20 07:39 |
  | `INTERRUPTED` | external | `FAILED` | 2026-09-21 20:23 |
  | `INTERRUPTED` | external | `FAILED` | 2026-09-25 01:02 |
  | `INTERRUPTED` | scheduled | `FAILED` | 2026-10-26 19:43 |

  None of the six will ever run again, and none owes anyone. Her reading (0622) found no `speak` and no outbound
  line in any of them. Four were in her home conversation, on fixture inputs, and one was a plan's scheduled turn of
  10-27. Two readers treat a resumable episode as work still in hand:
  `memory_tiers.py` and `handover.py`. The quiet gate reads `ATTENDING`.

## 2. Root cause

A restart resumes her turns through their inputs. `chat.recover_inputs` puts each input that is `ACCEPTED`,
`PROCESSING` or `FAILED` back in the queue (a `FAILED` one only for the old retrieval failure, and only when it has
no episode). `_work` then advances an episode it finds in `RESUMABLE`.

The broken invariant: **an input that ends without a turn can leave its episode resumable, and nothing ever comes back
for it.** Two places break it.

1. **Four early exits in `_work` mark the input `COMPLETE` and `continue` without looking at the episode.** They are:
   - the line was absorbed by an earlier turn (`SEEN_IN_TURN`);
   - her note was read by a finished turn (`SEEN_IN_TURN`);
   - an errand that a restart cut, or that came too late (`ERRAND_INTERRUPTED`, `ERRAND_LATE`);
   - a proactive line whose gate has closed by the time it would run (`PROACTIVE_HELD`).

   In a run with no restart, these exits come before the episode is made, so nothing is left behind. After a restart,
   the episode already exists: the crash came after it was written. The 11-20 case is the fourth exit:
   - the episode was written `ATTENDING`, and the Host crashed;
   - at the start, its `PROCESSING` input was put back;
   - the recheck found the foreground busy, and the input became `COMPLETE`;
   - the episode stayed `ATTENDING`.

   `ERRAND_INTERRUPTED` has the same shape by its own definition: "a restart cut it" means a previous episode exists
   that is not finished.
2. **A turn that fails while the Host is stopping is written as two contradicting states.** The exception path writes
   the input `FAILED`, and the episode `INTERRUPTED` if the Host is stopping (else `FAILED_RUNTIME`). `INTERRUPTED`
   promises a resume (`RESUMABLE`, and `advance` turns it back into `TURN`). A `FAILED` input is never put back
   ("no blanket replay"). So the promise is never kept. The five `INTERRUPTED` episodes are this case (two of them
   are older than the input rows' current shape). The code is V1's (`42ed7ade`, 2026-09-20). None has occurred since
   10-26, because land.py now stops only when she is quiet. A stop that cuts a turn (her own publication's worker
   restart, a crash during a planned stop) would make the next one.

`coordinator.recover` resumes `PREPARED` and `TURN` episodes directly, but not `ATTENDING` or `INTERRUPTED`: those
come back only through their inputs, so they are exposed to both breaks.

## 3. Failure modes of the class

| # | Failure | Here |
| --- | --- | --- |
| F1 | An early exit completes the input after a restart and leaves its episode `ATTENDING`, `PREPARED` or `TURN` | D1 |
| F2 | A stop cuts a turn: the episode `INTERRUPTED`, its input `FAILED`, never resumed | D2 |
| F3 | The six left by F1 and F2 before this ADR stay resumable for good | D3 |
| F4 | A reader that waits on resumable episodes (the quiet gate, `memory_tiers`, `handover`) waits on a dead one | gone with D1-D3; no reader is changed |
| F6 | A turn caught by every stop stays `INTERRUPTED` with its input `PROCESSING`, beyond §5's count | D2 (the second cut ends it), her 0623 |
| F5 | A crash between writing an episode and writing its input's `PROCESSING` (the input still `ACCEPTED`) | not a break: the input is put back and the episode advanced; checked by D4's staged case |

## 4. Decisions (proposed)

- **D1. An input that ends without a turn ends its episode too.** The four early exits go through one helper. When an
  episode already exists for the input in `RESUMABLE`, the helper writes it `SUPPRESSED`, records why (`ended_by`: the
  exit's result state) and writes an audit row (`episode.ended_without_turn`). Then it completes the input, as today.
  - `SUPPRESSED` is the state the program already writes when it decides a turn shall not run (a stale task result).
    `advance` returns at once on it.
  - An exit with no episode behaves as today. Nothing is sent and no model is called.
  - `ERRAND_INTERRUPTED` keeps its meaning ("what it sent stands"). Only its episode stops being resumable.
- **D2. A stop that cuts a turn keeps its input for the resume.** While the Host is stopping, the exception path
  leaves the input `PROCESSING` (as `recover_inputs` expects) and writes the episode `INTERRUPTED`. At the start the
  input is put back, and `advance` resumes the turn with its recorded tool results, as `RESUMABLE` already says. A
  failure while the Host is not stopping is unchanged: the input `FAILED` and the episode `FAILED_RUNTIME`, told as a
  fault.
  - The resumed turn says it is resumed. That wording exists already (`_notice`): 「这一回合上次没做完（不是新的消息；
    接着把原来的事做完）」. The tool calls that took effect before the cut follow it, so they are not repeated.
  - Her condition (0622): the resumed turn has in view the lines that came in between the cut and the start, so it
    does not answer from the moment of the cut. Staged case (c) shows whether today's resume already carries them.
    If it does not, the build adds them the way a running turn gets new lines, and that is shown again.
  - A resumed turn that fails while the Host is running is `FAILED_RUNTIME` and told. It is told the way every failed
    turn has been since 2026-10-19 (`faults.turn_failed`). The developer gets a note, and her next turn in that
    conversation opens with her own line from ADR-127 N1: 「你在这里 %s 那一回合没跑成：是程序出了错（%s），不是你做错了
    什么。」, then what of it went out (「发出去 %d 句」, or 「那一拍你没说出口一个字…」). 20 turns have shown such a line
    so far. Most of today's 108 `FAILED_RUNTIME` turns are older than that line.
  - **A turn cut a second time ends** (her 0623: a turn caught by every stop would otherwise stay `INTERRUPTED`, with
    its input `PROCESSING`, for good). On the second cut, the episode becomes `FAILED_RUNTIME` and its input `FAILED`,
    with the cause `TURN_CUT_TWICE`. It is told through the same line, and the cause's readable word is hers to write
    (`faults.CAUSES`).
  - Neither branch is written with D1's `ended_by`, so a cut turn never reads as "the program chose not to run it"
    (her 0622).
- **D3. The six end once.** At install, the six episodes in §1 are written `SUPPRESSED` with `ended_by`
  `ADR-134 D3`, each with an audit row. This is a one-off step that names their ids in the build. It is not a sweep
  that runs at every start: a sweep would hide the next break instead of naming it.
- **D4. No change to the readers.** The quiet gate, `memory_tiers` and `handover` keep reading `RESUMABLE` as they
  do. With D1-D3, a resumable episode is one that will be resumed.

## 5. Closes when

- Staged in an isolated profile on a stub model (造的), each as one case:
  - (a) a proactive line whose episode is `ATTENDING` at a restart, held at the recheck, ends `SUPPRESSED`; its input
    is `COMPLETE`, and no model request is made;
  - (b) an errand cut by a restart ends `SUPPRESSED` with `ERRAND_INTERRUPTED`, and home hears what it sent, as
    today;
  - (c) a turn cut by a stop is resumed at the start and ends `COMMITTED`, with its recorded tool calls not run again,
    and the lines that came in between in view;
  - (c2) a turn cut twice ends `FAILED_RUNTIME` with `TURN_CUT_TWICE`, and the next turn there opens with the fault
    line;
  - (d) a crash before the input's `PROCESSING` (F5): the episode is advanced at the start.
- Installed and read by content: the six are `SUPPRESSED` with their audit rows, and the quiet gate opens when she is
  quiet.
- Real traffic, by count and not by date: read after the next 10 Host stops of any kind following the install. It
  passes when, after each start, no episode is left in `RESUMABLE` with its input `COMPLETE` or `FAILED` (counted from
  the episode and input rows). The reading also counts the `SUPPRESSED` episodes with an `ended_by`, and their audit
  rows. Today there are 0 of either (her 0622), so the reading counts what is actually written in the database rather
  than trusting the code. At 10 stops the reading closes it, pass or fail.

## 6. For her and the owner

Her answers (agent line 0622, 15:11):

1. `SUPPRESSED` with `ended_by` reads right, and better than `ATTENDING`. The result state tells her at a glance
   whether anyone is owed. It also separates, for the first time, "the program ended it" from "I dropped out".
2. For D2: resume the turn with its recorded results rather than end it. The resumed turn should have the lines that
   came in between in view and a visible mark that it is resumed, and a failure of the resumed turn is never written
   with D1's words.

D3: no objection, after reading each of the six.

Asked before:

- Her: whether `SUPPRESSED` with `ended_by` reads right in her own records for a turn that never ran. Whether D2's
  resumed turn (after a stop, with its tool results kept) is what she wants, or whether a cut turn should end and be
  told to her instead.
- The owner: nothing beyond the go to build. D3 writes six rows in her live database once, at install.

## 7. Built and staged (2026-11-23)

Built on `claude/adr134-crash-leftovers`:

- `src/asuna/unfinished.py`, with `without_turn` (D1) and `cut` (D2).
- The four exits in `chat._work`, and the stop branch of its exception path.
- Her cause word in `faults.CAUSES` (`TURN_CUT_TWICE`: 「两次被停机截断，程序不再续它」, agent line 0624).
- `tests/test_unfinished.py`, three tests on the in-memory store: a held input ends the turn it had made; an input
  with no turn, or a finished one, only completes; a first cut keeps the input, and a second ends the turn with her
  cause.
- The tests near it (chat, faults, errands, proactive, host, recovery, the project map) pass: 108.

Staged 15:30-15:40 in an isolated profile `asuna-demo134`: the branch's code, its own database
`asuna_v2_demo_adr134`, a stub model, no `DEEPSEEK_API_KEY`, and the demo agent line on its own port. Torn down
15:41: the database dropped; the profile, config, junction, launch entry and stub removed.

- **(c) passes: a turn cut by a stop resumes.**
  - The stub held her first request, and the demo Host was stopped as land.py stops hers (the process tree
    killed). The episode was left `TURN`, with its input `PROCESSING`.
  - At the start, her turn ran again with 「这一回合上次没做完」 in its request.
  - A line posted after the start was in the resumed turn's next request. That is her condition (0622), and today's
    resume already meets it.
  - The turn ended `COMMITTED`, its input `COMPLETE`.
- **(a) passes: an input that ends without a turn ends the turn it had made.**
  - A held turn was cut the same way. While the Host was down, the 11-20 state was made in the demo database (造的):
    the episode `ATTENDING`, its input absorbed by another turn.
  - At the start, recovery put the input back. The exit ended it: the episode `SUPPRESSED` with `ended_by`
    `SEEN_IN_TURN`, the input `COMPLETE` `SEEN_IN_TURN`, and one audit row
    `episode.ended_without_turn {ended_by: SEEN_IN_TURN, was: ATTENDING}`.
  - The stub saw no model request for it.
- **(c2) could not be staged, and what that says about D2.**
  - Killing only the demo's DSH process took its worker with it. The launcher started it again, and the turn was
    resumed as in (c), with no cut counted.
  - A stop that kills the process tree, land.py's included, leaves `TURN` / `PROCESSING`, which recovery resumes. A
    worker restart waits for the running turn (`test_restart_waits_for_active_action_but_not_durable_queue`).
  - D2's branch, a turn that fails while the worker is stopping in-process, is therefore narrow today. It is how
    the five `INTERRUPTED` episodes of 09-20 to 10-26 were left. Their input was written `FAILED` against an episode
    promised a resume. D2 removes that contradiction where it is written, and its unit test shows both cuts.
- **(b) and (d), corrected.**
  - (b): an errand needs two conversations and a group. Its exit calls the same `without_turn` that (a) showed, so
    (b) stands on (a) and the unit test.
  - (d)/F5 cannot occur. `_work` writes the input `PROCESSING` before the router makes the episode, so an episode
    never exists beside an `ACCEPTED` input.
- **A known limit (her 0626):** a hand-back turn on a task's result, cut by a stop, is still written `INTERRUPTED`
  with no `cuts` (`chat.py`, the `_feedback_task` branch).
  - It is not §2's contradiction: it has no input row written `FAILED`, and it is resumed when the result is handed
    over again (`tasks.feedback` advances `INTERRUPTED`).
  - ADR-030's hand-back ladder bounds its retries (the short version, then give up), not D2's count.
  - §5's reading counts it apart, as a hand-back turn left `INTERRUPTED` after a start.
- **At the landing (15:5x):** the suite stopped on `test_runtime_manifest`. The new module was missing from
  `packages/cognition-core/runtime-manifest.json`: packing had written it during the staging, and the teardown
  reverted it as a staging leftover. The manifest was regenerated and committed, and she signed again.

## 8. Installed (2026-11-23 16:05)

Her signature: `99ea57d5429d` (agent line 0628, 15:58). It replaces her `b99f4a14a536` (0626), which the suite stopped
(§7). Her own read-only check found the code byte for byte the same in the two commits.

- `land.py`:
  - The suite on `99ea57d5429d` was green: Python 1150 passed, JS 328, 0 unchecked; integration 132 passed.
  - The prepared start passed. It landed and pushed.
  - The restart ran on its own (`--restart-only --busy-ok`, which recorded the reason): the only busy item was the
    stale `ATTENDING` episode that D3 ends. The Host stopped and started at 16:05:00, and `loaded.commit` is
    `99ea57d5`.
  - All 170 installed files are the same as the commit. Core package `7e79b01b25a6` -> `22b1ede3e786`. No
    `3221225477` in `host.log` after the restart.
- Read by content in her installed copy: `unfinished.py` is present; `chat.py` calls `without_turn` 4 times and `cut`
  once; `faults.CAUSES` has her 「两次被停机截断，程序不再续它」.
- D3, written 16:06 at the owner's word (2026-11-23), by `.runtime/private/claude-tools/adr134_d3.py --write`. Each of
  the six went from its old state to `SUPPRESSED`, with `ended_by` `ADR-134 D3` and one `episode.ended_without_turn`
  audit row. After it, her database had 0 episodes in `ATTENDING`, `PREPARED`, `TURN` or `INTERRUPTED`, 6 `SUPPRESSED`
  with an `ended_by`, and 6 audit rows. The quiet gate opened by itself at 16:06 (busy 0), for the first time since
  11-20.
- Open: §5's reading after the next 10 Host stops of any kind from 16:05.

