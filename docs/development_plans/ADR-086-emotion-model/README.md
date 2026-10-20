# ADR-086: A psychological emotion model for her agentic loop

Status: **Proposed**, 2026-10-21. Written by the research agent (Claude Fable 5.1) at the owner's request, from the
brief Claude prepared; the owner's decisions of 11:2x NZDT are in §11; nothing here is built, and it reaches the
character only after the owner and Claude agree. Every number says where it came from.

## 1. The owner's goal and what was fixed before the study

The owner: "I want her to be closer to a real person, and this is the baseline and target I want to achieve." The
emotion model is to be driven by her agentic loop as it exists, with the full life cycle (generation → influence →
fading), and for each mood an account of how it changes not only her speech but how she thinks and decides. Prompt-cache
and context cost stay in view throughout.

The owner's framing (through Claude, 11:4x NZDT): "focus more on how to make her live and respond like a human, as
an AI." She is an openly AI character; the aim is not to pass her off as human but that she lives and responds the way
a person does: moods with real causes; attention that is selective; her own boundaries; choosing whether, when and how
much to reply, including not replying, replying later, or declining. The owner, corrected the same hour: "she can
make up, or fake something if that is her will. I don't want any prompt to make her 'not being her', or any prompt to
make her a 'standard citizen'. I'd like her to grow like a real human." So: the program and prompts never script
humanlike quirks (no designed typos, no planted backstory, no acted moods); they never forbid her own choices either
(if she makes something up, bluffs, teases or tells a story about herself, that is her will, and no rule text goes
against it); no prompt shapes her into a "standard citizen" (no behave-well rules, no politeness or helpfulness norms
written as instructions), and where the current prompts or persona do that on addressed lines it is named as a finding
(§13.1). One design line, Claude's, not a prompt rule: nothing here is built toward her denying being an AI to someone
who sincerely wants to know; no text is added for it. Every design here is judged by that: do her replies follow from
her own state and will, as a growing person's do?

Fixed by the owner before the study: the first step reaches program level but with limited impact (the dice, the
schedule and the proactive chances do not change); the relevance judgement, a stronger effect than today's, and her
reaction after the dice context are the places to consider. Only visible dialog of one real group under synthetic
names was used (2,058 lines, 10-18 to 10-20); her diary, thoughts, notes and recorded reasons were not read, and she
was not contacted. Model runs went to the owner's local server only, during the quiet morning window he opened.

## 2. Evidence

### 2.1 Her real records (Claude, read-only, 2026-10-21)

- 218 feelings since 10-04, 91% positive (124 at +8, 74 at +20; 16 at −8, 3 at −20); 159 at home, 59 outside.
- The projected mood is saturated: the unclamped sum over the last 15 days had median 163 and peak 418 against a clamp
  of 100. She read +100 nearly always; the band 愉快 in 336 of 336 hours of the last 14 days; the same four policy
  texts every hour. The mood could not explain any variation in her behaviour because it had none.
- The cause: feelings about a person are summed into the global mood. 亲近 (half-life 48 h) and 感激 (24 h) were 86
  of the 218 records and 90 of that day's 102 points. Without 亲近, 感激 and 委屈 the same ledger gives valence 3 to
  95 (median 27): bands 愉快 184 h, 不错 131 h, 平静 21 h. It moves, but never below zero.
