# ADR-129: One way to speak, at home too

Status: **Closed** 2026-11-14 15:09: §9's two exits (`_publish`, the retired tools' code) installed as `8c07e4e02cc2` and read
by content (§11). The rule closed 2026-11-13 21:1x by proof (§10): installed 20:12 as 816e825ea84f, one rule in every conversation
(D8-D12). The first part (her local chat only) was installed 17:50 as 92fd20700e55; the owner revised the scope the
same evening. ADR-128 waited on this page and may now be built.

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

**The ask, revised (11-13 evening, after the first part was installed).**
- "I thought web ui are all having the speak tool, and stay silent is drop everywhere, as from my perspective, the
  agent line is a local chat too."
- "The same rule applies everywhere, speak to speak, mumbling keeps as mumbling, print it if DSH doesn't support
  folding (which it does), and stay_silent is gone. For QQ, keep the same rule, and rule should drop for local chats.
  Therefore, from user perspective NOTHING should change, and from your agent line you should see exactly what she
  wants to see, and no more accidental keepping quiet."
- On storage: "local dm and agent line goes database and stored forever"; "make sure the ADR-129 will properly
  capture the life cycle of non-text image as well. The rule should follow what QQ does today", meaning "how QQ
  stores the image, not how she sees the image".

What the first part got wrong: D1 and §4 narrowed "All web chat" to one scene, though §1 already counted the agent
lines and the peer line as home; and it kept two rules (body text as speech at home, only `speak` on QQ).

## 1. What is known

- **Two meanings of one act.** On QQ (every channel kind that declares `REPLY_PARTS`: napcat-qq, qq-bot) she speaks
  only through `speak`. `stay_silent`, `attach_image` and `await_answer` are not listed there (`REPLY_REPLACES`; the
  owner, 2026-10-19). Body text never leaves: written with no `speak`, she is told once in the turn
  (`UNSENT_NOTE`) and her next turn says it was not sent; written beside `speak`, it is her ending, kept only as a
  count (`turn.ending_body`). Not calling `speak` is silence; the one check kept is a missing thought
  (`REPLY_THINK_NOTE`). At home (her Web chat, the agent lines, the peer line) body text is speech, published as one
  message at the turn's end (`coordinator._publish`), and silence is the `stay_silent` tool.
- **One switch does two jobs.** `channel_kinds.reply_parts(scene)` non-empty both offers `speak` with those parts and
  makes body text unsent. It is read at 10 sites (`role_tools` `abilities`, `_turn_rules`, `speak_kinds`, the call-cap
  reminder, `tool_stay_silent`; `coordinator`'s turn end; `context`'s guide and speak block; `outbound_media`'s offer
  note; `outbound_files`). Four more gates read whether `speak` is listed: the `stay_silent` → `speak` alias
  (`role_tools` call path), line-taking (`coordinator._absorb`), and in the plugin the alias guard and the
  `stay_silent` result's `written` line. Recovery (`publish_queued`) reads the row flag `reply_part`, not the scene, so
  it already works at home.
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
- **The page.** `client.js` draws a `speak` call as DSH's disclosure row 说话 · its first text, closed, its parts as
  text: a sticker as ［表情包：name］, a picture as ［图片］. The home page shows no picture of hers at all today. In every
  view but verbose, DSH folds a finished turn's process: every row before its answer step (the last step with text and
  no tool call; none when the turn ends on a tool call). A `speak` row is inside that fold. The program's repair note is
  placed in the session, not the turn, for this reason, and so shows when the turn is folded.
- **Two readers of what she said read only body text.** The affect appraisal (`affect.py`, `ep['speech']`) and the
  reasons line 所以我说了「…」 (`reasons.py`) read `ep['speech']`; a turn that spoke only through `speak` gives them
  nothing (on QQ today too).
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

