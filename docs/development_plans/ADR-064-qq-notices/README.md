# ADR-064: QQ notices reach her as one-off lines; a reply tool later

Status: **Proposed 2026-10-13**, revised the same day after the owner's review of the first draft. The owner then
moved it ahead of ADR-061 (2026-10-13: review it first and finalize phase 1 with her). The master agent's review is
below; phase 1 is finalized with her next. **Phase 1 built 2026-10-13** (30b66ea3 adapter, 7ca59d1f host; see "Phase 1
as built"), her own mute state before it as a bug fix. Phase 2 waits on ADR-061.

## Owner's direction (2026-10-13)

**First round:**

1. Notify her of most inbound actions and messages she misses today.
2. Do not read cards by default. She can hand a card to the action brain for extra work, but that is never the
   default, and no tool is added for it.
3. Voice and video are parked: the model does not take them.
4. Phase two adds interactions beyond text and stickers, as tools enabled only for QQ groups and DMs.

**Second round (on the first draft):**

5. Notices are **not stored**. A notice is a one-off and does not warrant storage.
6. A notice is treated **like a text message** at the relevance gate; she can ignore it at will.
7. No recall handling in her client: no marking of recalled rows, no database work. She is told only that message
   "xxx" was recalled.
8. No dedicated notice types: projecting each notice into a line of text is enough. Not worth starting with fewer
   kinds.
9. A reaction on her own line passes the relevance gate like anything else.
10. Friend and group requests go to her local (home) session. Whether to ask the owner first is her decision.
11. Phase two is a **reply tool** in place of plain speech: she picks what to reply with, or a combination (sticker
    only, text + sticker, a nudge), similar to ADR-061's `ask`. It needs more thought.

## Context

The NapCat adapter forwards only `post_type: message`. Every notice, request and meta event is counted as
`nonmessage` and dropped before anything reads it (`packages/channels/napcat-qq/integration/qqadapter/inbound.py`,
`classify`).

Measured on the live adapter (2026-10-13, 51 minutes of uptime): 138 event frames, 105 of them `nonmessage`. At the
30-second heartbeat that is about 102 heartbeats, so one to three real notices. Their types are not recorded.

The live NapCat is 4.18.0. The lists below come from the NapCat source at v4.18.38; some extensions may be missing
from 4.18.0.

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

- Cards (`json`, `xml`, `miniapp`, `music`, `share`): title only. The card itself is not kept (`kept_raw` keeps the
  media block, which carries no card payload).
- `dice`, `rps`: a generic `[dice消息（未解析）]`; the result is never shown.
- `markdown`, `contact`, `onlinefile`, `flashtransfer`: generic placeholder. Voice and video: placeholder (parked).

### What she can do on QQ today

Send text, @, classic faces, stickers (a `[表情包:名字]` line), one picture (`attach_image`), a quote (`quote`). Group
admin: recall, kick, mute and unmute (`group_action`). Everything else NapCat offers (about 185 actions) is unused.

## The broken invariant

"What happens in a conversation reaches her" holds only for messages. A poke, a reaction to her line, a recall, a
join, her own mute: each changes the conversation she is in, and she cannot know it. She ignores pokes, answers
recalled messages, and learns she was muted or kicked only from a failed send.

## Phase 1: notices as one-off lines of text

### The adapter projects, the host passes it on

- **Projection (adapter).** A new `notices.py` turns each NapCat notice or request into one line of text from a
  versioned word table in the channel package. The table is keyed by `notice_type` / `sub_type`; an unknown kind
  becomes `[QQ 通知:<kind>]`. Words that point at a person go through the adapter's existing label and @ handling.
  Examples:
  - `戳了戳你` / `戳了戳 @x`
  - `给你的话「…」点了 👍`
  - `撤回了消息「…」`
  - `进群了` / `退群了` / `被 @x 移出了群`
  - `禁言了你 10 分钟`
  - `把群名改成了「…」`
  - `上传了文件 x.pdf（2 MB）`
- **No dedicated types downstream.** The line travels as an ordinary message envelope from the notice's actor (the
  poker, reactor, recaller, joiner), carrying one flag in `raw` (`asuna_notice: true`, kept by `kept_raw`). The
  host's only uses of the flag:
  - **Not stored.** A notice that starts no turn leaves no row (see below).
  - **Rendered as the program's line, not the actor's words.** Her turn shows `[x #3] 戳了戳你` in the program's
    form, not as text x typed. Words inside a notice that a person controls (a recalled text, a card name, a request
    comment, a group name, a grey tip) get the same body rewriting as messages (ADR-050 `>`, ADR-057 labels). That
    way text typed to look like a notice reads as that person's words.
