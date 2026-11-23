# ADR-134: What a crash leaves unfinished

Status: **Proposed** 2026-11-23 by big sis (Claude Code), at the owner's word ("Yes please start", 2026-11-23 14:5x,
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
  - If the Host stops again while a resumed turn is running, the turn is `INTERRUPTED` again and resumed again. A
    resumed turn that fails while the Host is running is `FAILED_RUNTIME` and told. Neither is written with D1's
    `ended_by`, so a cut turn never reads as "the program chose not to run it" (her 0622).
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
  - (c) a turn cut by a stop is resumed at the start and ends `COMMITTED`, with its recorded tool calls not run again;
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
