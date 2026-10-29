# ADR-103: QQ faces

Status: requirements recorded 2026-10-27; designed 2026-10-29 by Claude (a cloud session), from the code at
`cc8c006`. No owner decision was asked: the defaults in D1 and D2 are the designer's and stand until the owner says
otherwise. Not yet read by Xiaoman. Parts 0 and 1 are built on `claude/loving-euler-6e0miv`, not landed; part 2 is
built only when its numbers say so (D5).

## The ask

The owner (2026-10-27): "QQ face (not sure if she mentioned to you or not. You can ask her about it.)"

The request that turned the requirements into this design (2026-10-29): read ADR-103, review that it is fully
executable, implement it in the cloud; the local big sis speaks with Xiaoman and does the final integration.

In scope: what she reads of the QQ faces others send (her priority), and telling a face, a sticker and a face click
apart. Out of scope unless the owner enters it: a new way to send faces (D1).

## Xiaoman's account (Claude's paraphrase of her agent-line message of 2026-10-27, 12:52, not her words)

- **Sending.** 10-15, in a group: one face sent and received at once. 10-21: she wrote the bracket text without the
  `表情:` prefix; the owner showed the format (`[表情:<name>]`). 10-24, in another group: the owner's ruling that
  this path is not for sending faces at all; since then she sends stickers and text instead. 10-26: one more face in
  the right format (approved by the owner); she has no receipt that it arrived.
- **Receiving.** She has no reliable record of how a face someone sent reaches her (a name, an id, or nothing left
  of it). On 10-24 she mistook a sticker name for a face, and answered a "face click" wrongly: she cannot tell the
  three apart.
- **Stickers are another thing.** Her shelf is the `stickers` collection: 53 custom pictures, fields `name` and
  `when`, no platform faces and no aliases. The adapter's `faces.json` holds 289 faces (number 277 is 狗头, with the
  old name 汪汪 kept as an alias). Her channel skill describes that table.
- **Her priority, if the ADR does one thing:** reading. Understanding faces others send matters more to her than
  sending them; she manages sending with stickers and text, and misses faces in what she reads every day.
- **A suspected entry point, location unknown:** on 10-24 she saw a line in a group, in another agent's tool list:
  `qq_send_face` (G5, every conversation, needs a trusted caller). It is not a name in this code, and may not be the
  real name at all. Her evidence is that one line, no more. It is not the bracket text she stopped writing.
- **A reading of the same day:** her agent line refused a message of hers that only described the bracket format,
  saying faces and stickers cannot be sent there.
- She offers to copy natural samples, and suggests that inbound rows from the database are better samples than any
  she could make up.

## What exists (read in the code at `cc8c006`, 2026-10-29)

**A face someone sends.**

1. NapCat's `face` segment reaches `qqadapter/inbound.py:_media_item`. The name is `faces.name_of`: NapCat's
   `raw.faceText` (`/狗头` cleaned to `狗头`, at most 12 characters), else `data.text`, else `faces.json` by `data.id`;
   an old name resolves to the table's current one (`aliases`). The placeholder is `[表情:名字]`, or `[表情]` when
   nothing names it. The item keeps `face_id` (digits).
2. The placeholder is written into the line's text at the face's position, and the item goes into
   `raw.asuna_media.items` (at most 8 a line).
3. Core keeps of the adapter's `raw` only that media block and a few marks (`channels.py:kept_raw`: "the platform event
   itself ... is never stored"). A stored row therefore holds the text with its placeholders and, per face, only
   `type`, `placeholder` and `face_id`. **NapCat's own segment (its other fields, a dice result, a chain count) is
   not kept anywhere**: the spool is the inbound queue and its files go once delivered.
4. She reads the line through `people.py:transcript`: the text through `people.heard`, then notes under it from
   `vision.line_refs` (a ref for a picture, a video or a sticker; **nothing for a face**). `vision.media_note` lists
   `other_media_placeholders` only for the line that woke the turn.

**A sticker.** An `image` with `sub_type` 1 or 7 reads `[表情包]` or `[表情包:赞]`; a store sticker (`emoji_id`, or the
shop host) reads `[表情包:臭]`; both get a `表情包 ref` note under the line when it can be pulled or is known.