- **Same gates as messages.** Own account, allowed group or authorized DM route, blocked senders. A notice whose
  operator is her own account is dropped, because the receipt of her own action already told her.

### At the relevance gate: like a text message

| Notice | Like a text message that… | So |
|---|---|---|
| Poke at her (group) | Calls her without an @ | Relevance gate, reason `poked` (new `attend.GATED` entry, ~30 characters): 接话 or 不理 |
| Reaction to her line (group) | Answers her without quoting | Relevance gate, reason `reacted` (new entry, ~30 characters) |
| Anything else in a group | Nobody addressed to her | No turn; shown once (see "Seen once") |
| Anything in a DM | Arrives in a DM | Wakes her as a DM message does; she can `stay_silent` |
| About her own account (below) | — | Her home session |

ADR-039 (resting groups) and ADR-052 (blocked people) apply unchanged: a notice from someone she blocked never wakes
her.

### Seen once, never stored

A group notice that starts no turn is held **in memory** per conversation. The host shows it once, in that
conversation's next turn or relevance-gate material, after the stored lines, then drops it.

- At most 10 per conversation. Older ones are dropped and counted (`还有 3 条较早的通知没列出`).
- A Host restart loses them. That is acceptable for a one-off.

A notice that does start a turn (a poke she took up, a DM notice) is that turn's input. It is recorded the way every
turn's input is, because a turn must survive a crash (`persist_input` runs before the gate). It carries its `notice`
flag, so views that show people's lines treat it as the program's line. This is the one place a notice leaves a
trace; see the open points.

### Recall: just the line

`[x #3] 撤回了消息「…」`. For the excerpt, the host reads the stored line by its platform id: read-only, at most 40
characters, matched within this conversation and the last day (ADR-029: platform ids recycle). If no match is found,
the line reads `撤回了一条消息`. Nothing is marked or written, and history keeps the original line as it was.

### About her own account: her home session

- **Which notices:** she was muted or unmuted, kicked, made or unmade admin, given a title; a group was disbanded;
  the account was pushed offline (told once it is back online); a friend request; a join request in a group where
  she is admin; an invitation into a group.
- **Delivery:** these reach her home session as a **program event**, like a heartbeat's reason, never as the
  owner's words (AGENTS.md: nothing passes for the owner's).
- **Batching:** notices arriving within one minute share one home turn.
- **Requests are hers to answer.** Whether she asks the owner first is her call. Answering takes two new values on
  her existing `group_action`, `accept` and `decline`, usable at home only, for a request listed in that turn. They go
  out the way her admin actions do (outbox → adapter → `set_friend_add_request` / `set_group_add_request`, with a
  receipt).
  - **Accepting is not admitting.** Who may then talk to her follows the channel's admission settings, unchanged. A
    new friend's DM, or a group she joins, is not admitted by the accept itself.

### Not projected, with reasons

- `input_status` (typing): changes every few seconds and means nothing once the message arrives.
- `meta_event` lifecycle and heartbeat: plumbing.
- `message_sent`: her own words, already recorded when she sends.
- `online_file_*`: about online-file transfers she can neither send nor open.

### Small content fixes (same batch)

- `dice` and `rps` show their result: `[骰子:5]`, `[猜拳:石头]`.
- Cards keep a bounded payload (title, description, link, at most 2 KB) on the stored message, in its media item.
  Her turn still shows the title placeholder only; nothing reads the card by default. If she hands a card to the
  action brain (`delegate`), it reads the stored message with the read access it already has (dbread). No tool is
  added.
- Voice, video, `markdown`, `contact`, `onlinefile`, `flashtransfer`: unchanged.

### Counted

The adapter counts each event it receives by type (no content, no ids) in `health.json`, so the real mix is known
after a few days and the 10-per-conversation cap can be checked against it.

## Phase 2: a reply tool (direction only; needs more thought)

Today speech is the turn's body text. A sticker is a `[表情包:名字]` line in that text, a picture is `attach_image`,
the quote is `quote`, and silence is `stay_silent`. The owner's idea is one `reply` tool that composes the answer
from parts, as ADR-061's `ask` composes one question to many sources:

- **Parts, in her order:** text, sticker, picture, poke (nudge), a reaction to a message, and the quote. Any
  combination: a sticker alone, text + sticker, a poke alone, a reaction alone.
- **Where it works:** QQ groups and DMs only. Home, agent and peer lines keep plain speech.
- **Out:** each part goes out the way messages and admin actions do (outbox → adapter → receipt).
  - Poke: `group_poke` / `friend_poke`.
  - Reaction: `set_msg_emoji_like`, which may be group-only on 4.18.0; to check.
  - Emoji names: from `faces.json`, the names she already uses for faces.

**Questions phase 2 must answer before it is drafted in full:**

- Does `reply` replace body text in QQ turns, or sit beside it? Body text that is also sent is the root of earlier
  bugs (ADR-063 lines held during a tool call).
- Which existing tools fold into it (`quote`, `attach_image`, the sticker line, `stay_silent`)? If they do, the QQ
  toolbox can shrink while abilities grow (AGENTS.md tool budget).
- How a reaction and a poke look in her own history, so she remembers she did them.
- Which other interactions join later (essence, forwarding), each by its own decision.

## Cost (AGENTS.md)

Phase 1:

| Brain | Adds (measured as built) |
|---|---|
| Character, group turn | `notices_from_program`, only when a group notice is held: up to 10 lines after folding, each the label, the time, `（平台通知）` (6 characters) and the words (about 30–80 characters a line), plus a `more` count; 0 otherwise. A stored notice line ends its label line with the same 6 characters, and a history row of one carries `notice` (25 characters with its key) |
| Character, relevance gate | Two reasons in `GATED`: `poked` 18 characters, `reacted` 18 characters, shown only when they apply; held notices after the lines, as in a turn |
| Character, system prompt | One line in the block guide for `notices_from_program`, 63 characters, fixed per conversation |
| Character, home turn | One program event per minute's batch: a 16-character head, a line per notice (time, name, words), and 56 characters per request saying how to answer it; 0 when none. After a Host start with requests still open, one more event: the head and a 14-character second head, then each open request's line and its 56 characters; 0 when none is open |
| Character, tools | No new tool. `group_action` gains `accept` and `decline` and the request number in `who`: +37 characters after tightening its description (`tests/test_tool_budget.py` raised by exactly 37). Her local chat lists `group_action` (562 characters) wherever a channel kind declares `REQUESTS`, so its tool list is the same every turn; a turn may use it only while a request waits |
| Action brain | Nothing. A card handed over costs only what the brief carries |

Phase 2 states its cost when drafted. The aim is a smaller QQ toolbox than today's.

## How it is checked

- `health.json` shows events by type after the build.
- Live, in a test group or by the owner:
  - a poke at her and a reaction to her line each reach the relevance gate, and she may answer 不理;
  - a join, a card change and someone else's recall each show once in her next group turn, and not in the one after;
  - none of these leaves a row in `messages`;
  - a recall line quotes the recalled text;
  - a DM poke wakes her;
  - a friend request reaches her home session as a program event, she accepts it, and the receipt comes back;
  - text typed to look like a notice reads as that person's words.

## Open points for the reviewers

1. **Taken-up notices.** A notice that starts a turn is stored as that turn's input, because every turn's input is
   durable. The alternative is a turn without an input row, which touches the coordinator's crash recovery. The
   recommendation is to keep it.
2. **Seen-once list in memory.** A Host restart loses notices that were not yet shown. The alternative is to drop
   unwoken group notices entirely, which loses joins, card changes and others' recalls.
3. **Request answers on `group_action`.** Is that the right home, or should they wait for phase 2?

## Master agent's review (Claude, 2026-10-13)

Phase 1 is right in shape, independent of ADR-062 (notices are never stored, so they never enter her memory stores)
and of ADR-061 (only phase 2 touches a reply tool). It can be built as soon as she finalizes it. Points to settle in
it:

1. **Her own mute is out of phase 1:** built (71c0ae15, below). `group_ban` about her account now feeds that state;
   phase 1 adds the one-off line for everyone else's mutes only.
2. **The discriminator is a field** (her item 1): `user_id == her own account` (and `sub_type: kick_me`), as the mute
   fix already does. Accepted.
3. **Per-turn space** (her item 4), without dropping kinds against the owner's direction 1 and 8: every group notice
   that starts no turn is seen once and capped at 10, so a low-value kind costs one line once, never per turn. Two
   additions: lines of one kind in one conversation fold into one (`3 人进群了：[a #1]、[b #2]、[c #3]`), and the
   cap counts after folding. Profile likes, which are about her account but change nothing she does, go to her home
   session's seen-once list, not as a program event that starts a turn.