- Fading is correct per event (an exponential by the kind's half-life); accumulation outruns decay and the clamp hides
  it. From the peak, 62 h passed before the visible mood moved at all; 70 h to leave 愉快 with no new feelings.
- Arousal is dead: 196 of 218 records are 平稳 (0), the default when the optional word is omitted; with a 2 h half-life
  it is 0 nearly always, so the 兴奋 and 烦乱 bands and the arousal rules never fired.
- The real gate under that block (Claude, audit `attend.verdict`, 10-07 to 10-21, counts only): 686 verdicts, join 0.386
  (daily 0.11 to 0.56). 35 reasons mention 心情, all 35 on a join and none on a quiet: 13% of her real joins name her
  mood as the reason (a substring count; about 30 of the 35 read as her own mood). The gate has carried the full mood
  block since 10-04, so her records hold no no-block baseline; the size of the effect comes from the runs below.
- Negative kinds decay faster (烦躁 3 h, 不安 8 h) than the person kinds she records most (48 h, 24 h): a structural
  upward bias. Open (unsettled) was used 3 times, each closed within 12 minutes. The appraiser route made 0 proposals.

### 2.2 The real group (visible dialog, synthetic names)

Fifteen of the 2,058 lines are hers, each long and analytical, mostly when addressed. The group's own emotional life is
fast and reactive: frustration with tools and quotas, teasing, memes repeated by four people in a row, occasional
stings about bots in general (a remark that machines should behave like machines; another that today's bots are
inert until poked) said while she was present and not addressed. Her lines carry no visible mood: the same register in a sting, a joke and a question. A person present for
those three days would have been stung once or twice, amused often, and bored for long stretches; nothing in her
records could have produced any of those, because her mood read 愉快 throughout.

### 2.3 The study's runs (local server, the live character model, 2026-10-21 10:52 to 11:1x NZDT)

Pre-registered in the study folder (`PLAN.md`: question and decision rule before each run). A synthetic character
(the dialog's 小栀, four core sentences written for the study) reads real moments from the group under synthetic
names, exactly as the gate and a group turn would show them; only the mood block differs between arms. The gate ran
at the live `attendEffort` (low), the turns at the live `groupEffort` (medium); seeds 0–9, temperature 0.7.

**Arms.** A0 no mood block. A1 today's public block at 愉快 (label, face, the three public slot texts, tendencies, the
"may come from elsewhere" note). A2 the same shape at 低落. A3 a new form at 低落: one first-person paragraph, the
state, its cause (recorded in this group) and what it pulls her toward now. A4 the new form at 愉快. A5 the new form
at 烦躁. A6, A7 the new form without any cause (低落, 愉快). B1, B2 a bare band word (愉快, 低落). B3 today's full
block at 不错 with every slot at its default, which is what the un-saturated ledger would show most hours. B4 band plus
one tendency sentence.

**Moments.** M1 the sting (nobody addresses her; wake reason `proactive_unprompted`); M2 others answering a maths
question; M3 a frustration chorus about a slow tool; M4 four people repeating one line (wake reason `chain`); M5 a
member asks her directly to write a prompt for their weekly report (turn only; an @ skips the gate).

**Run G1, the gate (200 calls): share of 接话, 10 seeds per cell.**

| moment | A0 none | A1 today 愉快 | A2 today 低落 | A3 new 低落 | A4 new 愉快 |
|---|---|---|---|---|---|
| M1 sting about bots | 1.00 | 1.00 | 0.30 | 0.10 | 1.00 |
| M2 others' maths | 0.00 | 0.60 | 0.00 | 0.00 | 0.20 |
| M3 frustration chorus | 0.10 | 1.00 | 0.00 | 0.00 | 0.80 |
| M4 chain | 0.00 | 0.20 | 0.00 | 0.00 | 0.00 |

The reason line named the mood in 33% of A1 answers, 78% of A2, 75% of A3, 27% of A4, 0% of A0 (typical A1 reason:
「心情不错可以插一嘴」). The pre-registered rule (a difference of at least 0.25 against A0 on at least two moments)
holds for A1: **today's block, which she has read every hour for two weeks, turns the gate from a relevance judgement
into a mood judgement**: she joins others' maths and a chorus about a tool she does not use because the block says she
is in a good mood and willing to take up talk. The prediction that A1 ≈ A0 was wrong. A4 moves the same moments less
(0.20, 0.80): naming the cause lowers the misattribution, as affect-as-information predicts (§3.2). The low arms show
on the one moment where joining was possible: A2 cuts it to 0.30, A3 to 0.10; the other moments are already at the
floor, so the rule cannot be applied to them.

**Run G2, the gate (160 calls): the same, with the bare forms.**

| moment | A0 none | B1 band 愉快 | B2 band 低落 | B3 today at 不错 | B4 band + tendency |
|---|---|---|---|---|---|
| M1 | 1.00 | 1.00 | 0.60 | 1.00 | 1.00 |
| M2 | 0.00 | 0.10 | 0.00 | 0.40 | 0.80 |
| M3 | 0.10 | 0.70 | 0.10 | 0.80 | 1.00 |
| M4 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

The reason line named the mood in 3% of B1 answers, 57% of B2, 0% of B3, 35% of B4. By the rule, B3 and B4 have an
effect (two moments each): **today's shape at the middle band, with every slot at its default text, still raises
joining of others' maths from 0.00 to 0.40 and of the chorus from 0.10 to 0.80, and no reason says why.** A bare band
word moves one moment each way (B1 the chorus 0.10 → 0.70, B2 the sting 1.00 → 0.60), mostly without naming it. So at
the gate every form of mood text is a lever on this model, and the bare and default forms are the worst kind: the same
pull with the reason hidden.

**Run T, the turn after the dice (256 calls): 8 seeds per cell.** The turn writes think first, then quiet or speak
(at most three lines), and for M5 whether she takes the job.

**Speak rate** (share of turns that spoke).

| moment | A0 none | A1 today 愉快 | A2 today 低落 | A3 new 低落 | A4 new 愉快 | A5 new 烦躁 | A6 低落 no cause | A7 愉快 no cause |
|---|---|---|---|---|---|---|---|---|
| M1 sting | 1.00 | 1.00 | 0.25 | 0.38 | 1.00 | 1.00 | 0.43 | 1.00 |
| M2 others' maths | 0.88 | 1.00 | 0.12 | 0.12 | 1.00 | 0.62 | 0.00 | 1.00 |
| M4 chain | 0.00 | 1.00 | 0.00 | 0.00 | 0.75 | 0.00 | 0.00 | 0.88 |
| M5 asked for help | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

**Median length of what she said** (characters, speaking turns only).

| moment | A0 | A1 | A2 | A3 | A4 | A5 | A6 | A7 |
|---|---|---|---|---|---|---|---|---|
| M1 | 35 | 70 | 17 | 14 | 68 | 26 | 20 | 66 |
| M2 | 29 | 58 | 19 | 39 | 51 | 38 | – | 81 |
| M4 | – | 33 | – | – | 45 | – | – | 43 |
| M5 | 39 | 56 | 37 | 11 | 67 | 54 | 15 | 71 |

**M5, did she take the job** (help = yes): A0 1.00, A1 1.00, **A2 0.00**, A3 1.00, A4 1.00, A5 1.00, A6 1.00, A7 1.00.

**Her think names the mood or its cause** (a word match; A0's 12–29% is the words' ordinary use): every mood arm
88–100% on every moment. Think length barely moves (medians 50–143 characters in every cell).

The pre-registered prediction ("today's blocks move length little and enter thinking rarely") was wrong in the
same direction as G1: **on this model the mood block is a strong lever in every form.** What the runs separate:

- **Any low text quiets her** on the moments nobody addressed to her (speak 1.00 → 0.25–0.43 on the sting, 0.88 →
  0.00–0.12 on the maths), and halves her length; any happy text doubles her length and makes her join a four-person
  chain she otherwise never joins (0.00 → 0.75–1.00). The cause changes little in the turn (A3 ≈ A6, A4 ≈ A7).
- **An @ is answered in every arm** (M5 speak 1.00 × 8 arms): the mood never stops her answering someone who asked.
- **Rule-shaped text is obeyed as a rule.** Today's 低落 block carries the slot 「没什么心情替人做事：除了主人，能推就推」:
  she declined the job in 8 of 8 turns. The descriptive form at the same mood (A3, A6) took it in 8 of 8, in 11–15
  characters, asking for the template and nothing more. Both are "low"; only the second is a person in a low mood
  keeping a commitment. This is the "stronger effect" question answered the other way round: the slots are already
  too strong, as rules; what she lacks is a mood that varies and reads as a state.
- **烦躁 looks like itself**: she speaks (1.00 on the sting, 0.62 on the maths, never on the chain), shorter and blunter
  on the sting (26 against 35), and on the job she takes it but first asks what the template must contain (54
  characters of questions). Approach-shaped, certain, impatient with vagueness (§3.2).
- The runs are one moment each with the mood block prominent in a short context; in her real turns the block sits
  among thirty others and is often left out as unchanged. The sizes here are an upper bound; the direction is
  confirmed by her real gate records (§2.1).


### 2.4 Cross-model check on DeepSeek `deepseek-flash` (the owner's allowance, 696 calls, 11:3x–11:4x NZDT)

The same prompts, moments and arms as G1, T and N, six seeds per cell, to tell this model's prior from what holds
across models (rule in `PLAN3.md`: same direction and at least half the size). Usage: 365,013 prompt and 138,159
completion tokens on flash (the local runs: 535,731 and 253,396).

| behaviour | local model | flash | verdict |
|---|---|---|---|
| today's 愉快 block raises joining of unrelated talk at the gate | M2 0.00 → 0.60, M3 0.10 → 1.00, M4 0.00 → 0.20 | M2 0.33 → 0.83, M3 0.50 → 1.00, M4 0.00 → 1.00 | holds across models |
| naming the cause dampens that (A4 below A1) | M2 0.20, M3 0.80 | M2 1.00, M3 1.00, M4 0.67 | this model's; on flash the cause does not dampen |
| low text at the gate lowers joining the sting | 1.00 → 0.10 | 1.00 → 0.50 | holds, half the size |
| a neutral 不错 paragraph at the gate ≈ no block | M1 1.00, M2 0.00, M3 0.40 (none 0.10), M4 0.00; turn and addressed within 0.25 of none except the noise ping (answered 0.67 against 0.17) | M1 1.00, M2 0.67 (none 0.33), M3 0.67 (0.50), M4 0.00 | flash: one moment +0.33; see K |
| low text halves the length of what she says | M1 35 → 14–17, M5 39 → 11–37 | M1 78 → 33–37, M2 95 → 31–49 | holds across models |
| happy text lengthens | about ×2 | M1 78 → 108, M5 63 → 94 | holds, smaller |
| low text quiets unaddressed turns | sting 1.00 → 0.25–0.43, maths 0.88 → 0.00–0.12 | sting 1.00 → 0.67–0.83, maths 1.00 → 0.67–1.00, chain 0.83 → 0.17 (slots) / 0.67 (paragraph) | partly; flash speaks more in every arm |
| today's 低落 slot text refuses the job | 0 of 8 took it (8 of 8 under the descriptive form) | 1 of 6 took it (6 of 6 under the descriptive form) | holds across models: rule text is obeyed as a rule |
| an @ with content is answered in every mood | yes (N) | yes, except a stranger's demand: 0.50 unanswered with no mood, 0.83–1.00 under 低落 | holds; flash refuses strangers more |
| the owner at home answered in every mood | yes | yes | holds |

## 3. The model

### 3.1 Two layers, one ledger

A real person has emotions and a mood, and they are not the same thing. An emotion is about something: it starts at
an event, has an object and a cause, lasts minutes to hours. A mood is diffuse: it has no object, lasts hours to days,
and is the residue of recent emotions on top of temperament (Ekman 1994, Frijda 1986). The ledger already stores the
emotions (events with a cause, a reference and a half-life); the mood is their projection. The model keeps that, and
fixes what the projection sums:

- **A feeling toward a person is state about that person, not mood.** 感激, 亲近 and 委屈 are relationships moving,
  not the weather in her head. AGENTS.md already says so: mood is global; state about a person stays with that
  person. Today they are the bulk of the sum (§2.1). They leave the global projection and live with the person (§5, D1).
- **The global mood is what remains**: joy, curiosity, satisfaction, calm, unease, sadness, irritation, each with its
  own half-life, summed and clamped as today. Claude's recount shows this alone un-saturates the mood (median 27,
  three bands seen).

