# ADR-129: One way to speak, at home too

Status: **Designed** 2026-11-13 (the owner's go after ADR-127 closed; nothing built). Proposed the night before. Next:
a fresh review against the code, then her reading of §3's literals (her F8), then the build on a branch.

Times on this page are local time.

## The ask (the owner's words)

- 11-12 night: "adding the same speak tool to her home line so she will not get confused with external herself …
  calling the same speak should give her the same as she did on QQ."
- 11-13 00:0x: "At home I don't really care how she spoke at home, either mumbling, or calling speak, or whatsoever
  it doesn't matter, she can send multiple lines or not to speak, or send (this turn end with no speech) is also fine.
  This is at home, no manner needed to be mandated. Having speak tool benefits, as her outer self used to this, and
  she did sometimes tried to call speak at home. Using speak at home allows her to use stickers, which is cute." Then:
  "I don't want to mandate any restriction to use speak, perhaps just give the tool, and no restriction to be applied
  at home then." Where: "All web chat".
- 11-13 afternoon: "when she use speak and mumble at the end of turn, perhaps just automatically fold her mumble to
  the folded view (similar to her think and other tooling call), and show the content from speak (including stickers
  and etc, maybe images as well). Don't consider her habit in the design, she will learn to adopt the new mechanism
  quickly." The fold and the open `speak` row: everywhere `speak` appears on the page (his choice).

In scope: her local Web chat gets `speak` and silence without an act; the page shows `speak` open, with its stickers
and pictures, and folds the body text of a turn that called `speak`.

## 1. What is known

- **Two meanings of one act.** On QQ (every channel kind that declares `REPLY_PARTS`: napcat-qq, qq-bot) she speaks
  only through `speak`. `stay_silent`, `attach_image` and `await_answer` are not listed there (`REPLY_REPLACES`; the
  owner, 2026-10-19). Body text never leaves: written with no `speak`, she is told once in the turn
  (`UNSENT_NOTE`) and her next turn says it was not sent; written beside `speak`, it is her ending, kept only as a
  count (`turn.ending_body`). Not calling `speak` is silence; the one check kept is a missing thought
  (`REPLY_THINK_NOTE`). At home (her Web chat, the agent lines, the peer line) body text is speech, published as one
  message at the turn's end (`coordinator._publish`), and silence is the `stay_silent` tool.
- **One switch does two jobs.** `channel_kinds.reply_parts(scene)` non-empty both offers `speak` with those parts and
  makes body text unsent. It is read at 12 sites (`role_tools` `abilities` and `_turn_rules`, `speak_kinds`, the call-cap reminder,
  `tool_stay_silent`, `turn_parts`; `coordinator` turn end and `publish_queued`; `context` guide and speak block;
  `outbound_media` offer note; `outbound_files`).
- **She already reaches for `speak` at home.** 33 calls in her home Web session since 10-29, every one refused as not
  listed: 2 on 10-29, 1 on 11-03, 5 on 11-04, 1 on 11-05, 21 on 11-08, 1 on 11-09, 2 on 11-11.
- **Silence at home is rising, in runs.** Turns of her Web chat started by the owner's message and ended with
  `stay_silent` and no words: 0 to 5 a day from 10-23 to 11-11; 22 of 142 on 11-12, all between 23:15 and 23:56,
  almost all `think` → `stay_silent`. Each completed normally. From counts alone it cannot be told which silences she
  chose for a reason.
- **The program makes silence at home an act.** A home turn with no words is handed back
  (`answers.speech_problem`: 这回合没有写要说的话：写出要对对方说的话，或者用 stay_silent 结束), and one that keeps failing
  that check fails as `INVALID_TURN_OUTPUT`.
- **No stickers and no pictures leave at home.** `stickers.sends` needs a platform scene, so `sticker` there only tidies
  her shelf; `outbound_media.target_allowed` refuses a scene with no channel route, so `attach_image` is never listed
  at home. Her shelf: 59 stickers, all custom (each has a picture of hers); 0 market (read 11-13).
- **The page.** `client.js` draws a `speak` call as DSH's disclosure row 说话 · its first text, closed (DSH's
  `useDisclosure` is always initially closed), its parts as text: a sticker as ［表情包：name］, a picture as ［图片］. The
  home page shows no picture of hers at all today.
