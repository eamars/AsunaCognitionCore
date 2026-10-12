# ADR-061: Asking for help: one question, many people, her own judgement

Status: **Proposed 2026-10-13** (owner's idea, written by Claude). For Xiaoman's review on 10-13; the owner's open
calls are listed at the end.

## Context

The owner wants her to have more ways to get help: ask Claude, ask a QQ group, ask him, ask the action brain. The
goal is not the right answer. A model answering itself is fairly deterministic; people give fresh input, sometimes
wrong, and judging it with common sense is how a person grows. She is also allowed to be impatient: each question
waits only so long.

What she has today, one route at a time:

| Ask whom | Today | What is missing |
|---|---|---|
| Claude | `message_developer` → developer inbox; the answer comes on the agent line | the answer lands in another conversation, not beside her question |
| A QQ group | `errand`/`visit` with a request, then `await_answer` or `watch` | the replies stay in the group; home hears only what she remembers to pass back |
| The owner | her home chat, or an errand to his QQ DM | nothing tracks whether he answered |
| The action brain | `delegate` | already tracked (task state and report) |

Nothing ties one question to the answers it got, nothing says how long she will wait, and nothing remembers later
whom she believed and whether that held.

## The life cycle, end to end

1. **A need.** Stuck, unsure, curious, or wanting an opinion: a bug, what to draw, how to answer someone, what a
   word means. Not only development.
2. **Choosing whom.** Her judgement. To help it, the question's record shows what she asked before on that kind of
   thing and how each source turned out (from her own closed questions, step 9). Models (Claude, the action brain)
   are labelled as models, people as people, so she knows which input is fresh.
3. **Asking.** In her own voice for each audience. Asking in a group is public speech like anything else she says
   there; what is fine to ask in public is hers to judge. One question may go to several sources at once.
4. **Waiting, with patience.** Each source gets a patience she picks from words (not minutes): 一会儿 (about 10
   minutes), 一小时, 半天, 一天. When it runs out with no answer, she gets one line at her next home turn: who did not
   answer, how long she waited. What she does with it is hers: wait more, ask someone else, answer it herself, give
   up, or say she is annoyed. The program records the lapse; it does not decide her mood.
5. **Hearing answers.** Each answer joins the question with its source, place and time, and a reference to the
   original line so it can be checked later:
   - from Claude, the owner on a trusted line, or the action brain: joined by the program when it arrives on that
     question's thread;
   - from a group or a QQ DM: she records it herself, in that conversation's turn, in her words with the line's
     reference. Public words reach home only by her own act (ADR-017), and a person remembers what they were told,
     sometimes imperfectly.
6. **Judging.** Answers sit side by side, labelled by source, never ranked or marked right by the program. She may
   ask a follow-up, ask someone else, or try it.
7. **Closing.** She writes what she concluded, whom she believed, and why. An unanswered question can close as
   "nobody answered" or "I worked it out".
8. **Closing the loop with people.** The close result names who answered, so she can thank them or tell them how it
   turned out, if she wants. That is how people learn she listens, and how she learns them.
9. **Looking back.** The review roll (复盘, ADR-058) now and then brings back an old closed question: "you believed
   X on 10-13; did it hold?" She answers held / partly / did not, with a line. What she learns about a person goes
   in her notes about them (`understand_person`), in her words: who knows what, who answers fast, who jokes.
10. **Ending.** A question open after its longest patience plus a day closes as lapsed, with one line at home.

## Proposal

- **One tool, `ask`, replaces `message_developer`** (tool count unchanged). Options (names per ADR-060; old
  `message_developer` keeps working as `ask` to Claude with its level):
  - `ask`: the question, why she asks, and one or more sources, each with a patience: `claude` (with wake or note,
    as today), `owner`, `action` (becomes a delegate tied to the question), or a place (a group or DM; she says it
    there in that place's next turn, or at once if she is there).
  - `heard`: record an answer heard in this conversation (question, the line's reference, her words).
  - `close`: conclusion, whom she believed, why.
  - `held`: the look back (held / partly / did not, a line).
- **A record per question** (`questions`): her text and why, each source with place, time asked, patience and
  state, the answers with source and reference, the conclusion, the look back.
- **Program lines**:
  - at home, `questions_from_program` while any are open: each question, whom she asked, how long ago, answers so far,
    patience left or lapsed;
  - in a place where she asked, one line while it is open there ("you asked here at 14:05: …, waiting until 15:05"),
    so she recognises an answer when it comes.
- **Answers from trusted lines**: Claude answers with the question's id on the agent line; the owner answers in the
  home chat or the agent line by replying to her question; both join the record. The action brain's report joins
  through the task.

## Cost (AGENTS.md)

- Character brain: one tool replaced by one tool (`ask` for `message_developer`); description grows by the options
  (counted at build, `tests/test_tool_budget.py`). Per turn: the home block only while questions are open (one line
  each, at most five shown); one line in a place where a question is open. Nothing otherwise.
- Action brain: none (a question to it is an ordinary task).

## Open calls

For the owner:
1. A question to him goes to his QQ DM, to her home chat, or to wherever he spoke to her last? (His QQ DM counts as a
   public interface; ADR-050's trust boundary.)
2. Asking in a group is hers to judge, with no extra rule. Agreed?
3. `message_developer` folded into `ask` ("ask Claude" and "report a problem" in one tool). Agreed?

For her:
4. The patience words and their lengths; how many questions open at once (or none counted).
5. Whether she records group answers herself (as proposed) or wants the program to collect replies to her question
   for her to accept.
6. How often the review roll brings back an old question.