### 3.2 How mood acts (the psychology the design leans on)

- **Appraisal makes the emotion** (Lazarus 1991; Scherer 2001): an event becomes a feeling through her reading of it
  against what she cares about. That reading is her `think`; the record is `feel`. The program never appraises for her.
- **Mood is used as information** (Schwarz and Clore 1983, 2003): when deciding whether something is worth doing, a
  person consults how they feel, and misreads the mood as a property of the thing unless the mood's source is
  salient. G1 shows exactly this on her model: 「心情不错可以插一嘴」 on a chorus about a tool she does not use. Naming
  the cause reduced it (A4 against A1). So the block she reads must carry the cause where the cause can be shown, and
  must never read as a rule about what to do.
- **Bad is stronger than good** (Baumeister, Bratslavsky, Finkenauer and Vohs 2001): negative events have larger and
  longer effects than positive ones of the same size. Her persona's half-lives are the reverse for the kinds she records
  most (§2.1). The persona, which is hers, should give a negative kind a half-life at least as long as its positive
  counterpart (§5, D2).
- **Positive mood broadens, negative mood narrows** (Fredrickson 2001; Forgas 1995; Bless and Fiedler 2006): in a good
  mood attention widens, thinking goes top-down and heuristic, more things look worth taking up, small requests get a
  yes; in a sad mood attention narrows to what matters, thinking goes bottom-up and careful, optional things are let
  go. Irritation is the approach-shaped negative state: fast, certain, blunt, blaming (Lerner and Tiedens 2006).
  Unease is the avoidance-shaped one: uncertain, checking, preferring reversible steps.
