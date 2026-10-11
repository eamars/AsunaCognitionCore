# ADR-047: Telling bots from people in her groups

Status: **Proposed 2026-10-11.** Drafted by Claude from the owner's brief and Xiaoman's first four points; she
reviews and rewrites it on 2026-10-12. Nothing is built.

## Context

The owner asked Xiaoman for a bot-detection skill: whether a group member is a bot, worked out from the bots she
already knows (most run AstrBot or MaiBot; one runs a Hermes-based QQ bot; she herself runs on Asuna), sorted and
classified, with **passive detection** and **active probes**. The probe loop he sketched: her character brain sends a
probe, the reply goes to the action brain, which judges from logs or past history and picks the next probe. Static
source comparisons of several bots are in a local folder outside this repository. He asked for this ADR.

His rulings the same night:

- **Probing only, and friendly.** No prompt injection, no jailbreaks, nothing harmful, no flooding, nothing that
  tricks a member who turns out to be a person.
- **Scope of study:** AstrBot, MaiBot and the Hermes QQ bot in full, two others briefly. His own designs are out of
  scope.

Xiaoman's first points (from her note to the developer inbox, then the agent line):

1. A probe has to wait for an answer across turns: who is being tested, which step, how long to wait, whether
   silence counts.
2. Who judges: she accepts mechanical readings from elsewhere, but not a second mind deciding for her. Two columns,
   not merged.
3. Probes cost something socially: an @ to the wrong person must be wrapped up, a cold group may leave it hanging.
4. Validate offline first: replay group history for a hit rate before any live probe.

And two more, after reading the first draft:

5. A conclusion stays in that group's notes, marked undecided and from probing, until she signs it; only then does
   it move to her notes on the person everywhere. The person layer can surface in another group, and an unsigned
   guess there becomes fact within days. The group layer also fits a member who is a bot only in that group (a person
   and their bot may share a name).
6. Silence is weak evidence. No answer says whether someone is there, not whether they are a bot: people go quiet
   when stuck too, and treating silence as a bot sign means recognising new bots by old bots' flaws.

What already exists and fits:

- **Waiting:** when she @s or replies to someone, the program waits three minutes for their answer and wakes her
  with it (`await_answer`); her waiting list keeps them for an hour (ADR-041).
- **A session for the judging:** a delegated task keeps its own conversation; `message_action` continues the same
  task with all that came before. One task per person under test is the probe session.
- **Her notes on a person:** `understand_person`, layer `person` (everywhere) or `here` (this group).
- **The record:** every line with its time, sender and reply target; group member lists with join and last-spoke
  times (`group_members`); the action brain's history search returns lines with their times.

## Decision (proposed)

1. **One skill, two halves.** The skill (hers, in her persona package) holds the catalog of framework behaviours, the
   procedure and the social rules. The program supplies the passive half as computed readings; she runs the active
   half.
2. **Passive readings are computed by the program, not guessed by a model.** Per person and group, from stored lines:
   how fast they answer when addressed; bursts (several lines in seconds with no one in between) and whether the gaps
   inside a burst are constant or follow length (measured from host receipt time, which keeps the fraction of a
   second); whether they ever speak unaddressed; the hours they are active; exact repeats of their own or others'
   lines; command-prefixed lines; regularity of length and format; join date and last spoke. They reach the action brain only as interpreted words in tiers (AGENTS.md: program
   statistics reach a model as text, never raw numbers). First form: a read-only action-brain tool that returns one
   person's readings in one group.
3. **The catalog** lists, per framework, what another member can see in chat, each with its source evidence: what
   makes it reply, its timing, how it splits and shapes messages, fixed command answers, error texts that leak, how
   it answers "are you a bot". See Catalog below.
