# ADR-089: A line's author is who wrote it

Status: **Built on a branch, not installed** (`claude/author-is-who-wrote`), 2026-10-22. Proposed by Claude after a
read-only study; the coordinating Claude session accepted it. Xiaoman agreed to the build with conditions (§7). It
installs after she reads the diff, in the order of §6.

## 1. The problem

`ingress.persist_input` stored every inbound event as a `messages` row with `author = event.person_id`. Only her own
moments (presence, settlement, visit, note, self-development) got the program's author `asuna:internal`. A task result
(`episode_kind` `task_feedback`, made in `tasks.py`) and a due plan (`scheduled`, made in `schedule.py`) are lines the
program writes, but they carried the person who authorized the turn, often the owner. Every reader of `author` then
read them as that person's words. In her notebook audit (2026-10-22) she found 5 of 20 "requests" were her own task
results or alarms read as the owner's.

The live record, read-only, counts only (2026-10-22, about 16:00 NZDT):

- 823 task-result rows and 180 due-plan rows carry `event.episode_kind`; all 1,003 have `author == event.person_id`.
  483 are the owner's: 30.5% of his 1,584 inbound rows.
- 9 more task-result input rows (2026-09-20/21) have no `event.episode_kind`, so the old `NOT_CORE_NOTICE` (by kind)
  never excluded them.
- 19 of the owner's newest 30 inbound rows were these notices; his newest was one, so `owner_last_message_at` at home
  named a task result.
- 2 such rows were shown to the agent on its line as words the owner wrote there (`channels.owner_lines`).
- 17 `asuna:internal` records sat in `scene_people` as people with a label number (14 in groups): `People.entry`
  enrolled any author it was given.
- No visible effect on familiarity for the 29 other people (0 level changes); all 173 memory units that cite these
  rows are tombstones.

At the dry run of the correction (§6, 16:40 NZDT) the numbers had moved with the running Host: 1,013 rows (833 task
results, 180 due plans) and 18 roster records.

## 2. Decision

A line's author is who wrote it. Who authorizes the turn is a separate thing: `event.person_id` on the row and the
episode's `person_id`, both unchanged.

- `ingress.PROGRAM_AUTHOR = 'asuna:internal'`, the value her own moments already had (one program value, the 926
  internal rows unchanged, one case in People). `author_of(event)` is the program for `INTERNAL_KINDS` and
  `CORE_NOTICE_KINDS`, else the event's person; the idempotency check compares with the same function.
- `NOT_CORE_NOTICE = {'author': {'$ne': PROGRAM_AUTHOR}}`: one field decides "a line someone wrote", the 9 rows of
  §1 included once corrected.
- The program is never a person (`people.py`): `entry()` returns a fixed record and writes none; `label()`,
  `speaker()` and `_author()` read 「程序」; it has no notes; `roster()` leaves out a stored program record; a program
  line cannot be pointed at (`POINTABLE`: no quote, reaction or recall of it). Her history shows such a row as
  「程序」 with its own text.

## 3. Readers

Changed (one exclusion each): the participants of a discussion digest (`discussion_digest.build_digest`), what
followed her line in her review (`self_review.exchanges`), the people here on the owner's Web page
(`native_api.here_people_rows`), the turn's `present` list (`context.py`, whom recall and understand_person may name),
the no-target branch of who she still waits for (`waiting.pending`), the lines and voices of a group's room
(`places.room`), a group's phrases (`condense._speakers`), the person her reply answers (`channels.addressees`, so her
answer in a task-result turn is addressed to nobody unless she @s someone).

Right with no change, since they ask for a person's own lines by author: what the agent line shows as the owner's
(`channels.owner_lines`), `owner_last_message_at`, familiarity's line count, the speaker's tail in a group turn,
history by person, the per-person branch of `waiting`, `People.ensure_roster` and `authors_of` (through `entry`).

Unchanged on purpose: everything that names the turn's `person_id`. She still reads who authorized a task-result or
due-plan turn in its header (`context['speaker']`, `People.relabel(context, scene, event['person_id'])`), the
relationship block and understanding target, the plans listed for that person, the workspace grant and integration
profile, the people entry of a group turn, and the task result's own `original_input`. Familiarity's reply count,
read by episode `person_id`, also stays.