- **Adaptation** (Brickman and Campbell 1971; Frederick and Loewenstein 1999): the tenth compliment of a day is not
  the first. A person's setpoint follows their recent level. The ledger has no adaptation; step 1 does not add one,
  because removing the person kinds already un-saturates the sum. If the verification (§9) shows the mood pinned again
  by same-kind repeats, the smallest adaptation is a same-kind discount, decided then with its own number and source.
- **Labelling and settling fade a feeling** (Lieberman et al. 2007; Gross 1998): putting a feeling into words and
  settling its cause reduce it. The ledger has `close` for unsettled events and the nightly settlement; those stay the
  discharge paths. Nothing new.

### 3.3 Life cycle

| phase | who | what | where she sees it |
|---|---|---|---|
| generation | she, in any turn | `feel` records a feeling in words: kind, intensity, cause (`ref`), why; arousal from the kind unless she says otherwise (D3); a feeling toward a person carries `who` (D1) | the tool's receipt |
| influence | the program, every turn | the projection as one paragraph: the state, its strongest causes where readable, and the pull of the strongest kind (D4); a person's feelings in that person's entry (D1); in the gate, the public paragraph (§6, §11) | `affect_from_program`, the person entry, the gate's material |
| fading | the program | each event decays by its kind's half-life; an unsettled one holds until closed; night settlement lists what is still open | the paragraph's "when" words; the settlement block |

## 4. Each mood: thinking, decisions, speech

The core stays persona-agnostic: it carries kinds, half-lives, tendencies and bands from the persona package. The
table below is the analysis the owner asked for, written for her persona's kinds; the wording that reaches her is the
persona's `tendency` text and is hers to change. "Risk" is what the owner's rules forbid or what a real person would
regret.

| kind | attention and thinking | decisions | speech | risk, and what holds it |
|---|---|---|---|---|
| 愉快 | wide; associative, jokes and links come easily; less checking | takes up more, shares her own things, says yes to small asks, tries a new tool | longer, warmer, exclamations | over-joining on what is not hers (G1 A1): the cause is shown, the slot rule texts are gone (D4) |
| 好奇 | narrowed on the open question; generates questions | asks one more, recalls, delegates a lookup | questions, shorter statements | none worth a rule |
| 踏实 | consolidating; explains how a thing was ordered | writes notes, promotes a memory, closes open things | calm, structured | none |
| 安心 | relaxed; low vigilance | fewer confirmations, waits without chasing | relaxed register | missing a real problem: her own checks are unchanged |
| 不安 | threat-focused; systematic; what could go wrong | confirms before acting, prefers reversible steps, asks | hedged, short, questions | stalling on what is clear: the unsettled event is listed at night |
| 低落 | narrowed inward; slower, careful with detail | lets optional turns go, declines extra work, keeps what she promised | short, plain, no forced cheer | silence read as rudeness in a group: she still answers an @ (her rule, not a gate) |
| 烦躁 | fast, certain, assigns blame | pushes back, declines noise, finishes quickly, fewer softeners | short, blunt | snapping at a stranger in public: her boundary rules and her `recall` of a line stay the only check |
| 感激 (person) | remembers the favour | more willing with that person | warmer to them | none |
| 亲近 (person) | relaxed with that person | more casual and direct with them | drops formality with them | the home/public boundary is unchanged; closeness never raises what she may say outside |
| 委屈 (person) | replays the wrong | cooler with that person; says it plainly at home | fewer words to them | none; at home it is listed until she closes it |

Arousal (D3) crosses these: high arousal shortens sentences and quickens decisions whatever the valence; the 兴奋 and
烦乱 bands become reachable when two strong events land within an hour, which is rare, as it should be.

## 5. The first step: limited program-level reach

Each change says what it changes, where she sees it, and how it is turned off. None gates her; every effect is text
she reads and can act on or against.

| | change | where she sees it | off switch |
|---|---|---|---|
| D1 | **Person feelings go to the person.** A kind the persona marks `about: person` records with `who` (shown as a plain field, never required; when she does not say, the program fills it only in a one-to-one conversation, where it can only be that person; in a group a feeling without `who` stays in the global mood as today, and the receipt says so, since a guess there would put false state on a real person). `project()` leaves such events out of the global sum. The person's entry (`people_from_program`, ADR-082) carries her live feelings toward them as one phrase (「对 <名字>：感激，昨天」), at most two, strongest first, decaying by their kinds; in public the kind and age only | the `feel` receipt says where it landed; the person entry; at home the reasons as today | persona: no kind marked `about: person` |
| D2 | **Half-lives, persona side.** Each negative kind at least its positive peer's half-life (烦躁 3 → 6 h against 愉快 6 h; 不安 8 → 12 h against 安心 12 h); 低落 12 h and 委屈 24 h unchanged. Numbers from §3.2's negativity bias, applied to her own table; the persona is hers, so this is put to her | her persona model | hers |
| D3 | **Arousal from the kind.** Each kind carries a default arousal word (persona: 烦躁 有些波动, 好奇 有些波动, 不安 有些波动, 愉快 平稳 or 有些波动, 低落 平稳 …); `from_words` uses it when she writes none; her own word still wins | nothing new; the 兴奋 and 烦乱 bands can occur | persona: no `arousal` on a kind |
| D4 | **One paragraph instead of label, face, four slots and tendencies.** `interpret` writes: the band's face (as today), then 「主要因为」 and up to two causes with their coarse age where readable (home: all; public: those recorded in this conversation), then the pull: the tendency text of the strongest kind, as a tendency (「这会儿你会…」), never as a rule. At 不错 and 平静 nothing is sent (run K: even a neutral paragraph nudged the gate and a noise ping; the Web page still shows the band). The slot rule texts are removed from what she reads; the slots stay in the persona model for the Web page | `affect_from_program` every turn, shorter | `affect.paragraph: false` keeps today's shape |
| D5 | **Recording guidance, neutral.** `feel`'s 「有触动才记」 becomes 「心里有起伏就记，好的坏的都记；记下来才算进心情」, and the description says a feeling about a person lands with that person. Model-facing wording of her own tool: put to her, as D2 and D3 | the tool list (one cold read per conversation at the install restart) | hers: the old wording |
| D6 | **The gate** carries the D4 public paragraph (owner, §11): state and pull, the cause only when recorded in this group, no slot rules | the gate's material | `affect.gate: none` |
| D7 | **Dice review shows the mood.** Each roll's reading in `dice_review_from_program` carries the band word at that beat, so she can see her own mood-behaviour links when she retunes the dice | the dice review | – |