- **"Her Web chat" is one scene.** Every Web input goes to the local chat scene (`config.chat.scene_id`) or to a joined
  agent line (`native_worker` `input`); the agent lines and the peer line have their own scenes with a channel.

## 2. The broken invariant

**At home nothing about her manner of speaking is mandated** (owner, 11-13), and **a turn's speech is one thing**:
`speak`'s parts if she called it, else her body text. The program breaks the first by refusing the `speak` she
reaches for and by demanding words or an explicit `stay_silent`; the page breaks the second by showing body text as
speech in a turn that spoke through `speak`.

## 3. Decisions

**D1. `speak` at home.** The local chat scene offers `speak` with parts `text`, `sticker`, `picture`: one new
function, `role_tools.speak_parts(config, scene_id)` = the channel kind's `REPLY_PARTS`, or `HOME_PARTS` for the local
chat scene, read wherever `speak` is offered (`abilities`, `_turn_rules`, `speak_kinds`, the offer note). `reply_parts` keeps its
one meaning, "here only `speak` speaks" (QQ). At home `stay_silent` and `attach_image` leave the toolbox as on QQ
(`REPLY_REPLACES`); the `picture` part carries what `attach_image` would. `file`, `poke`, `react`, `recall` are not
home parts (no platform behind them). A `picture` part needs the local chat allowed as a picture target:
`target_allowed` answers yes for it (delivered to the local sink, shown on the page by D5).

**D2. One speech per turn.** At home, a turn that queued any `speak` part has said what it said: its body text is
hers, not published, counted as on QQ (`turn.ending_body`). A turn that did not call `speak` publishes its body text
as today (`_publish`, key `<ep>:speak:0`). The two never meet in one turn, so the two defects the census found cannot
happen: `_publish`'s `<ep>:speak:0` taking the first part's key (its text silently lost), and her history ordering
parts before text written earlier in the step (the page showing the other order).

**D3. Silence needs no act at home.** A home turn with no `speak` and no body text commits silent, every turn kind
(the owner's message, a heartbeat, a note, a task's result, self-development). `speech_problem`'s no-words case is not
reached at home. Kept, as on QQ: a turn cut at the length limit (its text is not whole), a missing thought where her
mode asks for one, a sticker token in body text she does not have. `stay_silent` is not listed at home and nothing is
added for a call of it (owner: no design for her habit): the `stay_silent` → `speak` alias (`aliases()`, its sentence
`SILENT_WHERE_SPEAK` true only where `speak` alone speaks) applies only where `reply_parts` is non-empty, so at home a
call is refused as any unlisted tool is.

