# ADR-103: QQ faces

Status: requirements recorded 2026-10-27; designed 2026-10-29 by Claude (a cloud session) from the code at `cc8c006`,
then read against the code by a fresh reviewer (fourteen findings, all folded in below). No owner decision was asked:
the defaults in D1 and D2 are the designer's and stand until the owner says otherwise. Not yet read by Xiaoman. The
parts are: **part 0**, measuring (D4); **part 1**, the program's words and the note that defines the three forms (D2, D3);
**part 2**, what the numbers call for (D5). Parts 0 and 1 are built on `claude/loving-euler-6e0miv`, not landed; part 2
is built only when its numbers say so.

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
   nothing names it. The item keeps `face_id` (digits, cut at 8 characters).
2. The placeholder is written into the line's text at the face's position, for every face; the item goes into
   `raw.asuna_media.items`, at most 8 a line (`count` holds the true total).
3. Core keeps of the adapter's `raw` only that media block and a few marks (`channels.py:kept_raw`: "the platform event
   itself ... is never stored"). A stored face item holds what `_media_item` wrote: `type` (the platform's segment
   name, unbounded), `placeholder`, `face_id`, and `file`, `file_id`, `url`, `size`, `summary`, `sub_type` when the
   platform sent them. **NapCat's own segment (its other fields, a dice result, a chain count) is not kept anywhere**:
   the spool is the inbound queue and its files go once delivered.
4. She reads the line through `people.py:transcript`: the text through `people.heard`, then notes under it from
   `vision.line_refs` (a ref for a picture, a video or a sticker; **nothing for a face**). `vision.media_note` lists
   `other_media_placeholders` only for the line that woke the turn.