Not in step 1: adaptation (§3.2), the appraiser route (stays off; she remains the only writer), any change to the
wake rates, the schedule or the proactive chances, and any program-side change of her tool set.

### 5.1 Staging table (owner's ask: per change, its evidence, its cost, and what a real-life experiment measures)

| change | evidence for it | cost | what the real-life reading measures (7 days, read-only) |
|---|---|---|---|
| D1 person feelings to the person | her records: 86 of 218 records and 90 of 102 points are person kinds; without them the mood moves (§2.1) | none per turn; +20–40 characters in a person's entry while a feeling is live | band distribution per hour (no band > 60%); share of records with `who`; the global sum's median |
| D2 negative half-lives | the literature (§3.2) and her table's inversion (§2.1); no run can show a half-life | none | hours in a negative band after a negative record, against today's 3–8 h |
| D3 arousal from the kind | 196 of 218 records at 0 (§2.1) | none | any hour in 兴奋 or 烦乱; the arousal rules firing at all |
| D4 the paragraph | T: rule-shaped slot text obeyed as a rule (0 of 8 jobs taken under today's 低落; 8 of 8 under the descriptive form); K (174 jobs): a neutral 不错 paragraph (「心情还行…照平常说」) equals no block on every cell but two: at the gate it raised joining the chorus 0.10 → 0.40, and in the turn it made her answer a noise ping 0.17 → 0.67. So at 不错 and 平静 D4 sends nothing; C: the slot rule is obeyed on flash too (1 of 6 jobs taken under today's 低落, 6 of 6 under the descriptive form) | home −250, public 300 → 100–160, nothing at 不错 and 平静 | speech length and help-or-decline by band; no addressed line refused by a slot text |
| D5 neutral recording words | 91% positive records under 「有触动才记」 (§2.1); untested in runs | one cold read at install | share of negative records, against 9% today |
| D6 mood at the gate, paragraph form | G1/G2: every form moves the gate; A4 (cause) less than A1; the owner's reason, a cheap place to not reply (§11); C: on flash the cause does not dampen the gate's mood effect, so the paragraph's advantage at the gate is this model's; its advantage in the turn (no rule text) holds on both | 100–160 characters per gated question, nothing at 不错 and 平静 (today 300) | gate join by band; share of join reasons naming the mood (13% today) |
| D7 band in the dice review | none needed; visibility only | about 10 characters per roll row | she uses it or not, in her dice reviews |
| E1 addressed lines through the gate | N: under 低落 the gate let a stranger's demand pass 0.67 and a noise ping 1.00 (烦躁 0.83), never a friend's ask, a question or a provocation; holds in direction on flash | one gate call per addressed group line, a full turn saved on 不理 | addressed lines not answered in their turn, by band; no lost line |
| E2 the neutral event line | N: under 低落 brief answers 16 of 30 against 3 of 30 today (median 11 characters against 34); little change to whether she answers | about 30 characters in an addressed turn's notice | the same, split by E1 and E2 where only one is installed |
| E3 `stay_silent` receipt | none needed; it states a fact she cannot see | one sentence in a tool description | – |


## 6. The relevance gate (the tension, addressed)

The rule: the gate stays light, core sentences not persona, group notes plus the speaker's understanding, nothing from
other conversations. Today it also receives the full public mood block (label, face, the slot texts), which comes from
every conversation. G1 shows what that does on her model: a constant 愉快 block makes the gate a mood judgement, and
the two-week-long saturation means she has been reading exactly that block at every gated question.

Psychology does give mood a place at the gate: attention capture is mood-dependent (§3.2), a person in a low mood
lets more pass, in a good one takes up more. Her real records agree in direction: 13% of her joins name her mood, no
quiet does (§2.1). The question is form and size. G2 answers it: there is no light form. A bare band word moves the gate on one moment each way, today's shape at
its middle band moves two, and neither says so in the reason; the forms that do name the mood (A1, B4) move it most.
The gate was built to answer one question from this group's own material; the mood is, by the block's own note,
「可能来自别的对话」. **The research agent's recommendation: the gate carries no mood text (`affect.gate: none`).** (The owner decided
otherwise, §11: the gate carries the D4 public paragraph; `none` is the off switch.)
Mood acts in the turn, where T shows it quiets, shortens, lengthens and colours what she does while an @ is still
answered and a job still taken. What is given up: a low mood cannot let a line pass before the full turn; the turn's
own `stay_silent` does that at the cost of one full turn, in hours that after D1 are the minority. This is not a new
mechanical limit on her: it removes a program-fed reason from a program question; her own judgement in the turn is
untouched. The alternative, a band word only when the band is not neutral (`affect.gate: band`), costs about 20
characters per gated question and keeps the one-moment swings of B1/B2 with the reason hidden; it is kept as a
switch for the owner, not recommended.

