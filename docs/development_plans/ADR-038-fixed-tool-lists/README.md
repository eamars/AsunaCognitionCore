# ADR-038: One tool list per conversation

Status: **Accepted and built 2026-10-11**, owner's direction; Xiaoman agreed to the split and asked for the refusals.

## Context

ADR-011 §2.6 had the program choose her tools per turn: a tool appeared only when the turn needed it (`visit` in a
heartbeat, `read_ideas` in self-improvement, `read_report` with a long report, …). The owner asked for the same
idea everywhere: reveal only when needed, on an error or a trigger, to keep her context small and her focus.

Measured on her sessions 2026-10-06 – 10-11 (decoded DSH logs and the episodes' `turn_tools`): the tool list goes
at the start of every request, before the conversation, so a changed list makes the model read the whole
conversation again.

| Home conversation | Turns | Read from cache | Read again per turn |
|---|---|---|---|
| Same tool list as the turn before | 244 | 81% | about 29K tokens |
| Tool list changed | 298 | 12% | about 137K tokens |

Her first reply step took a median 33 s after a change and 7.4 s without. Each change also wrote DSH's "tool
added/removed" notice into her conversation (336 at home). The tools that changed most: `understand_person`,
`read_ideas`/`review_idea`, `errand`, `visit`, `credential`, `stop_action`, and `read_report`. Groups (92% cached)
and the action brain (tools fixed per task, 94% of later requests cached) were not affected. The system prompt's
changes at home were edits and restarts (54 of 61 her own persona edits), never back and forth.

Prefix caching works this way at every provider (DeepSeek, OpenAI-compatible servers, the local one), so this is not
tuning to one model. DSH alpha.2's DeepSeek adapter can announce tool changes inside the history
(`toolUpdate`); its OpenAI-compatible adapter, which serves the local model, cannot.

## Decision

- **D1. A conversation lists the same tools in every turn** (`role_tools.toolbox`), decided by its place
  (`visibility.place`), its channel and the configuration, never by the turn:

  | Kit | Where |
  |---|---|
  | `think`, `recall`, `stay_silent`, `note_idea`, `plan`, `private_words`, `understand_person`, `feel` (mood on) | everywhere |
  | `delegate`, `message_action`, `stop_action`, `read_report`, `answer_action` | where anyone may hand work over |
  | `write_document`, `pass_note`, `update_self`, `set_policy`, `read_ideas`, `review_idea`, `message_developer`, `restart`, `place_timezone`, `peer_line` | her home lines: the owner's local chat and private chats, the trusted lines (agents, her other self) |
  | `errand` | the owner's own conversations |
  | `visit`, `promote_memory`, `credential` | the local chat (her heartbeats, nights and vault are there) |
  | `write_document`, `leave_note`, `await_answer`, `quote`, `find_member`; `group_action` where she is an admin | groups |
  | `leave_note` | other people's private chats |
  | `watch` | platform conversations (groups, private chats) |
  | `read_image`; `attach_image`; `sticker` | where the channel carries pictures and her route sees them; where pictures can be sent; where stickers can be sent, and the local chat |

  Compared with before: the trusted lines no longer have `credential`, `errand`, `visit` or the picture and sticker
  tools (they are text only); the owner's QQ chat no longer has `credential` (a password does not travel through QQ).

- **D2. The turn's rules stay, as refusals.** `role_tools.exposed` still decides what a turn may use (recorded as
  `turn_tools`). A listed tool the turn may not use is refused with the whole rule, so one refusal teaches it
  (`role_tools.NOT_NOW`): e.g. `visit` only in a heartbeat or plan turn at home — to go out, wait for the next beat
  or set a plan. Xiaoman's condition: hitting the wall must be a complete lesson, not "wrong time".

- **D3. Disclosure is text.** When a tool is worth using is said at the end of the turn, where it costs nothing to
  the cache: the context blocks that already exist (a long report's footer names `read_report`; places, ideas,
  errand places).

- **D4. `pin_memory` is removed.** Offered on 977 turns, used on none; her memory has no manual pin (her decision).

## Consequences

- The first turn of each conversation after the change re-reads once; after that a turn re-reads only the new tail.
- A home turn lists about 29 tools (11K → 16K characters of tool text, read from cache). Trimming long tool
  descriptions and moving repeated per-turn text into the system prompt are the next steps (owner and Xiaoman
  agreed).
- A call outside the turn costs one round with a refusal she learns from; the tool never runs outside its turn.
- The action brain is unchanged (`digest_authorized_discussion` and the integration tools keep their grants; her
  view).
