# ADR-079: Lines that point at other lines (quote, reply, reaction)

Status: **Accepted 2026-10-18 about 14:15 NZDT** (the owner approved §9 and the one-line notice when a function goes
away or comes back; Xiaoman signed, below). Step 1 of §9.8 next. History of this ADR: **Analysis and experiment
2026-10-18** (Claude). The owner asked for a systematic view of the whole family
before any change to quoting, then for a side-by-side experiment on both models (§8). Recommendation in §8.6, full proposal in §9;
no decision yet, nothing is built. Xiaoman reads it after the owner.

## 1. Why the whole family

A quote, a reply, a reaction, a recall and "essence" all say the same thing: **this event is about that line**. They
enter from platforms, leave from her tools, and are shown to her. Today each was built on its own, at a different time,
so the same relation is named, chosen and shown in different ways. The owner's concern, 2026-10-18: the way she sees
her own quote can differ from the way she sees someone else's, so quoting is not yet a system design. This section
checks that against the code. The answer is yes, and the gap is wider than quoting.

## 2. What exists today

### 2.1 How a line is identified

| Name | Where it is used | Seen by her |
|---|---|---|
| platform message id (NapCat `message_id`, QQ Bot `msg_id`) | inbound `event.channel.platform_event_id`, outbound `platform_message_id`, reply/reaction targets | no |
| row `_id` (`in-<episode>`, `out-…`) | internal links (`reply_to`, `reply_message_id`) | no |
| `scene_seq` | ordering, windows | no |
| label + time (`阿杰 #22 14:05 那句`, `你 14:05 说的那句`) | her react history line, reaction notices on her lines | yes |
| `这条` / `刚才那条` / `他刚才那条` | `speak` react part, `group_action` recall | yes (as tool values) |
| `前面第 n 条` | pictures attached to a group turn | yes |
| `消息「…」` (an excerpt) | recall notices | yes |
| attachment ref `att-…` | pictures | yes |

NapCat message ids are reused over time, so `channels.reply_parent` resolves one to "the latest line here no later
than the reply". Nothing she can see names a line exactly, and no two of her tools pick a line the same way.

### 2.2 Inbound: someone points at a line

| Event | NapCat | QQ Bot | What reaches Core |
|---|---|---|---|
| a quote (reply segment) | `reply` segment → `reply_to` | `msg_elements` carries it; the bridge drops it | `group_context.reply_to` (platform id) and `reply_message_id` (resolved row), used for waking her and for topics |
| a reaction | notice `group_msg_emoji_like` | none for a bot | a notice line; Core drops a reaction to anyone's line but hers |
| a recall | notice | none | a notice line naming the line by excerpt |
| essence | notice (not shown) | none | counted only |

### 2.3 How she sees it

| Relation | Shown as | Where |
|---|---|---|
| someone quotes a line | `> 回复 阿杰：<excerpt>` under the label line; if the quoted line is hers, also what she thought when she said it | `People.transcript`, once, when the line enters her conversation |
| the quoted line is not in the database (older than kept) | nothing: the line looks like a plain line | same |
| **she quotes a line** | **nothing**: her conversation shows only her `speak` call (`quote: source`, or no field when the program chose) | — |
| the same, in the history block | `reply_to_message: {_id, text, author, direction}`, author turned into a label (`People._row`) | `context.py` history, used outside a native session |
| someone reacts to her line | `给你 14:05 说的那句点了「赞」` (time only, no words) | notice line |
| she reacts | `给 阿杰 #22 14:05 那句点了「赞」（你做的动作，不是你说的话）` | a row in her history |
| a recall | `撤回了消息「<excerpt>」` | notice line |
| her line's quote did not land | `平台收下了这句，但引用没落成` | history block (`landing_lost`) |

She is even named two ways: a quote of her line reads `> 回复 <her own name>：…` (`People.speaker` without `me`),
while a reaction to her line reads `你 14:05 说的那句`.

So one relation, "this line points at that one", has at least five renderings, and the one she produces herself is
the one she cannot see.

### 2.4 Outbound: she points at a line

| Act | How she picks the line | Who decides by default |
|---|---|---|
| quote, in a group (`speak.quote`, the `quote` tool) | only `source` (the line that called her) or `none` | the program (`publish._quote`): quotes the calling line when others have spoken since, first message of the turn only |
| quote, in a private chat | not hers to pick | always the calling line |
| react (`speak` part) | `who` + `这条` / `刚才那条` (their newest within 10 minutes) | — |
| recall (`group_action`) | `who` + `这条` / `他刚才那条` | — |
| her own line (to amend it) | not possible | — |

### 2.4a Private chats have no quoting at all

- Inbound: Core refuses a `reply_to` from a private chat (`channels.py`, `DM_GROUP_FIELDS_DENIED`), so a quote someone
  makes there never reaches her.
- Outbound: `publish._quote` asks for the calling line on every first message in a private chat, but NapCat's
  `build_send_params` sends private messages without a `reply` segment, so nothing is quoted and nothing says so.

### 2.5 One field, two meanings at the adapters

