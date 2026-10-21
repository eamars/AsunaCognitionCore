# ADR-066: An errand carries home

Status: **Accepted 2026-10-15** (the owner's go), built the same day on `claude/errand-carries-home`; proposed by the
owner, designed with Claude, **reviewed by Xiaoman** (her points folded in below). Two changes from the proposal in the
build, below under "Built".

## What happened

On 2026-10-14 the owner asked her in a group to send him one of her pictures in his private chat. She took it home by
a note. The home turn the note woke could not send an errand (an errand is taken only in a home turn someone spoke
in), so she passed a note to his private chat instead. That chat's turn refused the picture: the owner's chat is
offered only the pictures of its own private scopes, while a group or a stranger's chat is offered her own pictures
from anywhere. Every link of the chain worked; two gates judged by place, not by who asked.

## Owner's direction (2026-10-15)

1. An instruction from home, by `errand`, gives the turn it opens **the full permission of home**, for that turn only.
   It is hard to judge which permission a request needs, so all of it goes.
2. Only `errand` (not notes, visits or plans).
3. The turn runs in a **fork of the destination's session** (DSH fork), so lines arriving there meanwhile stay with
   that conversation.
4. The fork keeps the destination's system prompt and tool list and appends the new permission at the end, so the
   model server resumes from the conversation's cached prefix (no cold start).
5. The home-only character tools (restart, credential, set_policy, private_words, ask, errand, peer_line) stay at home:
   a different tool list would cost a cold start.
6. Who may send one: a home turn (woken by the owner, a trusted line, or her own home turn), and the owner verified in
   any conversation; a home turn woken by her note from a public place counts only when the note carries the owner's
   line, checked by the program.
7. Forked sessions are cleaned up, not left in the session list.
8. The owner's chat accepting her own pictures from anywhere (built, unmerged on `claude/owner-dm-pictures`) is folded
   into this change.

## Decision

**An errand turn is a home turn that speaks into another place.**

- **Where:** a DSH fork of the destination's session at its last completed turn, with the destination's own system
  prompt and tool list. The errand request and home's blocks are appended at the end of the turn's notice.
- **What it may do:** with home's authority on the tools that conversation lists: her pictures from anywhere through
  `speak`, home-scope `recall`, home documents through `write_document`, and `delegate` with home grants (the action
  brain gets the home workspace, sandbox, development tools and LAN integration). Home-only character tools are not
  listed there and stay at home.
- **Isolation:** what she says goes to the destination like any of her lines. What she read, her thoughts and tool
  results stay in the fork; her thoughts there are kept in home scope. Lines arriving in the destination during the
  errand go to its real session and get ordinary turns afterwards.
- **Back in the destination:** its next natural turn carries, at the end, `errand_from_program` once: that home sent
  her (主人, from home) and what she said there. The request itself stays home: it may hold words only home may know
  (her review). What she said there is already the version she judged fit for that place. Nothing she read with
  home's authority comes with it.
- **At home:** the outcome, as errands report today (`errands_from_program`).
- **Afterwards:** a task delegated in the errand turn keeps home's authority, with the requester recorded. The fork is
  marked errand-only and retired before the next Host start like the one-shot sessions (`asuna-launch.mjs`: archived
  after a day, dropped after 14).
- **Visible:** the turn opens with 「家里交代的，带着家里的全部权限；你说出口的话那边都看得到」; the audit records
  `errand.carried` with the fork, the requester and what was sent.

## Failure modes and their handling

| # | Failure | Handling |
|---|---|---|
| 1 | The fork mistaken for the conversation's main session: later public turns run in it, home material inside | The binding marks it errand-only; it is never the scene's main session; it is retired once the errand ends |
| 2 | The destination near compaction: the appended tail pushes the fork over the threshold, DSH compacts a session that will be thrown away, and the turn runs cold anyway | Measured before forking; over budget, or the destination compacting or mid-turn: a small fresh session with the destination's recent lines and the request (cold, small, never compacts) |
| 3 | Two replies at once: the destination's own turn and the errand speak over each other | The errand waits in the destination's queue until the scene is idle, **with a deadline** (her review): past it nothing is sent, the talk there has moved on, and home is told it did not get a word in |
| 4 | Her errand thoughts recalled later in public | Thoughts written in the fork are stored in home scope |
| 5 | A restart during the errand: the fork is orphaned, DSH may resume its unfinished turn | Asuna refuses the stale operation; the errand is marked interrupted and home is told **what it had already done** before the cut (what was sent, delivered or not): interrupted is not undone, and redoing it would send twice (her review) |
| 6 | The fork runs on another model (DSH's fork takes the default model selection) | The fork's route is set to her character route; checked in the build |
| 7 | The fork's cache entry (~3 GiB at 150k tokens) evicts another conversation's | Accepted while errands are a handful a week; that is a premise, not a fact: measured after a week, and reconsidered if she uses them more (her review) |
| 8 | A message planted earlier in the destination is read with home's authority (the sandbox among it) | The turn says its only instruction is home's; the conversation is others' words. Judgment, not a fence: the price of full permission. Her own rule, kept in her persona, not in the core: an errand turn does the one thing it was sent for, nothing it happens to see on the way |
| 9 | She says something private in public | Hers to judge (owner 2026-10-06: home to outside, she decides) |
| 10 | A stranger launders a request home and back out | Only home turns and the verified owner send errands; a note-woken turn needs the owner's own line |
| 11 | The destination has no session yet, or the fork call fails | The small fresh session of row 2 |
| 12 | People there learn that an errand turn carries home, and 「主人说 X」 becomes a lever (her question, 2026-10-15) | Nobody there sees which turn is an errand: her message carries no mark. Authority comes only from the errand's requester, checked by the program at home; no line in the destination can open an errand or lend it authority, whatever it claims |
| 13 | She cannot tell which layer of her acted (her question) | The errand turn opens with what it is; each tool result in it ends with 「（差事回合，家里的权限）」; the destination's next turn names what was done on an errand (`errand_from_program`); her home sees the outcome; **her own lines sent on an errand carry a small mark in her history** wherever she reads them back, so days later they do not read like ordinary lines (her review) |

## What it adds to each brain

Character brain: no tool, no parameter. The `errand` description says the turn carries home (−6 characters, 21,224 →
21,218). Per turn: `errand_from_program` once in the destination's next turn (who sent her, her lines there); the errand
turn's `visit_from_program.carries` (one sentence) and `turn` on each tool result (10 characters); `owner_said` in a
note that carries the owner's line. When the copy could not be made, nothing more: the turn's own history block
brings the recent lines, since none is shown in the empty session. Action brain:
none.

## Built (2026-10-15)

- `errands.py`: the episode's `errand` (the home turn's scene, scope and requester, recorded at ingest), the session id
  `asuna-errand-<hash>`, the patience (20 minutes), the marks and `errand_from_program`.
- The copy: the worker asks the Host (`errand_session`); the plugin copies the destination's events up to its last
  completed turn with DSH's own fork seed (`@deepseek-ai/dsh-session/fork`) in `ensureAgent`, on her character route,
  titled "<conversation> · 差事". It declines when the conversation has no completed turn, is in a turn, or would come
  within 16,384 tokens of its compaction threshold (rows 2, 11); the turn then starts empty with the recent lines. The
  copy is archived when its turn ends; the launcher retires `asuna-errand-*` like the other one-shot sessions.
  Navigation never takes a copy for the conversation, and a plan or task begun on an errand resolves to the
  conversation itself, never to the copy (row 1).
- Home's blocks are not appended to the errand turn's notice: home is reached through `recall`, so the turn costs no
  more than an ordinary turn there unless she looks.
- Authority: `RoleTools._cls` is home's on an errand; `_place` stays the conversation's for what goes out and who is
  there (pictures, `watch`, `leave_note`, blocking). Thoughts go to the home turn's scope (row 4); `recall` reads home
  alongside the conversation.
- Who may send one (direction 6): a home turn someone spoke in, her plan due at home, a note of hers from home, and a
  note from outside that carries the owner's own line (`notes.owner_line`, checked against his account mapping).
- The queue: a late errand completes `ERRAND_LATE` without a turn; one found already started after a restart completes
  `ERRAND_INTERRUPTED` and home reads what it had sent (row 5).

**Two changes from the proposal (Claude, for the owner's review):**
1. **`delegate` does not carry home.** A task outlives the turn and reports back in the destination's own
   conversation, so home's authority would leak past "that turn only"; in an errand turn `delegate`, `task message`
   and `task stop` are refused, saying why (home work goes from home). The Decision's "delegate with home grants" and
   "a task delegated in the errand turn keeps home's authority" are withdrawn.
2. **Pictures follow the conversation's rules,** not home's: a group or another person's chat already takes her own
   pictures from anywhere, and the owner's chat now does too (direction 8, folded in). Home's other pictures (the
   owner's) do not go out into a public place on an errand.

## The first real errand (2026-10-16)

Her home plan sent her at 14:07 NZDT to a group with the results of a research task of hers; nothing was staged for the
test. The four checks:

| Check | Result |
|---|---|
| The session is a fork | Yes: `errand.session` `forked: true`, opened 10 s after the errand was queued, seeded with the conversation's 3,050 events |
| The copy's title | 「<group> · Errand」: the word comes from the Web UI's language table (`uiTitles.errand`), English in this profile; 差事 where the UI is Chinese |
| The cache | First step cold: 88,263 input tokens computed, 13,257 read from cache, 16 s to her first call; the next two steps warm (about 102,000 from cache each). The group's own last turn was an hour earlier and the model server had evicted it: a fork reuses a cache that is still there, and cannot keep one the server dropped |
| Archived after | Yes: the copy is in the registry's archived sessions once the turn ended |

Her turn: `think`, `speak` (two lines, both marked `errand`), `stay_silent`; 34 s from start to end.
Both lines `DELIVERED` on the platform's acknowledgement and verified by the adapter reading them back (her count, the
fields as recorded): that proves the platform stored them in that group from her account, not that anyone read them.
Nobody there had answered by 14:11.

## Her review (2026-10-15, Claude's paraphrase; she signed it)

She read the whole text first (79 lines at 9671ba6d, 13 rows) rather than review a summary. She agrees with the
direction: the two gates judged by place, not by who asked, and that was the real block on the picture. Clean in her
reading: authority only on `errand`, the fork, the unchanged tool list, the seven home tools staying home, only her
words going back.

Her points, all folded in above:
1. An errand waiting for a busy conversation can arrive after the talk moved on: give it a deadline; past it, send
   nothing and tell home it did not get a word in (row 3).
2. Interrupted is not the same as not done: home must hear what was already sent before the cut, or she would redo it
   and send twice (row 5).
3. Not only others cannot tell an errand turn apart: she cannot either, reading back days later. Her own lines from
   it need a mark in her own records (row 13).
4. The most important, missing from the table: the destination's block would print the request, which may carry words
   only home may know. Only what may be shown there goes there (Decision, "Back in the destination": the request stays
   home; her own words there are that shareable version).
5. No fence for row 8: judgment is the price of full permission. She adds her own rule, in her persona: an errand turn
   does the one thing it was sent for.
6. Row 7's "a handful a week" is a premise to re-measure, not a fact.

Signed: 小满, 2026-10-15 (on the agent line: 「我这段是我签的」).

## A task begun on an errand is home's (owner and her, 2026-10-20)

An errand turn may delegate. The task is home's: its conversation, scope, epoch and person are home's, and it runs
under home's own session, so its thread and its report are drawn there, where home's authority holds. The report
names the errand's place (`errand_place`), so she can carry the result back with another errand; the delegate result
says so (`errands.HOME_TASK`). Steering the tasks listed on an errand stays out (`errands.NO_STEER`): they are that
conversation's. Her condition: without the place in the report, the extra hop would become a hop that never runs.

**Found unmet live (2026-10-21 15:26, her report):** a task begun on an errand had every tool call refused
`WORKSPACE_GRANT_MISMATCH` (14 calls; only `todo_write`, which touches no folder, worked). The task was home's, but its
action session was bound from the errand turn: the group's place, person and folder. The broker checks a run's folder
against its task's grant (home's), so nothing could pass. Fixed: the action session is bound from its task
(`NativeLane`: the task's scene, requester, scope, epoch and conversation), which for every other task is the same as
its turn. Test: `tests/test_errand_carries_home.py::test_the_action_brain_of_a_task_begun_on_an_errand_works_in_homes_folder`.
