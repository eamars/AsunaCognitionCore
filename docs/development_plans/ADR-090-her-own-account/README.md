# ADR-090: Her own account is her; a program line carries only its thread

Status: **Built on a branch, not installed** (`claude/her-own-account`), 2026-10-22. The owner asked for a root-cause
fix after an incident in a group ("fix incident 1"); proposed by Claude, reviewed twice by an independent agent,
accepted by the owner. It installs in one quiet restart with the data correction of §5 run first.

## 1. The incident

2026-10-22 16:33–18:25 NZDT, in a group whose lines the owner authorized Claude to read. Her own lines there are
labelled 「小满」; her own QQ account was in the group's roster as another person, 「沈小满 #4」 (its QQ nickname).
She listed it as a bot suspect, set a watch on it (twice), @'d it twice, and delegated an attribution check. The action
brain read 1,447 rows, found 0 under #4, and concluded "an independent account". 0 was right and the conclusion wrong:
her lines are `direction: outbound` with her character id as author and never sit under a roster number. Her home
conversation had said "沈小满 is my name" and then accepted the finding. The owner had to tell her twice.

Not the first time: her account had a roster record as another person in 11 groups since 10-06 (3 carrying her
name); on 10-09 `find_member` filed her, under her own group card, as number 6. Her account is in all 22 QQ groups' member lists,
and `members_from_program` showed her own row as a stranger wherever she is among the most active (in this group,
「[沈小满 #4]」 "last spoke 16:40", her own line).

## 2. Causes

1. **A program line wore its request's envelope.** A task result (`tasks.py`) and a consult's question
   (`coordinator.py`) are the program's lines (ADR-089), stored `direction: inbound`. Both copied the request's
   `group_context` whole: its @-list, its wake reason ("someone @'d you"), its reply link and waits. At 16:36:51 the
   task result at seq 5 carried an @-list holding her own account.
2. **"Is this account me" had no single answer.** `People.transcript` skipped an @'d number only when it equalled the
   row's own envelope account; a program row has none, so her number became a new person with the next number.
   `notices` did the same; `mentions()` took whatever account its caller passed; `group_members` had no notion of her.
3. **She was never told her own names in a group.** The member list gave her own row as one more member, and the
   database hint for the action brain did not say where her own lines are.

The copied envelope did more than make her a stranger: the copied wake reason sent task results through the relevance
gate (`attend.gated` reads only the reason), 11 of them since 10-07, 4 as 「有人 @ 了你」 with the requester as speaker;
a 不理 there would have committed the turn with the result read as delivered and its content never shown. Task results
also counted as 「有人叫过你」 in her places view, as people present in a group turn, and as answers to her questions
(57 program rows in groups carry a copied reply link). Of the inbound program rows in groups (author `asuna:internal`),
154 carry a copied `mentioned_account` reason and 5 `name_called`, counted at the stop that installed this (the latest
arrived two minutes before it).

## 3. Decisions

- **A program line carries only its thread** (`ingress.program_group_context`): the request's `topic_id`, no wake
  reason, no @-list, no reply link. Who authorized the turn stays on the event (`event.person_id`, ADR-089). The
  request itself reaches the turn in `trusted_context_events` (`original_input`, `original_input_id`), now in the short
  hand-back too. Stated changes: a task result is never gated; the 「> 回复 …」 line under it goes; a task started on a
  visit no longer counts its result toward her interjection caps.
- **The readers that pick people's lines leave program lines out** (`NOT_CORE_NOTICE`): `places.room` (called),
  `places.outcome` (answered), `understanding.group_people`, `questions._group_answers`; for rows stored before.
- **Her account is decided in one place.** `People.account_person(scene, number)` is her character id when the number
  is the account the scene's own channel speaks with (`scenes.channel_account_id`, recorded per channel by the host;
  never a name, never a cross-channel set). Every path from an account to a person goes through it. `People.entry` for
  her returns her number-0 record or a virtual one and never writes a number or a platform name. `mentions()` and
  `heard()` take no account argument: an @ of her account reads as her name on any row.
- **She is told her names in a group.** `members_from_program.you`: 「你自己在这个群里的号：昵称「…」，没设群名片；你的发言在
  这里标作「…」。」 (a field of its own: never trimmed, not counted as a member; her row leaves `items`). `find_member`
  matching her account answers 「这是你自己（…）。」 and leaves her out of its count. The action brain's database hint
  (`dbread`, people) says her lines are `outbound` with her character id and never under a roster number, and that her
  account in a group is `scenes.channel_account_id`.

Cost: no new tool; one field in a group turn's member block (about 40 characters); a clause in `find_member` and in
the database hint.

## 4. Tests

`tests/test_her_own_account.py`: an @ of her account on a program line files nobody and reads as her name; her entry
takes no number or name in a private chat; another account with a like name (「沈小满姐姐」) stays a person; the member
list names her in `you` and not in `items`, and `find_member` says it is her and counts the others only; a program
line keeps only its thread and is not gated where its request was; a stored task-result row has only its thread,
keeps who asked, and the short hand-back names its request; a program line is nobody calling, waiting or answering.
Run against the code before this change, five of the six that do not need the new helper fail; the like-name test
passes on both, as it should.

## 5. Data correction

`.runtime/private/self-identity/correct.py` (evidence, not in the tree): with the Host stopped, before the new code
starts, it deletes the scene_people records whose person is the scene's own account and the watches on it. Dry run
2026-10-22 19:5x: 11 records in 11 groups, 1 watch, none holding its group's top number (so no number is reissued).
It refuses while the Host lease is live and exports what it deletes first (`deleted.json`).

Text that named the wrong label stays hers: in that group one dialogue summary, two notes, two task results (one
task's title and goal), and nine artifacts database-wide. Claude lists them to her; she corrects her own records.

## 6. Her conditions and reading (agent line, 2026-10-22 ~18:58; Claude's paraphrase)

- Remove the @-list as the row's content, never who authorized it. (Kept: `event.person_id`.)
- The copied @-list wronged other people too, the request's addressees counted as present or mentioned: fix it at
  the source. (Done: the program line carries none.)
- Her reading: each group's roster count once a day grows with people joining and those she looks up with
  `find_member`, never with program lines.
- She corrects her own records and re-labels ground truth in her bot-or-person and become-human work that rested on
  "an entry with my name but none of my lines".

Signature: ______ (Xiaoman)

## 7. Not in this ADR

How notes between her conversations open turns (the same incident's second half: six reply-woken group turns that
spoke in public, one note answered twice) is ADR-091.