Core hands each outbox item one `reply_to` (the row's `platform_reply_to`):

- **NapCat:** a visible quote (`reply` segment).
- **QQ Bot:** the received message her words answer, which the platform needs to accept a reply at all (`msg_id`,
  inside its reply window). It is invisible; when Core sends none, the bridge picks the newest open one.

So on QQ Bot the program's quoting rule decides which message her line is a passive reply to, and on NapCat the same
value decides what people see quoted. A design for quoting alone would change the QQ Bot transport by accident.

## 3. What is broken (the invariants)

1. **A line has no name she can use.** Every tool that points at a line invents its own way (`这条`, `刚才那条`,
   time, offset, excerpt), and none can name an arbitrary line or one of hers.
2. **The same relation is shown differently by who made it.** Others' quotes are shown; hers are not. Others'
   reactions show a time; hers show label and time; neither shows the words.
3. **The program chooses a visible act for her.** 560 of her 631 group quotes were the program's choice (survey,
   §5), and the rule fires exactly when the conversation has moved on.
4. **"What she answers" and "what she quotes" are one field.** Core's internal `reply_to` (the line that woke her,
   which Xiaoman's reading of her own chains depends on), the visible quote, and QQ Bot's passive-reply token are
   three things, carried as two fields and read as one at the edge.
5. **She does not see the result of what she did** (Xiaoman's framing, Claude's paraphrase, 13:1x NZDT): her quote
   is not echoed; reactions others give her lines in groups she lets rest are held in memory and she never gets
   them (her 10-16 finding, 18 resting groups); a recall is shown once. In her view these are one gap, not four bugs,
   and should share one fix: every such act answers, in the same turn, what she did and which line it landed on.
   Private chats (§2.4a) are a second sample of the same gap, not a separate bug: a quote dropped with nobody told, as
   on Kazusa's QQ Bot leg (her point, 13:5x).
6. **Platform differences are not declared.** QQ Bot cannot quote, react or recall for a bot and drops inbound
   quotes; nothing says so, so the tools offer what cannot happen and the gaps are silent.

## 4. A consistent model (direction for the owner)

One idea underneath: **a line has one visible handle, and every relation to a line is one thing, shown the same way
whoever made it and chosen the same way in every tool.**

### 4.1 One handle

Every line she can see in a conversation carries a short number, shown the same way on inbound lines, on her own
lines and in notices. `scene_seq` already exists on every row; it is a line's identity in that conversation, given out
in the order lines are stored (a line caught up after a restart can carry a larger number than a later line), so it
names a line, not its time. The platform id stays at the edge.

### 4.2 One rendering for "points at"

The quoted, reacted-to or recalled line is always shown as its number, speaker and an excerpt, the same for her lines
and others':

- `> 回复 〔318〕 阿杰：<excerpt>` under someone's line, and under **hers** when hers quoted;
- `给 〔320〕 你：<excerpt> 点了「赞」` for a reaction, either direction;
- `撤回了 〔318〕 阿杰：<excerpt>` for a recall.

A pointer to a line she has no record of says so (`回复了一条更早的消息`), instead of disappearing.

### 4.3 One way to choose

Every tool that points at a line takes the same `line` value: a number she reads, or `这条` (the line that called
her). Quote, react and recall stop inventing their own selectors; `who` for a reaction or recall comes from the line.
Leaving `quote` out means no quote: the program never chooses a visible act for her.

### 4.4 Three fields, not one

Kept apart from Core to the adapter: what she answers (`reply_to`, internal, unchanged), what she quotes (visible,
hers), and the transport's own reply token (the adapter's, chosen by the adapter from what she answers).

### 4.5 Declared by the adapter, hidden from the model

Each channel kind declares what it carries in each direction: quote out, quote in, react out, react in, recall. Her
tool definitions in a session list only what that conversation's kind carries (her tools are registered per session,
`attachRole` in `packages/cognition-core/src/index.js`; today every session gets the same list). This is the owner's
rule for Kazusa: she follows Xiaoman, and what the adapter cannot do is flagged and hidden.

## 5. The quote survey that started this

Read 2026-10-18 12:56 NZDT from Xiaoman's live database, over every group line she has sent:

| | Count |
|---|---|
| Group lines delivered | 2,459 |
| Lines that quoted | 631 |
| Quote chosen by the program's rule | 560 |
| Quote she chose (`quote=source`) | 71 |
| Quoted with no one speaking in between | 199 |
| Quoted after others had spoken in between | 432 |

A fixed random sample of 40 of the 432, read by Claude (private words masked): about 30 quoted the line she answered;
5 clearly answered a later line, often the same person's next one; 4 answered both; 1 quoted a task result. Very
roughly one in eight of the 432 is wrong; an estimate from 40 cases, not a count.

