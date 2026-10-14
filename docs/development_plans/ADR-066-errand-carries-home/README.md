# ADR-066: An errand carries home

Status: **Proposed 2026-10-15** by the owner, designed with Claude the same day; waits for Xiaoman's review, then the
owner's go to build.

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
- **Back in the destination:** its next natural turn carries, at the end, `errand_from_program` once: who sent her
  (主人, from home), what was asked, and what she said there. Nothing she read with home's authority comes with it.
- **At home:** the outcome, as errands report today (`errands_from_program`).
- **Afterwards:** a task delegated in the errand turn keeps home's authority, with the requester recorded. The fork is
  marked errand-only and retired before the next Host start like the one-shot sessions (`asuna-launch.mjs`: archived
  after a day, dropped after 14).
- **Visible:** the turn opens with 「家里交代的，带着家里的全部权限；你说出口的话那边都看得到」; the audit records
  `errand.carried` with the fork, the requester and what was sent.

## Failure modes and their handling

| # | Failure | Handling |
|---|---|---|
| 1 | The fork mistaken for the conversation's main session: later public turns run in it, home material inside | The binding marks it errand-only; it is never the scene's main session; retired after |
| 2 | The destination near compaction: the appended tail pushes the fork over the threshold, DSH compacts a session that will be thrown away, and the turn runs cold anyway | Measured before forking; over budget, or the destination compacting or mid-turn: a small fresh session with the destination's recent lines and the request (cold, small, never compacts) |
| 3 | Two replies at once: the destination's own turn and the errand speak over each other | The errand waits in the destination's queue until the scene is idle |
| 4 | Her errand thoughts recalled later in public | Thoughts written in the fork are stored in home scope |
| 5 | A restart during the errand: the fork is orphaned, DSH may resume its unfinished turn | Asuna refuses the stale operation; the errand is marked interrupted and home is told |
| 6 | The fork runs on another model (DSH's fork takes the default model selection) | The fork's route is set to her character route; checked in the build |
| 7 | The fork's cache entry (~3 GiB at 150k tokens) evicts another conversation's | Accepted: errands are a handful a week |
| 8 | A message planted earlier in the destination is read with home's authority (the sandbox among it) | The turn says its only instruction is home's; the conversation is others' words. Judgment, not a fence: the price of full permission |
| 9 | She says something private in public | Hers to judge (owner 2026-10-06: home to outside, she decides) |
| 10 | A stranger launders a request home and back out | Only home turns and the verified owner send errands; a note-woken turn needs the owner's own line |
| 11 | The destination has no session yet, or the fork call fails | The small fresh session of row 2 |
| 12 | People there learn that an errand turn carries home, and 「主人说 X」 becomes a lever (her question, 2026-10-15) | Nobody there sees which turn is an errand: her message carries no mark. Authority comes only from the errand's requester, checked by the program at home; no line in the destination can open an errand or lend it authority, whatever it claims |
| 13 | She cannot tell which layer of her acted (her question) | The errand turn opens with what it is; each tool result in it ends with 「（差事回合，家里的权限）」; the destination's next turn names what was done on an errand (`errand_from_program`); her home sees the outcome |

## What it adds to each brain

Character brain: no tool, no parameter; one block once in the destination's next turn and the errand turn's own
notice. Action brain: none (home grants already exist). To be measured in characters in the build.

## Her review

Her words, paraphrased by Claude, go here with her signature slot.
