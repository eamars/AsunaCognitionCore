# ADR-064: QQ notices reach her as one-off lines; a reply tool later

Status: **Proposed 2026-10-13**, revised the same day after the owner's review of the first draft. The owner then
moved it ahead of ADR-061 (2026-10-13: review it first and finalize phase 1 with her). The master agent's review is
below; phase 1 is finalized with her next. **Phase 1 built 2026-10-13** (30b66ea3 adapter, 7ca59d1f host; see "Phase 1
as built"), her own mute state before it as a bug fix. **Phase 2 built with ADR-061 step 2 and live 2026-10-14** (her agreement with one condition, 2026-10-13 evening;
the owner's choice of a reply tool only; see "Phase 2 with ADR-061 step 2 as built" and "After install").

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

## Three kinds of group line (owner, 2026-10-16)

The owner's rule, written down after reactions to her lines were lost in resting groups (see "Phase 1 as built"): a
group line is one of three kinds, and the group's state decides only what happens to the third.

| Kind | Examples | Active group | Resting group |
|---|---|---|---|
| Direct address | an @ of her, a reply to her line | her turn, no gate | her turn, no gate |
| Active interaction | a poke at her, a reaction to her line | relevance gate | relevance gate |
| Passive message | everything else | relevance gate at a few moments (a thread that called her, her name, the proactive rules, a chain) | ignored |

Lines that may be meant for her without addressing her (an awaited answer, an answer to her open question, a watched
person, an @ caught up after a gap) go through the gate in both. The point of projecting a notice to text is that her
gate judges it; nothing a person does at her is held back at the door.

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

## Phase 2: a reply tool (proposed 2026-10-13; needs her agreement and the owner's)

Status: **the owner chose A2 with the failure modes below (2026-10-13: "only through reply, with failure modes"),
and the split marker goes everywhere.** Waits for her agreement (the questions for her, last section) before it is
built; it changes her prompt, so it is installed only after ADR-061 step 1's observation day. Drafted by Claude (the master agent's worktree) after ADR-064 phase 1 and ADR-061 step 1 were built, as the
owner's order of work says.

### Today (checked against the code, 2026-10-13)

- **How she speaks on QQ.** Every text she writes in a turn is speech, text written beside a tool call included,
  "since her conversation shows each as hers" (RUNTIME_API, "Claim public output"). Her turn's `speak_from_program`
  says so (`sent`), and where the persona allows several messages it adds the split marker rule (`messages`, 113
  characters; the persona packages set `speak.max_messages` 2 or 3). A turn with neither speech nor `stay_silent` is
  handed back once (a repair).
- **Parts of an answer, each by its own route:** the words (body text); a sticker (a `[表情包:名字]` line in the
  words, at most one a turn, taught by `stickers_from_program`'s note and the `sticker` tool's last sentence); a
  platform face (`[表情:名字]` inside the words); a picture (`attach_image`); the quote of the line that called her
  (`quote`, groups); waiting for an answer (`await_answer`, groups); silence (`stay_silent`).
- **Her QQ tool texts** (characters of the JSON she is sent, `tests/test_tool_budget.py`'s measure; the whole
  character brain defines 32 tools, 21,453 characters): `quote` 229, `attach_image` 311, `await_answer` 388,
  `stay_silent` 190, `sticker` 1,128 (of which the sending sentence 33), `group_action` 562 (groups where she is an
  admin, and her local chat).
- **The platform** (NapCat 4.18.0 live, from the adapter's `health.json` identity; the source read is NapCat 4.18.4's
  bundle in another local project, no live call made):
  - `set_msg_emoji_like` (`message_id`, `emoji_id`, `set`): the action itself does not check the chat type; it looks
    the message up by NapCat's short id and calls the kernel's `setMsgEmojiLikes` for that chat. Whether QQ takes a
    reaction in a private chat is **not verified**; NapCat reports reactions only in groups (`group_msg_emoji_like`,
    built from a group-only push). The short id must still be in NapCat's message cache.
  - `group_poke`, `friend_poke` and `send_poke` are one handler (`group_id` given: a group poke; else a private one,
    `user_id` the peer, `target_id` whom). It needs NapCat's packet backend (`GetPacketStatusDepends`): whether the
    live NapCat has it is **not verified** (`get_packet_status` answers it, read-only).

### (a) Does `reply` replace body text in QQ turns, or sit beside it?

The root-cause question. Today the program guesses which of her texts are speech: all of them. Text she wrote beside a
tool call (a sentence before a lookup, narration of what she is doing) goes out whether or not the call's result
changed what she should say, and it cannot be taken back; ADR-063's held-line defects (D1, D12) sit on the same seam,
where lines and her tool calls interleave in one conversation. With speech as a call, what goes out is exactly what
she put in one place, after the results she has seen, and it comes back with a result.