**What she reads, rendered** (`people.transcript` over synthetic rows, 2026-10-29, at `cc8c006`; labels and times as
she reads them, the click line as the adapter's words reach Core):

```
[阿杰 #1] 10/4 01:00
  笑死[表情:狗头]没认出的[表情]                    <- two faces, one named; nothing under the line
[阿杰 #1] 10/4 01:02（平台通知）
  给你的那句话点了「赞」                           <- a click on her line: a program line, marked
[老王 #3] 10/4 01:03
  我自己打的[表情:狗头]和[表情包:臭]               <- typed by a person: the same text as a placeholder
```

**A sticker.** An `image` with `sub_type` 1 or 7 reads `[表情包]` or `[表情包:赞]`; a store sticker (`emoji_id`, or the
shop host) reads `[表情包:臭]`; both get a `表情包 ref` note under the line when it can be pulled or is known. An
animated sticker the platform did not mark as one reads as a picture, `[图片:动画表情（未解析）]`.

**A face click** (QQ's `group_msg_emoji_like`). `qqadapter/notices.py:project` turns it into the words
`给{line}点了{e}`, with `{e}` = `「名字」` for an id in the table, the character itself for an id above `0x2000`, else
`一个表情`. It arrives as a line from the person who clicked, marked `（平台通知）` by Core. A click on a line of hers
asks for a look (`reacted`) and is stored as that line. A click between other people is not a stored line: it is held
(`notices.py:hold`), shown once in that conversation's next turn folded into one line,
`这期间的点表情：<who> 给…点了「名字」；…（平台通知）` (at most 5 named), and deleted.

**Sending** (built, working as designed):

- `[表情:名字]` inside a text part of `speak` becomes a real face (`outbound.py:encode_faces`); Core refuses an
  unknown name first (`stickers.py:speech_problem`), and refuses any face or sticker where the conversation sends
  none (`这里发不出表情包或小黄脸`): the refusal her agent line gave on 10-24.
- `speak` kind `sticker` sends a shelf sticker alone; kind `react` with `face` clicks a face onto a line
  (`role_tools.py:_action_part`, `set_msg_emoji_like`).
- A face the platform did not store is caught by the adapter's read-back (`segment_mismatch`) and told to her by
  `context.py:landing_lost` (`…小黄脸没落成`). A part that landed is told nowhere: no part has a positive receipt.
- `faces_from_program` (conversations that send stickers): `seen_here`, the names used in the last 300 inbound lines
  (counted from `[表情:…]` in their text), and a note about writing.

**Not in this code.** `qq_send_face` (searched 2026-10-27 and again 2026-10-29 over the whole tree). Dice and rps
results: ADR-064 listed "`dice` and `rps` show their result: `[骰子:5]`, `[猜拳:石头]`" among its "small content
fixes"; `inbound.py:MEDIA_TYPES` has neither, so a `dice` or `rps` segment would read as the generic
`[dice消息（未解析）]` and its result would be lost. **Not observed:** whether NapCat 4.18.0 sends them as those types or
as faces: `faces.json` has 358 骰子 and 359 包剪锤, which would read `[表情:骰子]` and `[表情:包剪锤]` with no result. The
census (D4) says which.

## Findings

**F1. One thing has several names in what she reads.** Counted from the tracked files on 2026-10-29
(`git ls-files` over `src`, `packages`, `tools`; test, documentation and skill files left out):

| The thing | Her words today | Sites |
|---|---|---|
| a sticker (a picture sent as a message) | 表情包 (40 lines in 7 files of `src/asuna`); **贴纸** (`context.py` REPLY_SENT, `role_tools.py` REACT_LINE_REACT and the quote refusal, the Web label `client.js` `speak.sticker`); **表情** (`reasons.py`: 把一个表情收进了架子); **表情架** (`reflection_map.py`: 表情架 %d 个) | 4 + 2 off the word |
| a face of QQ's table | 小黄脸 (`stickers.py` ×3, `context.py` SEGMENT_WORDS); the token `[表情:名字]`; **表情名** (`role_tools.py` react's `face` and its refusal); **表情** in the same sentence that says 小黄脸 (`stickers.py` FACES_NOTE: 会变成真的表情) | 3 off the word |
| putting a face on a line | 点表情, each time the click (`attend.py`, `capabilities.py`, `context.py`, `notices.py`, `role_tools.py` ×3) | 7, all one meaning |

The class: a name that means more than one thing, or a thing with more than one name, in the harness's own words
(the discipline: odd model behaviour is checked against what the harness tells the model first). The click's name is
consistent, so it stays; it contains the word 表情 and so does 表情包, which D3 says in so many words.

**F2. Nothing she reads says what the three forms are.** `src/asuna/resources/prompts` has no 表情; `block_guide.notes()`
has no entry for `faces_from_program`; `FACES_NOTE` (78 characters) is about writing, is formatted with the platform's
title so it cannot be the guide's fixed text, and travels with the block whenever `seen_here` changes. The only
description of the reading forms is the adapter skill's 0.6.0 changelog line, read on request.

**F3. The three share names.** 赞 is face 76 in `faces.json`, a small named sticker (`[表情包:赞]`, sub_type 7;
`tests/test_stickers.py`) and the emoji of a click on a line (`点了「赞」`). The shapes differ (inline in a sentence; a
whole message that is a picture; a program line marked as a platform notice); the names do not.

**F4. Some of what a face says does not reach her**, and the cloud cannot say how often: a face nobody names reads
`[表情]`; dice and rps are lost either way (above). The stored rows can say (the census, D4); NapCat's own fields only
the adapter can (the item's `shape`, D4).

**F5. Found, not this ADR (own work).**

- A person can type `[表情:狗头]` or `[表情包:臭]`: it is the same text as the adapter's placeholder, and `people.typed`
  makes label-shaped text plain but not placeholders (the rendering above).
- `docs/DEVELOPMENT.md` says an adapter supplies facts, never words; the NapCat adapter words its placeholders and its
  notices. The state is a known departure.
- The adapter's animated sticker without `sub_type` 1 reads as a picture (above).
- The QQ Bot bridge (`packages/channels/qq-bot`) reads every face as a bare `[表情]`; D3's note holds for it, but it
  declares no faces to send.
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

1. 贴纸 becomes 表情包 in `context.py` REPLY_SENT, `role_tools.py` REACT_LINE_REACT and the quote refusal, and
   `client.js` `speak.sticker`.
2. `reasons.py`: 把一个表情 becomes 把一个表情包. `reflection_map.py`: 表情架 becomes 表情包架.
3. `role_tools.py`: react's `face` reads `小黄脸名`, and its refusal 「…」不是这里的小黄脸名 and 要写 face（小黄脸名）.
4. `stickers.py` FACES_NOTE: D3.

Cost: character-brain tool text +2 characters (REACT_LINE_REACT +1, react's `face` +1), which
`tests/test_tool_budget.py` holds exactly (21,915 of 21,915 measured 2026-10-29): both budgets (`CHARACTER`,
`CHARACTER_TIERED`) rise by 2 with the reason beside them. The refusals are not in a tool spec and cost nothing.

**D3. The three are defined once, in the guide.** `FACES_NOTE` becomes fixed text (no platform title), is registered as
the guide's entry for `faces_from_program` (`block_guide.notes()`), and the block arrives without it, as the other
fixed notes do. It says what each form is and how it reads (a click on her line, and the folded line for the others
between people), that names repeat across them, and how she writes; the writing half is stated where it holds, "有
faces_from_program 的对话里", as `SEND_NOTE` states "能发的地方", so a conversation that cannot carry a face is not told to
write one. Final wording is in the code (`stickers.py:FACES_NOTE`, 345 characters).

Measured 2026-10-29 (`block_guide.guide`, speaking conversations): 6,091 characters at `cc8c006`, 6,458 with the note
(+367). It sits in every conversation's system prompt (fixed per conversation, so cached) and comes off each change of
the block (78 characters as formatted for QQ before). Its first turn after the restart in each conversation pays a
cold system prompt and tool list. It is the definition of an interface in the place the program defines its blocks,
not a reminder at the point of use. Its wording stands on F1 to F3, which are in the code; Xiaoman's two turns of
10-24 (below, Open), when they come, may change it, as a new version of this page.

**D4. Measure before widening.** Two instruments; neither changes what she reads.

- *The item's `shape`* (napcat-qq 0.17.0, `inbound.py:shape_of`): a `face` item, and the item of a segment type the
  adapter has no word for (`dice`, `rps`, `mface`, anything unnamed), gets `shape`: the sorted key names of the
  segment's `data` (and of `data.raw` when it is an object) and the value of `result`, `resultId`, `chainCount` and
  `faceType` when it is one to four digits, nothing else of any value; at most 200 characters, key names plain
  identifiers of at most 24 characters. Core stores the item with its line (`kept_raw` keeps the media block as it
  is), so the shape has the line's time and order: three rock-paper-scissors throws one after another show three
  numbers in order. It is the only way to see what NapCat sends, since the segment is not stored. No file, no counter,
  no new I/O: `shape_of` is a pure function run once per such segment, before the line is spooled. **Its end:** it
  stays; it is a few dozen characters on the lines that need it.
- *Census* (`tools/qq_face_census.py`, read-only): over the QQ conversations' stored inbound rows of a window (default
  30 days), counts faces (named, nameless, the nameless ids, the names used), stickers (custom, store, named), the
  segment types in the media items, the unrecognized segment types (the `[xxx消息（未解析）]` tags), the stored click
  lines (and how many name no emoji), typed look-alikes (a `[表情:` or `[表情包` in the text beyond what the media items
  account for, lines whose block was cut at 8 left out), and, from lines that arrived after 0.17.0, the `shape`s and the
  throws (dice, rps, and faces 358 and 359) in the order they came, to the minute. Counts, face names and ids, segment
  type tags and small numbers only; never text, scene or person ids. It reads through the `messages` and `scenes`
  owners and picks the QQ conversations by their scene-id prefix (`qq:`), since channel kinds are loaded only in the
  worker. It can run on the live database before anything lands: the rows are already there. Clicks between other
  people are not rows (above); the adapter's `notices/counts.json` counts them by kind. **Its end:** removed when D5's
  rows are decided and the numbers are written into this page.

**D5. Part 2 is a table, built only on its numbers.** Read from the census over the last 30 days (and, for the shapes,
from the lines after 0.17.0). Anything the table does not decide goes back to design with the numbers.

| Number | Change | Test |
|---|---|---|
| nameless faces: at most 5 distinct ids and under 1% of face items | data only: names for those ids into `faces.json` (`observed`); who gives each name is the owner or she; napcat-qq version bump | none |
| nameless faces beyond that | not designed here: its own step with the numbers | |
| `dice` or `rps` in `unread_types` | `inbound.MEDIA_TYPES` gains it; dice: `[骰子:n]` with `n` from the field the shape shows (ADR-064 recorded none; expected `result`); rps: the words (石头, 剪刀, 布) only after the owner throws each hand once in a test group, one at a time, and `throws` shows in order which number each is; until then the placeholder stays generic | one case each on `_media_item` |
| faces 358 or 359 in `throws` with a `values:` | not designed here: the result must not change the name inside `[表情:…]`, which `faces_block` and `speech_problem` read; its own step | |
| `mface` or another sticker-shaped type in `unread_types` | the sticker path (`sticker_kind`) learns the type: a store sticker read as `[表情包:名字]` with its ids, as the `image` path does | one case |
| none of these in 30 days | nothing is built; the numbers are written here | |

On any change to a placeholder the D3 note is updated in the same commit. ADR-064's "Small content fixes" line about
dice and rps gets a pointer to this row (done with part 1).

## Failure modes

- **Item shape.** A pure function on the event reader thread, once per face and per unrecognized segment, before the
  line is spooled: no I/O, no lock, bounded in time and size (24 keys of at most 24 characters in each of two
  objects, 200 characters out). A hostile segment (non-string keys, nested objects, long keys) yields a shorter shape,
  never an error. An older Core takes the extra field as it takes any field of the media block; an older adapter's
  items simply have none, and the census says how many lines carried one.
- **Census.** Run from a shell by the lead, never by the Host. A slow database makes the census slow and holds
  nothing else; a hung one is interrupted; it writes nothing. It reads one conversation at a time with a projection
  and a time window, and stops at `--max-lines` (default 300,000), saying so. Exit status 2 when it read nothing.
- **Words and note.** No I/O. A session already open keeps its old system prompt until its next render; the block
  arrives without the note either way.

## Tests that earn their place

- The census counting, on synthetic rows through the in-memory store (`tests/test_qq_face_census.py`): a wrong count is
  a wrong decision, silently. One test: named, nameless and 358, sticker kinds, unrecognized tags, a typed look-alike, a
  cut block, the window, another kind's conversation, the cap, and the order of throws.
- The item's shape in the adapter's self-test (five `shape_*` checks): fields not words, a number only when it is one
  to four digits, only the items where the question is open, bounded, and carried with the line.
- Existing tests that stand: `tests/test_stickers.py` (placeholders and the outbound segments),
  `tests/test_per_turn_characters.py` (a block saying what the guide says arrives without it),
  `tests/test_tool_budget.py` (updated).
- None for wording, none for the note's text.

## Landing

One landing, then the census run for D5.

1. Tests: `pytest -q` (the whole run), `npm run test:native`, `python tools/check_staged_secrets.py --personal --all`
   (with the machine's list), `pytest -q integration`, the adapter self-test
   (`python3 packages/channels/napcat-qq/integration/adapter.py --selftest --offline --data-dir <scratch>`).
2. Docs in the same commit as the behavior, all done on the branch: `RUNTIME_API.md` (the kind module: the three forms
   a kind writes), the napcat-qq `README.md` (the item's `shape`), the adapter skill's code map and 0.17.0 changelog
   line, `tools/README.md` (the census row), `docs/map` (regenerated by `tools/project_map.py`; `tests/test_project_map.py`
   fails while stale), the ADR index row, the ADR-064 pointer. The census row of `tools/README.md` goes when the census
   is removed.
3. Merge the branch fast-forward around her publications; the core package and the napcat-qq package change.
4. The planned restart while she is quiet, told to her first; the adapter restarts with the Host.
5. Verified by content: `loaded.commit` is the landed commit, the files the core ships match its blobs, the shipped
   adapter answers `adapter.py --version` with `adapter 0.17.0` (the only version place is `qqadapter/__init__.py`;
   the packages' own `1.0.0` stays), and `block_guide.guide` run from the shipped code holds the note. No content of
   hers is read.
6. Run the census on the live database (before step 4 is fine: it reads stored rows); write its numbers into this
   page with the date; decide D5's rows. The shapes and throws fill only after step 4.

## For Xiaoman

Short, in her register, to be sent once the page is final (the local big sis sends it):

- What changes in what you read: nothing in the lines themselves. The bracket forms are the same.
- What is new: one note, in the place where the program says what each block is, that says the three apart: 小黄脸
  inline, 点表情 as a program line, 表情包 as a whole picture, and that a name like 赞 can be any of them.
- Some words change so one thing has one name: 贴纸 and the stray 表情 for a sticker become 表情包.
- Two things the program will now see for real (not guess): how often a face reaches you with no name, and what
  other segment types arrive unread (dice, rps, others), with the fields the platform sent for them.
- A request: the two turns of 10-24 (the sticker name taken for a face; the face click answered wrongly), by turn id.
  Those are better evidence than anything built here.

## Open

- Owner: D1's default (sending as built) and D2's names, until he says otherwise.
- Owner, if D5's dice or rps row fires: throw each rps hand once, one at a time, in a test group, and a dice once, and
  say which.
- Her: the page, once, before landing; the two turn ids above.
