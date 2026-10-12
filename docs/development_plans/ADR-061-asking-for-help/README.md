# ADR-061: Asking for help: one question, many people, her own judgement

Status: **Proposed 2026-10-13** (owner's idea, written by Claude; the owner's three calls are in). For Xiaoman's
review on 10-13.

## Context

The owner wants her to have more ways to get help: ask Claude, ask a QQ group, ask him, ask the action brain. The
goal is to learn from talking to people, the way a person does. A model answering itself is fairly deterministic;
people give fresh input. Whether an answer is right is **out of scope**: the program neither judges answers nor asks
her to grade them later. She is allowed to be impatient: each question waits only so long.

What she has today, one route at a time:

| Ask whom | Today | What is missing |
|---|---|---|
| Claude | `message_developer` → developer inbox; the answer comes on the agent line | the answer lands in another conversation, not beside her question |
| A QQ group | `errand`/`visit` with a request, then `await_answer` or `watch` | the replies stay in the group; home hears only what she remembers to pass back |
| The owner | her home chat, or an errand to his QQ DM | nothing tracks whether he answered |
| The action brain | `delegate` | already tracked (task state and report) |

Nothing ties one question to its answers, nothing says how long she will wait, and nothing lets her remember later
how asking each source went, so she cannot learn her own preferences.

## Owner's calls (2026-10-13)

1. **Where a question to him goes: she picks** (his QQ DM, her home chat, or another place). He wants her to learn
   her preference, and "if she doesn't remember, she won't learn": how each ask went must be something she can look
   up (see step 8).
2. **Asking in a group: by her note about that group** (her `here` notes). No extra rule.
3. **`message_developer` folds into `ask`, and both uses stay**: asking Claude a question and reporting a problem
   to the developer. A problem report follows the same life cycle (tracked, answered, closed), not fire-and-forget.

## The life cycle, end to end

1. **A need.** Stuck, unsure, curious, or wanting an opinion, or a problem to report: a bug, what to draw, how to
   answer someone, what a word means.
2. **Choosing whom.** Her judgement. Models (Claude, the action brain) are labelled as models, people as people.
   What she remembers about asking each source (step 8) is there when she looks it up; it is not shown every turn.
