# ADR-064: QQ notices reach her; more than text and stickers later

Status: **Proposed 2026-10-13**. The owner's direction is below. This ADR waits for the master agent's review of the
plan, then her review. Nothing is built until the review is done.

## Owner's direction (2026-10-13)

1. Notify her of most inbound actions and messages she misses today.
2. Do not read cards by default. She can hand a card to the action brain for extra work, but that is never the
   default, and no tool is added for it.
3. Voice and video are parked: the model does not take them.
4. Phase two adds interactions beyond text and stickers. Poke and reactions come later, as new tools enabled only for
   QQ groups and DMs.

## Context

The NapCat adapter forwards only `post_type: message`. Every notice, request and meta event is counted as
`nonmessage` and dropped before anything reads it (`packages/channels/napcat-qq/integration/qqadapter/inbound.py`,
`classify`). The host's channel API accepts only message envelopes (`channels.py` `_receive`, a strict field
allowlist).

Measured on the live adapter (2026-10-13, 51 minutes of uptime): 138 event frames, 105 of them `nonmessage`. At the
30-second heartbeat that is about 102 heartbeats, so one to three real notices. The adapter does not record their type,
so the actual mix is unknown.

The live NapCat is 4.18.0. The event and action lists below come from the NapCat source at v4.18.38
(`packages/napcat-onebot/event`, `action/router.ts`); some extensions may be missing from 4.18.0.

### What NapCat sends that she never hears

| Event | Meaning |
|---|---|
| `group_recall`, `friend_recall` | A message was taken back (with operator) |
| `notify/poke` (group, friend) | Someone poked someone (`target_id`) |
| `group_msg_emoji_like` | Emoji reaction on a group message (who, which emoji, added or removed) |
| `group_increase` (approve / invite) | Someone joined |
| `group_decrease` (leave / kick / kick_me / disband) | Someone left, was kicked, she was kicked, the group was disbanded |
| `group_ban` (ban / lift_ban) | A mute or unmute, including the whole group (`user_id` 0) and her |
| `group_admin` (set / unset) | Admin granted or removed |
| `group_card` | Group card changed (old, new) |
| `notify/title` | Special title granted |
| `notify/group_name` | Group renamed |
| `essence` (add) | A message marked as essence |
| `group_upload` | A file uploaded to the group (name, size) |
| `notify/profile_like` | Someone liked her profile |
| `notify/gray_tip` | A grey tip the platform did not recognise, with a real sender (possible forgery) |
| `friend_add` | A new friend |
| `request/friend`, `request/group` (add / invite) | Friend request, join request, invitation into a group |
| `bot_offline` | Her account was pushed offline |
| `notify/input_status` | A friend is typing |
| `online_file_send` / `online_file_receive` | Online file accepted, refused or cancelled |
| `message_sent` | Messages sent from her account elsewhere (`reportSelfMessage`, off) |
| `meta_event` lifecycle / heartbeat | Connection plumbing |

### Message content she gets only as a placeholder

- Cards (`json`, `xml`, `miniapp`, `music`, `share`): title only. The card itself is not kept: `kept_raw` keeps the
  media block, which carries no card payload.
- `dice`, `rps`: shown as a generic `[dice消息（未解析）]`; the result in the segment is never shown.
- `markdown`, `contact`, `onlinefile`, `flashtransfer`: generic placeholder.
- Voice, video, files: placeholder (voice and video parked; files are covered by `group_upload` only).

### What she can do on QQ today

Send text, @, classic faces, store stickers (`mface`), pictures, replies. Group admin: recall (`delete_msg`), kick, mute
and unmute (`set_group_kick`, `set_group_ban`). Everything else NapCat offers (about 185 actions) is unused.

## The broken invariant

"What happens in a conversation reaches her" holds only for messages. A recall, a poke, a reaction, a join, her own
mute: each changes the conversation she is in, and she cannot know it. She answers recalled messages, ignores pokes,
and learns she was muted or kicked only from a failed send.

## Decision (proposed)

### Phase 1: notices as program lines (no tools)

**1a. Count first (adapter only).** The adapter journals each dropped event by `post_type` / `notice_type` /
`sub_type` (no content, no ids) and shows the counts in `health.json`. It runs at least three days before 1b is
switched on. The counts set the fold rules below and show which extensions 4.18.0 really sends.

**1b. Notices reach her.**

- **Adapter.** A new `notices.py` maps a NapCat notice or request to a structured notice: kind (a fixed table),
  scene (group or DM route), actor, target, and the few typed fields the kind needs (message id, duration, old and
  new card, emoji ids, file name and size). It passes the same gates as messages: own account, allowed group or
  authorized DM route, blocked senders. A notice whose operator is her own account is dropped: the receipt of her own
  admin action already told her. The adapter posts notices to a new channel endpoint (`notices`, like `members` and
  `media_keys`), never as a message envelope.
- **Host.** `notices.receive` checks the kind against its table, resolves actor and target to people (labels as in
  ADR-057), and writes the line itself from a versioned word table (AGENTS.md: interpreted state). The adapter never
  supplies the words. A notice line therefore has a form no person's text can produce, the same root fix as ADR-057.