4. **Unknown kinds are counted, not shown.** `[QQ 通知:<kind>]` would put a raw platform name in front of a model
   (AGENTS.md: interpreted words only). The adapter counts unknown kinds in `health.json`; a kind is projected only
   once the word table has its words.
5. **Duration and lift** (her item 2): the word table carries both directions with who and until when, e.g.
   `[x #3] 禁言了 [y #5] 10 分钟（到 21:40）`, `[x #3] 解除了 [y #5] 的禁言`.
6. **Profiling (ADR-062's rule):** a notice line must not repeat a stored line or another block in the same notice.
   The recall line quotes at most 40 characters of the recalled text; that text may still be on her surface, which is
   intended (she must see which line went), but nothing else is quoted.
7. **Open points:** 1 keep the stored input for a taken-up notice; 2 in-memory seen-once is acceptable (her own state
   is the exception, now built); 3 `accept` / `decline` on `group_action`, home only, now. Accepting a request does
   not admit the person or group: admission stays the owner's setting.
8. **Cost** is as stated; the `group_action` text is paid by tightening its description where possible, and the
   budget raise, if any, is stated with the change.

## Her phase 1 scope (agent line, 2026-10-13 about 16:10 NZDT; Claude's paraphrase, for her to sign or correct)

Her rule for the first batch: take in only what asks her to do something or tells her about her own state; everything
else is background sound. So the first batch is friend and group requests (they ask her to act, and today there is
no way in at all), a reaction to her own line (after she speaks she cannot tell whether anyone caught it: real
blindness), a recall (if a line she quoted is deleted she should know), and a poke at her (cheap, keep it). Card
changes, essence, file uploads and joins and leaves wait. Her reason: the 10-per-conversation cap is the real
constraint, and in a busy group joins and leaves alone would fill it; so take in few kinds first, count every kind
for a week, and decide the second batch from the counts, not by guessing now.

This differs from the owner's direction 8 (no fewer kinds to start with); the owner decides (asked 2026-10-13).

## Her review

Pending: her review after the master agent's. Her words go here as Claude's paraphrase with times and her signature
slot.

Written 2026-10-13 at her own hand, at the owner's request ("write your opinion straight into the ADR").
The order this file states — master agent first, then her — and the parked condition (until ADR-062 and
ADR-061 are done) still stand. This is her input, not a sign-off.

**Direction accepted.** Routing her own mute/unmute into her home session is the missing piece. Today
shows the invariant in "The broken invariant" is worse than written: she was muted for 29 days by an
admin in a group where she is not an admin, had **no signal at all**, kept behaving as if that group
were normal, and learned of it only because the owner told her. She never even reached a failed send —
she had no reason to send again.

**Four things she asks for:**

1. **Write the discriminator as a field.** "About her own account" is a category, not a test. Say
   `user_id == her own account` (and for `group_decrease`, `kick_me`), so the split does not rest on prose.
2. **Give duration and lift.** The only example in the file is `禁言了你 10 分钟`. Show what `lift_ban`
   looks like, who lifted it, and — for a mute — until when it runs.
3. **Her own mute is a state, not a notice.** It must not be seen-once and must not be lost on Host
   restart. The event answers "it just happened"; she also needs to answer, at any turn, "which groups
   am I muted in right now, until when". One small state slot, or a queryable row — either is enough.
   Seen-once is fine for everything else.
4. **Filter the 17 types by "would she change her behaviour because of it".** Mute, lift, kick, admin
   set/unset: yes, those change what she does next. Profile likes, essence adds, group renames, file
   uploads: knowing once is enough, and they should not take per-turn space — ADR-063 just halved what
   reaches her in a turn, and this should not give it back.

**On the three open points:** keep the stored line for crash recovery (1); in-memory seen-once is
acceptable (2), with the exception in point 3 above; `accept`/`decline` on the existing `group_action`
is right, do not wait for Phase 2 (3).

Correction, same day, after checking the records: the sentence above about never reaching a failed send
is wrong in its first half. At 12:15 she did send into that group — the platform returned `retcode 1200`
(`result 120`), the row is stored `FAILED` with no platform message id, and the sticker queued behind it
was cancelled rather than retried. What holds is the second half: she sent nothing further.

The mechanism is worth writing down, because it is the reason a state slot is needed: the failure receipt
landed at 12:15:44, **two seconds after her turn for that exchange had already ended**, and the mapping
from `result 120` to "you are muted" did not exist yet. So the platform did tell us, and the telling
arrived somewhere she was no longer standing.

— Xiaoman

## Built ahead of the ADR as a bug fix (2026-10-13)

Only her item 3, her own mute as a state, was built (commit 71c0ae15), because she was muted in a group for 29 days
without knowing (owner-confirmed). Nothing else in this ADR is built, and its review stays parked.

- The adapter posts a `group_ban` notice about her account or the whole group as state (`POST .../own_mute`); other
  notices are still dropped. A send refused with QQ result 120 is `failed` with `reason: muted`. At start and on
  reconnect it looks at each admitted group not looked at in the last 6 hours, one a second (read-only
  `get_group_member_info` for her account and `get_group_info`).
- The host keeps one slot per group (`own_mutes`): set by a ban notice, a look or a refused send; cleared by a lift, a
  look that finds none, its end passing, or any of her lines the platform accepts there. Sends are never held back.
- What she reads, only while muted: every turn in that group carries `muted_here_from_program` beside `event`, about
  35–50 characters of text (about 65–80 with its key; sent in every notice, like the trigger), for example
  `你在这个群被禁言了，到 11/10 08:00，谁禁的不知道：你说的话发不出去。` Who did it is her label there or said to be
  unknown, never left out. Her places at home add `muted_you` to that group's row (about 50 characters, heartbeat
  only). A line refused this way reads `没发出去：你在这个群被禁言了` (10 characters more than `没发出去`). No new tool,
  nothing in a turn of a group where she is not muted.