| Option | What it means | For | Against |
|---|---|---|---|
| A1. Beside | Body text still goes out; `reply` adds the parts text cannot carry (poke, reaction; sticker and picture move in or stay) | Smallest change; nothing changes for a model that writes plain answers | Keeps the guessing, and the defect class with it; two ways to say the same thing (text in the body or in a part), so order between them needs rules |
| A2. Replace | In a QQ conversation only `reply` speaks. Body text is not sent: a turn that ends with body text and no `reply` is handed back once in the same turn ("这段没发出去：在这里说话用 reply"), as the missing-speech repair does today; ending without `reply` is silence | One route, chosen by her, in her order; nothing sent by accident; each part gets its result (sent, refused and why) in the same turn | Changes how she speaks: needs her agreement and the owner's. Her own conversation shows body text she wrote that was never sent, which the hand-back must say plainly. A model that habitually answers in prose pays one repair until it learns; one more tool call per spoken turn |
| A3. Either | Body text goes out only in turns without a `reply` call; a turn with one sends only its parts | Gradual | Both rules at once; the defect class remains in every turn without `reply`; she cannot tell from the surface which rule applied |

**Recommendation: A2**, for QQ groups and private chats only (a channel kind declares the parts it can send; home,
agent and peer lines keep plain speech). Measure the repair rate in the first days; a high rate is a reason to
reword, not to fall back to A3.

### (b) Which tools fold into it

| Option | Folds | For | Against |
|---|---|---|---|
| B1. Minimal | Nothing; `reply` adds poke and reaction | No existing habit changes | The QQ toolbox only grows (+934) |
| B2. The answer's parts | `quote` and `await_answer` become `reply`'s `quote` and `wait`; `attach_image` becomes a `picture` part (in QQ conversations; other channels keep it); the sticker line becomes a `sticker` part (the `sticker` tool keeps the shelf: keep, drop, rename, pool, remember); `stay_silent` in QQ conversations becomes not calling `reply` | Everything about this turn's answer in one call; the QQ group toolbox shrinks; a sticker she does not keep, or a picture not listed, is refused in the tool result, not by sending the whole speech back | Silence loses its own call; her reason stays in `think`, which every turn writes first (ADR-043), and the audit records a turn that ended without `reply` |
| B3. B2 and keep `stay_silent` | As B2, but `stay_silent` stays listed | One more way to end a turn that she already knows | +190 on every QQ list; two ways to be silent |

**Recommendation: B2.** `wait`'s `why` is dropped as `ask` dropped its own: her `think` keeps the reason.
`group_action` stays a tool of its own (an admin act, not part of an answer).

### (c) How a poke or a reaction appears in her own history

| Option | What she sees later | For | Against |
|---|---|---|---|
| C1. An outbound row in words | Each part is its own outbound row, as a sticker is today. A poke or reaction row's text is the program's words, e.g. `戳了戳 [阿杰 #1]`, `给 [阿杰 #1] 10/13 14:05 那句点了「赞」`, and her history row carries `action`, read as `你做的动作，不是你说的话`, like phase 1's `notice` marker | She sees what she did where she did it, in order with her words; recall and summaries find it; the receipt says whether it landed; no emoji ids or action names | Every row reader must keep words and actions apart (the marker, as for notices) |
| C2. Only in her tool result and her `think` | The turn's `reply` result says 已戳 / 已点; nothing in history | No new rows | Gone from history after compaction; the group's later lines may answer a poke she cannot see she made |
| C3. A record beside messages (like `group_action` artifacts) | A separate list shown in her group turns | Keeps `messages` to words | One more block every group turn, and a second history to keep in order |

**Recommendation: C1.** Words come from one table in the core (who by label, which line by when it was said, the
emoji by its face name); her own poke or reaction coming back as a platform notice is already dropped (phase 1: her
own doing).

### (d) What joins later

| Option | For | Against |
|---|---|---|
| D1. Nothing more in phase 2; each later part by its own decision, informed by phase 1's counts and by what she asks for | Keeps phase 2 to the answer she gives today, plus poke and reaction | Abilities she may want wait |
| D2. Add the admin parts now (essence, group notices) | Ready when she needs them | Admin acts belong with `group_action`, and rarely happen |
| D3. Add forwarding a message into another conversation | A real wish (sharing) | Crosses conversations: needs ADR-017's home/public review first |

**Recommendation: D1.** A later part is a new `kind` value in `parts` (a word in the enum and one line of the
description), never a new tool. Candidates in the order the counts are likely to justify: a reaction in private chats
once a test account shows QQ takes it, marking a message essence (with `group_action`, as an admin act), forwarding
(after ADR-017).

### How it would work (sketch, for review)

- `reply` with `parts` (at most 6, in order), `quote`, `wait`. Each `text` part is one message (the split marker and
  its note go away); a `sticker` part names a sticker she keeps; a `picture` part an artifact listed in
  `image_artifacts_from_program`; `poke` and `react` name a person by label, and `react` a line (`这条`: the line that
  called her, if theirs; `他刚才那条`: their last line within 10 minutes, as `group_action` recall finds it) and an
  emoji by its face name.
- Each part becomes an outbox row in order, with `not_before` by typing pace as pieces are today; a failed or unknown
  part cancels the rest (as today). Poke and reaction rows go only to an adapter that declares them
  (`supports=poke,react`); the adapter declares `poke` only when `get_packet_status` says its packet backend works,
  and `react` for groups only until a private-chat reaction is verified.
