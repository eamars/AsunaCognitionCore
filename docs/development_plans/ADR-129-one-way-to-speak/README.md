# ADR-129: One way to speak, at home too

Status: **Designed** 2026-11-13 (the owner's go after ADR-127 closed; nothing built), revised the same day on a fresh
review against the code (§8). Proposed the night before. Read by her the same day (agent line 0433): D6's literals are
hers. Next: the build on a branch, shown in a demo profile, then installed in a slot she gives (not with ADR-128).

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

**D3. Silence needs no act at home.** A home turn with no `speak` and no body text commits silent, in every turn kind
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
  request, cached on the page by episode, call and part, since DSH remounts nodes as the list scrolls). The plugin
  serves only a call found in that session's own events, of a character session; the worker only the rows that call's
  record names. Nothing is written into her session; no picture can reach her model; animated stickers stay animated
  (DSH's attachment store would flatten them). While loading, on any error (an older worker or plugin, an unknown
  method), and for a call made before the install (no link), the node draws her call's own words as today.
- (c) **Her mumble is folded.** In a turn with a `speak` result that is not an error, the text of her steps is drawn
  closed under a row of its own (DSH's `DisclosureRow`), through a delegate of DSH's `assistant-step` node registered
  as the turn-trigger and max-tokens notices are (priority -1, DSH's shipped component for everything else). Unlike
  those, it forwards the shipped entry's `inject` and declares the same child slots (as the permission picker
  forwards its own), takes out only `text` blocks (DSH's `reasoning`, `tool-call` and `image` blocks stay DSH's), and
  draws its row only outside DSH's reasoning group. ADR-007
  forbids taking `assistant-step` over globally (every DSH assistant becoming her); a delegate that changes only her
  turns that spoke keeps that rule, and the comment in `client.js` says so. The mark is the page's own turn data from
  the session's events, as `asuna-stage-finish` is; nothing is added on the plugin's side.

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
  能发表情包和图。这一回合用了 speak，说出去的就是 speak 里的，正文留给你自己；没用 speak，正文就是你要说的话。在家里说几条都行，
  不数行数。
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
empty and the turn queued `speak` parts, the texts of those parts as they left (a sticker as its row's own
[表情包:name]; a picture adds nothing). Read once per turn, not per thought. The affect appraisal and the reasons line
read it, so a turn that spoke through `speak` is not read as saying nothing. It also closes the same gap on QQ (wider
than the ask, one helper; the owner told).

## 4. Where

Her local Web chat: the scene `config.chat.scene_id`, every DSH session bound to it. Unchanged: the agent lines
(joined from the Web or not) and the peer line keep body-text speech and `stay_silent`; QQ keeps everything but the
page (D5).

## 5. Failure modes

| Case | What happens | Why it holds |
|---|---|---|
| Body text and `speak` in one turn | Parts are her speech; the body is kept as a count and drawn folded | D2, D5(c) |
| No words, no `speak` | Silent commit, no hand-back | D3 |
| A consult turn with no answer | Handed back, as today | D3's one exception |
| Parts left, then the body is cut at the length limit | Commits; the body is hers, not checked | D3 |
| The turn run again as a new generation (Host stop, session carried on, a task result queued again) | A text already sent is refused as sent; a sticker or picture may go again (as on QQ); `ep['reply']` carries the count, so D2 still holds | D4 keeps the repeat check |
| Host stops after parts were queued | Recovery publishes the READY parts through the local sink | `publish_queued` reads `reply_part` |
| Turn fails after parts were shown | Her next line (ADR-127 N1) counts them as sent | `faults.lost` reads delivered rows |
| Turn replayed from its lane receipt | Parts are not queued again | the receipt is replayed, not the tools |
| `speak` refused, then she writes body text | The body is published and not folded | D2 reads queued parts; D5 marks non-error results |
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