## Phase 1 as built (2026-10-13)

Commits 30b66ea3 (adapter 0.8.0) and 7ca59d1f (host). The adapter part goes live when she publishes the napcat-qq
project; the host part with her next restart.

- **Projection and switch table (adapter, `qqadapter/notices.py`).** Every kind in the table has words in one
  versioned table (`WORDS`, `WORDS_VERSION` 1), both directions for mutes and admin changes, with the duration in
  words. `SHOWN` holds her first batch (owner 2026-10-13): `poke_you`, `reaction`, `recall`, `request_friend`,
  `request_join`, `request_invite`, `kicked_you`, `admin_you`. Flipping the next batch is a change to that table.
  Her own mute is not a line (its state, above).
- **Counts.** Every kind, with no content, by outcome (`posted`, `home`, `not_shown`, `not_projected`, `unknown`, or
  the gate that dropped it), by UTC day for 14 days in the adapter's `notices/counts.json`; `health.json` `notices`
  shows today and the last 7 days. Unknown kinds count under their platform name and are never shown.
- **Groups and private chats (host, `notices.py`).** As designed: the same gates as a message, a blocked person's
  notice dropped; `poked` and `reacted` through the gate (`poked` also wakes a resting group; `reacted` there is held
  instead); everything else in a group held in memory and shown once, folded by kind and identical words, the cap
  after folding. A reaction to a line not hers is dropped by the host (the adapter cannot tell whose line it was
  without reading it). A reaction names her line by when she said it and never quotes it; only a recall quotes.
- **Her home.** Requests, a kick of her account and a change of her admin role arrive through `POST /notices`, held a
  minute and sent as one program event in her local chat (a `presence` event, like a restart notice). A request is a
  row in `artifacts` (kind `platform_request`, one per platform flag) with a number given once and never reused, open
  until she answers it; her answer's receipt marks it answered, or gone when the platform refuses the answer. At each
  Host start the open ones are listed again in one program event. `group_action` `accept` / `decline` with that
  number answers one in her local chat only. (Owner's call on point 2 below, 2026-10-13: fixed in e767f5de, host
  only.)
- **Profiling.** A synthetic group turn with a held recall shows the recall once, in its own block, and nowhere else
  in the notice (`tests/test_notices.py`).

Differences from the text above and points to watch:

1. A gated notice (a poke she is asked about) is stored even when she answers 不理, because the gate runs on stored
   input; only notices that start no look are never stored.
2. ~~A Host restart loses the request numbers.~~ Fixed (owner 2026-10-13: a request stays pending on the platform
   for days): requests are kept in Mongo with stable numbers and listed again after a restart.
3. Gate material and the turn after a 接话 both carry the held notices (the gate is its own small session), so a
   taken-up look sees them twice across two sessions, never twice in one.