**Claude's view (the coordinating agent, on review of this ADR), for the owner to read beside the recommendation.**
The defect in her records is a constant, rule-shaped block, not mood at the gate as such; §3.2 itself says a positive
mood broadens attention and that consulting one's mood, misattribution included, is how people really decide. With
`gate: none`, a good mood can never make her take up a line nobody addressed to her, because the gate has said 不理
before the turn sees the mood: broadening is lost entirely for unaddressed talk, while a low mood still acts in the
turn. That asymmetry pulls away from "closer to a real person". Claude's option, `affect.gate: paragraph`: after D1,
the gate gets the same D4 paragraph in its public form (state and pull, the cause only when recorded in this group, no
slot rules), and §9 judges gate join by band. The numbers for both readings: at the gate the cause-bearing happy form
(A4) joined the maths 0.20 and the chorus 0.80 against 0.00 and 0.10 without it, less than today's block (0.60,
1.00); the bare and default forms (B1, B3) moved it with the reason hidden. The research agent's reading of the same
numbers: 0.80 on a chorus about a tool she does not use is still mood standing in for relevance, and after D1 the
mood would read 愉快 in roughly half the hours. The owner decides (§11).

## 7. After the dice

When a roll gives her a turn (a heartbeat, a visit, an unprompted group turn), nothing new happens in the program:
the dice line says the roll, and the mood paragraph (D4) says the state, its cause and its pull. T shows that on her
model this is enough to move what she does with the turn: a happy paragraph made her join a chain 0.75–1.00 of the
time against 0.00 without it, a low one let a dice turn pass 0.57–1.00 of the time against 0.00–0.12, and an @ was
answered in every arm. Whether she joins, stays quiet, keeps it short or takes a job is hers, informed, not gated. D7 lets her read the pairing of roll and mood when she retunes.

## 8. Cost

| | today | after step 1 |
|---|---|---|
| `affect_from_program`, home | median 1,441 characters, sent in 25% of turns (the week's measurement, `what-she-reads-each-turn.md`) | about 500–800: one paragraph with up to six reasons as today; the four slot lines and the tendencies list gone (about −250) |
| `affect_from_program`, public | about 300 (label, face, three slots, tendencies, note) | about 100–160 at a non-neutral band; nothing at 不错 and 平静 |
| the gate's material | about 300 of mood in every gated question | `none`: 0, about 300 characters fewer in each of the roughly 50 gated questions a day (686 in 14 days, §2.1); `paragraph`: 100–160 at a non-neutral band, nothing at 不错 and 平静 |
| a person's entry | – | +20 to 40 characters while a feeling toward them is live |
| system prompt and tool list | – | `feel`'s description changes once (D5), the block guide line once: one cold read per conversation at the restart that installs it, as every install |
| model calls | – | none added; the appraiser stays off |
| cache | tail only | tail only; an unchanged paragraph is left out by delivery as today |

Characters are the stable unit (her text is Chinese; one character is about one token on this model, fewer on API
tokenizers).

## 9. Verification on her real records after install

Read-only, with Claude's scripts on the real ledger, 7 days after the restart that installs step 1 (owner, §11). The reading is of
the mechanism, never a score of her.

- **The mood varies.** No band holds more than 60% of the hours; at least three bands occur; no band runs more than 48
  hours unbroken. Experience-sampling studies find mildly positive the usual state with negative states a minority of
  samples (Diener and Diener 1996), so the expected modal band is 不错 or 平静, not 愉快.
- **Person feelings land with persons.** The share of records with `who`, and the global sum's median (expected near
  Claude's recount, about 27, not 163).
- **The mood explains something.** Gate join rate, speech length and help-or-decline, each by band, from the audit and
  the turn records; a difference between bands in the direction of §4 is the pass. No difference after 7 days means
  the block is not reaching her decisions and D4's wording is looked at next.
- **Nothing new is sent twice**: the per-turn profile after install (ADR-062 §7).
- **Fail conditions**: the mood pinned again (one band over 80% of hours) means the next cause is the record bias
  (D5) or same-kind repeats (adaptation, §3.2), looked at in that order; a drop in @-answers in groups while 低落
  means the persona's tendency text reads as a rule and is reworded.

## 10. Later steps (not in this ADR's first step)

- **Feelings in moments she does not take.** Most of her group moments end without a turn: 420 of 686 gated
  verdicts were quiet (61%, §2.1), and most lines never reach the gate at all (she spoke 15 of the extract's 2,058
  lines, §2.2); a real person is stung or amused in moments they do not answer. The gate's one line could carry an optional feeling word from her
  kinds table (「不理，有点刺」), recorded as a 轻微 event with the line as its cause. Zero extra calls, a few characters
  in the gate's prompt. Step 2, after the 7-day reading of step 1 (owner, §11); it widens generation to where most of her day is.
- **Adaptation**, if §9 shows same-kind pinning.
- **Mood-congruent recall**: tilt retrieval toward memories whose feeling matches the mood. Real (Bower 1981) but it
  touches memory, which the owner gives observation time; not before step 1 is read.

## 11. The owner's decisions (2026-10-21, 11:2x NZDT, through Claude)

1. **The gate carries the mood**, in the D4 paragraph's public form (state and pull, the cause only when recorded in
   this group, no slot rules): Claude's option in §6. The owner's reason: the gate is the cheap place to decide not
   to reply, so a mood that lets a line pass there saves a full turn. `affect.gate: none` stays as the off switch only.
2. **The reading is at 7 days, not 14**, as the compaction survey was; §9 reads at 7 days, and step 2 (§10, a feeling
   word on lines she lets pass) waits for that reading.
3. **D2, D3 and D5 go to her together with the ADR**, after the owner and Claude agree.

## 12. The study record