**A face click** (QQ's `group_msg_emoji_like`). `qqadapter/notices.py:project` turns it into the words
`给{line}点了{e}`, with `{e}` = `「名字」` for an id in the table, the character itself for an id above `0x2000`, else
`一个表情`. It arrives as a line from the person who clicked, marked `（平台通知）` by Core. A click on a line of hers
asks for a look (`reacted`); clicks between other people are held and shown once, folded.

**Sending** (built, working as designed):

- `[表情:名字]` inside a text part of `speak` becomes a real face (`outbound.py:encode_faces`); Core refuses an
  unknown name first (`stickers.py:speech_problem`).
- `speak` kind `sticker` sends a shelf sticker alone; kind `react` with `face` clicks a face onto a line
  (`role_tools.py:_action_part`, `set_msg_emoji_like`).
- A face the platform did not store is caught by the adapter's read-back (`segment_mismatch`) and told to her by
  `context.py:landing_lost` (`…小黄脸没落成`). A part that landed is told nowhere: no part has a positive receipt.
- `faces_from_program` (conversations that send stickers): `seen_here`, the names used in the last 300 inbound lines
  (counted from `[表情:…]` in their text), and a note about writing.

**Not in this code.** `qq_send_face` (searched 2026-10-27 and again 2026-10-29: `packages/`, `src/`, `tools/`).
dice and rps results: ADR-064 listed "`dice` and `rps` show their result: `[骰子:5]`, `[猜拳:石头]`" among its
"small content fixes"; `inbound.py:MEDIA_TYPES` has neither, and no adapter file other than `faces.json` says 骰子,
so both still read as the generic `[dice消息（未解析）]`.

## Findings

**F1. One thing has several names in what she reads.** Counted from the tracked files on 2026-10-29
(`git ls-files` over `src`, `packages`, `tools`, test and documentation files left out):

| The thing | Her words today | Sites |
|---|---|---|
| a sticker (a picture sent as a message) | 表情包 (40 lines in 7 files of `src/asuna`); **贴纸** (`context.py` REPLY_SENT, `role_tools.py` REACT_LINE_REACT and the quote refusal, the Web label `client.js` `speak.sticker`); **表情** (`reasons.py`: 把一个表情收进了架子) | 4 + 1 off the word |
| a face of QQ's table | 小黄脸 (`stickers.py` ×3, `context.py` SEGMENT_WORDS); the token `[表情:名字]`; **表情** in the same sentence that says 小黄脸 (`stickers.py` FACES_NOTE: 会变成真的表情) | 1 off the word |
| putting a face on a line | 点表情, each time the click (`attend.py`, `capabilities.py`, `context.py`, `notices.py`, `role_tools.py` ×3) | 7, all one meaning |

The class: a name that means more than one thing, or a thing with more than one name, in the harness's own words
(the discipline: odd model behaviour is checked against what the harness tells the model first). The click's name
is consistent, so it stays.

**F2. Nothing she reads says what the three forms are.** `src/asuna/resources/prompts` has no 表情; `block_guide.notes()`
has no entry for `faces_from_program`; `FACES_NOTE` (78 characters) is about writing, is formatted with the platform's
title so it cannot be the guide's fixed text, and travels with the block whenever `seen_here` changes. The only
description of the reading forms is the adapter skill's 0.6.0 changelog line, read on request.

**F3. The three share names.** 赞 is face 76 in `faces.json`, a small named sticker (`[表情包:赞]`, sub_type 7;
`tests/test_stickers.py`) and the emoji of a click on a line (`点了「赞」`). The shapes differ (inline in a sentence; a
whole message that is a picture; a program line marked as a platform notice); the names do not.

**F4. Some of what a face says does not reach her**, and the cloud cannot say how often: a face nobody names reads
`[表情]`; dice and rps read as unrecognized segments (above). The stored rows can say (the census, D4); NapCat's own
fields only the adapter can (the shape counter, D4).

**F5. Found, not this ADR (own work).**

- A person can type `[表情:狗头]` or `[表情包:臭]`: it is the same text as the adapter's placeholder, and `people.typed`
  makes label-shaped text plain but not placeholders.
- `docs/DEVELOPMENT.md` says an adapter supplies facts, never words; the NapCat adapter words its placeholders and its
  notices. The state is a known departure.
- ADR-064 is marked Built while its dice and rps fix is not (above). It gets a pointer here (D5).

## Decisions

**D1. Scope: reading and telling apart. Sending stays as built.** Owner open question 2, answered by default: the
10-26 approval of a face in the right format and the working path say sending stands; the 10-24 ruling is read as
about where, not whether. No new tool and no `qq_send_face`: that name is another agent's. If the owner rules the
bracket path off, the change is removing the writing half of the note and `speech_problem`'s face check, a separate
small change.

**D2. One name per thing, tokens unchanged.** 小黄脸 is a face of QQ's table; 点表情 is putting one on a line; 表情包 is
a sticker. The tokens `[表情:名字]`, `[表情包:名字]` and the nameless `[表情]` do not change: the owner taught the
first, and she writes the first two. Edits (the whole list, counted above):

1. `context.py` REPLY_SENT, `role_tools.py` REACT_LINE_REACT, the quote refusal in `role_tools.py`, `client.js`
   `speak.sticker`: 贴纸 becomes 表情包.
2. `reasons.py`: 把一个表情 becomes 把一个表情包.
3. `stickers.py` FACES_NOTE: see D3.
4. `role_tools.py` `react：表情名` and its refusal stay (the name of the face you click); not worth four tool
   characters over a budget with none to spare.

Cost: character-brain tool text +1 character (REACT_LINE_REACT), which `tests/test_tool_budget.py` holds exactly
(21,915 of 21,915 measured 2026-10-29): both budgets rise by 1 with the reason beside them.

**D3. The three are defined once, in the guide.** `FACES_NOTE` becomes fixed text (no platform title), is registered as
the guide's entry for `faces_from_program` (`block_guide.notes()`), and the block arrives without it, as the other
fixed notes do. It says what each form is and how it reads, that names repeat across them, and the two ways she
writes. Draft (final wording is in the code):

> 小黄脸：平台自带的小表情，每个有名字。别人夹在句子里发的，读作「[表情:名字]」，没认出名字的读作「[表情]」。点表情是
> 另一样：把一个小黄脸点在某一句话上，你读到的是程序转来的一行「给…点了「名字」」（平台通知），不是他说的话。表情包又是
> 一样：整条消息是一张图，读作「[表情包]」或「[表情包:名字]」，下面标着表情包 ref。三样里有重名的（比如「赞」），看形状分，
> 不看名字。你自己说话时把小黄脸写成「[表情:名字]」夹在话里，会变成真的小黄脸（seen_here 是这里最近有人用过的，别处
> 见过的也行），不认识的名字会被退回；点表情用 speak 的 react。

Measured 2026-10-29 at `cc8c006`: the guide is 6,091 characters (speaking conversations); the note adds about 250 to
every conversation's system prompt (fixed per conversation, so cached) and takes 78 off each change of the block.
It is the definition of an interface in the place the program defines its blocks, not a reminder at the point of
use.

**D4. Measure before widening.** Two instruments, neither changes what she reads.

- *Census* (`tools/qq_face_census.py`, read-only): over the QQ conversations' stored inbound rows of a window (default
  30 days), counts faces (named, nameless, the nameless ids, the names used), stickers (custom, store, named), the
  unrecognized segment types (the `[xxx消息（未解析）]` tags), stored click lines (and how many say `一个表情`), and
  typed look-alikes (a `[表情:` or `[表情包` in the text beyond what the media items account for). Counts, face names and
  ids, segment type tags only; never text, scene or person ids. It reads through the `messages` and `scenes` owners.
  It can run on the live database before anything lands: the rows are already there. **Its end:** removed when D5's
  rows are decided and the numbers are written into this page.