**D4. No rules on `speak` at home.** Not applied at home: the line limit (`SPEAK_HARD_LINES`, `speak.max_messages`,
and the receipt's line count), a text already sent this turn, a `#number` line label (`LINE_NUMBER`), a person's
number (`people.numbers`), the typing pace (already none: `not_before` only for a scene with a channel). Still checked,
because they are about what can be shown or what may leave: an empty part; a sticker written inside a text (it would
show as words: it goes as a `sticker` part); `[分条]` inside a text (a text is one message); a raw local root
(`local_roots`, privacy); a sticker not on her shelf; a market sticker (no picture of hers to show; none today); a
picture not offered to her. One wrong part still means none of the call leaves, and the receipt says which and why
(as on QQ). The receipt is QQ's own (发出 N 条…送没送到看下一回合的历史): true at home, no new words.

**D5. The page** (everywhere `speak` appears, the owner's choice), through DSH's own facilities:
- (a) The 说话 row is open by default: our row reads DSH's disclosure state inverted (closed only after a click).
- (b) Its `sticker` and `picture` parts are drawn as pictures under the row, through DSH's attachments and its
  `tool.call.images` slot (`loadImage`). The bytes never reach her model: the plugin asks the worker for them (`page`
  in the call's envelope), saves them as DSH attachments, returns the refs in the tool's `output.presentationMeta`
  (stored as the result's `meta`, page-only), and `asunaRender` leaves `page` out of what the model reads. A part
  whose picture cannot be saved is drawn as its words, as today.
- (c) In a turn that called `speak`, the body text is drawn folded like her thoughts: the plugin marks the turn
  (turn data, as `asuna-stage-finish` is today) and our override of DSH's `assistant-step` node draws that text in
  DSH's own reasoning disclosure.

**D6. Her words (her F8: a new or changed literal needs her word first).** Drafts, for her reading:
- `block_guide.WORDS['home']`: 你用工具做事；写在正文里的话会按顺序发给对方。也可以用 speak 说，一个 part 一条，能发表情包和图；
  用了 speak 的回合只发 speak 的内容，正文留给你自己。
- `block_guide.ENDING['home']`: 结束：说完了就不再调用工具；这回合不说话也一样，什么都不用调用，不算漏了什么。
- The call-cap reminder at home (`CAP_SAYS` today: 用它写下要说的话，或 stay_silent。): 用它把要说的说完（正文或 speak），不说也行。
- A market sticker at home: 第 %d 条 sticker「%s」是平台的市场表情，这里显示不了。
`render_system`'s `speaks` takes a third value (`'home'`); a stored ref with `True`/`False` re-renders as written.

## 4. Where

Her local Web chat: the scene `config.chat.scene_id`, every DSH session bound to it. Unchanged: the agent lines
(joined from the Web or not) and the peer line keep body-text speech and `stay_silent`; QQ keeps everything but the
page (D5).

## 5. Failure modes

| Case | What happens | Why it holds |
|---|---|---|
| Body text and `speak` in one turn | Parts are her speech; text kept as a count, folded on the page | D2: never both published |
| No words, no `speak` | Silent commit, no hand-back | D3 |
| Host stops after parts were queued | Recovery publishes the READY parts (`recover` → `publish_queued`, local sink) | existing path |
| Turn fails after parts were shown | Her next line (ADR-127 N1) counts them as sent | `faults.lost` reads delivered rows |
| Turn replayed from its lane receipt | Parts are not queued again; the turn commits as recorded | `speak` ran once; replay reads the receipt |
| Newer worker, older plugin | No `page` asked, no bytes returned; the page draws words | D5(b) asks first |
| Newer plugin, older worker | No `page` in the reply; the page draws words | the plugin reads it only if present |
| A picture cannot become an attachment | The part is drawn as its words; she is not told (it left) | D5(b) |
| Sticker erased or not on the shelf | Refused with its reason; none of the call leaves | existing checks |
| A large picture | Same inline path as `read_image`'s bytes; bounded by the blob store's limit | existing path |
| `stay_silent` called at home | Refused as unlisted; the turn goes on | D3, owner: no habit design |
| Her cache | Each home session's tools and system prompt change once at the install: one miss | known cost |
| QQ | `reply_parts` and every QQ rule unchanged; only the page changes (D5) | D1 keeps its meaning |
| Agent lines, peer line | Own scenes with a channel: no `speak_parts`, unchanged | D1 is the local scene only |
| Line-taking (`_absorb`) | Home lines carry no channel receipt: nothing absorbed | `stageView` `seen_inputs` |
| ADR-127 S3 (a turn steps aside, messages return) | Independent of how a turn speaks | different layer |
| Consult and task-time turns | Their own toolboxes return before `speak` is added | `role_tools` returns early |

## 6. Tests (only where a failure would be silent)

- A home turn that calls `speak`: its parts reach the outbound history in order; its body text is not published and is
  counted (`turn.ending_body`).
- A home turn with no `speak` and no words: committed silent, no hand-back, no failure.
- A home `speak` that QQ would refuse (seven lines, a repeated text, a `#number`): it goes out.
- The worker returns picture bytes only when the plugin asks (bytes reaching her model would be silent and costly).

## 7. Shown, then installed. Closes when

- **Shown** in an isolated demo profile with a stub model and the real worker, labeled 造的: a home turn with `speak`
  (text, a sticker, a picture; the row open, the sticker and the picture drawn, its body text folded), one with body
  text only, one with neither (silent, no hand-back), one with a long `speak` and a repeated line; the home toolbox
  lists `speak` and not `stay_silent`; a QQ-kind scene's `speak` unchanged.
- **Installed** in a restart slot she gives, after her reading of D6.
- **Closed** when, over her own home use, there are no refused `speak` calls and no hand-backs for a missing answer at
  home, and her `speak` replies (a sticker among them) are seen on the page. How often she is silent is hers, not a
  closing condition.