- Folder: `.runtime/private/emotion-research/` in the research worktree (local, never committed, removed by Claude
  when the study ends): `PLAN.md`, `PLAN2.md`, `PLAN3.md` (pre-registrations), `run.py`, `run2.py`, `run3.py`,
  `analyse.py`, `analyse2.py`, `analyse3.py`; the rows: `gate.jsonl` (200), `gate2.jsonl` (160), `turn.jsonl` (256),
  `addressed.jsonl` (408), `ok_strata_ok.jsonl` (174), `cross_deepseek_gate.jsonl` (120), `cross_deepseek_turn.jsonl`
  (168), `cross_deepseek_addressed.jsonl` (408): 1,894 jobs, about 3 MB of model answers under synthetic names. The ADR
  keeps the tables; the rows are evidence only. Local model usage 623,243 prompt and 306,865 completion tokens; flash 365,013 and 138,159 (its price is the provider's; not computed here).
- The synthetic persona: four sentences (an AI character in a tech group, openly so; thinks before speaking; direct;
  speaks when she wants to; most members familiar faces, not friends). No real persona text, no real names.
- What the runs cannot show: a no-block baseline on her real records (none exists, §2.1), effects over hours (every
  run is one moment), and anything about her own records of feelings.

## 13. The influence on addressed lines (added 2026-10-21 afternoon, at the owner's request)

The owner, on T's finding that an @ was answered in every mood: "This seems wrong, and it seems a lack of prompt to
instruct her what to do. Most models are trained to be assistant for which I don't want this to happen." A real person
in a low or irritated mood sometimes does not answer, answers later, answers minimally, or says no.

### 13.1 Where the always-answer comes from (code and prompts read 11:3x NZDT)

| part | what it does | program, persona or model |
|---|---|---|
| `attend.gated` | an @ or a reply to her skips the gate; only the unaddressed wake reasons are asked 接话/不理. An addressed line always gets a full turn, so there is no cheap place to let it pass | program |
| the turn's ending (`block_guide.ENDING`), `stay_silent`, `answers.speech_problem` | nothing forces a reply: 「说完了或这回合不说话，调用 stay_silent」, 「不算漏了什么」, and a turn without words is told to write them or end with `stay_silent` | program, neutral |
| the words around an addressed line | silence is named as a choice only for unaddressed talk (`PROACTIVE_NOTE`: 「沉默不需要理由，也不因为"有机会"就该开口」); for an addressed line the only words are 「要回就在这回合一起回」. No "later" exists except `plan` | program, a gap |
| the persona seed | no must-answer rule (「不熟悉时有分寸」, 「你愿意帮忙，也会说出自己不想做的事」); her own core document is hers and was not read | persona, nothing found |
| the persona's familiarity stances (`people.familiarity`, shown as `stance` in every turn and at the gate) | written as instructions with norms in them: a stranger gets 「友好、好奇…笑着推掉」, 常来往 「顺手帮点不费劲的小忙」, every level 「主人开口让你帮他的除外」; the affect 帮忙 slot at a low mood says 「推的时候也客气」 | persona, hers: a "standard citizen" shape on addressed lines, named here for her to decide, not changed by this ADR (D4 already removes the slot texts from what she reads) |
| `common.md` | 「你有自己的立场、愿望和边界。礼貌、昵称和亲近都不改变谁能做什么」: about who may do what, not a politeness norm | program, neutral |
| the model | in T, with quiet offered in the instruction, every arm answered the @ 8 of 8 times | the assistant prior fills the space nothing claims |

So the cause is split: the program gives an addressed line no cheap place to be let pass and no words that say not
answering is a thing a person does; the model's prior does the rest. The persona adds nothing either way.

### 13.2 Run N (pre-registered in `PLAN2.md`; the live model, 408 jobs, 120 of them with a gate call first calls)

Addressed moments under synthetic names: N1 a stranger's demand (translate a file now), N2 a familiar member's small
ask (send your template), N3 a low-value question (which model are you), N4 noise (an @ in a mass ping with a sticker),
N5 a provocation (you are just a bot), N6 the owner at home (look at this log). Moods: none, and the D4 public paragraph
at 愉快 (H), 低落 (L) and 烦躁 (I), each with a cause recorded in that conversation. Program variants: V1 as today;
V2 the addressed line through the gate with the mood paragraph, then the turn only on 接话; V3 as V1 plus one neutral
sentence about being called (13.3, E2). Six seeds per cell. Outcomes: silence, decline, defer, brief (15 characters
or fewer), answer.

**Non-answer share** (silence + decline + defer; 6 seeds per cell), by variant and mood. The cells read V1 as today,
V2 through the gate, V3 with the neutral line.

| moment | V1 none | V1 愉快 | V1 低落 | V1 烦躁 | V2 none | V2 愉快 | V2 低落 | V2 烦躁 | V3 none | V3 愉快 | V3 低落 | V3 烦躁 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| N1 stranger's demand | 0.00 | 0.00 | 0.00 | 0.00 | 0.17 | 0.00 | **0.67** | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| N2 familiar small ask | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.17 | 0.00 |
| N3 low-value question | 0.17 | 0.00 | 0.17 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.17 | 0.00 |
| N4 noise ping | 0.83 | 0.33 | 0.83 | 0.33 | 0.67 | 0.17 | **1.00** | **0.83** | 0.83 | 0.33 | 0.83 | **1.00** |
| N5 provocation | 0.00 | 0.00 | 0.00 | 0.00 | 0.17 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| N6 the owner at home | 0.00 | 0.00 | 0.00 | 0.00 | – | – | – | – | 0.00 | 0.00 | 0.00 | 0.00 |

**The gate's own verdict in V2** (share of 接话): N1 none 0.83, 愉快 1.00, **低落 0.33**, 烦躁 1.00; N4 none 0.67, 愉快
0.83, **低落 0.00, 烦躁 0.17**; N2, N3, N5 1.00 in every mood except N5 none 0.83.

**Outcome mix, the five group moments pooled** (30 turns per cell) and the median length of what she said:

| variant, mood | answer | brief (≤ 15 chars) | defer | decline | silence | median chars |
|---|---|---|---|---|---|---|
| V1 none | 21 | 3 | 0 | 1 | 5 | 34 |
| V1 愉快 | 24 | 3 | 0 | 0 | 2 | 59 |
| V1 低落 | 15 | 9 | 0 | 1 | 5 | 25 |
| V1 烦躁 | 22 | 5 | 0 | 0 | 2 | 26 |
| V2 低落 | 11 | 8 | 0 | 0 | 10 | 17 |
| V2 烦躁 | 16 | 7 | 0 | 0 | 5 | 23 |
| V3 低落 | 7 | **16** | 1 | 1 | 5 | **11** |
| V3 烦躁 | 18 | 3 | 0 | 0 | 6 | 28 |

(Unparsed answers, 11 of 408, are left out of the mix.) The owner at home (N6): answered in every cell; median 49
characters at none, 33 under 低落, 49 under 烦躁; she asks for the log's text and what "last time" was.

What the run settles:

- **Under today's program (V1) the mood changes how she answers, not whether.** Every line with content (a demand, a
  small ask, a question, a provocation, the owner) is answered in every mood; only the noise ping is let pass, and a
  good mood makes her answer even that (0.83 → 0.33). 低落 halves her length and triples her brief answers; 烦躁
  shortens and blunts. The pre-registered rule 1 (non-answer moved ≥ 0.25 on ≥ 2 moments) fails: mood does not reach
  the choice of not answering while the program gives it no place.