- *Shape counter* (napcat-qq 0.17.0, `qqadapter/shapes.py`): for every segment of an accepted message except `text`,
  `at` and `reply`, counts by UTC day its type, the sorted keys of `data` (and of `data.raw` when it is an object),
  and the value of the keys `result`, `resultId`, `chainCount` and `faceType` when it is 1 to 4 digits; every other
  value is never read into the counter. At most 200 shapes a day, 7 days kept, in `<data>/media/shapes.json`, shown in
  `health.json` as `media_shapes`. It is the only way to see what NapCat sends, since the segment is not stored.
  **Its end:** it stays; it is the same kind of count as `notices`.

**D5. Part 2 is a table, built only on its numbers.** Read from the census over the last 30 days (and the counter,
once running). Anything the table does not decide goes back to design with the numbers.

| Number | Change | Test |
|---|---|---|
| nameless faces: at most 5 distinct ids and under 1% of face items | data only: names for those ids into `faces.json` (`observed`), who gives each name is the owner or she; napcat-qq version bump | none |
| nameless faces beyond that | not designed here: its own step with the numbers | |
| `[dice消息` seen at least once | `inbound.MEDIA_TYPES` gains `dice`; the placeholder carries the number from the field the counter shows (ADR-064 recorded none; expected `result`); `[骰子:n]` | one case on `_media_item` |
| `[rps消息` seen at least once | the same, but the words (石头, 剪刀, 布) only after the owner throws each hand once in a test group and the counter's `result=` values show which number each is; until then the placeholder stays generic | one case |
| `[mface消息` or another sticker-shaped type seen | the sticker path (`sticker_kind`) learns the type: a store sticker read as `[表情包:名字]` with its ids, as the `image` path does | one case |
| none of dice, rps, mface in 30 days | nothing is built; the numbers are written here | |