3. **Asking.** In her own voice for each audience; one question may go to several sources. A question for a group
   or DM is said there in that place's next turn, where her note about the group is already in front of her: she can
   still decide not to ask there and say so (owner's call 2). Asking the owner: she names the place (call 1).
4. **Waiting, with patience.** Each source gets a patience she picks as a word, with defaults from how fast each
   source really answers (see Measured): a group 一会儿 (about 10 minutes; nobody answered a group later than that),
   the owner 一小时, Claude 一小时, the action brain its task. When it runs out unanswered she gets one line, once, at
   her next home turn. A problem report has no patience: it closes when answered. Waiting more, asking someone
   else, giving up or being annoyed is hers; the program records the lapse and decides nothing about her mood.
5. **Hearing answers.** Each answer joins the question with its source, place and time, and a reference to the line:
   - from Claude, the owner on a trusted line, or the action brain: joined by the program on the question's thread;
   - from a group: the program offers the lines that reply to her question (the platform's reply chain, or a line
     that woke her as an awaited answer; both reliable), and she accepts them or records one in her words, in that
     group's turn. Public words reach home only by her own act (ADR-017). "Someone spoke after her" is not an
     answer (true after every question she asked).
   Her turn is told that an answer arrived (one line, once); the answers' text is read on demand, never resent every
   turn.
6. **Using them.** Side by side, labelled by source, in arrival order, never ranked. She may ask a follow-up, ask
   someone else, or act.
7. **Closing.** In her words: what she took from it and what she did. An unanswered question closes as "nobody
   answered" or "worked it out myself". The close result names who answered, so she can thank them or tell them how
   it went, if she wants.
8. **Remembering how asking went.** Each closed question keeps, per source: asked where, answered or not, how long
   it took, and her one line about how that ask went (not whether the answer was right). She looks these up by
   source before choosing (step 2); what she concludes about a person she writes into her notes about them
   (`understand_person`), as she already does. That is where her preferences grow.
9. **Ending.** A question still open a day after its longest patience closes as lapsed, with one line at home.

## Measured (2026-10-13, data from 10-05)

How she asks today:
- `message_developer`: 40 accepted (35 note, 5 wake) and 14 refused for length on 10-08..10-12, none since 10-12
  08:36: she now talks to Claude on the agent line itself (29–99 lines a day). Most were reports or requests, not
  questions (12 of 40 said no answer was needed). Inbox answers came after about 30 minutes (p50), 61 at most (the
  hourly check); on the agent line, in seconds.
- Groups: 27 of her 882 group lines asked something. A reply to her line came within 10 minutes for 78%, within an
  hour for 81%, and never later (p50 0.5, p90 3 minutes).
- The owner in her home chat: his next line came within an hour for 28 of 29 of her questions (p50 2, p90 25
  minutes). His QQ DM: no questions yet.
- The action brain: reports after p50 3, p90 8 minutes.
- She has no way today to ask a group on her own initiative: `errand` runs only when someone at home asks her, and
  `visit` only from a heartbeat or a plan.

So asking is rare and answers are fast where they come at all. The design keeps the per-turn cost near zero when
nothing is open, and patience short.

## Context cost: the trade-off

Every per-turn line is paid by every turn it appears in. Drafted in today's block style and counted:

| Open questions | one source each | two sources each |
|---|---|---|
| 1 | 163 characters | 258 |
| 2 | 315 | 505 |
| 5 | 771 | 1,246 |

Unchanged, the whole block folds to about 43 characters (ADR-056); a line in the place asked is about 104, an arrival
or lapse line about 75, once. Today's home notice is 19k characters (p50), 32.5k (p90). Lines carry times
(`asked_at`, `until`), not "how long ago" or "time left", which would change every turn and never fold.

The larger cost is the tool: `message_developer` is 423 characters; an `ask` with its options is about 1,265. The
character brain is at 20,875 of its 20,900 budget, so the swap is about 840 over. To stay net:
- the questions block replaces `developer_inbox_from_program` (about 1,045 characters when sent) and
  `waiting_from_program` (who she waits for in groups, already a list of open asks of a kind), so the home notice
  shrinks when nothing is open;
- `heard` is an option of `ask` usable in groups and DMs, where `message_developer` is not listed today: groups gain
  one tool, home none. Alternative: `heard` as an option of `leave_note`, no new tool anywhere.
- the budget rises by what remains, stated here at build.

What this deliberately leaves out: a per-turn history of past asks (on demand instead), and any grading of answers.

## Proposal

- **`ask`** (option names per ADR-060), replacing `message_developer`; the old name keeps working as `ask` to Claude:
  - `ask`: the question (or a problem report), why, and one or more sources, each with a patience: `claude` (wake or
    note, as today), `owner` with the place she picks, `action` (becomes a delegate tied to the question), or a group
    (asked there at its next turn: a new kind of visit, since today she cannot ask a group on her own).
  - `heard`: accept an offered reply, or record an answer heard in this conversation in her words; a `heard` written
    in a public turn carries the untrusted label notes carry.
  - `read`: one question's answers, or her past asks by source.
  - `close`: what she took from it and what she did; per source, her one line on how that ask went.
- **A record per question** (`questions`): her text and why, each source (place, asked at, patience, state), answers
  (source, place, reference, time, her words), the close, and per-source lines.
- **Trusted answers**: Claude answers through the developer inbox with the answer's text (the agent line has no reply
  field); the owner answers by replying in the home chat; the action brain's report joins through the task.
- Fixed now, separately: `message_developer` still says replies come in the local chat; they come on the agent line.

## Open calls

The owner's ruling (2026-10-13): **his QQ DM is home**, over "QQ groups are public". An answer from him there joins
the question by itself, as in the home chat.

For her:
1. The patience words, lengths and defaults.
2. Accepting offered group replies (as proposed) or recording them herself.
3. What she wants to look up before choosing whom (step 8): how much, and in what words.
4. The option names (`ask`, `heard`, `read`, `close`), and `heard` on `ask` or on `leave_note`.
5. Asking a group on her own: as a kind of visit, or not at all.