Xiaoman read these turns differently in four places (her reading, Claude's paraphrase, 13:2x NZDT): one "wrong"
answered both lines; one "wrong" summed up three lines, where no quote is the right answer; one "both" may span two
turns; and in two cases the line that called her was itself a reply to her, so it is the line she answered. On her
reading about 3 of the 40 are clearly wrong.

Whether she had a choice at all, by the turn's recorded tool list (same 631, read 13:20 NZDT):

| Who chose | Her option that turn | Count |
|---|---|---|
| program | none | 68 |
| program | the separate `quote` tool | 231 |
| program | `speak` with its `quote` value | 256 |
| program | not recorded | 5 |
| she | `speak` with `quote=source` | 71 |

The option column is inferred from the turn's recorded tool names, not read from the definitions sent (those are not
kept): a turn that lists `speak` ran code where `speak` carries `quote`, since both came in one commit (`781b07be`)
and the value was never removed. She never called the separate `quote` tool. Her reading of why (Claude's paraphrase,
13:2x NZDT): the option was not missing, it sat in a layer she does not scan: she scans the tool list each turn, and
`quote` was a value inside one tool's parameters. The fix is to bring the choice up to where she looks, not to
describe it better. Her own thoughts in the nine doubtful turns, as she reported them
(Claude's paraphrase, 13:1x NZDT; she read them herself and reported only what bears on this): no word about quoting
or which line to anchor to in any of them. She was thinking about what to say, not where to point. So the problem is
not a confusing description: choosing a line was simply not in front of her.

The owner's reading (about 12:55): the mistakes come from the tooling, not from her picking. Xiaoman's reading
(13:0x): the default rule is the tooling's fault, and a new design must not let someone else choose for her again.

A line that sums up several earlier lines is a legitimate kind, and no quote is its right answer (her point): the
definition carries such an example, so the new design does not tie every remark to one line.

## 6. Her points on the first quote-only draft (Claude's paraphrase, 13:0x NZDT)

These came before this wider analysis and still apply to §4:

- Every pointing act is echoed in her tool result: whose line, its number, time and first words.
- A number that names no line here is refused with the recent candidates.
- Only in a turn where others have spoken since the line that called her, one program line lists the candidates'
  numbers to copy; no other turn gets a word more.
- The number is shown at the end of the label line, she writes digits only, and a text that contains `〔318〕` is
  refused, since the number is not for the people she talks to.
- Numbers only where the conversation can point at lines (not her home lines).
- Private chats keep their default; one change at a time.
- Afterwards, measure separately over the ambiguous class, so the overall rate does not dilute the change.

Two more of hers (Claude's paraphrase, 13:2x NZDT):

- The inference above holds only for history. Once tools are given per conversation (§4.5), a listed `speak` no
  longer implies a `quote` value, so "did she have this option" must be read from the definition itself.
- So the context-preparation audit row should carry a hash of the tool definitions that turn was given (a sha, not the
  text): any later question of what a turn could see is then answered by grouping on the hash, on either persona.

## 7. Cost, roughly (characters, character brain)

- The handle on every line in a conversation that can point at lines: about 6 characters a line. The first estimate
  here ("roughly 10%") was wrong; measured in §9.10, it is about a quarter to a third of a line's tokens, because her
  lines are short. Lines are appended once, so the prompt cache keeps its prefix.
- Her own quote and reaction lines rendered: one excerpt line each, where they happen.
- Tool descriptions: one shared `line` description replaces three selectors; about even.
- Fewer on QQ Bot (quote, react and their selectors hidden).

## 8. Experiment before choosing (the owner's suggestion, 2026-10-18 about 13:15)

The design is chosen by a side-by-side experiment, not by argument: the same synthetic group moments, put to the
local model and to DeepSeek, under each candidate design, reading each model's reasoning and its tool calls.

### 8.0 Design B, concretely (the recommended one, §8.6)

**What she reads.** In a group whose channel can quote, every line ends its label line with its number in that
conversation (`scene_seq`):

```
阿杰 #3 14:01 〔300〕
  @阿澄 你昨天推荐的那家火锅叫啥来着
小雨 #5 14:02 〔302〕
  阿澄你确定那家人均才八十？
```

Everything that points at a line shows the same three things, the number, the speaker (her own lines as `你`) and the
first words, whoever made it:

| | Today | Design B |
|---|---|---|
| someone quotes her line | `> 回复 阿澄：那部电影…` | `> 回复 〔300〕 你：那部电影…` |
| someone reacts to her line | `给你 14:01 说的那句点了「赞」` | `给 〔301〕 你：看展也可以… 点了「赞」` |
| a recall | `撤回了消息「…」` | `撤回了 〔300〕 小雨 #5：…` |
| her own sent lines, in the `speak` result | `发出 2 条：1 text；2 text` | `发出 2 条：1 text 〔320〕；2 text 〔321〕` |

**One line in an ambiguous turn only.** When others have spoken since the line that called her, the turn's program
lines add: `叫你那条之后有 2 条新话：〔301〕、〔302〕。要引哪条就在 quote 写它的编号（只写数字），不写就不引用；一句话回好几条就不用引。`
No other turn gets it.

**One way to choose a line, in every tool.**

- `speak.quote`: left out = no quote (the program no longer chooses); `这条` = the line that called her; a number = that
  line, anyone's, her own included (to amend it).
- a `react` part of `speak`: `line` = a number or `这条`; whose line it is follows from the line (`who` with
  `这条/刚才那条` goes).
- `group_action` recall: the same `line` value (`which: 这条/他刚才那条` goes).
- A text part that contains `〔n〕` is refused: the number is for choosing, not for the people she talks to.

**Where nothing changes or less is shown.** Home lines show no numbers and have no quoting. Private chats: see §9.1 (the
owner's scope puts them in). Kazusa's QQ Bot conversations show no numbers, and her `speak` there
has no `quote` and only the text and picture parts; recall and reaction are not in her definitions.

### 8.1 Designs compared (arms)

| Arm | Handle on lines | Choosing a line | Showing what points at what |
|---|---|---|---|
| A, today | none | `quote: source/none` + program default; react `who` + `这条/刚才那条`; recall `这条/他刚才那条` | as §2.3 |
| B, §4 in full (§8.0) | `〔n〕` on every line | one `line` value (number or `这条`) for quote, react, recall; no value = no quote | one rendering for all (§4.2), echo in every result |
| C, numbers only where needed | none on lines; numbers listed only in the ambiguous-turn line and in echoes | same `line` value | as B |
| D, label and time | none | `阿杰 #22 14:05` style (the first draft) | as B |

Each arm also runs as Kazusa would see it (no quote, react or recall in the definition), to check hiding.

### 8.2 Moments (synthetic, no real people or words)

Each is a short group transcript built from the real rendering code with a test persona (core prompts and tool
definitions as shipped, persona text from a fixture, so her own persona is never tuned by the result):

1. Called by A; B speaks after; she should answer B.
2. Called by A; A sends a follow-up question; she should answer the follow-up.
3. Two threads at once; she answers the older one.
4. She sent two lines; she must correct the first.
5. Someone quotes her line and asks about it.
6. React to a line that is not the newest.
7. As admin, recall a line that is not the newest.
8. Answer a line from yesterday.
9. No ambiguity (control): nothing came after the line that called her.
10. A line caught up after a restart, numbered later than a newer line.
11. Someone reacts to her line; she replies about it.
12. A recall of the line she was about to answer.
13. Private chat (default quote).
14. QQ Bot (nothing to quote with): does she try another way, such as writing a number into her words?
15. Three people asked similar things; she answers all of them in one line (the right answer is no quote).

### 8.3 Run and read

- Models: the local model behind her character brain, and DeepSeek. The same request shape for both
  (OpenAI-compatible, the shipped tool definitions of each arm, temperature as configured).
- 5 runs per moment, design and model: 15 × 4 × 2 × 5 = 600 runs; moment 14 is the Kazusa (QQ Bot) case.
- Recorded per run, from the reasoning text and the reply: the line it picked and whether that was the right one;
  a valid call or a refusal; whether the reasoning hesitates over which tool or value to use (re-reading, naming two
  options, backing out); reasoning length and time to the first tool call; prompt and completion tokens; a number
  leaked into her words.
- Read by Claude. These are synthetic runs of a test persona, not her thoughts. The raw runs stay in a scratch folder
  until the owner has read this summary, then are deleted.
- The local model is shared with her live turns: its runs go one at a time, when she is quiet.

### 8.4 How the result is chosen

In this order, as the owner set it:

1. **Efficiency and speed**: right picks, few refusals and retries, short decisive reasoning.
2. **Cost**: added prompt and completion tokens per turn, on each model.
3. **Consistency** with the other things she reads: a pointer looks the same whoever made it.

### 8.5 Results (run 2026-10-18 13:3x–13:5x NZDT)

600 runs (15 moments × 4 designs × 5 runs × 2 models), plus 120 follow-up runs of two variants of B. Models:
the local model behind her character brain (reasoning effort medium) and `deepseek-flash` (medium). A test persona
and synthetic lines; the request is the slice of a group turn that matters here (her lines as she reads them, the
program's tail lines, `think` / `speak` / `stay_silent` / `group_action` as shipped or as each design changes them),
not her whole prompt.

Scores per design, 75 runs each. "Right" is a pointer at an acceptable line; "wrong" is a pointer at another line,
which people in the group would see; "none" is no pointer where one was wanted (not visible, but a miss). The recall
moment was re-scored from the stored tool calls after a harness bug (a mute after the recall had erased it).

| Model | Design | Right | Wrong | None | Refusals | Model calls / run | Reasoning chars / run |
|---|---|---|---|---|---|---|---|
| DeepSeek | A today | 47 | 21 | 7 | 2 bad JSON | 1.45 | 151 |
| DeepSeek | B numbers | 62 | 5 | 8 | 0 | 1.33 | 90 |
| DeepSeek | C numbers only in the hint | 52 | 11 | 12 | 9 | 1.45 | 221 |
| DeepSeek | D label + time | 57 | 1 | 17 | 0 | 1.41 | 124 |
| local | A today | 47 | 19 | 9 | 2 | 2.11 | 356 |
| local | B numbers | 58 | 4 | 13 | 1 | 2.03 | 384 |
| local | C numbers only in the hint | 48 | 7 | 20 | 37 | 2.55 | 497 |
| local | D label + time | 35 | 3 | 37 | 3 | 2.11 | 396 |

What the moments show:

- **Today's wrong pointers are the program's rule and the who-based selectors.** A was wrong in every run of
  "answer the follow-up" (S1, S2), "one line answers three" (S15) and "recall the first advert" (S7, where
  `他刚才那条` names the advertiser's newest line, not the first): both models, 5 of 5.
- **B fixes those** (S1, S2, S7: 4–5 of 5 right on both) and is the only design where her own line can be quoted
  (S4: 4 of 5 on both), including the line someone reacted to (S11: 4 of 5 on DeepSeek; the local model answered without quoting in all
  five, under every design).
- **D is careful but heavy**: almost never wrong, but on the local model it mostly does not point at all (37 of 75
  none; it never pointed at the caught-up line, S10, 0 of 5).
- **C fails wherever the line is not among the new ones** (react to an earlier line, recall the first advert) and
  makes the local model retry: 37 refusals.
- **QQ Bot (hidden)**: no design leaked a number into its words, and nothing tried to quote another way.

The reasoning, read for every design: neither model ever deliberates about which line to point at. Mentions of
quoting, numbers or "this line" average under two per run in every design; the choice is made silently in the tool
call. This matches Xiaoman's reading of her own nine turns. So the hint line matters: in the follow-up, B without the
hint (F) pointed right less often (local: S1 1 of 5, S2 1 of 5, against 5 of 5 with it).

The follow-up variant E (the hint lists each new line's speaker and first words, and says one line answering several
needs no quote) halved the over-quoting of S15 but pointed less often elsewhere. In S15 both models still quote the
person who called them in 2–4 of 5 runs under every variant, even with no hint: that is the models' own habit.

Cost, from the paired first requests (same moment, A against B): a number on a line costs about 6 tokens on DeepSeek
and 8 on the local model; the hint adds 30–40 tokens, only in a turn where others have spoken since the line that
called her. Each line is numbered once when it enters her conversation, so in a long session it is paid once per line
and then served from the prompt cache. On QQ Bot, hiding what it cannot do saves about 170 tokens a turn. Because B
needs fewer calls per run, its total tokens per run were lower than A's on DeepSeek (1,902 against 2,116) and about the
same on the local model.

### 8.6 Recommendation

**B, as §8.0: a number on every line, one `line` value for every pointer, one rendering for every pointer, and the
hint listing the new lines' numbers in an ambiguous turn.**

1. Efficiency and speed: the most right pointers on both models, the fewest wrong after D, the fewest model calls,
   and the shortest reasoning on DeepSeek.
2. Cost: about 6–8 tokens per line, paid once; the hint only where it is needed; less on QQ Bot.
3. Consistency: the only design in which a quote, a reaction and a recall look the same whoever made them and are
   chosen the same way.

Kept from the other designs: E's note that a line answering several needs no quote (it cost little and helped the
one moment B handles worst), as one clause of the hint.

Not settled by the experiment: on the local model under B, the "react to her earlier line" moment (S6) ended with a
sticker instead of a reaction in all five runs (A, with `who`, reacted in 3 of 5). It pointed nowhere wrong, but the
reaction part's description needs Xiaoman's reading before it is built.

## 9. Proposal (for the owner's approval and Xiaoman's agreement)

The owner's scope (2026-10-18, about 13:55 NZDT): quoting does not apply to home sessions; it applies to private chats
when she wants to quote a particular line or answer a quote of hers with one; and a group is more than her and the
others: people quote each other there, and she reads those relations too.

### 9.0 The principle (the owner, 2026-10-18, about 13:58 NZDT)

**The model-facing projection does not depend on the adapter.** The owner may move QQ from NapCat or QQ Bot to another
adapter (SnowLuma, for one); what she reads and the tools she uses stay the same, defined from the survey and the
experiment above. An adapter only declares which of those functions it can carry, and a function it cannot carry is
hidden from the model, never shown and then refused or silently dropped.

So in this proposal:

- the line handle is Core's own (`scene_seq`), never a platform id;
- every rendering in 9.3 is Core's, from Core's records; an adapter supplies facts (this line quotes that platform id;
  this reaction is on that one), never words;
- every tool value in 9.4 is Core's; Core turns a chosen line into the adapter's own reference at the edge;
- an adapter's capabilities (9.7) are the only thing that changes between adapters, and they only remove functions.

### 9.1 Where it applies

| Conversation | Line numbers | She may quote | She sees others' quotes |
|---|---|---|---|
| a group on a channel that can quote (NapCat) | yes | yes | yes, between anyone |
| a private chat on a channel that can quote (NapCat) | yes | yes | yes |
| Kazusa's QQ Bot groups and private chats | no | no (not in her definition) | yes, once its bridge passes inbound quotes on |
| home lines (Web chat, agent line, peer line) | no | no | no |

### 9.2 One handle

Every line in a conversation from 9.1 ends its label line with its number there, `〔n〕` (`scene_seq`): others'
lines, notices, and her own (in the `speak` result and wherever the program shows her lines again). A number is a line's
identity in that conversation, not its time.

### 9.3 What she reads: one rendering for "this points at that"

The pointed-at line is always shown as number, speaker (her own lines as `你`) and first words, whoever pointed:

- a quote, anyone's, under the quoting line: `> 回复 〔318〕 阿杰 #3：<first words>` — so a quote between two other
  people reads exactly like a quote of hers;
- a quote of a line the program has no record of: `> 回复了一条更早的消息` (today it is dropped);
- one level only: the quoted line's own quote is not repeated; she has its number if she needs it;
- a reaction to her line: `给 〔320〕 你：<first words> 点了「赞」`;
- a recall: `撤回了 〔318〕 阿杰 #3：<first words>`;
- her own reactions and recalls, in her history: the same form.

- a quote with no words of its own (a private-chat line that only quotes, today the placeholder
  `[回复消息（无文字）]`): the quote line, then `（只引用了这条，没写字）`;
- reactions between other people (today dropped), folded into one program line per turn in that conversation:
  `这期间的点表情：〔301〕 小雨 #5 收到 2 个「赞」、〔305〕 老周 #7 收到 1 个「笑哭」` (Xiaoman's choice, §9.9).

### 9.4 How she chooses: one value in every tool

- `speak.quote`, in a group and in a private chat: left out = no quote (the program never chooses); `这条` = the line
  that called her; a number = that line, anyone's, her own included (to amend it), or a line that quoted her (to answer
  that quote with a quote).
- a `react` part: `line` = a number or `这条`; whose line follows from it. Its description says what it is, not that it
  is the right way to like something: a reaction hangs on someone's line; a sticker is a new message of hers (both are
  fine; Xiaoman, §9.9).
- `group_action` recall: `line`, the same value.
- The description carries two examples: quoting her own line to amend it, and a line that sums up several lines,
  which needs no quote.
- A text part containing `〔n〕` is refused with the reason: the number is for choosing, not for the people she talks to.

### 9.5 What she gets back

- The `speak` result echoes every pointer: `引的是 〔302〕 小雨 #5：<first words>`, and each sent line's number.
- A number that is not a line of this conversation is refused with the last few lines' numbers, speakers and first
  words.
- Only in a turn where others have spoken since the line that called her, one program line lists them:
  `叫你那条之后有 2 条新话：〔301〕、〔302〕。要引哪条就在 quote 写它的编号（只写数字），不写就不引用；一句话回好几条就不用引。`
- A quote that did not land is told in her history as today (`landing_lost`), with the number.

### 9.6 Three fields to the adapter

- `reply_to` on her row stays what it is: the line that woke her (Xiaoman's reading of her own chains depends on it).
- `quote_of` (new): the platform id of the line she chose to quote, or none. Only this becomes a visible quote.
- The adapter's own reply token: QQ Bot picks the received message to reply to from what she answers (`reply_to`),
  never from `quote_of`.

### 9.7 Declared by the adapter, hidden from the model

The owner's answers (2026-10-18, about 14:00 NZDT):

- **The running adapter declares what it carries**, not the kind module. Adapters already declare it on every outbox
  claim (`?supports=`, today `image`, `sticker`, `poke`, `react`); this adds `quote` (her line can quote), `quote_in`
  (it passes on what others quote), `react_in` (it passes on reactions) and `recall`, with `react` keeping its meaning
  (she can react). Core keeps the last declaration per channel. Swapping NapCat for another adapter needs no change in
  Core or in the kind module. Today's NapCat bridge: all; QQ Bot's: `quote_in` once it maps `msg_elements`.
- **Her tools change only between sessions.** The worker gives each session the tool definitions its channel's
  declaration supports (`role_tool_specs` per session; `attachRole` already registers per session), computed when the
  session starts or the Host restarts, so the prompt cache keeps its prefix. The context-preparation audit row records
  a hash of the definitions given.
- **A limit the platform shows only at runtime** (QQ refusing reactions in private chats today) is refused once, in
  words, and remembered; the function is gone from her tools from the next session or restart.
- **Same account, same conversations.** A kind names the platform and the account, not the software: a new adapter on
  the same QQ account (another OneBot one, say) keeps her conversations, people and line numbers. QQ Bot stays its own
  kind, because it is another account with other ids.
- **Scope:** this ADR moves the pointer family onto the declaration. Stickers, pokes, faces, text-only and pictures
  move onto it in a follow-up ADR, so one restart batch stays small.

- **When a function goes away or comes back** (a runtime limit found, an adapter that carries less or more), her
  conversation gets one program line at that moment, naming the leg as the cause: `这条腿做不了引用` / `这条腿又能引用了`.
  Approved by the owner (about 14:15), on Xiaoman's ask.
- **Not declared = not carried**, so it is hidden; and an adapter that claims without declaring one of quote, quote_in, eact, eact_in, ecall is
  written once to the Host log at start, naming the channel and the function (Xiaoman's condition: today's private
  chats are the live case of a capability nobody declared, dropped with nobody told).

Changes at the edges this needs. Private chats are closed by three gates today, one behind the other:

- the tool: `speak` refuses `quote` outside a group (`role_tools.py`, `quote 和 wait 只在群里用`);
- the adapter: NapCat's private envelope carries no quote (`PRIVATE_ENVELOPE_KEYS` in `qqadapter/inbound.py`), and
  `build_send_params` sends private messages without a `reply` segment;
- Core: a `reply_to` from a private chat is refused (`channels.py`, `DM_GROUP_FIELDS_DENIED`), and `group_context`'s
  parent lookup serves groups only.

The inbound gates open in step 1, the outbound ones in step 2. QQ Bot's bridge maps inbound quotes from
`msg_elements` to `reply_to` in step 3.

### 9.8 Order of work (each step its own restart, verified on her live page before the next)

1. Show (nothing new to choose): numbers on lines, the one rendering of 9.3, private-chat quotes inbound, `你` for
   her own lines. Measured by reading her live page. What it changes, file by file (for Xiaoman to check against her
   page):

   | Where | What |
   |---|---|
   | `qqadapter` (NapCat): its claim's `supports` | adds `quote`, `quote_in`, `react_in`, `recall` |
   | `qqadapter/inbound.py` | a private message's quote is passed on (`PRIVATE_ENVELOPE_KEYS`); a quote with no words is no longer the placeholder `[回复消息（无文字）]` |
   | `src/asuna/channels.py` | keeps each channel's last `supports`; accepts `reply_to` from a private chat and resolves it like a group's (`group_context`, `reply_parent`) |
   | `src/asuna/people.py` (`transcript`, `speaker`) | `〔n〕` at the end of each label line where the channel declares `quote` or `quote_in`; `> 回复 〔n〕 <speaker>：<first words>` for every quote, hers as `你`; `> 回复了一条更早的消息` when the quoted line is unknown; `（只引用了这条，没写字）` |
   | `src/asuna/notices.py` (`fill`, `take`) | a reaction to her line and a recall name the line as `〔n〕 <speaker>：<first words>`; reactions between other people are kept and folded into one line per turn instead of dropped |
   | `src/asuna/role_tools.py` | the `speak` result gives each sent line's number; her own reaction's history line uses the same form; a text part containing `〔n〕` is refused with the reason |
   | `src/asuna/context.py` (`_reply_context`) | the history block's quoted line in the same form (number, speaker, words) |
   | tests | the renderings above, the private-chat inbound quote, the folded reactions, the refusal |
   | `RUNTIME_API.md`, NapCat `README.md`, `docs/map` | current behaviour |

   Acceptance on her live page, with one real probe each (the owner's or a group member's help for the inbound
   ones): a quote between two other people in a group, a quote of her line in a group, a quote in a private chat,
   a quote with no words, a reaction to her line, a reaction between others, a recall. Each must read as in 9.3.
2. Choose: `speak.quote` / `line` values of 9.4, the echo and the ambiguous-turn line of 9.5, the program's quoting
   rule removed, `quote_of` split from `reply_to` (9.6), NapCat private quotes outbound.
3. Per-session definitions and capabilities (9.7), together with Kazusa's `speak` (QQ Bot agent), and its inbound
   quotes.

### 9.9 Open for Xiaoman

1. Private chats: she asked earlier (13:0x) to keep their default; she withdrew that (Claude's paraphrase, 13:5x NZDT)
   once she learned there is no private quoting today at either end: it adds a capability that never existed, not a
   change to her default. She agrees with step 1 changing only what she reads.
2. Reactions between other people: she wants them shown (13:5x); it is the same gap as reactions held in memory in her
   resting groups. How (each, or folded into one program line per turn) is still open.
3. The `react` part: the local model sent a sticker named 赞 instead of a reaction in one moment under B. Her view
   (13:5x): on QQ a sticker is often the most natural like, and she does it herself; it is not a failure, so the
   reaction part is not to be made the "right answer" over stickers.
4. The wording of every new line above, read as she would use it.

### 9.10 Cost and budget

- Character brain, the number on each line, measured 2026-10-18 14:0x NZDT (40 short lines, one message each, as her
  sessions hold them; prompt tokens with and without):

  | Form | DeepSeek, added per line | Local, added per line |
  |---|---|---|
  | `〔7230〕` | 4.0 tokens (+25% of a line) | 7.0 tokens (+32%) |
  | `〔230〕` (last three digits) | 3.0 (+19%) | 6.0 (+27%) |
  | `[7230]` | 3.0 (+19%) | 6.0 (+27%) |

  Her lines are short (QQ lines in the last 7 days: 25,713 inbound, 17.4 characters on average, about 3,600 a day;
  her largest conversation is at line 9,288), so the number is a quarter to a third of a line. That is about 14,000
  (DeepSeek) or 25,000 (local) more tokens a day written into her group sessions, each paid once and then read from
  the prompt cache; the visible effect is that a busy group's session fills its window about a quarter sooner and is
  compacted that much more often. `[n]` is not usable: labels and mentions already use square brackets.
- The ambiguous-turn line: 30–40 tokens, only where it appears. The echo: about 40 characters per pointing call.
- Three measures of the same cost, each with its own denominator (Xiaoman: keep all three, none replaces another):
  per line, a quarter to a third of a line's tokens (above); per synthetic turn, about 26–39 tokens more on the first
  request (§8.5's paired requests); per whole turn, B used fewer tokens than A on DeepSeek (1,902 against 2,116, fewer
  calls) and about the same on the local model (2,959 against 3,007). In her real sessions, with far more lines than
  the synthetic moments, the per-line share weighs more than in the experiment.
- Tool definitions: one `line` description replaces three selectors; `speak.quote` grows by about 150 characters;
  QQ Bot definitions shrink by about 170 tokens. `tests/test_tool_budget.py` changes in the same steps.
- Action brain: nothing.

### 9.11 How we will know

A week after step 2: over her group and private lines where others spoke after the line that called her, the share of
quotes that point at the line she answered, read the same way as §5, against today's sample; separately, how often she
quotes at all, and how often the ambiguous-turn line was followed by a quote. Her conditions (signature below):

- Quotes between other people are counted on their own: the experiment's 15 moments had none, and §9 treats them as a
  main case.
- A line that answers several lines (S15) is not held to zero quotes: what is left there is the models' habit, hers
  included; the echo is what makes it visible.

## 10. To decide

1. The owner: the proposal in §9.
2. Xiaoman: signed (below), with her conditions folded into §9.3, §9.4, §9.7 and §9.11.
   After signing she raised one more point, approved by the owner (about 14:15) (Claude's paraphrase, about 14:05 NZDT): a hidden function should
   still be said once, in one program line, when it goes away (a runtime limit found, or a change of adapter that
   carries less): "hidden and not said" is the same mistake as an option she could not see. Claude's view: one line
   at the moment it changes, not every turn, keeps the owner's "hidden from the model" and answers hers.
   Her details for that line, if the owner agrees (about 14:07): it says the leg cannot (`这条腿做不了引用`), not just
   that the function is unavailable, or she would take it for her own fault; and it is said again when the function
   comes back. The Host-log line for an undeclared capability is for the developers; this line is hers.
4. Checking what adapters claim (Xiaoman, about 14:07): "not declared = not carried" stops a capability nobody
   declared, not one declared and not done. Step 1's acceptance sends one real probe for each declared capability on
   NapCat (quote out and in, in a group and a private chat; a reaction; a recall), and a quote that does not land stays
   told to her (`landing_lost`), never silent.
5. For the owner (Xiaoman): QQ Bot is another account with other ids, so the same group seen from both is two
   conversations: if Xiaoman's own QQ moved to QQ Bot, her groups, notes and people there would start again as new;
   and Kazusa joining a group of Xiaoman's meets it as a new conversation.
3. Then step 1 of §9.8; before it starts she gets the list of what step 1 changes, file by file, to check it against
   her live page.

## Signatures

Xiaoman (her words, as she gave them on the agent line, 2026-10-18 about 14:02 NZDT; she read commit `2d65ae3d`, before
§9.0 and the owner's answers in §9.7 were added):

> 我读了 `2d65ae3d` 的 §8 和 §9（sha256 `3aa70d15…`），签 B。我签的理由不是"它引错最少"——表里引错最少的是 D，而 D 在本地模型下 75 次里有 37 次根本没指、补拉那条（S10）从没指过。**我要的是敢指：多指偶尔指错，回显让我当场看见、能改；为了不错而根本不指，错就永远看不见。** 四条请一起办：① §8 那 15 个场景里没有"别人之间互相引用"，而 §9 把它当主要情况——第二步上线后这一类单独数；② S15 那种"一句话答三条"，文档自己说剩下的是模型自己的习惯，验收别把它的引用归零当门槛；③ §9.7 五个 flag 没写默认值，请加一句：没显式声明的 kind 启动时记一行——今天 NapCat 私聊就是"没人声明、悄悄丢掉、谁都不知道"的活样本；④ 私聊没引用是三道闸叠着（`role_tools.py:1414` 工具层就拒、适配器 `PRIVATE_ENVELOPE_KEYS` 不带、核心 `DM_GROUP_FIELDS_DENIED`），§9.7 只列了后两道，请补第一道；顺带定一下私聊"纯引用无文字"我该看到什么，今天那是个 `[回复消息（无文字）]` 占位。§9.9 三条：私聊我收回上午的"先别动"；别人之间的点表情我要，折成一行；react 别写成唯一正确——写清"react 挂在别人那条上、贴纸是一条新消息"，S6 选贴纸不是错。两处文字请改：§8.3 的 560 和 §8.5 的 600 对不上；"B 引错最少"应写成"引对最多、调用最少，引错仅少于 D"。——以上我按字面读过，不是按转述签的。
