# ADR-086: A psychological emotion model for her agentic loop

Status: **Proposed**, 2026-10-21. Written by the research agent (Claude Fable 5.1) at the owner's request, from the
brief Claude prepared; nothing here is built, and it reaches the character only after the owner and Claude agree.
Every number says where it came from.

## 1. The owner's goal and what was fixed before the study

The owner: "I want her to be closer to a real person, and this is the baseline and target I want to achieve." The
emotion model is to be driven by her agentic loop as it exists, with the full life cycle (generation → influence →
fading), and for each mood an account of how it changes not only her speech but how she thinks and decides. Prompt-cache
and context cost stay in view throughout.

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
| influence | the program, every turn | the projection as one paragraph: the state, its strongest causes where readable, and the pull of the strongest kind (D4); a person's feelings in that person's entry (D1); in the gate, nothing, or the public paragraph (§6, the owner's call) | `affect_from_program`, the person entry, the gate's material |
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
| D4 | **One paragraph instead of label, face, four slots and tendencies.** `interpret` writes: the band's face (as today), then 「主要因为」 and up to two causes with their coarse age where readable (home: all; public: those recorded in this conversation), then the pull: the tendency text of the strongest kind, as a tendency (「这会儿你会…」), never as a rule. At 平静 with no cause: one line. The slot rule texts are removed from what she reads; the slots stay in the persona model for the Web page | `affect_from_program` every turn, shorter | `affect.paragraph: false` keeps today's shape |
| D5 | **Recording guidance, neutral.** `feel`'s 「有触动才记」 becomes 「心里有起伏就记，好的坏的都记；记下来才算进心情」, and the description says a feeling about a person lands with that person. Model-facing wording of her own tool: put to her, as D2 and D3 | the tool list (one cold read per conversation at the install restart) | hers: the old wording |
| D6 | **The gate**: §6 | the gate's material | `affect.gate: none` |
| D7 | **Dice review shows the mood.** Each roll's reading in `dice_review_from_program` carries the band word at that beat, so she can see her own mood-behaviour links when she retunes the dice | the dice review | – |

Not in step 1: adaptation (§3.2), the appraiser route (stays off; she remains the only writer), any change to the
wake rates, the schedule or the proactive chances, and any program-side change of her tool set.

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
「可能来自别的对话」. **Decision proposed: the gate carries no mood text (D6, `affect.gate: none` as the default).**
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
| `affect_from_program`, public | about 300 (label, face, three slots, tendencies, note) | about 100–160 at a non-neutral band; one line (about 20) at 平静 |
| the gate's material | about 300 of mood in every gated question | `none`: 0, about 300 characters fewer in each of the roughly 50 gated questions a day (686 in 14 days, §2.1); `paragraph`: 100–160 at a non-neutral band, about 20 at 平静 |
| a person's entry | – | +20 to 40 characters while a feeling toward them is live |
| system prompt and tool list | – | `feel`'s description changes once (D5), the block guide line once: one cold read per conversation at the restart that installs it, as every install |
| model calls | – | none added; the appraiser stays off |
| cache | tail only | tail only; an unchanged paragraph is left out by delivery as today |

Characters are the stable unit (her text is Chinese; one character is about one token on this model, fewer on API
tokenizers).

## 9. Verification on her real records after install

Read-only, with Claude's scripts on the real ledger, 14 days after the restart that installs step 1. The reading is of
the mechanism, never a score of her.

- **The mood varies.** No band holds more than 60% of the hours; at least three bands occur; no band runs more than 48
  hours unbroken. Experience-sampling studies find mildly positive the usual state with negative states a minority of
  samples (Diener and Diener 1996), so the expected modal band is 不错 or 平静, not 愉快.
- **Person feelings land with persons.** The share of records with `who`, and the global sum's median (expected near
  Claude's recount, about 27, not 163).
- **The mood explains something.** Gate join rate, speech length and help-or-decline, each by band, from the audit and
  the turn records; a difference between bands in the direction of §4 is the pass. No difference after 14 days means
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
  in the gate's prompt. Proposed for step 2 after step 1 is read; it widens generation to where most of her day is.
- **Adaptation**, if §9 shows same-kind pinning.
- **Mood-congruent recall**: tilt retrieval toward memories whose feeling matches the mood. Real (Bower 1981) but it
  touches memory, which the owner gives observation time; not before step 1 is read.

## 11. Decisions that are the owner's

1. The gate's form (§6): no mood text at the gate (the research agent's recommendation, on G2), the D4 public
   paragraph (Claude's option), or a band word when the band is not neutral.
2. Whether step 2's gate feeling word (§10) waits for the 14-day reading or goes in with step 1.
3. D2 and D3 are persona changes: the owner decides whether they are put to her with this ADR or after it.

## 12. The study record

- Folder: `.runtime/private/emotion-research/` in the research worktree (local, never committed, removed by Claude
  when the study ends): `PLAN.md` (pre-registration), `run.py`, `analyse.py`, `gate.jsonl` (200 rows), `gate2.jsonl`
  (160 rows), `turn.jsonl` (256 rows), about 0.9 MB of model answers under synthetic names. The ADR keeps the
  tables; the rows are evidence only.
- The synthetic persona: four sentences (an AI character in a tech group, openly so; thinks before speaking; direct;
  speaks when she wants to; most members familiar faces, not friends). No real persona text, no real names.
- What the runs cannot show: a no-block baseline on her real records (none exists, §2.1), effects over hours (every
  run is one moment), and anything about her own records of feelings.