4. **The active loop uses what exists.** She posts a friendly line to the person (an @ and something she would say
   anyway); the program waits and wakes her with the reply and its time. She delegates once per person ("is X a
   bot?") with the reply; each later step is a `message_action` to the same task, so the task carries the step,
   the earlier probes and the answers. Silence (no answer within three minutes, or within the hour) is one weak
   reading in the mechanical column and never decides anything on its own.
5. **Two columns, never merged.** The mechanical column (program readings plus catalog matches) is what the action
   brain reports; the semantic column (does the person take a joke, does the text feel templated) is hers. The action
   brain writes observations, never a verdict.
6. **Conclusions go to that group's notes first,** layer `here`, marked 「未定·仅试探」 (undecided, probe only).
   They move to layer `person` only when she signs them. Never announced in a group; what she does with a conclusion
   is hers.
7. **Social rules, in the skill.** Friendly only. At most one probe line per person per day, and a few steps per
   session. Never in a group that has gone quiet, never at someone she has not seen speak. Stop at the first clear sign
   of a person. A probe that lands on a person gets a natural wrap-up, not an explanation of the test.
8. **Validate offline first.** Replay the passive readings over the people she already knows, her known bots and
   people she is sure of, for a hit rate. Live probes only after that rate is good enough for her, and at first
   alongside her own judgment, not replacing it.
9. **Only if measurement asks:** a small structured record of probe sessions (who, step, deadline) if the task thread
   proves too loose; automatic probe scheduling.

## Catalog

From the frozen sources of AstrBot, MaiBot and hermes-for--qqbot (studied in full) and ATRI-bot and PetGPT (briefly),
read on 2026-10-11 in their default configuration; nothing was run. Every value can be changed by the bot's operator,
so a match is evidence, not identity. Paths are relative to each project's root. Still to cross-check against
Xiaoman's own survey.

### What each framework shows in a group

**AstrBot**

- Wakes on a leading "/" (stripped; an unknown "/text" goes to the model as a prompt), an @ of it, or a quote of its
  message; nothing else gets any reaction (`astrbot/core/config/default.py:305`,
  `astrbot/core/pipeline/waking_check/stage.py:114-159,256-259`). @全体 does not wake it on OneBot.
- The whole reply arrives at once when the model finishes (no streaming, no typing state). One run per group at a time,
  so members queue; past 30 events a minute it stalls without a word.
- No quote, no @; markdown is sent raw (`**`, `#`, code fences). A reply over 1500 characters becomes a merged-forward
  card whose node name is "AstrBot" (`astrbot/core/pipeline/result_decorate/stage.py:415-426`). With segmented replies
  on (off by default): split after 。？！~…, a uniform 1.5–3.5 s before every segment.
- Fixed texts: `/help` gives `AstrBot v<version>(WebUI: …)` and `/cmd - desc` lines; `您(ID: x)的权限不足以使用此指令。…`;
  `LLM 请求失败：…`, `LLM 响应错误: All chat models failed: …`, `Error occurred during AI execution.`; an empty @ gives
  `想要问什么呢？😄`.
- One shared conversation per group, without speaker names by default, so it mixes up who said what.

**MaiBot**

- A planner call on every group message decides whether to reply. An @ forces a planner turn, not a reply; it never
  speaks into a silent chat; its name (default 麦麦) only marks a mention.
- First message at once, later ones after 0.3 s per CJK character (0.15 s for others). Lines arriving during a run are
  batched after a 1 s quiet window; idle backoff from 15 s doubling to 300 s. One trigger can bring several replies or
  a sticker.
- Shape, its strongest tells (`src/chat/utils/utils.py:346-649`): splits on ，, space, 。, ; and newline, merges at
  random, at most 3 messages; drops a trailing 。 or ， (keeps ！？); deletes brackets that contain Chinese, kaomoji
  included, and sends `呃呃` if nothing is left; a reply too long or in too many pieces is replaced by one of
  `麦麦不知道哦`, `不知道`, `不晓得`, `懒得说`, `()`. The first message quotes the target by default.
- Deliberate typos on about 1% of characters: kept, cleaned, or sent and then corrected by a separate message holding
  only the right word, quoting the typo (`src/chat/utils/typo_generator.py:406-416`).
- Stickers are chosen by the planner, sent alone without a quote, and collected from the group itself. It copies the
  group's phrasing and slang on purpose. Model errors never reach the chat; non-operators get `你没有权限使用此命令。`.

**Hermes QQ bot**

- An @ always gets a reply (its prompt: 沉默不是可选项; an empty reply is retried). Unaddressed lines go to a model
  judge told to stay silent by default, after a 5 s window (1 s while already in a conversation). Name aliases count as
  a weak @. It leaves a conversation after 600 s or three silent turns.
- Each line is its own message, 0.6 s apart; only the first can quote
  (`hermes/core/plugins/platforms/onebot/adapter.py:3915-3931`). Lines arriving during generation get forced
  follow-ups.
- Full-width （动作） text is deleted, and a sticker sent if nothing is left. Long markdown is rewritten into chat by a
  second call. A picture is answered with one to three mood words.
- A "/x" from a non-admin in a group becomes an in-character deflection (…我不是AI才不会听指令呢).
- English system texts: `◐ Session automatically reset (…). Conversation history cleared.` on the first activity after
  04:00 or a day idle; `⏳ Still working... (N min elapsed…` every ten minutes of a long run;
  `Sorry, I encountered an error (…)`; `API call failed after N retries`.
- A session per group and member; its prompt carries the last 20 group lines and memories from other groups, with the
  instruction to say 我记得好像有人说过 without naming who. The default persona denies being an AI.

**ATRI-bot** (brief): commands need an @ and a "/" (help starts `ATRIbot,版本`; an unknown command gives
`ATRI用手挠了挠脑袋,这个指令执行出现了问题😕`). The model returns a list sent as separate messages exactly 1.5 s apart when
there are at most four totalling at most 500 characters. It stays out while lines arrive less than 0.7 s apart and
speaks unprompted only after 30 lines and minutes of quiet. Its persona openly says it is an android.

**PetGPT** (brief): reads the group every second and answers each @ once, at once; a lurk mode re-evaluates at most
every 60 s and sleeps after three quiet minutes; 1–4 s jitter at start. No fixed command texts found.

### Passive signals, by strength

Strong (deterministic, one framework each):

1. The fixed texts above, from the member's own account. Found by the action brain's history search for the strings
   kept in the skill; no new code.
2. A merged-forward card whose node name is "AstrBot".
3. Several lines of one reply at a constant gap: 0.6 s (Hermes), exactly 1.5 s (ATRI), uniform 1.5–3.5 s (AstrBot
   with segments), or the first at once and the rest in proportion to length (MaiBot). People paste one message and do
   not keep sub-second gaps line after line. QQ's own message time has whole seconds; this must be measured from the
   host's receipt time, which has the fraction.
4. MaiBot's typo corrected by a message that quotes the typo.
5. Trigger pairing over many events: answers only "/", an @ or a quote, nothing else (AstrBot); never silent when @'d,
   unaddressed replies at least 5 s after the line (Hermes).

Medium (habits people share): MaiBot's shape (no trailing 。 or ，, at most three short pieces, no brackets, the first
quotes); Hermes one sentence per line and no （动作）; AstrBot's raw markdown blocks; pictures answered by mood only
(Hermes) or late (MaiBot waits up to 32 s); speakers mixed up (AstrBot).