## 4. Authorization

Every check for these turns reads `person_id`, never `author`: `store.authorize(scene, person_id)` in
`ingress.persist_input`, `Coordinator.ingest`/`advance`, `schedule.py` firing; the feedback episode must have
`person_id == task.requester_id`; the route check uses the plan's person; `grants.workspace_grant` and
`integration.event_profile` read the event. The only authorization that reads `author` is
`NativeWorker.channel_input`, reached only for rows with a channel envelope, which a notice never has. A test keeps
this: a due plan for someone not in the conversation is refused whatever its author.

## 5. Notes

Her condition: what a note shows her stays as it is. Note rows were already the program's (`INTERNAL_KINDS`,
direction `internal`), and stay so. What a note shows (where it came from, its hop, its trust, the owner's own line,
the answers it brings) is read from the `notes` collection, from the source row of an external turn with a channel
envelope (`notes.owner_line`), and from `questions._lines_after`, which already left notices out; none of it changes.

One effect remains, through the label alone: the copied-words refusal for a note written in a public turn
(`notes.borrowed`, a 20-character run shared with someone else's line of the last 2 hours) names whose line matched.
If that line is a task result or a due plan, it now names 「程序」 instead of the person who asked. Leaving program
lines out of that check was proposed and is not built: it changes what a note may say, so it waits for her decision.
The record holds 26 such refusals; which of them matched a program line is not known without reading their text.

## 6. The correction and its order

Order: stop the Host, run the correction, then install the new code. The new code refuses a repeated arrival
whose stored author differs (the idempotency check), so old rows must be corrected first.

`.runtime/private/author-fix/correct.py` (not in the tree):

- `--dry-run` reads only and prints counts and the sha256 and size of the export it would write now.
- `--apply` refuses while a Host holds the database lease. It writes the export
  `.runtime/private/author-fix/old-authors.json` (each corrected row's id and old author; the program roster
  records) before any change, then sets `author` to the program on the input row of every task-result and due-plan
  episode (selected by the episode's kind) with `store.put` on the row's revision, audited in stream
  `adr089:author-correction`. A rerun skips corrected rows and keeps the old values already exported; it prints
  changed, skipped and failed, a post-check (rows of these kinds whose author is their person; the kind of the
  owner's newest inbound row) and the time of the closing `author.corrected` event.

The rows are corrected, not deleted: deleting would take over 1,000 lines out of her history, break her reply links to
them (1,005), leave their episodes without a source row and let a due plan's repeated firing in again.

The program's roster records are kept, not deleted. A new label number is the highest in the scene plus one, and 5 of
the 18 hold their scene's highest; deleting them would give those numbers to the next person. They stay as they are,
their numbers taken, and the new `roster()` keeps them out of every list, label and lookup.

Evidence: `.runtime/private/author-fix/` holds the script and, after `--apply`, the export (117,599 bytes at the dry
run; the real run prints its own size and sha256).

## 7. Counts before and after; her conditions

The "who asked" count changes at the correction's commit: the `author.corrected` event in stream
`adr089:author-correction`, whose time `--apply` prints. A count made before it (her notebook audit of 2026-10-22
included) follows the old rule; after it every record, whatever its date, follows the new one. The two are not
compared as alike.

Only program-made lines change: task results and due plans (her own moments already were the program's). A line a
person wrote keeps its author.

Her conditions (Claude's paraphrase of her agreement, relayed by the coordinating Claude session, 2026-10-22, after
16:00 NZDT): in a task-result or due-plan turn she still sees who authorized it (§3); notes stay as they are, or the
change stops and is reported (§5); the correction is idempotent and reports changed, skipped and failed (§6); the 17
roster records are exported first and their numbers never reused (§6); the export's sha256 and size are reported
(§6); the real run prints the commit time, so it can be told to her (§6, §7).

Tests: `tests/test_author_is_who_wrote.py`.

## Her review

______
