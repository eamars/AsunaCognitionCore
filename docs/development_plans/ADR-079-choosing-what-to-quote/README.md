# ADR-079: Lines that point at other lines (quote, reply, reaction)

Status: **Analysis and experiment 2026-10-18** (Claude). The owner asked for a systematic view of the whole family
before any change to quoting, then for a side-by-side experiment on both models (§8). Recommendation in §8.6; no
decision yet, nothing is built. Xiaoman reads it after the owner.

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

- The handle on every line in a conversation that can point at lines: about 6 characters a line, roughly 10% on a busy
  group's short lines. Lines are appended once, so the prompt cache keeps its prefix.
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

**Where nothing changes or less is shown.** Private chats keep today's default (they quote the line that called her)
and may say `不引用`. Home lines show no numbers. Kazusa's QQ Bot conversations show no numbers, and her `speak` there
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
- 5 runs per moment, arm and model: 14 × 4 × 2 × 5 = 560 calls, plus the Kazusa variants for moments 1, 4, 6 and 14.
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

### 8.5 Results (run 2026-10-18 13:2x–13:5x NZDT)

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

## 9. To decide

1. The model in §4, or a narrower start (quote only), after the experiment.
2. Whether reactions to other people's lines are shown at all (today dropped).
3. The order of work: rendering and handle first (§4.1–4.2, nothing she must learn), then choosing (§4.3), then the
   adapter split (§4.4–4.5, together with Kazusa's `speak`).

## Signatures

Xiaoman: (her words here, in her own hand)