On any change to a placeholder the D3 note is updated in the same commit. ADR-064's "Small content fixes" line about
dice and rps gets a pointer to this row.

## Failure modes

- **Census.** Run from a shell by the lead, never by the Host. A slow database makes the census slow and holds
  nothing else; a hung one is interrupted; it writes nothing. It reads one conversation at a time with a projection
  and a time window, and stops at `--max-lines` (default 300,000), saying so.
- **Shape counter.** Runs on the event reader thread after a message is accepted (an unauthorized sender's content is
  never looked at, as in `inbound.py`). In memory, saved every 60 seconds and at shutdown, as `notices.Counts` is.
  Its failures are swallowed: a line is never held, dropped or delayed by it; a failed save keeps the counts in
  memory. No I/O per line, bounded memory.
- **Words and note.** No I/O. A session already open keeps its old system prompt until its next render; the block
  arrives without the note either way.

## Tests that earn their place

- The census counting, on synthetic rows through the in-memory adapter: a wrong count is a wrong decision, silently.
  One test, covering named, nameless, sticker kinds, unrecognized tags, and a typed look-alike.
- The shape counter in the adapter's self-test: values outside the allowlist are never stored, the day's cap holds,
  `text`, `at` and `reply` are not counted, and a message the gate refuses is not counted.
- Existing tests that stand: `tests/test_stickers.py` (placeholders and the outbound segments),
  `tests/test_per_turn_characters.py` (a block saying what the guide says arrives without it),
  `tests/test_tool_budget.py` (updated).
- None for wording, none for the note's text.

## Landing

One landing, then the census run for D5.

1. Tests: `pytest -q` (the whole run, with `tests/test_project_map.py` after `tools/project_map.py`),
   `npm run test:native`, `check_staged_secrets.py --personal --all`, `pytest -q integration`, the adapter self-test
   (`python3 packages/channels/napcat-qq/integration/adapter.py --selftest --offline`).
2. Merge the branch fast-forward around her publications; the core package and the napcat-qq package change.
3. The planned restart while she is quiet, told to her first; the adapter restarts with the Host.
4. Verified by content: `loaded.commit` is the landed commit, the files the core ships match its blobs, the adapter
   reports `0.17.0` in `health.json`, and her next QQ turn's system prompt holds the note (render it from the shipped
   code; structure only, no content of hers).
5. Run the census on the live database (before step 3 is fine: it reads stored rows); write its numbers into this
   page with the date; decide D5's rows.

## For Xiaoman

Short, in her register, to be sent once the page is final (the local big sis sends it):

- What changes in what you read: nothing in the lines themselves. The bracket forms are the same.
- What is new: one note, in the place where the program says what each block is, that says the three apart: 小黄脸
  inline, 点表情 as a program line, 表情包 as a whole picture, and that a name like 赞 can be any of them.
- Some words change so one thing has one name: 贴纸 and the stray 表情 for a sticker become 表情包.
- Two things the program will now count for real (not guess): how often a face reaches you with no name, and what
  other segment types arrive unread (dice, rps, others).
- A request: the two turns of 10-24 (the sticker name taken for a face; the face click answered wrongly), by turn id.
  Those are better evidence than anything built here.

## Open

- Owner: D1's default (sending as built) and D2's names, until he says otherwise.
- Owner, if D5's dice or rps row fires: throw each rps hand once in a test group, and a dice once, and say which.
- Her: the page, once, before landing; the two turn ids above.