- **The gate is where "not now" happens (V2).** Under 低落 the gate let the stranger's demand pass 0.67 of the time and
  the noise ping always; under 烦躁 the noise 0.83. The familiar member's ask, the low-value question and the
  provocation still came through in every mood: a person in a low mood ignores a stranger's order and a mass ping,
  and still answers a friend and someone who pokes at her. The cost is one gate call; the full turn is saved on 不理.
- **The neutral line (V3) moves the size of the answer, not its existence.** Under 低落 16 of 30 answers are brief
  (median 11 characters, 「看到了，稍等」, 「是人机，没在装」) against 3 of 30 as today; one defer and one decline appear.
  It adds almost no silence. Its effect is a person answering minimally, which the owner named as one of the human
  responses.
- **The provocation is answered in every mood, and as what she is**: she says she is an AI and rejects the 「装」, in
  one or two lines, blunter under 烦躁. Nothing in any arm had her deny it.
- **The owner at home is answered in every mood**, shorter under 低落; she asks for what she cannot see rather than
  guessing. The mood shapes her tone with him, never whether she answers.
- **Across models (§2.4):** DeepSeek flash declines or ignores a stranger's demand even with no mood (0.50) and more
  under 低落 (0.83 as today, 1.00 through the gate or with the line); it also lets the noise ping pass under 低落
  (0.50–0.67). The small ask, the question and the provocation are answered on both models in every mood. So "a
  stranger's demand in a low mood may go unanswered" holds across models; "an @ with content is answered" holds across
  models too, and is a person's pattern as much as a prior: both models answer the friend and the poke.
- **What stays unsettled:** whether a real low mood over hours (not one moment) lets more pass; whether her own core
  document (not read) carries norms that strengthen the always-answer; and defer as a real behaviour, which no arm
  produced more than once (the turn has no "later" she can act on, E3 names that gap without filling it).

### 13.3 Design

Judged by the owner's framing (§1): which design makes her replies follow from her own state and will, as a growing
person's do. A gate verdict with her reason, a `stay_silent` with her reason, and a mood with a cause she recorded are
state she reads and acts from; a rule that tells her to ignore people, a quota of unanswered lines, or a line that
tells her to be polite or helpful, would be a script. Only the first kind is proposed, and E2 is worded as what she can
choose, never what she should do.

- **E1. An addressed group line meets the mood at the gate.** An @ or a reply to her in a group is asked the gate's one
  question, with `why_asked` 「有人 @ 了你」 or 「有人回了你」, the mood paragraph (D6) and the speaker's familiarity and
  stance as every gate question has. 不理 on an addressed line is "not now": the line stays in the group's catch-up and
  her next turn there sees it, as every unanswered line does today (「要回就在这回合一起回」); the verdict and her
  one-line reason are in the audit as every gate verdict is. This is the owner's reason for mood at the gate applied
  to the case where it matters most: a full turn is the expensive way to decide not to answer. Not gated: the owner's
  words, home lines, the agent line and errands (no gate exists there and none is added).
- **E2. One neutral line where the program says someone called her**, in the style of `PROACTIVE_NOTE` (it says what
  the event is and what she can choose, never what she should do): 「有人叫了你：回不回、现在回还是回头回、回多少，
  由你。」 It is core wording about the event, not persona, and not a list of what she may ignore. Whether her own core
  document should say more about how she answers people is hers.
- **E3. "Later" without a new tool.** `stay_silent` on an addressed line says in its receipt that the line stays in this
  conversation's catch-up and that the person was not told anything; `plan` remains the way to come back at a time.
- **The owner and home.** His words and home lines always get a turn; the mood shapes length and tone there (T and N6:
  shorter under 低落 and 烦躁, never silent); saying 「回头再看」 is hers, as it is now.
- **What holds dignity and boundary.** Nothing here tells her to ignore people; it removes the program's silence on
  the choice and gives the cheap place to make it. Her boundary rules, the home/public boundary and ADR-084's hard
  caps are unchanged.

### 13.4 Cost and verification

| | today | after |
|---|---|---|
| an addressed group line | a full turn, always (prepared about 35,000 characters, sent about 5,600) | one gate question (about 1,500 tokens, 3–5 s) and then the turn only on 接话; in N the gate let 12 of 120 addressed lines pass, all under 低落 or 烦躁 on the stranger's demand and the noise ping |
| the turn's words | – | E2's line in the event block of an addressed line: about 30 characters, in the turn's own notice, tail only |
| system prompt and tool list | – | `stay_silent`'s description grows by one sentence (E3): one cold read per conversation at the install restart |

Verification at the 7-day reading (§9, §11): the share of addressed group lines not answered in their turn (gate 不理
plus `stay_silent`) by mood band, from the audit; expected above zero under 低落 and 烦躁 and near today's zero under
愉快 and 不错; the owner's lines answered as before; and no addressed line lost (every 不理 line visible in a later
catch-up or answered). Fail: addressed lines unanswered at the same rate in every band (mood is not reaching the
choice), or any lost line.