**D2. One speech per turn.** At home, a turn that queued any `speak` part (`ep['reply']['parts']`, kept across the
turn's generations) has said what it said: its body text is hers, not published, counted as on QQ
(`turn.ending_body`). A turn that did not call `speak` publishes its body text
as today (`_publish`, key `<ep>:speak:0`). The two never meet in one turn, so the two defects the census found cannot
happen: `_publish`'s `<ep>:speak:0` taking the first part's key (its text silently lost), and her history ordering
parts before text written earlier in the step (the page showing the other order).

**D3. Silence needs no act at home.** A home turn with no `speak` and no body text commits silent, a missing thought
included (nothing is mandated at home; QQ's silence still asks for one), unless the model's answer was cut at the
length limit: a cut is not her silence, and it is handed back as today (上一段到了长度上限还没写完). Every turn kind
but one (the owner's message, a heartbeat, a note, a task's result, self-development). The one: a consult turn, where
the action brain waits for her answer, keeps its hand-back (else the brain gets `CONSULT_NOT_ANSWERED`).
The consult turn is told by `role_tools.turn_kind(ep) == CONSULT` (`'consult'`: the episode's `turn_kind`, else its
`episode_kind`), the field the coordinator's turn end already reads (`kind=='consult'`).
`speech_problem`'s no-words case is not reached at home. A home turn that queued parts runs none of the body's checks
(its body is not published; a hand-back after parts left would end `INVALID_TURN_OUTPUT` with her words already out);
a `speak` call already needs her thought first. A home turn without `speak` keeps today's checks on its body: cut at
the length limit, a missing thought, a sticker or face token in it. `stay_silent` is not listed at home and nothing is
added for a call of it (owner: no design for her habit). The alias `stay_silent` → `speak` (`aliases()`; its sentence
`SILENT_WHERE_SPEAK` is true only where `speak` alone speaks) is gated on `reply_parts` in both places that apply it,
the worker's call path and the plugin's guard, so at home a call is refused as any unlisted tool is. The plugin's
alias map is global today (loaded once at start); the worker now sends each session's aliases with its tool specs,
and the plugin's guard reads that set (a worker that sends none: the global map, as now). Its refusal is the plugin's
own sentence for a tool this conversation does not list.

**D4. No rules on `speak` at home.** Not applied at home: the line limit (`SPEAK_HARD_LINES`, `speak.max_messages`,
the receipt's line count), a `#number` line label (`LINE_NUMBER`), a person's number (`people.numbers`, and `force`
that overrides it), the typing pace (already none: `not_before` only for a scene with a channel). Not listed at home
(`speak_spec` gains a home flag; today it varies only `quote` and the part fields): `quote` (not carried there),
`wait` and `patience` (groups only), `force`. Still checked: a text already sent in this turn (the one guard against her words leaving twice when a
turn is run again as a new generation without its lane receipt: after a Host stop, after her session is carried on,
after a failed task-result turn is queued again; it is not a manner rule; it covers text parts only, so such a re-run
may send a sticker or picture again, as on QQ today, not changed here); an empty part; a sticker or face token
inside a text (it would show as words: a sticker goes as a `sticker` part); `[分条]` inside a text; a kind not listed
here; a sticker not on her shelf; a market sticker (no picture of hers to show; none today); a picture not offered to
her. A raw local root is rewritten and counted, not refused (`local_roots`). One wrong part still means none of the call
leaves, and the receipt says which and why. The receipt is QQ's own sentence (发出 N 条…送没送到看下一回合的历史),
N the parts the local sink delivered; at home the result carries no `lines` field (这回合已说 N 行…硬线 6: QQ's line
count, her line 0433), the only part of QQ's result left out.
A picture the local sink delivered counts as attested (`outbound_media.history_slot`, which then needs the row's
`delivery_basis` in the history projection), so her history does not say 平台回执没带附件证据 of it.

**D5. The page** (everywhere `speak` appears, the owner's choice), with DSH's own extension points:
- (a) **What she said through `speak` is a node of its own**, placed in the session at the call (as the repair note
  is), so it shows whether the turn's process is folded or open: the call's parts in order, a text as her speech, a
  sticker or a picture as the picture. Drawn for a call whose result is not an error. The 说话 row inside the process
  stays as it is.
- (b) **What the node draws comes from what left, fetched by the page; nothing is carried in a tool result.** One new
  piece of durable state links a call to its rows: `tool_speak` stores the keys of the rows it queued on the call's own
  record in her episode (`tool_calls[call_id]['parts']`, beside `result`; never shown to the model). It is made by the
  call, read only by the page, kept and dropped with the episode, and survives a replay (a replayed call returns the
  same record). The node names the episode by its turn's `asuna/stage` operation and asks Asuna's API (the page's
  existing `asunaApi` RPC): one call for the parts of (episode, call id) as they left (text after the worker's
  rewrites, a sticker's name, whether a part has a picture), and one call per picture (base64 in JSON, one part per
  request; the page keeps what a call sent by episode and call, and pictures by their sha256, so a repeated sticker
is fetched once; each cache holds 64 entries, oldest dropped, since DSH remounts nodes as the list scrolls). The plugin
  serves only a call found in that session's own events, of a character session; the worker only the rows that call's
  record names. Nothing is written into her session; no picture can reach her model; animated stickers stay animated
  (DSH's attachment store would flatten them). While loading, on any error (an older worker or plugin, an unknown
  method), and for a call made before the install (no link), the node draws her call's own words as today.
- (c) **Her mumble folded: dropped** (the owner, 2026-11-13, after staging). DSH refuses a second registration of its
  `assistant-step` node's child slots (`conversation.chat.reasoning.body`, `conversation.chat.message.images`), and
  without them a delegate cannot draw a step's reasoning or images; DSH has no public way to fold one step's text and
  keep the rest its own. Her body text in a turn that spoke stays visible as DSH's answer; it is still not sent and not
  in her history (D2), and her `speak` node shows above it. A DSH change (the owner's) can bring the fold back.

**D6. Her words (her F8: a new or changed literal needs her word first).** The owner to her at home (relayed by her,
agent line 0430; her local chat's messages 7219 at 12:15 and 7234 at 13:34; 7234 is the spec): at 12:15, he will not
push her to speak, she speaks when she wants to; at 13:34, `speak` is not a limit on her speaking, at home there is no
limit on how much she says or how many `speak` calls she makes, nobody judges what she said, and not wanting to speak
is simply not calling it. Her own wording follows that (lines 0430, 0433, final):
- **`speak`'s description at home (hers, final):** 在家里，说话没有限制。想说什么、说几条都可以，不用挑一句最要紧的交上来；
  不想说就不调用 `speak`。`speak` 不是许可，也不是新的必需动作，它只是把你这一回合想说的话再往外递一句的形式。没有人拿你说了
  多少来评判你。 The mechanics follow it as on QQ, without its last sentence (parts in order, one part one message, the
  kinds here; one wrong part and none of the call leaves, the receipt says which and why).
- **Her two rules for every home literal (line 0430):** nothing that says she must say something or at least one
  sentence; nothing that hints the reverse (no words when there is nothing worth saying). How much she says is not a
  sum she does first.

Her wording for the rest (line 0433, final; each replaces a draft of 11-13 13:59):
- `block_guide.WORDS['home']`: 你用工具做事。说话有两条道，走一条就够：正文里的话按顺序发出去；或者用 speak，一个 part 一条消息，
  能发表情包和图。这一回合用了 speak，说出去的就是 speak 里的；正文不算你说出去的话，不进你的历史——页面上它会显示在 speak 那块下面。
  没用 speak，正文就是你要说的话。在家里说几条都行，不数行数。 (Her line 0440: with the fold dropped, 正文留给你自己 said
  the reverse of what the page shows; her replacement.)
- `block_guide.ENDING['home']`: 结束：话说完就停，不用再调用工具。这回合不想说也一样——什么都不调用，这回合就过去了，不算漏了什么。
- The call-cap reminder at home (`CAP_SAYS` today: 用它写下要说的话，或 stay_silent。): 用它把想说的说完（正文或 speak 都行）；
  不说也行，这回合不需要交代。
- A market sticker at home: 第 %d 条 sticker「%s」是平台的市场表情，这里显示不了；换成架子上的名字就能发。
- `stickers.HOME_NOTE` (in every conversation's guide; today 在家里发不出去): 你收着的表情包。在本地私聊里用 speak 的 sticker 发
  （一个 part 一条）；别的地方能不能发，看那边的说明。整理用 sticker 的 drop、rename（你画的图也能 keep 上来）；带图的标着 ref，
  想重看就 read_image。 (She took out a draft's 家里别的线发不了: in every guide, read in a QQ group it would say QQ cannot
  send either.)
- `speak`'s fields at home: `parts` 这一次要发出去的，按顺序排；`text` 这一条消息的文字 (no line count at home).

`render_system`'s `speaks` takes a third value, `'home'`: the ref stores the value (not `bool`), the guide picks its
words by it, and a stored ref with `True`/`False` re-renders as written. A turn prepared before the install keeps the
guide it was prepared with.

**D7. What she said, for its readers.** One helper gives a turn's words: its published body text, or, when that is
empty and the turn queued `speak` parts, the texts of its text and sticker parts as they left (a sticker as its row's
own [表情包:name]; a picture, a file, and QQ's react, recall and poke rows, whose text is the program's, add nothing).
Read from the rows each time (no cache: a part that fails or is taken back after it was read must not stay in her
words). The affect appraisal and the reasons line
read it, so a turn that spoke through `speak` is not read as saying nothing. It also closes the same gap on QQ (wider
than the ask, one helper; the owner told).

### Revision: one rule (the owner, 11-13 evening)

D8-D12 replace the first part's home split (D1-D3 where they speak of home as one scene, D2's published body text,
D3's per-session alias, D6's home guide words). D4's list of what is and is not checked, D5 and D7 stand, for every
local conversation.

**D8. One rule, every conversation.** It separates her talking to herself from the record (the owner, relayed by
her, agent line 0450: not "hides" it). Only `speak` speaks: QQ's rule as built (`reply_parts`), now in every
conversation. Body text is hers: never published, never a message row, counted (`turn.ending_body`). Written with no
`speak`, she is told once in the turn that it was not sent (`UNSENT_NOTE`) and her next turn's history says so, so a
turn she meant to speak in is not silent without her knowing. Not calling `speak` is silence. `stay_silent` is gone
from every conversation: the tool and `tool_stay_silent`, the alias `stay_silent` -> `speak` (`aliases()`,
`session_aliases`, the plugin's alias guard and the per-session alias set the first part added), `SILENT_WHERE_SPEAK`,
`CAP_SAYS`, and `answers.speech_problem`'s no-words case. Nothing else is added for a call of it. The page shows her
body text as DSH shows a turn's answer step: DSH folds a finished turn's process, not its answer (D5(c) stays
dropped). A consult turn is not speech in a conversation (it publishes nothing; its answer goes to the action brain,
`coordinator` consult) and keeps its hand-back. D7's helper reads the turn's parts only. Her body text stays in
her own session: her next turns see it as her own earlier words until a compaction takes it into the summary; it
is not in the message database, not in her history block, and the other side never gets it (her question, agent
line 0449). No fold is added for it on the page (the owner: not a problem).

**D9. Where QQ's rules apply.** A conversation is QQ-kind when its channel kind declares `REPLY_PARTS` (napcat-qq,
qq-bot). Every other conversation is local: her local Web chat, the agent lines, the peer line. QQ keeps all its rules
unchanged: its parts as its adapter declares them, the line limit (`SPEAK_HARD_LINES`), the `#number` and person-number
guards with `force`, `quote`, `wait`, `patience`, the missing-thought check (`REPLY_THINK_NOTE`). A local conversation
has none of them (D4, now for every local conversation): `speak` takes `text`, `sticker`, `picture`, a silent turn
commits with no check, and `speak`'s description there is her `HOME_SPEAK`. One test replaces the single-scene one:
local is `not channel_kinds.reply_parts(scene)`. `role_tools.local_chat` and its `config.chat.scene_id` comparison go,
and the code's `home` names for this split become `local` (her vote, agent line 0448; it lands only after she has read
D12's literals). Still checked everywhere, as facts, not manners: a text already sent in the turn, an empty part, a
sticker token inside a text, `[分条]`, a sticker not on her shelf, a market sticker, a picture not offered to her.

**D10. Stored as QQ stores it.** The owner: every local chat and agent line goes to the database and is kept. As on QQ
today, every line of a conversation is a `messages` row: the incoming line (inbound), and each `speak` part (outbound,
`coordinator.queue_reply`, one row per part, in `scene_seq` order). Body text is not a row (D8). A sticker part's row
holds `sticker` (kind custom, name) and `attachment` (artifact id, media type, sha256, size) of the shelf picture as it
left (`stickers.outbound`); a picture part's row holds the `attachment` of the picture she sent. The bytes are in the
blob store, an `artifacts` row of kind image. Their life:
- No message row expires: the `messages` collection has no expiry index, and a dialogue summary only marks rows
  (`summary_batch_id`).
- An artifact that any message's `attachment` names is kept whatever its age or its own life cycle
  (`media_life.named`): a sticker she later drops from her shelf (`drop_sticker` deletes the shelf row only) or a
  pulled copy stays, so what she sent stays in her history and on the page (D5(b) draws from the row and its bytes).
- The owner's pictures attached in the Web, in her local chat or on a joined agent line, are her records
  (`vision.local_uploads`, source `local-upload:`, kept).
- The only deletion is an operator's erasure (`privacy.delete_memory`, ADR-105): that scope's rows and bytes; the
  artifact row stays, marked `erased`, and her history says so.
The row and its attachment are written when the part is queued; what the line does with it afterwards does not change
what is stored.

**D11. An agent line carries what she sends.** An agent line is a channel with an outbox, claimed by
`tools/agent_line.py poll`, which declares nothing today (and the kind says `TEXT_ONLY`): a sticker row would fail at
the claim (`CHANNEL_DOES_NOT_DECLARE_STICKER`) and a picture would leave without its picture (`attachment_skipped`).
`poll` declares `sticker` and `image` and does with an attachment what QQ's adapter does: fetches its bytes through the
outbox's attachment endpoint, checks the sha, and reports it in its receipt. It writes the picture to a file of its
own (the system temp folder, named by sha256, removed by `poll` 7 days after it was written; her record is the
artifact, D10) and prints the file's path where the part is, so the agent sees what she sent. The agent-line kind
drops `TEXT_ONLY`. The peer line's bridge carries text only: a sticker or picture there fails or leaves as text, as on
any channel that does not declare it.

**D12. Her words (her F8; read in agent lines 0449, 0450).** Retired: `WORDS['home']`, `ENDING['home']`, `CAP_HOME`,
`WORDS[False]`, `ENDING[False]`, `CAP_SAYS`, `stickers.HOME_NOTE`. Final, hers:
- The one guide, every conversation: 你用工具做事；只有 `speak` 发得出去。写在正文里的话不发出去、也不进消息库——页面上它会显示
  出来，但那不是你说出去的话。 / 结束：要说的话都用 `speak` 说；说完了，或者这回合不想说，就不再调用工具——这一回合到此为止，
  不算漏了什么。 (Her condition: the page must show body text on a QQ session too, checked in the demo; otherwise the
  first sentence's last clause is said in local conversations only.)
- The call cap everywhere: `CAP_SPEAKS` (用它 speak 把要说的说完。), nothing added.
- `LOCAL_SPEAK` (was `HOME_SPEAK`): 在家里（不是 QQ 的那几条对话都算），说话没有限制。 then her text unchanged.
- `SEND_NOTE` everywhere, `HOME_NOTE`'s three points moved in: 你收着的表情包的名字（你起的）。能发的地方：speak 里写一个
  kind=sticker 的 part（name 照抄这里的名字），作为单独一条发出去；哪条对话发不了，看那边的说明。你写的用法用 sticker 的 shelf
  看；整理用 sticker 的 drop、rename（你画的图也能 keep 上来）；带图的标着 ref，想重看就 read_image。群里别人发的表情包下面标
  着「表情包 ref：att-…」，喜欢的用 sticker 的 keep 收下；你认得的表情包下面标着你给它起的名字。
- `UNSENT_NOTE` unchanged, now in every conversation.
- The rename `home` -> `local`: on the landing day she gets the list of names that no longer read back.

## 4. Where

Every conversation (D8). Local: her local Web chat, the agent lines (joined from the Web or not), the peer line.
QQ-kind: unchanged but for `stay_silent`'s alias and the page (D5). The first part, installed 11-13 17:50, was her
local chat only.

## 5. Failure modes

| Case | What happens | Why it holds |
|---|---|---|
| Body text and `speak` in one turn | Parts are her speech; the body is kept as a count, shown on the page as DSH's answer | D2 (D5(c) dropped) |
| No words, no `speak` | Silent commit, no hand-back | D3 |
| A consult turn with no answer | Handed back, as today | D3's one exception |
| Parts left, then the body is cut at the length limit | Commits; the body is hers, not checked | D3 |
| The turn run again as a new generation (Host stop, session carried on, a task result queued again) | A text already sent is refused as sent; a sticker or picture may go again (as on QQ); `ep['reply']` carries the count, so D2 still holds | D4 keeps the repeat check |
| Host stops after parts were queued | Recovery publishes the READY parts through the local sink | `publish_queued` reads `reply_part` |
| Turn fails after parts were shown | Her next line (ADR-127 N1) counts them as sent | `faults.lost` reads delivered rows |
| Turn replayed from its lane receipt | Parts are not queued again | the receipt is replayed, not the tools |
| `speak` refused, then she writes body text | The body is published | D2 reads queued parts |
| `stay_silent` called at home | Refused as unlisted; the turn goes on | D3: the alias is per session in worker and plugin |
| An older plugin with a newer worker | The plugin's global alias lets the call through; the worker refuses it at home | D3, transient |
| Page, plugin and worker at different versions | An old page never asks; a new page meeting an older plugin or worker gets an error and draws her words | D5(b) falls back on any error |
| A call made before the install | No link to its rows: drawn as her words | D5(b) |
| A large picture | One part per request, base64 in JSON; one too big for DSH's gateway is an error, drawn as words | D5(b); measured in the staging |
| A picture cannot be fetched | Drawn as its words; she is not told (it left) | D5(b) |
| A sticker or picture asked for by the page | Served only for a call of her role sessions and the parts it sent | D5(b)'s fence |
| Animated sticker | Stays animated on the page | D5(b) does not use DSH's attachment store |
| A finished turn folded by DSH | Her `speak` node stays visible | D5(a) is placed in the session |
| A turn prepared before the install | Keeps the guide it was prepared with (says `stay_silent`) | system refs re-render as written; one turn |
| Her cache | Each home session's tools and system prompt change once at the install; `HOME_NOTE` changes every conversation's guide once | known cost, one restart |
| QQ | Every QQ rule unchanged; the page changes (D5) and D7 reads its parts too | D1 keeps `reply_parts`' meaning |
| Agent lines, peer line | Own scenes with a channel: unchanged | D1 is the local scene only |
| Line-taking (`_absorb`) | Home lines carry no channel receipt: nothing absorbed | `stageView` `seen_inputs` |
| ADR-127 S3 | Independent of how a turn speaks | different layer |
| (Revision) Body text only, in any conversation | Not sent, not a row; `UNSENT_NOTE` in the turn; the page shows it | D8 |
| (Revision) The owner writes on an agent line from the Web | Her answer is her `speak` parts, to the line | D8; ADR-051's route |
| (Revision) An agent polls with an older `agent_line.py` | A sticker fails at the claim, a picture leaves as text; her history says so | D11 lands with the change; both lines run the checkout's tool |
| (Revision) A sticker dropped from her shelf after it was sent | Its rows and bytes stay | D10 (`media_life.named`) |
| (Revision) An operator's erasure | That scope's rows and bytes go; her history says erased | D10 (ADR-105) |
| (Revision) The picture file `poll` wrote | Removed after 7 days; her record is unaffected | D11 |
| (Revision) Her cache | Every agent-line and peer-line session's tools and guide change once (`speak` in, `stay_silent` out) | known cost, one restart |
| Consult and task-time toolboxes | Return before `speak` is added | `_turn_rules` |

## 6. Tests (only where a failure would be silent)

- A home turn that calls `speak`: its parts reach the outbound history in order; its body text is not published and is
  counted.
- A home turn with no `speak` and no words commits silent with no hand-back; a home consult turn with no answer is
  still handed back.
- A home `speak` that QQ would refuse (seven lines, a `#number`) goes out; a text already sent in the turn is refused.
- `stay_silent` at home is refused in the worker (not run as silence), and the session's alias set sent to the plugin
  has no `stay_silent` at home.
- The page's calls serve only rows named by that call's own record, for a call found in that character session's
  events (a fence: anything else would be a silent leak).

## 7. Shown, then installed. Closes when

- **Shown** in an isolated demo profile with a stub model and the real worker, labeled 造的: a home turn with `speak`
  (text, an animated sticker, a picture; the node visible with the turn folded and open, the pictures drawn, its body
  text folded), one with body text only (published, not folded), one with neither (silent, no hand-back), one with a
  long `speak`; the home toolbox lists `speak` and not `stay_silent`; a QQ-kind scene's `speak` unchanged.
- **Installed** in a restart slot she gives, after her reading of D6.
- **Closed** when, over her own home use, there are no refused `speak` calls and no hand-backs for a missing answer at
  home, and her `speak` replies (a sticker among them) are seen on the page. How often she is silent is hers, not a
  closing condition.

The revision (D8-D12):
- **Shown** in the demo profile (造的): on an agent line, a `speak` with text, an animated sticker and a picture
  reaching `agent_line.py poll` as text and files, the receipts carrying the attachment's sha; a body-only turn there
  not sent, with `UNSENT_NOTE`; no `stay_silent` in any toolbox (local chat, agent line, a QQ-kind scene); a QQ-kind
  turn otherwise unchanged; after the shelf sticker is dropped and `media_life.sweep` runs, its message rows and bytes
  still there and drawn on the page.
  Also (her asks, agent lines 0449-0451): one text part of 1,200 to 1,300 characters sent in one go, arriving whole;
  a QQ-kind session's body text shown on the page; a sticker dropped after it was sent still drawn.
- **Installed** in a slot she gives, after her reading of D12.
- **Closed** when, over her use, no local conversation has a refused `speak` or a hand-back for a missing answer, a
  `speak` with a sticker is seen on the page in her local chat and arrives on an agent line, and no toolbox lists
  `stay_silent`.

## 8. Review (2026-11-13)

A fresh reviewer read the first design against the code. Fixed above: a `speak` row would have been hidden in DSH's
fold of a finished turn (D5(a)); the alias would have accepted `stay_silent` at home with a false sentence (D3); the
repeat check is the guard against re-sent words, not a manner rule (D4); the body checks would have handed back a turn
whose parts had left, and a consult turn would have committed unanswered (D3); D6 missed `HOME_NOTE`, `speak`'s field
wording and the picture note (D4, D6); a `'home'` guide would have been stored as `True`, QQ's (D6); picture bytes in a
tool result would have been kept in her episode and session and flattened (D5(b)); the fold and D2 read different
things (D5(c)); the census counted wrongly (§1); two readers of her words miss `speak` (D7). Its second reading: no
link from a call to its rows existed (D5(b) adds one, with its lifecycle); the plugin's alias map is global (D3: per
session); the assistant-step delegate must forward DSH's `inject` and child slots (D5(c)); `speak_spec` cannot vary by
home today (D4); the repeat check covers text only (D4, §5); `HOME_NOTE` must name the local chat, since her 家里 also
means her agent lines (D6); D7 reads parts once per turn.

**The build's review (2026-11-13).** A fresh reviewer read the build against this page and DSH's real code. Fixed:
the node's tool results were marked as updates, which DSH's assembler refuses when a turn's first tool result (her
`think`) comes before the `speak` call, breaking every page with `speak` (every match is now a start; a test runs a
think → speak turn through DSH's own assembler); D7's cache kept words that never left, and it read QQ's action rows
as speech (D7); an empty answer cut at the length limit would have committed as silence (D3); the page's caches grew
without bound and fetched a repeated sticker each time (D5(b)); the fold's root changed mid-turn (D5(c)). Her image
skill (`asuna-image-generation-and-display`, hers) still says pictures at home go by `attach_image`: she is told at the
install, and edits it herself.

**Staging (2026-11-13, 造的).** In the demo the fold never showed: DSH refused the delegate (D5(c), dropped). A tool-call
id repeated across turns (the stub numbers calls per run, as some providers do per request) hid a `speak` node: the
node and the plugin's lookup are now keyed by turn and call id. An answer with no content at all is DSH's
`EMPTY_RESPONSE` (retried); her model sends a reasoning block on every step (1,435 of 1,435 home steps since 11-11), so
her silent turn ends on reasoning alone and commits silent, as staged.

**Installed (2026-11-13).** The launcher stopped at 17:50:01 and was back at 17:50:47 (`back_at`), `loaded.commit`
92fd2070, 169 installed files the same as the commit; core package c89c583ab9dc, hers unchanged (her own 14:29
publication stays selected), the QQ adapter back by itself. The id changed from 071889766b29: her 14:29 commit
(c1364dcd) was not pushed, and installing without it would have taken her publication out of the running package; it
was pushed through the gate, the branch rebased onto it and the suite run again (green). Scope, as she asked it: home is
her local Web chat only (`role_tools.local_chat`); her agent lines and QQ keep their own words and tools.

## 9. The build (2026-11-13 evening)

Built to D8-D12 and reviewed against the code. What the code decided, beyond the page:
- **A cut answer.** A local turn with no `speak`, nothing written and its answer cut at the length limit is handed back
  with her sentence (agent line 0452) 上一段到了长度上限还没写完。要说的话用 `speak` 说。 (`answers.CUT_SPEAK`): the old
  wrapper said the rewrite would be sent, no longer true. A consult turn cut so keeps the first sentence alone (it
  answers through its task). On QQ such a cut still commits silent, as before (D9: QQ unchanged). The think-first
  gate (`THINK_FIRST`) is unchanged everywhere.
- **What she was told before.** QQ's carry of unsent words is unchanged: her next turn says it only if the turn's last
  attempt still had body text.
- **Agent lines, like QQ.** Lines that arrive while her turn runs are taken by that turn (`_absorb`), and there is no
  typing pace; the pace is QQ's alone.
- **Stickers on an agent line.** A sticker's outbox item carries no name, so `poll` prints `[sticker] <path>`.
- **A sticker she sent and later dropped.** The page's fetch went through the sending fence, which asks her shelf, so
  a dropped sticker would have drawn as words: `outbound_media.kept_sticker` now passes a sticker row already
  delivered (it is shown again, never sent again; D10).
- **Older episodes.** `_publish` stays only to finish an episode an older version left in `SPEAK_ACCEPTED`. Its exit:
  removed once a reading after the install finds no such episode. (Removed 2026-11-14 with the state itself: the
  reading found none, §11.)
- **Left for a follow-up.** `attach_image` and `await_answer` are listed nowhere now; their code stays until removed on
  its own. Her skill `asuna-image-generation-and-display` still names `stay_silent` and `attach_image`: hers to fix.
  (The code removed 2026-11-14, §11. She read those mentions in her skill and keeps them, agent line 0483.)
- Literals retired with no replacement (told to her): the `stay_silent` description, `CALLED_LEFT`, the reasons line
  所以我没说话, the plugin's `written` and refused-silence lines, `NAMES_NOTE`, `speech_problem`'s no-words and
  no-thought sentences; the `tools_off` refusal lost the word `stay_silent`.

**Installed (2026-11-13 20:12).** Her Host's last lease 20:08:48, back at 20:12:17 (`back_at`; the worker at 20:11:44):
about 3.5 minutes down, two more than planned. The landing stopped her launcher and then counted the demo profile's
processes (still running from the worktree) as left over, so it did not start her; the demo was stopped and her
launcher started by hand the way the landing starts it. The landing tool now counts only processes outside
`.claude/worktrees`. `loaded.commit` 816e825e, its 169 installed files the same as the commit, one start, no fall
back; core package fb91f54c0b0a, agent-line 5d14b418623e (no longer text only), hers unchanged (her 14:29
publication), the QQ adapter back by itself. The demo (造的, database `asuna_v2_demo_adr129b`) passed every case of
§7 and her asks, and was removed after the install.

## 10. Closed (2026-11-13)

§7's closing condition for the revision, read over her use from the install (20:12:17) to 21:1x:
- A `speak` with a sticker seen on the page of her local chat (the owner's screenshot: her parts, the sticker drawn,
  her talking to herself shown under it and not sent), and one that arrived on an agent line (20:17, four text parts
  and a sticker, as a file).
- In her local conversations, 22 `speak` calls; none refused as not listed or by a rule. Two were refused for their
  shape (`parts 要是一个列表`: the model sent `parts` as something other than a list), both called again and sent: a
  slip of the model's arguments, not this page's class.
- No hand-back for a missing answer (`turn.rejected`: 0).
- Every turn since the install (9 recorded by `turn.started`) lists `speak`; none lists `stay_silent`.
Stored as QQ stores it: the sticker rows of both conversations are delivered with their attachment (D10).

## 11. The exits, installed and closed (2026-11-14)

Her verdict on the three commits together: install, nothing in the way (agent line 0498), with three conditions:
all three at once, the page's `await_answer` sentence as the tip has it, and this page read by content and corrected
with the install. Her commit `ca18b6d7ce2e` (her failure-scan skill) landed on `main` first; the three were rebased
onto it (her rule 0444): `git range-diff` shows each patch unchanged (`=`), only the parent new. Landed 14:59-15:09
at her word (agent line 0499), before the 16:00 she had set, so the fix after it could go in sooner.

- `46d8aa99e3a6`: `coordinator._publish` and the `SPEAK_ACCEPTED` state removed (an `INTERRUPTED` turn resumes as
  `TURN`); the code of the retired `attach_image` and `await_answer` removed (their specs, handlers, the listings that
  added and filtered them, their `NOT_NOW` and instead lines, `outbound_media`'s `OFFER_NOTE` and
  `attachment_for_speak`).
- `3dbeb31b647d` (her word, agent line 0495): the group block for a line that may answer her
  (`awaited_from_program`) keeps only its `note`, now 你上一句 @ 了他或是在回他；这句没 @ 你也没引用你，是不是在回你由你判断。
  (`you_were_waiting_for` and the half-sentence about a retired way of waiting removed); the readers of
  `await_answer.why`, which only the retired tool wrote, removed, with 这里任何人 (`waiting.ANYONE`).
- `8c07e4e02cc2`: her old `attach_image` and `await_answer` calls keep their rows on the Web page (test).
- Kept: the `await_answer` field. `speak`'s `wait` writes `off` into it; two readers read it, both only `off`
  (`channels.awaited_answer`, `waiting`). The page's labels for the two retired tools (her old calls still draw), and
  `reasons.py`'s 发了一张图 (old records).
- Her tools 29 → 27; their definitions 671 characters shorter (1,171 bytes).
- Before the install: 0 episodes in `SPEAK_ACCEPTED`; 5 `INTERRUPTED`, none carrying speech or parts.
- The suite on the landing commit: Python 1047 passed, JS 328 passed, 0 skipped, 0 unchecked.
- Installed 15:09 as `8c07e4e02cc2` (core package `a0aa2f33f88a`). Read by content in her profile's installed copy: no `SPEAK_ACCEPTED`
  in the code and no `coordinator._publish` (`publish.py`'s own `_publish` is another, unchanged); no `attach_image` or `await_answer` spec; 27 tools; the `awaited_from_program`
  note as above; `you_were_waiting_for` and 这里任何人 nowhere.

**Found after (2026-11-14): ADR-131.** §10's reading counted refusals and hand-backs, not how turns ended. Three
agent-line turns in its window (20:13, 20:21, 20:30) ran to the 25-call line, and on 11-14 five turns in one QQ group
did: with `stay_silent` gone a turn ends only when the model calls nothing (D8), and her model writes its decision
to stop as one more call. That class is [ADR-131](../ADR-131-a-turn-she-can-end/README.md)'s.