- **Storage.** A notice is a `messages` row with `direction: 'notice'` (like ADR-029's `archived`). Every existing
  query that counts people's lines (`inbound`) skips it by default: awaited answers, "others' lines" in ADR-049,
  people's last-spoke times, watches, summaries and chunks. Only the history views include it on purpose. A recall
  also stamps the recalled row (`recalled: {at, by}`).
- **Where she sees it.** In the conversation it happened in, as a line in the history her next turn reads there (the
  group's lines since she spoke, the DM history). A notice is not a turn by itself, except as listed under wake rules.
- **About her.** Notices that change what she can do (she was muted or unmuted, kicked, made or unmade admin, given a
  title, the group disbanded, the account pushed offline), and requests (friend, join, invite), also appear at home:
  one block listing the ones she has not been shown yet, at most 5 lines, absent when empty. Requests are notified
  only. Answering them needs an action this ADR does not add; she can tell the owner.

**Wake rules.** A notice wakes her only when it is meant for her, the same test as ADR-039's resting groups:

- a poke at her (group `target_id` is her account, or a poke in a DM);
- nothing else. A reaction to her line, a recall, a join and her own mute are seen on her next turn there, or at
  home.

ADR-052 applies: a notice from someone she blocked is kept and never wakes her. A poke in a group she lets rest still
wakes her, as an @ does.

**Recall shown honestly.** A recalled message she was already shown keeps its text in history, marked `（已撤回）`,
because a person who read it remembers it. One she was never shown reads `（已撤回，没看到内容）`. The record keeps the
text either way.

**Folding.** A busy group must not fill her history with notices (ADR-063 context growth). Notice lines fold in history:
consecutive notices of one kind become one line (`3 人进群：…`, `[x #3] 等 4 人给 [你的话] 点了 👍`). Reactions on
other people's messages fold per message, and only the count is shown. The fold thresholds are set from the 1a counts
and stated in the word table.

**Not shown, with reasons:**

- `input_status` (typing): changes every few seconds and means nothing once the message arrives.
- `meta_event` lifecycle and heartbeat: plumbing.
- `message_sent`: her own words, already recorded when she sends.
- `online_file_*`: about online-file transfers she can neither send nor open.

**1c. Small content fixes (same batch).**

- `dice` and `rps` show their result: `[骰子:5]`, `[猜拳:石头]`. A self-describing placeholder, no new parsing.
- Cards keep a bounded payload (title, description, link, at most 2 KB) on the stored row, inside the media item. Her
  turn still shows the title placeholder only; nothing reads the card by default. When she hands a card to the action
  brain (`task`), the action brain reads the stored row with the read access it already has (dbread). No tool is
  added.
- Voice, video, `markdown`, `contact`, `onlinefile`, `flashtransfer`: unchanged (parked or generic).

### Phase 2: interactions beyond text and stickers (new QQ-only tools)

The first two are poke and reactions. They are new tools present only in QQ group and DM toolboxes, never at home or on
agent and peer lines.

- **Recommended: one tool, two operations.** `gesture` with `op: poke | react`:
  - poke takes the person's label;
  - react takes a message (the same reference her replies use) and an emoji name from `faces.json`, the names she
    already uses for faces in text.
- **Alternative: two tools,** `poke` and `react`. Each is clearer alone, but adds two choices to every QQ turn.
- **Path.** Both go out the way her admin actions do today: a queued publication the adapter claims and turns into a
  NapCat call, with a receipt.
  - Poke uses `group_poke` / `friend_poke`.
  - React uses `set_msg_emoji_like`. Whether it works in DMs is to be checked on 4.18.0.

Candidates after poke and reactions, each needing its own decision: essence (`set_essence_msg`), forwarding
(`send_forward_msg`), answering requests (`set_friend_add_request`, `set_group_add_request`). Voice out stays parked
with voice in.

## Options considered for phase 1

1. **Notices as program lines in their conversation, waking only when meant for her** (recommended). Honest and
   cheap: she learns at her next turn there, as a person scrolling up would.
2. **Every notice is a turn.** Rejected: pokes from strangers in big groups, joins and card changes would each start a
   model turn, the growth ADR-063 just closed.
3. **Notices as message envelopes with a marker text** (reuse the message path). Rejected: the line would be text a
   person can type, the ADR-057 hole, and every query that counts people's lines would count notices.
4. **A home digest only.** Rejected: a recall or reaction belongs where it happened. Home gets only what is about her.

## Cost (AGENTS.md)

The character cost is upper bounds before the build; the build measures the real numbers.

**Phase 1** adds no tool and no tool description. Per-turn text:

| Brain | Where | Adds |
|---|---|---|
| Character | Group or DM turn | Notice lines inside the existing history, after folding. Each line is at most about 60 characters; the fold rules cap the count |
| Character | Home turn | One block when there is something new about her: about 60 characters of heading, plus at most 5 lines of at most about 60 characters. 0 when empty |
| Action | — | Nothing. A card handed over in `task` costs only what the brief already carries |

**Phase 2** adds one tool (`gesture`) to the character brain's QQ toolboxes only. About 350 characters of schema and
description; the build measures it and raises `tests/test_tool_budget.py` in the same change. Home, agent and peer
lines: 0. Action brain: 0.

## How it is checked

- **1a.** `health.json` shows counts by type. After three days the counts go into this ADR and set the fold
  thresholds.
- **1b.** Live, in a test group or by the owner:
  - a recall, a poke at her, a reaction to her line, a join and a card change each appear once, as program lines in
    that group's history on her next turn;
  - only the poke woke her;
  - a mute of her appears at home;
  - text typed to look like a notice reads as that person's words.
- **Replay.** A day of real notices from 1a, folded, stays within the per-turn cost above.
- **Unchanged counters.** Queries that count people's lines give the same numbers with notice rows present.
- **Phase 2.** A poke and a reaction from a group turn arrive on QQ, and the receipt reaches her.

## Open questions for the reviewers

- Should a reaction on her own line ever wake her (for example, the first one in a resting group), or never?
- Should 1b start with fewer kinds (recall, poke, reactions, join and leave, her own mute and kick), with the rest
  following once the counts are in?
- Who answers friend and group requests until a later phase does: the owner by hand, as now?

## Her review

Pending: her review after the master agent's. Her words go here as Claude's paraphrase with times and her signature
slot.
