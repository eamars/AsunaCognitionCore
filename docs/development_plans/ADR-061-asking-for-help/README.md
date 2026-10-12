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
4. **Waiting, with patience.** Each source gets a patience she picks as a word: 一会儿 (about 10 minutes), 一小时,
   半天, 一天. When it runs out unanswered she gets one line, once, at her next home turn. Waiting more, asking someone
   else, giving up or being annoyed is hers; the program records the lapse and decides nothing about her mood.
5. **Hearing answers.** Each answer joins the question with its source, place and time, and a reference to the line:
   - from Claude, the owner on a trusted line, or the action brain: joined by the program on the question's thread;
   - from a group or a QQ DM: she records it herself in that conversation's turn, in her words, with the line's
     reference. Public words reach home only by her own act (ADR-017).
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

## Context cost: the trade-off

Every per-turn line is paid by every turn it appears in; a question list that grew with answers would cost a lot.
The design keeps the per-turn part to counts and arrivals, and everything else on demand:

| Where | What she sees every turn | On demand only |
|---|---|---|
| Home, while questions are open | one line per open question, at most five: whom, how long ago, answers so far (a count), patience left or lapsed; unchanged lines folded (ADR-056) | the answers' text; past asks by source |
| A place where she asked | one line while it is open there ("you asked here at 14:05 …, waiting until 15:05") | |
| When something happens | one line, once: an answer arrived, a patience lapsed | |
| Anywhere else, or nothing open | nothing | |

Estimate: about 60 characters per open question at home, about 60 in the place asked. Two open questions add about
120 characters to a home turn (under 1% of today's ~12.9k-character notice); none open adds nothing. The answers'
text, which could be long, never sits in the per-turn context.

The other cost is choice: one tool replaces one tool (`ask` for `message_developer`), so the count is unchanged; its
description grows by its options (counted at build in `tests/test_tool_budget.py`). The action brain gains nothing.

What this deliberately leaves out to stay small: a per-turn history of past asks (on demand instead), automatic
collection of group replies (she records what she heard), and any grading of answers.

## Proposal

- **`ask`** (option names per ADR-060), replacing `message_developer`; the old name keeps working as `ask` to Claude:
  - `ask`: the question (or problem), why, and one or more sources, each with a patience: `claude` (wake or note,
    as today), `owner` with the place she picks, `action` (becomes a delegate tied to the question), or a group or DM.
  - `heard`: record an answer heard in this conversation (question, line reference, her words).
  - `read`: one question's answers, or her past asks by source.
  - `close`: what she took from it and what she did; per source, her one line on how that ask went.
- **A record per question** (`questions`): her text and why, each source (place, asked at, patience, state), answers
  (source, place, reference, time, her words), the close, and per-source lines.
- **Trusted answers**: Claude answers on the agent line naming the question; the owner answers by replying to it in
  the home chat or on an agent line; the action brain's report joins through the task.

## For her review

1. The patience words and their lengths.
2. Recording group answers herself (as proposed), or the program collecting replies to her question for her to accept.
3. What she wants to look up before choosing whom (step 8): how much, and in what words.
4. The option names (`ask`, `heard`, `read`, `close`).