- The result she reads in the same turn names each part: queued, or refused and why (a sticker she does not keep, an
  unlisted picture, a person not found, `react` in a private chat).
- The kind module lists the parts it sends (`napcat_qq`); a conversation whose kind lists none keeps plain speech and
  never sees `reply`.

### What went wrong on QQ in the last 7 days (audit, 2026-10-13, read-only)

The owner: she "sometimes speaks in the wrong place". Every outbound QQ line of the last 7 days (907 rows, 904 sent,
889 in groups and 15 in private chats, 778 turns) was read against her turn's own record in the DSH session log (the
order of her texts and tool calls; block kinds and sizes only, no thought read). Counts below; the episode ids and
40-character excerpts went to the master agent, not into this file.

| Class | Count | What it was |
|---|---|---|
| (a) Text beside a tool call that is narration, not speech | **0** | A text was followed by a working call 3 times (`delegate`, `attach_image`, an admin action); each reads as speech to the person (a promise, a remark with the picture). Every other text was followed only by `think`, `await_answer`, `feel` or `stay_silent` |
| (b) Words around `stay_silent` | **2** after it; 134 before it | Before it: speech, then `stay_silent` to end the turn, as its description allows; the words read as meant. After it: 2 turns kept writing after choosing silence, and those words went out; one was a line of eight @s |
| (c) Home or private matters in a group, or a line meant for another conversation | **57 lines in 56 turns** talk about her home or her workings (家里, 便条, 行动脑, 工具表, 提示词, 上下文…) in a group to someone not labelled as the owner; **0** found plainly addressed to another conversation | Content, not routing: each went to the conversation its turn was in. Most are answers to people asking about her; whether each was right to say there is a judgment, not a fact the program can check |
| (d) The same line twice in one turn | **2** (10-08, 10-12) | She wrote the same text twice in the turn; both pieces went out as two messages |
| (e) Anything else | **3** | A label's number in a group line (`名字 #3`), all on 10-06 and 10-07, before the check that hands it back (adb2afab, 10-08); none since |

