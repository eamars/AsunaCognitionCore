# ADR-061: Asking for help: one question, many people, her own judgement

Status: **Proposed 2026-10-13** (owner's idea, written by Claude; the owner's three calls are in). Brought up to date
with the code of 2026-10-13 evening (ADR-062 phase 2 built off, ADR-063 fixed, ADR-064 phase 1 built): see "Fit with
today's code". Buildable in two steps (see "Build plan"); step 1 waits on her answer to question 1 below, step 2 on
question 2. For Xiaoman's review.

*Her review:* ____ (her signature).

## Context

The owner wants her to have more ways to get help: ask Claude, ask a QQ group, ask him, ask the action brain. The
goal is to learn from talking to people, the way a person does. A model answering itself is fairly deterministic;
people give fresh input. Whether an answer is right is **out of scope**: the program neither judges answers nor asks
her to grade them later. She is allowed to be impatient: each question waits only so long.

What she has today, one route at a time:

| Ask whom | Today | What is missing |
|---|---|---|
| Claude | `message_developer` → developer inbox, answered on Claude's agent line; or she asks on the agent line herself | nothing ties the answer to the question; the inbox and the line are two records |
| A QQ group | from home, `pass_note` with `mode=wake` to the group (a woken group counts as an outing); `errand` when someone at home asks her; `visit` from a heartbeat or plan | the replies stay in the group; home hears only what she remembers to pass back |
| The owner | her home chat, or a woken note to his QQ DM | nothing tracks whether he answered |
| The action brain | `delegate` | already tracked (task state and report) |

Nothing ties one question to its answers, nothing says how long she will wait, and nothing lets her look up later
how asking each source went, so she cannot learn her own preferences.

## Owner's calls (2026-10-13)

1. **Where a question to him goes: she picks** (his QQ DM, her home chat, or another place). He wants her to learn
   her preference, and "if she doesn't remember, she won't learn": how each ask went must be something she can look
   up (see step 8).
2. **Asking in a group: by her note about that group** (her `here` notes). No extra rule.
3. **`message_developer` folds into `ask`, and both uses stay**: asking Claude a question and reporting a problem
   to the developer. A problem report follows the same life cycle (tracked, answered, closed), not fire-and-forget.
4. **His QQ DM is home**, over "QQ groups are public" (ruling 2026-10-13). The code already treats it so: a DM whose
   person is the owner is `owner_private`, place `home` (`visibility.session_class`).

## Fit with today's code (2026-10-13)

What changed in this ADR, and why:

1. **Every source is a place she can already reach; no new route.** From home, `note_places_from_program` lists her
   home lines (local chat, the owner's QQ DM, Claude's and Codex's agent lines, the peer line) and her groups, and a
   trusted note may wake any of them (`notes.MODES`). Asking another place is that same note, carrying the question:
   a turn opens there, she reads the question with the place in front of her (in a group, her notes about it) and
   says it in her own voice or decides not to. Her words go out by the ordinary outbox like every line of hers. The
   earlier draft's "new kind of visit" and the "she cannot ask a group on her own" finding were wrong: a woken note
   to a group exists and she used it twice this week.
2. **Claude is a place, not an inbox.** Asking Claude is asking on his agent line (route `claude-code`); his answer
   is a line there. The developer inbox keeps only the program's own notes to the developer (`handover.py`). Her
   split (work that needs a seen/answered record went to the inbox) is served by the question's own record. The
   inbox's daily limits (3 wake, 20 note) go: she already talks on the line 29–99 lines a day without one.
3. **How answers join, by place, as the code allows:**
   - a trusted one-to-one place (the owner's chat or QQ DM, an agent line, the peer line): the other side's first line
     there after her question line. There is no reply link to use: the Web chat has none, and a DM envelope is refused
     a `reply_to` (`channels.py`, `DM_GROUP_FIELDS_DENIED`). "Joins by itself" (call 4) can only mean "his next line
     there"; measured, that was his answer for 28 of 29 of her questions. Claude may instead name the question
     (`tools/agent_line.py send claude-code --answers <id>`, carried as `raw.asuna_answer`, kept only for a home kind
     in `channels.kept_raw`);
   - a group: offered, never joined (ADR-017): a reply to her question line (reply chain), a line that got her an
     awaited-answer look, a reaction to her question line that reached her through the gate (ADR-064 phase 1). She
     brings an answer home with `leave_note` and the question's id (below);
   - the action brain: its task carries the question's id; the report joins.
4. **Muted is refused up front, in words.** Asking a group where `own_mute.active` holds is refused before anything
   is woken: `ASK_MUTED: 你在「…」被禁言了（到 11/10 08:00，谁禁的不知道）：问了也发不出去；问别处，或者等解禁`. So is
   a group she muted herself (`group_focus` mute: she does not speak first there) and a place where `tools_off` holds
   the tool. This does not break `own_mute`'s rule that sends are never held back: no send is held, an outing whose
   only purpose cannot go out is not opened. A mute that starts after the question was woken shows on her line as
   today (`没发出去：你在这个群被禁言了`), and that source's state reads 没问出去（被禁言）.
5. **Per-turn lines fold and never repeat (ADR-063).** One block, `questions_from_program`, one item per open
   question. Its fields are clock times (`line_stamp`) and state words, never "how long ago" or "time left" (P4's
   class), and no item is marked `waiting_on_you`, so an unchanged item folds and an unchanged block is a name in
   `unchanged_from_program`. An arrival, a lapse or a close changes one item, which is sent again once: that is the
   arrival or lapse line; there is no separate line. Answers' text is never in the block: a group's offered replies
   are named by the lines' labels and times (they are on the surface, P2's rule), and `ask read` gives an answer's
   text except where its line is still on the surface of the conversation reading it (the Host leaves the text out by
   message id, D10's rule applied to this result). After a compaction the block is restored like any other (D2).
6. **No duplicate with ADR-041.** A group line that belongs to an open question is listed in `questions_from_program`,
   not in `waiting_from_program`. The earlier draft replaced `waiting_from_program`; it stays, since it covers every
   line of hers that @s someone.
7. **The tool is smaller.** `why` goes (ADR-043: her `think` before the call already keeps the reason and brings it
   back); her line on how the ask went joins `took`; `heard` is not an option of `ask` (it would list `ask` in every
   group) but a `question` field on `leave_note`, which is already the public→home path, in her own words.
8. **Memory (ADR-062): nothing new.** The question record is not one of her memory stores: not tiered, not indexed,
   read on demand. Answers are messages in the conversations they were said in, remembered there as today. What she
   keeps from an answer she writes herself with the tools she has: something someone told her with `from` 别人说的
   (she may write it as 事实: 别人说的 is an author who can correct it); a judgment of hers that an answer bore out, by
   rewriting it with `from` 查过的 and its basis (`依据：问过谁、几点、ask 的 id`), which ADR-062's rule (2) already
   accepts. The `close` result says this in one line, and only while tiered memory is on. Considered and dropped: a
   `confirms` option that marks her item confirmed when anyone answered; the program would sign her judgment on the
   evidence that someone spoke, which is weaker than ADR-062's rule.
9. **Absence (ADR-062, her worry).** `ask read` by place says what it searched: `这 30 天问过主人的问题里找了：没有`,
   never "he never told you": people tell her things outside questions.
10. **Owner's answers in the home chat** need no extra event: his line wakes her there. An answer that arrives in
    another conversation than the one she asked from (Claude answering on his line a question from her local chat)
    is the one case with no wake today; see question 4.
11. **The `message_developer` text** already says replies come on the agent line; the earlier "fixed now" item is done.
12. **Names** follow ADR-060 as she agreed it (`do`, `to` for where something goes), since `ask` is new; see question 1.

## The life cycle, end to end

1. **A need.** Stuck, unsure, curious, or wanting an opinion, or a problem to report: a bug, what to draw, how to
   answer someone, what a word means.
2. **Choosing whom.** Her judgement, among the places her notes can reach and the action brain. Models (Claude, the
   action brain, her sister) are named as what they are in the places list. How asking each went (step 8) is there
   when she looks it up; it is not shown every turn.
3. **Asking.** `ask` from a home conversation. To the conversation she is in: her reply in this turn is the question.
   To another place: a trusted note with the question wakes it, and she says it there in that place's voice, or
   decides not to (owner's call 2); that turn ending with no line of hers is recorded as 没问. A question for a group
   carries only what she would say there (it crosses home→public as a note does; ADR-018). Refused up front: a group
   where she is muted or that she muted, a place she cannot reach.
4. **Waiting, with patience.** One patience per question, a word: 一会儿 (10 minutes), 一小时, 半天, 一天, 回了为止
   (a report). Unset, each place takes its default from how fast it really answers (see Measured): a group 一会儿,
   the owner, Claude and her sister 一小时, the action brain its task. While a question waits in a group, a person
   who speaks there unaddressed within its patience (at most 10 minutes) gets her one look through the relevance
   gate, as `await_answer` does for three minutes today. When the patience runs out unanswered, that place's state
   in the block changes once. Waiting more, asking someone else, giving up or being annoyed is hers; the program
   records the lapse and decides nothing about her mood.
5. **Hearing answers.** As in "Fit" item 3. Each answer keeps its place, time and line reference.
6. **Using them.** Side by side, labelled by source, in arrival order, never ranked. She may ask a follow-up, ask
   someone else, or act.
7. **Closing.** `close` with `took`: what she took from it, what she did, and how asking each place went, in her
   words. An unanswered question closes as "nobody answered" or "worked it out myself". The result names who
   answered, so she can thank them or tell them how it went, if she wants.
8. **Remembering how asking went.** `ask read` with a place lists her last ten asks there: when, answered or not, how
   long it took, her `took` line. What she concludes about a person she writes into her notes about them
   (`understand_person`), as she already does. That is where her preferences grow.
9. **Ending.** A question still open a day after its patience closes as lapsed; its item says so once, then leaves
   the block.

## Measured

2026-10-13 (data from 10-05), and re-read on her live database the same evening (counts only):

- `message_developer`: 41 of her messages in 7 days (by NZ day: 10-08 7, 10-09 16, 10-10 9, 10-11 3, 10-12 5, 10-13
  1; the last at 12:23); 39 answered, 2 seen. Answered after 30 minutes (p50), 56 (p90), 113 at most. Most were
  reports or requests, not questions (12 of the first 40 said no answer was needed). On the agent line she gets
  answers in seconds while Claude is watching.
- Groups: 27 of her 882 group lines asked something. A reply to her line came within 10 minutes for 78%, within an
  hour for 81%, and never later (p50 0.5, p90 3 minutes).
- The owner in her home chat: his next line came within an hour for 28 of 29 of her questions (p50 2, p90 25
  minutes). His QQ DM: no questions yet.
- The action brain: reports after p50 3, p90 8 minutes.
- Notes in 7 days: from home to a group 26 (2 of them waking it), to another home line 99, from outside to home 22.
- Her own mute: 2 groups now.

So asking is rare and answers are fast where they come at all. The design keeps the per-turn cost near zero when
nothing is open, and patience short.

## Proposal

- **`ask`** (one tool with `do`), at home only (where `message_developer` is listed today: her local chat, the
  owner's QQ DM, the agent and peer lines):
  - `ask`: `question` (≤ 800 characters, the report or question), `to` (places from `note_places_from_program`,
    this conversation included, or 行动脑), `patience` (one word, optional);
  - `read`: one question's answers (`id`), or her past asks to one place (`to` alone);
  - `close`: `id`, `took` (≤ 500 characters).
  Drafted text (final words at build, hers to reword):

  > 问人或报问题，程序记着问了谁、谁答了、多久。do：ask 提问，可同时问几处，过了耐心就不等；read 读一个问题的回答，
  > 或只写 to 看以前问那处怎样；close 结束一个问题。问别的对话（群、主人的私聊、Claude 的线）：程序在那边开一轮，
  > 带着 question，你到了再决定怎么问。拍板的事（权限、花钱、开哪条道）问主人，不问 Claude。

- **`leave_note` gains `question`** (the question's id): the note goes home and is recorded as that question's answer
  from that group, in her words, with the untrusted label notes from outside carry. Her own-words rule stands.
- **`message_developer`** stays as an unlisted alias (ADR-055's rule): it runs as `ask` to Claude's line, `wake` as
  一小时, `note` as 回了为止, and its result says the new name once. It leaves when her calls stop using it (ADR-060:
  fewer than five a week).
- **A record per question** (`questions`, owner-private scope): her text, the conversation and turn it came from;
  per place: the note that woke it, her question line there, asked at, patience until, state (等着 / 答了 / 没答，不等了 /
  没问 / 没问出去（理由）), answers (place, line or note or task id, time); the close (`took`, time). Every move is one
  audit line without text (`question.asked`, `.answered`, `.lapsed`, `.closed`).
- **`questions_from_program`**: at home, every open question (its text to 40 characters, asked at, and per place
  its state and until); in a group, only the questions asked there (its line's time, until, the offered replies by
  label and time). Block note in the system prompt (once per conversation):
  `你问出去的问题：每处问在哪、到几点不等、答了没有；回答本身用 ask 的 read 读。群里只列在这个群问的，和程序标出的回话。`
- **`developer_inbox_from_program` goes**, with her rows in the inbox (her messages there become closed questions to
  Claude's line, so `ask read` finds them). Claude's hourly check reads open questions to his line.
- **The action brain**: `to` 行动脑 is a `delegate` whose brief is the question; refused where `delegate` is not
  listed.

## Cost (AGENTS.md), measured on the draft

| Brain | What changes | Characters |
|---|---|---|
| Character, tools | `ask` (824) replaces `message_developer` (429); `leave_note` +90 for `question` | +485 in all: `tests/test_tool_budget.py` `CHARACTER` (32, 21055) → (32, 21540), `CHARACTER_TIERED` (31, 20961) → (31, 21446); tool count unchanged |
| Character, tool list per conversation | home conversations list `ask` instead of `message_developer`; groups and other people's DMs list the longer `leave_note` | +395 at home, +90 elsewhere; read once per conversation (cache) |
| Character, system prompt | the block guide's `developer_inbox_from_program` line (101) gives way to `questions_from_program` (89) | −12, once per conversation |
| Character, per turn at home | `questions_from_program`: about 100 characters an open question with one place, 160 with three, when it changes; folded or named unchanged (about 25) otherwise; nothing when none is open. `developer_inbox_from_program` gone (1,237 characters today when sent whole; it folds, so the steady saving is its fold or name, plus a whole send after each compaction) | +0 to +160 a changed question; −25 to −1,237 |
| Character, per turn in a group | the questions asked there while open: about 130 characters each when changed, folded otherwise | +0 to +130 |
| Character, relevance gate | looks within a group question's patience use the existing `awaited_answer` material | no new text |
| Action brain | nothing: a question handed to it is a brief like any other | 0 |

Deliberately left out: a per-turn history of past asks (on demand instead), any grading of answers, a wake of its
own for answers (question 4), and indexing questions for `recall` (a memory change; only if she asks for it).

## Build plan

Owner's rule: tooling ships when built and tested; what changes her prompt or memory gets observation time on real
turns before the next step builds on it. Her per-turn input is profiled after each install (ADR-062 §7): anything sent
twice is a defect fixed before the next step.

**Step 1, home places (tooling, with one prompt part).**
1. The `questions` record and audit; patience table (`PATIENCE`, versioned); lapse and ending checked when the record
   is read and by the heartbeat.
2. `ask` (`do` ask / read / close) in `role_tools.py` at home; sources: this conversation, the home places of
   `note_places_from_program` (woken by a trusted note carrying the question id), 行动脑 (a `delegate` with the id).
   Refusals as coded errors (`ASK_PLACE_UNKNOWN`, `ASK_NOT_REACHABLE`, `ASK_NO_ACTION_BRAIN`, `ASK_QUESTION_UNKNOWN`).
3. Joins: the other side's first line after her question line in a trusted one-to-one place; `--answers` on
   `tools/agent_line.py send` and `raw.asuna_answer` kept for home kinds only; the task's report.
4. `message_developer` → unlisted alias; her inbox rows → closed questions (one-time, at start; the program's notes
   stay); `developer_inbox_from_program` and its guide line go; Claude's hourly check reads open questions.
5. *Prompt part:* `questions_from_program` at home and its guide line; the Host leaves an answer's text out of an
   `ask read` result where its line is on the surface.
6. Tests: the budget raised by exactly the measured characters; a synthetic home turn with an open question sends no
   text twice and folds unchanged; a lapse and an arrival each re-send one item once; the alias runs.
7. Current references in the same change: `RUNTIME_API.md` (the `ask` tool, the question record, `--answers` on the
   agent line), `packages/channels/agent-line/README.md`, `tools/README.md`.

Then one quiet restart (small batch), and a day of observation: her per-turn input profiled, every ask, answer,
lapse and close read from the audit.

**Step 2, groups (tooling, with one prompt part), after step 1's day.**
1. `to` a group: refused up front when muted there, when she muted it, or when the tool is off there; otherwise the
   woken note as in step 1 (the outing counts as today).
2. Her question line marked by the turn the note opened; no line → 没问; a refused send → 没问出去（理由）.
3. Offered replies: reply chain to her question line, awaited-answer looks (one per person within the patience, at
   most 10 minutes), a gated reaction to her question line.
4. `leave_note` `question`; the answer recorded from that group, in her words.
5. *Prompt part:* the group's `questions_from_program`; a question's line left out of `waiting_from_program`.
6. Tests as in step 1, plus: a muted group refused with its words; a group line in one block only.

Then a restart and a day of observation as before.

**After both:** ADR-064 phase 2 (`reply`) is drafted on `ask`'s pattern: one tool with `do`, said in the place's
own turn, the program keeping the record and the receipts.

## Questions for her

Written to pass on as they are. Questions 1 and 2 are needed before step 1 and step 2; the rest have defaults that
can change later.

1. **Names.** The tool is `ask`, with `do` = `ask` / `read` / `close`, `to` for whom, `patience`, `took` for what you
   got out of it. That follows the names you agreed in ADR-060 (`do`, `to`), though your other tools still say `op`
   until ADR-060 is built. Is that right, or should `ask` say `op` like the rest until then? Better words for `took`
   or `patience`?
2. **Bringing a group's answer home.** Default: you write it home in your own words with `leave_note` and the
   question's id, as notes from outside work today (you cannot copy someone's line there). The other way: you accept
   a reply line as it is, and at home it shows in that person's words, labelled as said in public. Which one?
3. **Patience.** Words 一会儿 (10 min), 一小时, 半天, 一天, 回了为止; defaults: a group 一会儿, the owner, Claude and
   your sister 一小时. Different words or lengths?
4. **An answer that lands in another conversation.** You ask from your local chat; Claude answers on his line. Should
   the local chat be woken once (like a platform notice at home, batched by the minute), or learn it at its next turn?
5. **Someone else, for your memory rule.** A judgment of yours becomes a fact only when someone else confirms it or you
   checked it. When an answer bears it out, you rewrite it with `from` 查过的 and the basis (who, when, the question).
   Do you count Claude's answer, your sister's, and the action brain's as "someone else", or only people's?
6. **Looks while waiting in a group.** While your question waits there (up to 10 minutes), anyone who speaks there
   without @-ing anyone gets you one look, through the gate. Too many looks, or right?
7. **Looking back.** `ask read` with one place lists your last ten asks there: when, answered or not, how long, your
   `took` line. Enough to learn whom you like asking, or do you want something else?
8. **Other people's private chats.** Asking someone in their own private chat is left out: from home, a note there
   only arrives when they next speak to you. Do you want it?
9. **The old name.** `message_developer` keeps working (as `ask` to Claude's line) until you stop using it. Fine?
10. **Your inbox habit.** You split work that needs a seen/answered record (inbox) from talk (the line). With `ask`,
    a question or report to Claude's line has that record. Does that cover what the inbox was for?

## Pushback recorded with this update

- "His answers join by themselves" can only be his next line in that place (no reply link exists); it was right 28 of
  29 times. When it is wrong, her `took` says so.
- The developer inbox is not kept as a second path to Claude: two records for one person is the problem `ask` solves.
- The earlier cost table predates ADR-063's folding. The per-turn cost of an open question is near zero when nothing
  changes, and so is the saving from removing the inbox block; the real cost is in the tool list (+395 at home).