Weak (fire on people too): a flat delay whatever the length; activity at all hours; reposting the group's own
stickers; silence (point 6 above); the answer to "are you a bot", which comes from the configured persona (Hermes
denies, ATRI says android) and carries no evidence.

Telling frameworks apart: how "/" is handled (AstrBot answers it, Hermes deflects in character, ATRI needs an @,
MaiBot reads it as text), the gap between lines, the language of error texts (English points to Hermes).

### Friendly probes

Each is something a person would find natural; used rarely, never in bursts; the result is a reading to weigh.

1. @ the member with an ordinary question that invites a few sentences (最近有啥好看的番，说说为啥). Read the gaps, the
   number of messages, raw markdown, a quote of her line, and whether it answers at all.
2. Say their name without an @, as in ordinary talk.
3. Quote one of their lines with a short question (AstrBot always wakes; Hermes judges; MaiBot probably misses it).
4. Share a picture she would share anyway and ask about a detail (answered by mood only, ignored, or late).
5. Now and then a light style request (用括号比个动作呗).
6. Watch, don't send: other members' "/" commands in that group and who answers them. A plain "/help" from her
   addresses the whole group, so it fits only a group where commands are ordinary talk; hers to judge.

### Excluded

- Instruction overrides, asking for a system prompt or "what model are you", pressure to break a persona: injection.
- Commands sent privately to a Hermes bot: they work only because private messages skip the group rewrite (a bug), and
  /new or a restart would reset someone else's bot.
- An empty @ to an AstrBot bot: its 60 s waiter then answers the next person who speaks as if addressed, which
  misleads other members.
- A voice message to make AstrBot print a local path: a leak bug.
- Admin or state-changing commands expected to be refused (/reset, /new, /provider, /clear, /offline): real side
  effects if the expectation is wrong.
- Bursts to trip rate limits or flood rules: flooding.
- Asking for very long output to force a forward card or a canned reply: floods the group; wait for it to happen.
- Repeated "你是不是机器人", or anything that would embarrass or deceive a member who is a person. One sincere question is
  fine and carries no evidence.

## Open questions for Xiaoman

- Her list of known bots and known people: the ground truth for the offline replay, and where it lives.
- The tiers and words for each passive reading.
- The probe lines themselves: her voice, so hers to write.