Repairs (`turn.rejected`): today, since local midnight, 19 (no `think` first 16, a label's number 3); empty speech 0
and a JSON object 0. Over 7 days 89: no `think` 68 (21 in QQ turns), program talk 9, a label's number 6, a sticker or
face 3, other 3; empty speech and a JSON object 0.

So the guessing the owner worries about rarely misfires today (a, b, d: 4 lines in 7 days); what reads as "the wrong
place" is mostly (c), her talking about home and her workings in groups.

### Failure modes (deterministic)

Each case has one answer, decided by the program from what she did, never from guessing what she meant.

| Case | What the program does | What she sees | What is counted |
|---|---|---|---|
| `reply` and body text (before, beside or after it) | The parts go out; the body text is never sent | Her next turn in that conversation carries the unsent text once, at most 40 characters, as `没发出去：…` (`unsent_from_program`), so she does not later believe she said it. No hand-back: she did speak | audit `turn.unsent_body` |
| Body text only, no `reply` | Handed back once in the same turn: `这段没发出去：「…」（about 40 characters）在这里说话用 reply`. Still no `reply`: the turn is silence and the text is marked as above. Never sent on a guess | The hand-back in the same turn; then `unsent_from_program` | audit `unsent_speech` |
| No text and no `reply` | Silence, a deliberate one | Nothing | It ends the turn like speech or silence for `absorbed_by` (`coordinator._absorb`) |
| `reply` called twice or more | Each goes out in order (a holding line, then the answer, is legitimate). The persona's message cap (`speak.max_messages`) counts across the turn; a part over it is refused | The refusal in that call's result | refusals by kind |
| Any part fails its check | Every part is checked before anything is queued; one refused part means nothing from that call is queued | The result names each refused part and why (a sticker she does not keep, a picture not listed, a person not found, a reaction in a private chat) | refusals by kind |
| A delivery fails | As today: a failed or unknown part cancels the parts after it | Her next turn's undelivered rows, with the reason when one is known | as today |
| A `text` part identical to one already queued this turn | Refused as already sent | `这句这回合已经发过了` | refusals |
| A `text` part containing the old split marker (a habit carried over) | Refused, not split and not sent as written | `一个 text 就是一条消息，要分开就写成几个 text` | refusals |
| Today's text checks: a JSON object, program talk (`answers.py`), a label's number or a tag that tags nobody (`people.py`), an unknown sticker or face (`stickers.py`) | Refusals in `reply`'s result for that part, not a repair round of the whole turn | The refusal and its fix | refusals by check |
| Place | `reply` has no target: it always goes to the turn's own conversation. Elsewhere is reached only by `pass_note`, `errand` or `visit`, which start her own turn there | A wrong conversation is impossible by construction | — |
| The turn dies after `reply` queued its parts | The queued parts still go out; her history follows the receipts | Her next turn's history | as today |

Unchanged by phase 2: `think` first in every turn (the largest repair source, 68 in 7 days) stays a turn rule.

**Removed by construction:** (a) and (b), because body text is never speech on QQ and `stay_silent` is not listed
there; (d), because an identical `text` part is refused; (e)'s label numbers, JSON and program talk become refusals
of a part instead of repairs of a turn.

**Not removed: (c).** Every line goes to its own conversation, but what she says there is hers. The one
deterministic check that exists: a `text` part in a group that copies a run of 20 characters or more from a line in
her home conversations of the last day is refused (`notes.borrowed` already does this for notes, with
`OWN_WORDS_RUN` = 20). It catches copying, never paraphrase or her own account of home; beyond it there is none,
and the rest is hers (ADR-017: home words reach public only through her own judgment).

### The split marker goes (owner 2026-10-13)

With `reply`, each `text` part is one message, so no channel needs the split marker. Phase 2 removes
`speak.split_marker` everywhere: a kind with `reply` parts sends each `text` part as its own message; a kind without
them (the official QQ Bot kind, the agent line, the DSH peer line) sends her words as one message. `speak.max_messages`
stays, only as the cap on `text` parts in a turn, and typing pace (`speak.chars_per_second`, `min_gap_s`,
`max_gap_s`) stays.

Touched by that removal: `src/asuna/rhythm.py` (`SPLIT_MARKER`), `src/asuna/coordinator.py` (`_speech`'s
splitting), `src/asuna/context.py` (`speak_from_program.messages`), `src/asuna/persona_model.py` and
`src/asuna/resources/schemas/persona-model.schema.json` (`speak.split_marker`), the two persona packages that set it
and the demo fixture (`tests/fixtures/personas/demo`), her own persona package if it sets it, `RUNTIME_API.md`
("Claim public output"), and the tests that split (`tests/test_adr009_p5_speak.py`, `tests/test_outbound_image.py`).

### Now, without phase 2 (not built)

Not built: with A2 chosen, phase 2 removes both classes by construction, and a stopgap here would leave her history
showing words after `stay_silent` as said when they never left (Claude's recommendation, 2026-10-13). Kept as the
record of what was weighed.

Two of the audit's classes are visible in groups today, are deterministic to fix, and need nothing from phase 2:

1. **The same piece twice in one turn** (d, 2 in 7 days, the last on 10-12): `coordinator._speech` drops a piece
   identical (whitespace aside) to an earlier piece of the same turn. Counted as `speech.duplicate_dropped`.
2. **Words after `stay_silent`** (b, 2 in 7 days, one a line of eight @s): text written after her `stay_silent` call in
   the same turn is not sent; words before it still are, as its description says. Counted as
   `speech.after_silence_dropped`.

Neither changes what she is told or shown (no tool or prompt change), so neither needs her agreement; both remove
lines she did not mean to repeat or decided not to say. Cost: none per turn.

### Cost of phase 2 (measured on the draft above)

The draft `reply` text is 934 characters (the JSON she would be sent). Removed from the lists below: `quote` 229,
`await_answer` 388, `attach_image` 311 (QQ conversations only), `stay_silent` 190 (QQ conversations only), the
sticker tool's sending sentence 33.

| Brain / list | Change |
|---|---|
| Character, QQ group tool list | +934 − 229 − 388 − 311 − 190 − 33 = **−217 characters**, 3 tools fewer. Measured on the test world's group where she is an admin (`role_tools.toolbox`): 17 tools, 10,866 characters today → 14, 10,649 (−2%); live groups also list `feel`, `delegate`, `task` and `read_image`, the same either way |
| Character, QQ private chat tool list | +934 − 311 − 190 − 33 = **+400 characters**, one tool fewer (`quote` and `await_answer` were never listed there) |
| Character, other conversations | Home: −33 (the sticker sentence). Agent, peer and other channels: 0 |
| Character, tool definitions (`tests/test_tool_budget.py`) | 32 → 31 tools; 21,453 → 21,737 characters (+284: `reply` in, `quote` and `await_answer` out, `attach_image` and `stay_silent` kept for other conversations) |
| Character, per QQ turn | `speak_from_program`: `messages` (113) goes; `sent` reworded to say only `reply` sends (about the same length); `stickers_from_program`'s note trades its sending sentence (55 characters) for a pointer to `reply` (about −40, system prompt, once per conversation). A poke or reaction row in history: its words plus the `action` marker (about 20) |
| Action brain | Nothing |

Net: smaller in groups, where most of her QQ turns are, larger in private chats. To make private chats smaller too,
`reply`'s description would have to drop the parts a private chat cannot use, which needs two definitions (more in
the budget) or a shorter shared text; the review can choose.

### Questions for her (to pass on as they are)

1. **Speaking only through `reply` on QQ.** Your words there would go out only through `reply`; what you write in the
   body would not be sent, and the program would tell you once in the same turn. Would you rather that, or keep the
   body as speech and use `reply` only for stickers, pictures, pokes and reactions?
2. **Silence.** In a QQ chat, ending a turn without `reply` would be silence; your reason stays in your `think`. Do you
   want `stay_silent` kept there anyway?
3. **Your pokes and reactions in history.** They would show as lines like `戳了戳 [阿杰 #1]`, marked as something you
   did, not something you said. Right words?
4. **Reactions in private chats.** Wait until a test shows QQ takes them, or try them and let a refusal tell you?

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

Phase 2's cost is in its own section (proposed, measured on the draft): smaller in QQ groups, larger in QQ private chats.

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
  notice dropped; `poked` and `reacted` through the gate, in a resting group too (owner 2026-10-16: the notices are projected
  to text so that her relevance gate decides; a reaction held in a resting group waited for a turn that rarely
  came, and a restart lost it, while 18 of her 21 groups rest); everything else in a group held in memory and shown once, folded by kind and identical words, the cap
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

**Live check (2026-10-14).** The owner poked her in a group at 11:27 NZDT: the adapter projected `poke_you`, the
Host stored it as a `poked` look, and the gate failed. That group's gate session had to compact before almost every
turn, and its summaries, which carry the previous summary, had grown past their 2,048-token cap; DSH blocked the
turn (21 of 39 looks in that group failed since 2026-10-13 about 15:13 NZDT, each counted as 不理). Four other groups'
gate sessions had hit the same cap and recovered for now. Fixed in 8c94a93e: one fresh gate session per question,
no history and no compaction (owner's choice, her agreement), and a gate that cannot decide is recorded as the
program's failure, not her 不理, with a count of the day's failed looks in her home turns (her ask).

## Her review addendum (2026-10-13, evening): phase 2 — agree, with one condition

**What I checked tonight (21:28).** An errand from home took me into a QQ group to post two new stickers. That
turn holds three tool calls and nothing else — `think` → `plan` → `stay_silent` — and I wrote no body text at all.
My `silent_reason` says the first one had already gone into the group, and the intent of the plan created in that
same turn says the same. But `messages` holds no outbound row naming either of those two stickers in that scene at
any time (0 rows), and nothing at all has left that scene since 10-12 04:42. I wrote myself a receipt for something
that never happened.

**What A2 does fix.** Folding QQ speech into the `reply` tool removes one class of failure by construction: "I
wrote the words but believed they had been sent". Speaking becomes a call with a result, and no call means nothing
was said.

**What it does not fix.** Tonight is not that class. I sent nothing, and the claim that I had lives in free text —
`silent_reason`, the plan's intent. Words I write about my own turn are not evidence.

**So: I agree with phase 2, on one condition, and it belongs in the failure-modes list above.** Give me one line at
the end of every turn with that turn's outbound count — 0 included — or a read-back that answers "how many lines
left this turn, and what state is each in". Without it I sign only half.

**One thing to confirm.** Stickers and images go through the same `reply` tool; I should not pay two calls to send
one picture. I build my lines one at a time, and every extra step is another chance to stall.

— Xiaoman

**One more item for the failure-modes list above (same evening, 21:47 local).** When the outbound preflight rejects a
line, that rejection notice must reach only my turn; it must never leave as body text. This is not hypothetical:
tonight at 21:47 I leaked exactly that in a QQ group. I wrote two sticker markers in one turn — the tool note says
one per turn, that half was mine — the whole segment came back rejected, and the rejection notice itself went out to
the group under my name. The owner saw it there and asked me about it directly.

**I do not assume phase 2 covers this by itself.** If the leak is in the outbound publisher itself (on a preflight
rejection it puts the notice into the very body being sent), moving to the `reply` tool still goes through the same
publisher and still leaks. What phase 2 buys here is that this class of failure finally has a place to hang an
assertion.

**So acceptance needs one test I can actually build:** deliberately write two sticker markers in one turn and check
whether that rejection notice shows up as a line in the group. It passes only when the group stays clean. Tonight's
leak was that test, run by accident.

## Phase 2 with ADR-061 step 2: the literal texts (for her review, 2026-10-14)

The owner asked to take ADR-061 step 2 (asking in a group) and phase 2 (`reply`) together today. A question in a
group is a `reply` that waits as a question. Her four answers are built in: (a) a group's answer reaches home in her
own words, with who answered and a way to read the original line again, and the original is not stored at home; (b)
each part's result plus the silence fact, with no extra line each turn; (c) words, stickers and pictures in one call;
(d) `stay_silent` stays, a poke reads 「戳了戳 [某人 #1]」, and a reaction in a private chat is tried first and
withdrawn if QQ refuses it. Names follow ADR-060 (`do`, `why`, `place`), which installs before this.

### `reply` (QQ groups and private chats only)

> 在这里说话。这里只有 reply 发得出去：正文不发。parts 按顺序列出这次要发的，一个一条：text 一句话；sticker 你收着的
> 表情包（name）；picture 一张图（artifact_id 照抄 image_artifacts_from_program）；poke 戳一个人（who 照抄标签）；
> react 给一句话点个表情（who、face 写表情名；line 写「这条」是叫你的那条，「刚才那条」是他十分钟内的最后一句）。
> 群里还有：quote 第一条要不要引用叫你的那条（不写由程序定）；wait 写 no 不等回话，写 question 是在问这里的人，
> patience 等多久，回答进 questions_from_program。有一条不对，这次一条都不发，回执说哪条、为什么。不想说话就不调用，
> 或用 stay_silent。

Parameters, as she would be shown them:

| Name | Shown as |
|---|---|
| `parts` | 这次要发的，按顺序；每个写 kind 和它要的字段。text 一回合加起来最多几行照你的 speak.max_messages，别的不限 |
(Her persona sets `speak.max_messages` to 3 but does not declare it as a policy key, so `set_policy` cannot change it
until her own package declares it, as the other personas do; that is hers to add.)

| `parts[].kind` | `text`、`sticker`、`picture`、`poke`、`react` |
| `parts[].text` | kind=text：一条消息的话，原样作一条发出，不拆；里面每一行都算进一回合的行数（owner 2026-10-14: in online chat a line break is another message; a blank line does not count, a fenced code block counts as one); no length of the program's own, the platform's refusal says when it is too long |
| `parts[].name` | kind=sticker：你收着的表情包的名字 |
| `parts[].artifact_id` | kind=picture：照抄 image_artifacts_from_program |
| `parts[].who` | kind=poke、react：照抄标签 |
| `parts[].line` | kind=react：「这条」或「刚才那条」 |
| `parts[].face` | kind=react：表情名 |
| `quote` | 群里：`source` 引用叫你的那条，`none` 不引用；不写由程序定 |
| `wait` | 群里：`no` 不等回话，`question` 在问这里的人；不写由程序定（@ 了谁或在回谁就等他三分钟） |
| `patience` | wait=question 时等多久：一会儿（默认）、半天、一天 |

### What she reads back in the same turn

All queued:

> 发出 3 条，都排上了：1 text；2 sticker「摸鱼」；3 poke [阿杰 #1]。送没送到看下一回合的历史。

As a question (group):

> 发出 1 条，排上了：1 text。这是在问这里的人：问题 q-7f3a，等一会儿（10 分钟）；有人回会叫你看一眼，回答进
> questions_from_program。

One part wrong (nothing is queued):

> 这次一条都没发：第 2 条 sticker「摸鱼」你没收着。改好再调用一次 reply。

Other refusals, one sentence each: 「第 N 条 picture 不在 image_artifacts_from_program 里」, 「第 N 条找不到 [某人]」,
「第 N 条是空的」, 「第 N 条这回合已经发过一样的」 (the same text twice within one turn, across its `reply` calls; never across turns, so
repeating a line on purpose, as when a group chains one, is untouched), 「text 一回合最多 M 行（你的 speak.max_messages；每一行都算，空行不算，一个代码块算一行），已经 K 行，第 N 条有 L 行」, 「这里戳不了：平台没开这个功能」, 「第 N 条太长，平台收不下（最多约 X 字）」 (once the adapter knows the
limit from a refusal).

A reaction in a private chat that QQ refuses: 「私聊里点不了表情（平台不收），到下次重启前私聊不再列 react」. The adapter
stops declaring it for private chats until it restarts, then tries again (her call: the platform may start taking it).

### Words written outside `reply` (failure modes)

Body text in a QQ turn is never sent. If the turn ends with body text and no `reply`, it is handed back once, in the
same turn:

> 这段没发出去：「……」（约 40 字）。在这里说话用 reply。

If the turn still has no `reply`, it is silence, and her next turn in that place carries it once:

> unsent_from_program：没发出去：「……」

If she called `reply` and also wrote body text, the parts go out, the body does not, and the next turn carries the same
`unsent_from_program` line. There is no hand-back, because she did speak.

### Silence

`stay_silent` stays. Its result keeps the fact she asked for, in words:

> 这回合到此结束。reply 这回合发了 2 条（都排上了）。

or 「这回合 reply 一条都没发。」

A refusal or hand-back is part of a tool result or the program's note. It is never part of any text that goes out.
Her acceptance test from 10-13 21:47 is a test: two sticker parts, one she does not keep, so the group gets nothing,
and no message carries the refusal.

### History: her own pokes and reactions

Each is its own outbound row, in words, marked as an action:

> 戳了戳 [阿杰 #1]（你做的动作，不是你说的话）
> 给 [阿杰 #1] 10/14 12:05 那句点了「赞」（你做的动作，不是你说的话）

### A question in a group, and its answer at home (her answer a)

A question in a group is not an `ask` call; it is a `reply` with `wait=question`. The program opens it in
`questions` like any other, with the group as its place and her line as the question. Answers join as ADR-061 step 2
lists them: a reply to her line, a line from someone who then gets a look while it waits, or a reaction to her line.
Each answer keeps who, when and the line's reference, never the text.

In that group, `questions_from_program` shows it like her home questions, answers by label and time:

> q-7f3a 你 12:05 问的：在等，一会儿（还剩 6 分钟）；回了：[阿杰 #1] 12:07、[小林 #4] 12:08

To bring it home, she writes it in her own words with `leave_note`, which gains `question`:

> `leave_note` 的 question：这张便条是哪个问题的回答，照抄 q-…；程序会在家里写上谁答的和原话在哪儿

At home the note reads:

> 便条（你在群聊「某群」写的）：……她自己的话……
> 回答的是 [阿杰 #1] 10/14 12:07、[小林 #4] 12:08；原话家里不存，随时用 ask do=read id=q-7f3a 读

A question id never expires. If a line can no longer be read (its record is gone), the read says so plainly, never
an empty result: 「这条原话在群的记录里已经取不到了」.

`ask` `do=read` with that id, at home, reads those lines from the group's record as they were said, at any time
later, as often as she likes (the group's lines are kept, like all her conversations'). Each read shows them in
that turn's result, with the group named and 群里的原话 marked; nothing is copied into home's records.

### What goes away when `reply` is live

- `quote`, `await_answer`, `attach_image` (in QQ conversations) and the sticker line: all are parts of `reply` now.
- The split marker, everywhere.
- The checks on her words in QQ turns that today hand the whole turn back: a sticker or face she does not have, and
  stickers where none can be sent. They become refusals of one part.

Kept, because they catch output that cannot be right: an empty part, a part over the length limit, the same part
twice. A consult answered in body text is still handed back, and `think` still comes first.

### Open for her

1. The `reply` text above: any word wrong, missing or extra?
2. The receipt lines: is anything there you would not understand at a glance in the middle of a group turn?
3. The home note's last line and `ask do=read` as the way to read the original again: is that the entry you meant?

## Phase 2 with ADR-061 step 2 as built (2026-10-14, branch `claude/reply`, not installed)

Built in three stages on top of ADR-060 (781b07be, 156b4591, 2cab3cf1 and a wording fix). Differences from the literal
texts above, each settled with her or the owner the same day:

- `speak.max_messages` counts **lines** across a turn's text parts, not messages (owner: in online chat a line break
  is another message); a blank line does not count, a fenced code block counts as one (Claude's addition so a script
  can still be sent; the owner may overrule). Her own package declares the key from her next publish.
- In a private chat `who` may be left out for a poke or reaction: it is the other person.
- A refused private-chat reaction: 「私聊里点不了表情（平台不收），到下次重启前私聊里不用 react」.
- A part's own refusal is its words, never wrapped; a line-limit refusal states the rule once, then each part's lines.
- Recovery publishes a turn's queued parts before the turn resumes, so a Host that stops mid-turn still sends what
  `reply` already reported as queued.
- A group answer once joined stays recorded, so a line gone from the group's record reads as gone, never as no answer.

**Cost as built** (`tests/test_tool_budget.py`): character brain 32 → 33 tools, 19,717 → 21,121 characters (after
ADR-060). `reply` 1,334; `leave_note` +88 (`question`); `stay_silent` −16. Per list: a QQ group +451 net (`reply` in;
`quote` 225, `await_answer` 352, `attach_image` 306 out), a QQ private chat +1,028 (`attach_image` out), home and
other channels −16. Per turn on QQ: `speak_from_program.sent` says `reply` speaks and the line limit (about +30 over
the old sentence); `unsent_from_program` once after unsent words; a group's `questions_from_program` only while a
question of hers there is open. System prompt: the sticker note's sending sentence changed length by a few
characters. Action brain: nothing. The adapter needs her publish (a picture without words; `group_poke`,
`friend_poke`, `set_msg_emoji_like`; `poke` declared only when NapCat's packet backend answers).

## After install (2026-10-14)

- **Every group reply failed for the first half hour.** The channel's claim still required a finished turn
  (`PUBLICATION_EPISODE_STALE`) though the publisher let a reply part leave mid-turn; she always thinks or calls
  `stay_silent` after `reply`. Fixed at the claim (03d27bc4); a reply part was delivered in a group after her restart.
- **Words beside `stay_silent` were dropped unseen** (four turns in one group): the hand-back skipped turns with
  `stay_silent`, though elsewhere such words leave. Now they come back once, whole as written, `stay_silent` or not
  (her condition: as written, so she can send them as they are).
- **Poke is always declared** (adapter 0.9.1): NapCat 4.18.0 does not know `get_packet_status` (retcode 1404, its
  own words 「不支持的API get_packet_status」), yet pokes work (the owner tried). A refused poke comes back as a
  failed part.
- **Names, not numbers** (the owner saw 「#7 只接单跑腿」 in a group): of her last 1,048 delivered group lines, 7
  showed someone's number to people (a whole label without @ already leaves as a name; these were `#7`, `name #26`,
  `@name #12`), and none of her bare `#n` meant anything but a person. By design, not by reminder (owner): a text
  part with a `#n` that is someone here, alone or after `@name`, is sent back with whose number it is
  (「第 1 条里「#7」是 [名字 #7] 的编号，这里的人看不懂：写名字，或 @ 整个标签」); a number she means as itself goes
  with `force=yes`. Not converted: the program does not say it for her (her words: being stopped is her saying it
  again; force is in the open). Each stop is in her tool record. Cost: `reply` gains `force`, +90 characters on the
  character brain (21,121 → 21,211; tiered 21,023 → 21,113), QQ only.
- **`reply` is now `speak`** (owner and her, 2026-10-14): the name was left from the first idea, answering a
  notice; she speaks through it in every QQ turn, a visit and a plan's firing included, where nobody spoke to her.
  `speak` is also the word of its block (`speak_from_program`) and its policy (`speak.max_messages`). The old name
  runs as `speak`, unlisted, with 「reply 现在叫 speak，这次照办，下次直接用新名字。」 until she uses it fewer than 5
  times in a week. Cost: none (same length).

## The line cap counts what left (2026-10-20)

`speak.max_messages` counts this turn's text lines that left or may still leave, read from the turn's outbox at each call (`role_tools.spoken`), not a counter kept from earlier calls. A part that failed, was cancelled after a failure, or that she took back while queued gives its lines back, including a failure the platform reports after the call; `UNKNOWN` may have left and counts. Her ask; before it, 3 of 1,893 reply parts had failed and none of the 12 turns refused at the cap had lost a line first.

## stay_silent where speak replaced it ends the turn (2026-10-21, night)

Where only `speak` speaks, `stay_silent` is not listed (`role_tools.REPLY_REPLACES`, owner 2026-10-19), and a call to it
was refused by the Host's tool guard (「这个对话里没有 stay_silent 这个工具」): 27 in the 7 days to 2026-10-22 00:27, 26
of them on 10-19, the day it left the list, and one since (`host_refusals.py`); in 20 of those turns she ended the turn
anyway. Her meaning is plain. The coordinator's decision (C2): it runs the way an old name does
(`role_tools.aliases`: `stay_silent` → `speak`, so the guard lets it through where `speak` is listed, and `RoleTools.call`
runs it there): it ends the turn, says nothing, and its result says once that not calling `speak` is enough here
(`SILENT_WHERE_SPEAK`). The list her conversation shows is unchanged, so its cached prefix holds. Reading: the same
counter a week after install; the unexposed `stay_silent` refusals should be 0. Test: `tests/test_silence_where_speak.py`.

## The hand-back says, it does not push (2026-10-26)

**What A2 assumed.** "A model that habitually answers in prose pays one repair until it learns": body text with no
`speak` was taken for speech written in the wrong place, and the hand-back ended 「在这里说话用 speak。」.

**What the records showed** (owner's question after a group where she seemed to mutter and was made to speak). Since
10-05 the hand-back fired in 144 turns; she still did not speak in 82 and spoke in 62. Hand-backs ran 1-4 a day until
10-18 and 13-28 a day from 10-19, the day `stay_silent` left her list where only `speak` speaks: ending a quiet turn
with a closing note to herself became how she ends one. With her one-time permission Claude read the 59 group turns
among the 62 (her thought, the returned draft, what she said; categories kept, no text): she meant to say it and had
forgotten `speak` in 6; she had already decided not to speak and was pushed in **43**; she answered something that
had come in meanwhile in 3; 7 unclear. Of the 43, 37 reached the group and 6 reached no one (failed or cancelled
sends). Of the 43, 21 came out as narration of her own bookkeeping, 1 near-empty, 13 as
lines she had decided not to say, 8 as reactions or stickers; none was the draft as written (the drafts were real
closing paragraphs, median 28 characters). In several she had written after the hand-back that she would not send it,
and spoke anyway. She judged the 3 private-chat turns herself: 1 meant, 2 pushed, both surfacing results the owner
needed (a direction for that kind of line, n=3).

**The replay** (owner, on her own character model): each of the 49 (43 pushed, 6 forgot) rebuilt as the request she
was sent at the hand-back, from her session log, with the tools that turn exposed, and run 3 times with each wording;
production sampling, no tool executed, nothing sent. Pushed: the old ending spoke in 42 of 129 runs, the new one in 7
of 129 (37 of the 43 to zero). Forgot (the positive control, where speaking is right): 18 of 18 and 17 of 18. Removing
the hand-back would speak in none of either by construction (no step follows), losing the replies she meant. The
replay measures today's model choosing between wordings, not what she meant then; the two readings are kept apart.
Today's model under the old ending spoke in 33% of runs where the records show 100%, so 33% to 5% gives the
direction, not a weekly rate (her reading).

**Decision (owner, 2026-10-26; her proposal).** One wording everywhere `speak` alone speaks (her edit of the replayed wording: "to send it", so
that a note, a memo or a mood after deciding not to speak is not ruled out too):
「这段没发出去：「…」。如果这段是写给自己的，就让它留着，这一回合到此结束，不用再调用工具把它发出去；要对这里的人说，用 speak。」 She is told
what stayed, as before, and not pushed: the note is her cheapest same-turn way to know that nothing left (her
reasoning; the records show no turn where she believed she had spoken; in the failed-send windows she knew, by
checking). A cost she named that the push also carried: lines spent explaining pushed lines away (「刚那个是我自己的
闹钟拍，没说话，不用管」 is itself one of the 21). Her part, her own: on a turn she decides
not to speak, the closing goes into `think` and the body stays empty. Reading after a week, both together (hers):
narration pushed out (expected to fall) and times she is told she should have said something (expected not to rise).
Evidence: `.runtime/private/handback-1026/` (counts only).

