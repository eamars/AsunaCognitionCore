# How human mood arises, acts and settles: research for ADR-086

Research for the owner, 2026-11-03 (NZDT). Research and a proposal only; nothing here is built.

## Summary

1. **Origin.** Mood is the slow, objectless part of affect. The brain keeps predicting what the body needs (energy, sleep, safety, other people), and mood is how that running balance feels. It rises out of recent emotions laid on top of temperament, and the body clock, sleep debt, hunger, illness and fatigue tilt it. It is measured on two axes, valence and arousal (§1).
2. **Impact.** A good mood widens attention and makes people quicker to say yes and to take a heuristic shortcut. A bad mood narrows attention and makes them slower and more careful. Anger is the bold negative state and fear the cautious one. Arousal speeds things up whatever the valence. The broad direction is well established, but most single lab effects are small (§2).
3. **Settling.** People settle mostly by **adapting**: the size of a feeling depends on how far the event beats what they expected, so the tenth routine success feels like nothing. Time also settles them, and so does closing the cause. Rumination drags it out and reappraisal speeds it up. Each person has a **home base** to return to, and that base is mildly positive. Experience sampling finds positive emotion about 2.5 times as often as negative, so mildly positive is the usual state and negative a minority of the time (§3).
4. **Sleep.** A night does **not** reset mood. Strong evidence: losing sleep lowers next-day positive mood (g ≈ −0.94) and raises anxiety, and a night's sleep predicts the next day's mood more than the day predicts the night. Mixed evidence: the claim that REM sleep takes the sting out of yesterday's emotions ("overnight therapy"). Weak evidence: the claim that sleep keeps emotional memories over neutral ones (two meta-analyses found no overall effect). A night lets arousal and the edge of settled feelings drop, keeps what is unresolved, and leaves expectations where they were (§4).
5. **Her mood.** It is pinned because the sum counts **how often** she feels something, not **how much**. A kind recorded n times a day, each fading over a half-life h, holds the sum near n × size × h / ln 2. Satisfaction alone (6.5 a day, 8 h half-life) holds about 39, above the 愉快 line of 25. The band lines are sized for one event, and nothing in the sum stands for expectation (§5).
6. **Recommendation.** A **same-kind repeat discount** read as expectation: positive kinds 0.7 and negative kinds 0.85 per earlier same-kind feeling in the last 24 h. Persona numbers, applied in the projection. It is the only option tested that un-pins the mood and stays steady in busy and quiet weeks alike. Two more changes: an **open (unsettled) feeling stops holding** once it survives a set number of nightly settlements, and the **night stays as it is**, with no reset of mood and no reset of the discount (§6–§8).

## 0. What I read and how I tested

- ADR-086 README §3–§4 and §9–§10, `progress.md`, `src/asuna/affect.py` (`project`, `from_words`, `describe`), the settlement block in `src/asuna/context.py`, and the persona's `affect` numbers: kinds and half-lives, the scale (轻微 8 / 明显 20 / 强烈 40), bands (愉快 ≥ 25, 不错 ≥ 8, 平静, 有点闷 ≤ −8, 低落 ≤ −25), arousal half-life 2 h.
- Measured facts from the brief: 愉快 in 82% of the last 7 days' hours, with a longest run of 97 h. About 20% of her events are negative. Satisfaction comes 6–7 times a day and gratitude 3–4. Her own reading for 10-20→10-27 (progress.md) was 99%. ADR §2.1 gives her intensity mix: positives about 63% at 8 and 37% at 20, negatives mostly at 8.
- **The simulation is synthetic and is not her ledger.** I did not query any database. The script is a scratch file, not part of the repository. It runs Poisson events over 16 waking hours a day for 28 days with 12 seeds. Rates: satisfaction 6.5, gratitude 1.5 (the global share), joy 1.5, curiosity 1, calm 0.5, unease 1.5, sadness 0.5 and irritation 0.9 a day, with her intensity mix and today's half-lives. Uncalibrated, this baseline gives 愉快 92% with a 206 h longest run, which is somewhat worse than her real 82%. Read its numbers as comparisons between options, not as predictions. Every option was also run at 1.5× and 0.5× the event rate, to stand for a busy week and a quiet one.
- Sources marked † were found and checked by web search during this research. The rest are standard references cited from knowledge whose title, year and venue I did not re-check here. No source was invented.

## 1. Where mood comes from

**Terms.** *Affect* is the umbrella: any felt good or bad. *Core affect* is the moment-to-moment feeling of pleasure or displeasure and of activation, with no object (Russell 2003, *Psychological Review*). An *emotion* is an episode about something: it has a cause and an appraisal, it is brief (seconds to hours), and it is intense. A *mood* is diffuse. It has no clear object, it is weaker, and it lasts hours to days (Beedie, Terry and Lane 2005, *Cognition and Emotion*; Frijda; Ekman). The lines are fuzzy. The working rule: an emotion answers "about what?" and a mood answers "how am I generally?"

**Two axes.** Valence (pleasant or unpleasant) and arousal (activated or quiet) are the most replicated structure of self-reported affect (Russell 1980, 2003). Some researchers rotate them into positive and negative activation (Watson and Tellegen 1985) or energy and tension (Thayer 1989). Positive and negative are partly separate systems: people can feel both at once (Cacioppo, Gardner and Berntson 1999 †, *JPSP*; Larsen, McGraw and Cacioppo 2001). Two of their properties matter for her:
- The **positivity offset**: when little is happening the system leans slightly positive.
- The **negativity bias**: per unit of input, negative rises faster.

**What generates it in the body.**
- **Interoception and the body budget.** The brain keeps predicting the body's needs (glucose, water, temperature, immune state, effort) and corrects for error. Affect is largely how those predictions feel (Barrett and Simmons 2015 †, *Nature Reviews Neuroscience*, the "EPIC" model). Mood is the slow read-out of how the budget is running. Strong as a framework; the specific mechanisms are still being tested.
- **Neuromodulators.**
  - Dopamine signals reward *prediction error* and "wanting" (Schultz 1997).
  - Opioid and endocannabinoid "hotspots" carry "liking" (Berridge and Kringelbach 2015, *Neuron*).
  - Noradrenaline from the locus coeruleus carries arousal.
  - The HPA axis and cortisol carry stress load. Cortisol peaks about 30–45 min after waking (the cortisol awakening response).
  - Serotonin modulates mood, but the "low serotonin causes depression" story is not supported: an umbrella review found no consistent evidence (Moncrieff et al. 2022 †, *Molecular Psychiatry*; contested by others).
  - Moral for modelling: no single chemical stands for "mood".
- **Inflammation.** Immune signals (IL-1β, TNF-α) reaching the brain produce "sickness behaviour": low mood, withdrawal and fatigue (Dantzer et al. 2008 †, *Nature Reviews Neuroscience*). Strong in animals and moderate in humans.
- **Circadian and homeostatic drives.**
  - Positive affect follows the body clock: low on waking, highest late morning to afternoon, falling in the evening. In forced-desynchrony studies it tracks core body temperature apart from the sleep–wake cycle (Murray et al. 2009 †, *Emotion*; Clark, Watson and Leeka 1989 †, *Motivation and Emotion*).
  - Negative affect shows little or no daily rhythm in most studies, though not all.
  - Sleep pressure (adenosine; Borbély's two-process model) adds the homeostatic part: the longer awake, the lower the positive affect and the shorter the fuse.
- **Hunger and fatigue.** Hunger makes people irritable only in context: hungry people read ambiguous things as negative when the setting is already negative, and not when they are attending to their own feelings (MacCormack and Lindquist 2019 †, *Emotion*). Fatigue works the same way: it lowers positive affect and the capacity to regulate.

**What this means for an AI character.** She has no body budget, clock, glucose or cytokines, and faking them would be invented physiology. What carries over is the *architecture*:
- Mood is a slow summary of recent appraised events on top of a home base.
- Events count by how far they depart from expectation.
- Valence and arousal are separate, and arousal is fast and valence slow.
- Positive and negative can coexist.

Do not model hunger, cortisol or circadian valence. The one honest analogue of a body clock is her own night: the settlement turn, which is her daily review (§4, §7).

## 2. What mood does (the impact map)

Evidence grades: **strong** = many studies or meta-analyses agree; **mixed** = the direction is reported but effects are small or replications vary; **weak** = few studies.

| domain | positive mood | negative mood | arousal | evidence |
|---|---|---|---|---|
| attention | broader, more global (Fredrickson 2001); but high-*approach* positive states such as desire narrow it (Gable and Harmon-Jones 2010) | narrower, local, detail-focused | high arousal narrows attention to what is central (Easterbrook 1959) | mixed (broaden: small lab effects; the motivational-intensity refinement is better supported) |
| perception and appraisal | ambiguous things read as more benign; mood is taken as information about the object (Schwarz and Clore 1983) unless its real cause is salient | ambiguous things read as threats; hunger and fatigue amplify this in a negative context | | strong for mood-as-information and the attribution effect; the salience-of-cause reduction is shown in her own §2.3 runs |
| memory | mood-congruent recall: happy memories come easier when happy (Bower 1981) | sad recall when sad; rumination loops | arousal at encoding strengthens memory of the central detail | mixed: robust for self-referential material, weaker otherwise |
| judgement style | heuristic, top-down, more stereotypes and more creativity (Forgas 1995, Affect Infusion Model; Isen 1987) | systematic, careful, fewer judgement errors, better at spotting deception (Forgas 2013) | | mixed to strong in the lab; small effects |
| decisions and risk | optimistic estimates. When a real loss is possible, happy people protect the mood and *avoid* risk (Isen and Patrick 1983) | **fear** raises perceived risk and pushes toward caution. **Anger** lowers perceived risk, raises certainty, and makes people blame others and act (Lerner and Keltner 2001; Lerner et al. 2015 review) | | strong for the fear/anger contrast; valence alone predicts poorly |
| social behaviour | more helping, more approach, more self-disclosure (Carlson, Charlin and Miller 1988 meta-analysis) | sadness: withdrawal but more politeness and more careful requests (Forgas 1999). Anger: confrontation | | strong for helping (moderate effect) |
| speech | more words, more abstract and global language (Beukeboom and Semin 2006), more exclamations | fewer words, more concrete and hedged; first-person singular rises in sadness | arousal shortens sentences and speeds speech | mixed |
| motivation | good mood is a resource: people in a good mood choose useful but unpleasant tasks, and people in a bad mood choose mood-repairing ones (Taquet et al. 2016 †, *PNAS*, 28,000 people by app) | low positive mood = less drive (anhedonia at the extreme) | | strong (large field sample) |

Two points matter more than any single row:
- **Discrete emotions beat valence for behaviour.** Anger and fear are both negative but push decisions in opposite directions, and contentment and excitement both positive but differ in arousal. Her `kind` already carries this, and §4 of the ADR uses it correctly.
- **Mood also regulates itself through behaviour** (Taquet et al. 2016). A good mood is spent on chores and a bad one repaired by chosen activities. This is a real homeostat in people: they act on the mood and the acts bring it back.

**What this means for her.** Keep the mood's influence as information plus a *tendency* by kind, which is what D4 already does. Showing the cause is exactly what the mood-as-information literature says reduces the misattribution. Do not add program rules that make her join more when happy: the effects are small and context-bound, and the model already shows them by itself (§2.3 of the ADR). Mood-congruent recall stays a later step, as §10 says.

## 3. How mood settles

### 3.1 Episode against mood: two clocks

- **An emotion episode** fades within seconds to hours. How long it lasts depends far more on the event than on the emotion's type:
  - Event importance and rumination together explain about half the variation in duration (Verduyn and Lavrijsen 2015 †, *Motivation and Emotion*; Verduyn et al. 2009, *Emotion*).
  - In recalled episodes, sadness lasted longest (median around days; press figures of ~120 h) and shame, disgust, surprise, fear, irritation and relief shortest (tens of minutes).
  - Recurrence of the cause, or reminders of it, lengthens an episode.
  - Grade: moderate (recall-based).
- **A mood** is the slower residue. Day to day it shows *inertia* (the autocorrelation of affect). More inertia goes with *lower* well-being (Houben, Van Den Noortgate and Kuppens 2015 †, *Psychological Bulletin*, 79 studies: inertia ρ ≈ −.15). Healthy affect moves and comes back.
- **The home base.** The DynAffect model (Kuppens, Oravecz and Tuerlinckx 2010 †, *JPSP*) describes each person's affect with four quantities:
  - a **home base** (attractor) it returns to;
  - **variability** around it;
  - an **attractor strength**: how fast it returns after a push;
  - noise.
  This is the closest scientific picture of "settling".

### 3.2 Adaptation: the main settler

- **The treadmill and its limits.** People return toward a baseline after most events (Brickman and Campbell 1971; Frederick and Loewenstein 1999). The baseline is not fixed and adaptation is not complete:
  - Unemployment, disability and widowhood leave lasting drops, with large individual differences (Lucas 2007 †, *Current Directions*; Diener, Lucas and Scollon 2006).
  - Life events affect *cognitive* well-being (life satisfaction) more consistently than *affective* well-being (Luhmann et al. 2012 †, *JPSP*, a meta-analysis of 188 publications).
  - Grade: strong.
- **Adaptation depends on valence and domain.**
  - The common claim is that people adapt faster to good than to bad. Direct evidence is limited and context-dependent (Larsen and Prizmic 2008; Lyubomirsky 2011 † chapter).
  - What *is* well supported is that bad is stronger than good per unit (Baumeister et al. 2001), and that the lasting changes come from losses.
  - Grade: mixed on adaptation speed, strong on negativity bias.
- **What slows positive adaptation: variety and surprise.** Gains from a positive change erode through fewer positive events and rising expectations. Appreciation and *variety* within the change slow the erosion (Sheldon and Lyubomirsky 2012 †, the Hedonic Adaptation Prevention model). Repeating the same good thing adapts fastest.
- **The computational version: mood tracks surprise, not totals.**
  - Momentary happiness in reward tasks is predicted by recent *expectations and reward prediction errors*, not by accumulated winnings (Rutledge et al. 2014 †, *PNAS*, replicated on 18,420 people by app). A later study found happiness follows *learning-relevant* surprises (Blain and Rutledge 2020 †, *eLife*).
  - Mood is "the momentum" of how things have recently gone *relative to expectation* (Eldar, Rutledge, Dolan and Niv 2016 †, *Trends in Cognitive Sciences*).
  - Carver and Scheier (1990) say the same from control theory: affect signals the *rate* of progress against an expected rate, so meeting the expected pace feels neutral.
  - Grade: strong in lab tasks; real-life generality is plausible but less tested.
- **Habituation** is the basic form of all this. A response to a repeated stimulus declines. It recovers in part after a pause (spontaneous recovery), and faster after rapid repetition (Rankin et al. 2009 †, *Neurobiology of Learning and Memory*). That short-term recovery is *not* the same as long-term hedonic adaptation, which spans days and does not reset overnight.

### 3.3 Regulation: what people do to settle

- **Reappraisal** (changing the meaning) reduces emotion with a small-to-medium effect. Distraction-type attention deployment and suppression do less (Webb, Miles and Sheeran 2012 †, *Psychological Bulletin*). Grade: strong.
- **Affect labelling.** Putting a feeling into words lowers its intensity, implicitly, without feeling like regulation (Lieberman et al. 2007; Torre and Lieberman 2018 †, *Emotion Review*). Grade: moderate (effects are real but modest). Her `feel` record is a label, and her `think` is a place for reappraisal.
- **Rumination** prolongs negative mood, and sadness most (Nolen-Hoeksema, Wisco and Lyubomirsky 2008; Verduyn and Lavrijsen 2015). Grade: strong.
- **Social sharing.** People share 80–95% of emotional episodes (Rimé 2009 †, *Emotion Review*). Merely talking about an event does *not* by itself lower its emotional load, though people feel it helped and it builds closeness (Zech and Rimé 2005 †). What helps is sharing that leads to reframing or to resolving the cause. Grade: moderate.
- **Resolution of the cause.** Goal attainment, an apology or closure ends the appraisal that sustained the feeling. Unresolved or recurring causes prolong it (Verduyn et al. 2009). Relief itself is short. Grade: moderate.
- **Opponent process.** Strong or repeated affect can be followed by a rebound of the opposite sign: the dip after a high, the relief after fear (Solomon and Corbit 1974). Grade: weak to mixed for everyday mood. It is real for drugs and some intense experiences but not a general law of daily affect.

### 3.4 Individual differences

- **Baseline affect.** The home base differs by person and is partly heritable and stable. Most people's home base is mildly positive: in Diener and Diener (1996, *Psychological Science*) most people rate themselves above neutral.
- **Neuroticism** means more exposure to stressors, stronger reactions, more **spillover of bad mood into the next day**, and more rumination (Suls and Martin 2005 †, *Journal of Personality*). In the model's terms that is longer negative half-lives, stronger negative weights and slower discharge. Extraversion goes with higher positive affect.
- Personality would sit in **persona numbers**: half-lives, factors, a home base. Nothing about it belongs in the core.

### 3.5 What everyday affect looks like (experience sampling)

- Positive emotions were reported **2.5 times as often as negative**; at least one emotion was present 90% of the time; joy was the most frequent, then love, then anxiety. Mixed positive and negative was common (Trampe, Quoidbach and Taquet 2015 †, *PLoS ONE*, 11,000+ people). On those counts negative feeling is present in roughly a quarter to a third of samples, usually mildly.
- **"Mildly positive" is the modal state**: the positivity offset (Cacioppo et al. 1999 †; Diener and Diener 1996).
- Kahneman and Krueger's U-index (2006 †, *Journal of Economic Perspectives*) measures the share of time in an unpleasant state. I could not retrieve the paper's own figures, so I give none.

**What this means for her.** Settling in people is mostly **expectation-relative**, not time-only. A routine good thing adapts fast. Variety adapts slower. Bad events weigh more and fade slower. Unresolved causes hold. Discharge comes from resolution and reappraisal, not from talking alone. The target picture is a mildly positive mood most of the time, real dips when real causes come, and returns within hours to days. That matches §9's expectation in the ADR (modal band 不错 or 平静) and gives it a source.

## 4. The sleep question: should a night settle the mood?

| claim | evidence | grade |
|---|---|---|
| Losing sleep lowers next-day **positive** affect and raises anxiety | Tomaso, Johnson and Nelson 2021 † (*Sleep*, 64 studies): positive mood g = −0.94, negative mood g = +0.45. Palmer et al. 2024 † (*Psychological Bulletin*, 154 studies, N = 5,717): all forms of sleep loss lower positive affect, raise anxiety and blunt arousal to emotional stimuli; effects on negative affect are mixed | **strong** |
| Sleep loss amplifies emotional reactivity | amygdala responses to negative pictures about 60% larger, with weaker prefrontal coupling (Yoo et al. 2007 †, *Current Biology*); also amplified reactivity to rewards (Gujar et al. 2011) | moderate (small samples, consistent direction) |
| Last night's sleep predicts today's mood more than today's mood predicts tonight's sleep | Triantafillou et al. 2019 † (*JMIR Mental Health*, 6 weeks of daily data); Konjarski et al. 2018 † (*Sleep Medicine Reviews*, a review of naturalistic studies) | moderate to strong |
| A night of REM sleep **takes the edge off** yesterday's emotional experiences ("overnight therapy"; "sleep to forget, sleep to remember": keep the memory, strip the feeling) | proposed by Walker and van der Helm 2009 † (*Psychological Bulletin*). Supported by van der Helm et al. 2011 † (*Current Biology*: amygdala reactivity and ratings fell after REM-rich sleep) and Wassing et al. 2019 † (*Current Biology*: consolidated REM lowers amygdala reactivity overnight, restless REM prevents it). Contradicted by Baran et al. 2012 † (*Journal of Neuroscience*: reactivity *preserved* over sleep and *reduced* over wake) | **mixed** |
| Sleep preferentially keeps **emotional** memories over neutral ones | two meta-analyses found no overall preferential effect: Lipinska et al. 2019 † (*Frontiers in Psychology*, 31 studies) and Schäfer et al. 2020 † (*Sleep Medicine Reviews*). A small REM/SWS subset hints at one | **weak** |
| Mood has a daily shape: positive affect rises through the morning and falls in the evening, negative affect is flatter | Clark, Watson and Leeka 1989 †; Murray et al. 2009 †; Twitter data (Golder and Macy 2011 †, *Science*: positive language peaks in the morning, shifted about 2 h later on weekends, consistent with sleep timing) | moderate (positive affect); mixed (negative affect) |
| Bad mood spills over into the next day, more so in neurotic people | Suls and Martin 2005 † | moderate |

**Answer.** A night does not wipe the slate:
- **Settled** feelings lose their edge and arousal drops to its low morning level.
- Memory of what happened is kept.
- **Unresolved** matters carry over and are what people wake up thinking about.
- What people expect does not reset: the routine pleasure is still routine the next morning.
- How *well* one slept moves the next day: a poor night costs positive mood. A good night does not add mood; it gives back the capacity to feel and regulate.

**For her.** She does not sleep and has no sleep debt, so do not simulate one. Her nightly settlement already does what a night does in the parts that matter:
- **"Sleep on it"**: she is shown what is still open and may close, void or keep it.
- **"Sleep to remember"**: memory promotion.

What the night should *not* do:
- **Reset valence.** The evidence is mixed. Her half-lives already shrink an evening's mild feelings by morning: an 8 h half-life leaves a quarter after 16 h. A reset would also cut the long feelings that ought to carry.
- **Reset the expectation memory.** Tested: resetting the repeat discount each night re-pins her (§6, E′).

Arousal needs no night rule either: its 2 h half-life brings it to zero long before morning, which is the human pattern.

## 5. Her ledger read against the science

**The broken invariant.** The band lines (愉快 ≥ 25) are sized like *one feeling* (one 明显 event is 20, one 强烈 is 40). The projection sums *every* feeling over its half-life. A kind recorded at rate r per hour with mean size s and half-life h holds the sum near **r × s × h / ln 2** in steady state.

| kind | per day | half-life | steady contribution at her mean size (12.4) |
|---|---|---|---|
| satisfaction | 6.5 | 8 h | ≈ 39 |
| gratitude, if global | 3.5 | 24 h | ≈ 63 |
| gratitude, the share left global in the simulation | 1.5 | 24 h | ≈ 27 |

So the band reads **how often** she records a feeling, not how strongly, and the 愉快 line is crossed by routine alone. People do not work this way. The tenth routine satisfaction is expected and moves almost nothing (§3.2). The sum has no expectation, so routine events count as fully surprising every time.

Her negatives are small, mostly 8, at 20% of events. Their kinds' half-lives (unease and sadness 12 h, irritation 6 h) are now equal to or longer than satisfaction's, which follows the ADR's D2. Even so, negative bands hardly ever appear, because a few small negatives cannot outweigh a continuous positive stream. This is right as far as it goes: the mood should follow her recorded causes (her condition in §9). But it means any fix that only shortens positives makes the mood **rate-sensitive**: a busy week pins it again (F below).

## 6. The options, side by side

Each was run on the same synthetic stream. Percentages are shares of hours by band, followed by the median longest unbroken 愉快 run. "Busy" and "quiet" are 1.5× and 0.5× the event rate.

| option | basis in the evidence | normal week | busy / quiet week | cost | failure modes |
|---|---|---|---|---|---|
| **A. Today** (sum of decays) | none for routine events | 愉快 92, 206 h | 98 / 60 | none | pinned by event rate; bands read frequency |
| **B. Same-kind repeat discount** (each earlier feeling of the same kind in the last 24 h multiplies a new one by f) | habituation; reference-dependent affect (Rutledge 2014; Carver and Scheier 1990); same-kind specifically because variety slows adaptation (Sheldon and Lyubomirsky 2012) | f = 0.7 for all kinds: 不错 52, 愉快 33, 平静 15; 38 h | about the same both ways (28 h / 22 h) | small: one pass over earlier events in `project()`; persona numbers; reversible, no history converted | (1) It is a count, not a size: a strong feeling after several mild ones is cut as much as a mild one; exempting stronger ones weakened the effect (愉快 58%). (2) In steady state a kind felt n times a day weighs about f^(n−1) each (0.7^5.5 ≈ 0.14 for satisfaction), so routine kinds nearly vanish. That is the point, but it is steep. (3) Discounting negatives as hard as positives conflicts with slow negative adaptation |
| B′. B with **positive 0.7, negative 0.85** | adds the valence asymmetry (negativity bias; slower adaptation to bad) | 不错 50, 愉快 28, 平静 20, 有点闷 2; 34 h | 27 h / 22 h, distribution unchanged | as B, one more number | as B, milder for negatives |
| B″. B on **positives only** (negatives 1.0) | strongest version of the asymmetry | 不错 44, 平静 26, 愉快 24, 有点闷 5; 24 h | busy: 有点闷 11, 低落 3 | as B | a busy week drifts **negative** even when 80% of her feelings are good: positives are capped and negatives grow with volume |
| B‴. B with a **fading memory** (count decays with a 12 h half-life, no window) | same as B, smooth | 不错 45, 愉快 40; 40 h | stable | slightly more to explain | very sensitive to the memory length: with 24 h memory, 愉快 falls to 8%; with negatives undiscounted, a busy week goes to 有点闷 25% |
| **C. Prediction-error scaling** (impact = 1 / (1 + a × recent same-kind count)) | the closest to Rutledge 2014 and Eldar 2016 | 愉快 55, 不错 38; 48 h | busy 72 / quiet 30 | as B | gentler, so it un-pins less and stays rate-sensitive; more tuning |
| **D. Set point follows recent level** (subtract 0.6 × a 72 h moving average of the mood) | treadmill; DynAffect's home base; opponent process | 愉快 40, 不错 28, 平静 23, **有点闷 9** | 62 / 23, 有点闷 6–13 | adds state over time; must be recomputed from the ledger to survive restarts | creates **bad moods with no bad cause** (the contrast dip after a good run). That breaks her own verification condition that the mood matches its causes, and the description would have no reason to show |
| **E. Overnight partial reset** (each local 04:00 crossed keeps half of every residual; 0.3 tried too) | the mixed REM evidence; the morning dip in arousal | keep 0.5: 愉快 67, 47 h; keep 0.3: 57, 19 h | keep 0.5: busy 85 | trivial; clock-based | does not touch the cause (rate × duration within a day); erases long feelings that should carry; a step in the mood at 04:00; must exempt open events |
| E′. Night resets the **expectation** (discount counts only since last night) | short-term habituation recovers after rest (Rankin 2009) | 愉快 63, 66 h | busy 71 | as B | **re-pins**: each morning's first routine feelings land at full strength. Hedonic adaptation spans days, so the night should not reset it |
| **F. Valence-asymmetric decay** (positive half-lives × 0.5) | bad stronger than good; faster positive adaptation (mixed) | 愉快 37, 不错 33, 平静 23, 有点闷 6; 23 h | busy 58 / quiet: 平静 39 | none in code; persona numbers only | still rate × duration, so a busy week re-pins; shortens single big joys too |
| **G. Duration by intensity** (轻微 lasts 0.35 × its kind's half-life) | Verduyn: importance predicts duration more than the type of emotion | 愉快 82, 103 h | busy 94 | small: a multiplier per intensity word in the persona scale | barely un-pins alone; worth it for realism, not as the fix |
| **H. Home base** (add a persona constant, e.g. +10) | DynAffect home base; positivity offset | alone: 愉快 97 | — | trivial | alone it **worsens** pinning. It makes sense only after adaptation exists, to say what "nothing happening" feels like, and it is a mood with no cause |
| **I. Re-draw the bands** (raise the lines, or bands by her own percentiles) | experience-sampling studies centre affect on the person's own mean | whatever is chosen | rate-sensitive if fixed; with percentiles every week looks the same | trivial | hides the dynamics instead of fixing them; percentile bands are complete adaptation in disguise (as D) |
| **J. Discharge on resolution** (`close`; a closed negative could fade faster than its kind's half-life) | resolution ends the appraisal; relief is short (Verduyn 2009) | no effect on pinning (positives are not held) | — | small | none for pinning; it is a life-cycle fix (§7) |

**Combinations tried:**
- B + E (night 0.5): 不错 45, 平静 38, 愉快 15; 12 h. It over-damps.
- B + E + H: 不错 57, 愉快 36, 平静 7; 19 h.
- C + E + H: 愉快 52, 不错 45; 27 h.
- None of them beats B′ alone on simplicity or on steadiness across busy and quiet weeks.

## 7. The proposed life cycle

Every stage below is a pure function of the ledger and the clock, so it survives a restart without any counter kept in memory.

| stage | human picture | today | proposal | what changes and why |
|---|---|---|---|---|
| **Create** | an appraisal turns an event into an emotion; its size is its departure from expectation | `feel` records kind, intensity, cause and `who`; size = intensity word | keep recording as is. Her record is the raw appraisal; the program never appraises | nothing |
| **Weigh** (new) | routine adapts; variety does not; bad adapts slower | every event counts in full | **same-kind repeat discount in the projection**: weight = f^(number of earlier non-void events of the same kind, in the same `who` scope, in the 24 h before it). Persona numbers: `repeat_discount` per valence or per kind (proposed positive 0.7, negative 0.85). Core default 1.0 (off). An event's weight is fixed by what came before it, so it never changes later and the mood curve has no cliff | the routine stream stops reading as joy. The discount is an expectation: the n-th satisfaction of the day is expected. A different kind still lands in full |
| **Use** | mood as information plus a tendency | band and description each turn; causes shown (D4) | keep. Optionally show the *weighted* size in the contributions so the description reads the same as the band | consistency only |
| **Decay** | episodes fade by importance and rumination; sadness longest | per-kind half-life | keep. Persona: negative half-lives at least as long as positive (D2, done). Later and optional: duration by intensity (G) | nothing now |
| **Hold** (rumination) | unresolved causes hold the feeling | `open` holds at full strength until closed; settlement lists it | keep, and **give the hold an end**: an open event still open after N nightly settlements (persona number, e.g. 3) starts decaying from that settlement as if closed, and the settlement after that says so. Even sadness ends in days | a state with no discard path otherwise. A forgotten open event would hold the mood for ever |
| **Discharge** | resolution or reappraisal ends it | `close` with `from_close` decay | keep. Optional later: a persona half-life for closed events (relief is short) | nothing now |
| **Night** | arousal falls; settled feelings lose their edge; unresolved ones carry; expectations do not reset | settlement turn: open list, memory promotion; no mood rule | **no valence reset, no expectation reset.** The settlement is the night: she reviews what is open (sleep on it) and promotes memories (sleep to remember). Arousal's 2 h half-life already gives a quiet morning | none; the research says the current design is right here |
| **Restart** | (no human analogue; a restart is not sleep) | projection recomputed from the ledger at wall-clock time; downtime counts as time passed | keep. Any new mechanism must stay a pure function of events and the clock (B is; D's moving average would need recomputing from history) | a requirement, not a change |
| **Interact** | kinds coexist; mixed feelings are common; feelings toward a person stay with that person | signed sum across kinds; `who` events in the person's projection | keep. The discount works per kind, so variety is never discounted against itself. It works per scope, so repeated gratitude toward one person adapts in that person's entry | nothing |
| **Individuality** | home base, reactivity, spillover | persona half-lives | the persona holds the discount factors and the open-hold limit. A home base stays 0 unless the persona later wants one (H), and only on top of B | persona-agnostic core kept |

## 8. Recommendation

**Build B′ (positive 0.7, negative 0.85, the 24 h rolling count, persona numbers) plus the open-hold end. Change nothing about the night.**

Why B′:
- It is the only tested option that un-pins the mood *and* gives the same shape in a busy week and a quiet one. In the synthetic run that shape is 不错 about 50% of hours, 愉快 about 25–30%, 平静 about 20%, with the longest 愉快 run 22–34 h. Today: 92% and 206 h.
- Claude simulated the same discount independently on her real ledger with the core's own weights (0.7 positive / 0.85 negative: 愉快 36%, longest run 38 h; `sim_repeat_discount.py`). The science gives it a meaning: it is a discrete stand-in for **expectation-relative affect** (Rutledge, Eldar, Carver and Scheier) applied **per kind** because **variety resists adaptation** (Sheldon and Lyubomirsky). The weaker negative factor is the **negativity bias**.
- It lands on the experience-sampling picture: mildly positive is the modal state.

Cost:
- About 15 lines in `project()`, two numbers in the persona model, and a line in the ADR. No history is converted and the off switch is 1.0.
- To verify, run the same §9 reading again for 7 days, plus one check: the weighted top kinds should still name her real causes.

Cost of the alternatives:
- **F (shorter positive half-lives)** is zero code and works on a normal week. But a busy week re-pins it (58%), and it changes the meaning of every positive, big ones included. It is the cheapest fallback if the owner wants no code.
- **C (prediction-error scaling)** is the most faithful to the science, but it un-pins less (55%) and stays rate-sensitive. Its extra parameters buy little.
- **D (moving set point)** produces negative moods without negative causes, against her own condition on the reading.
- **E (night reset)** un-pins only partly, rests on mixed evidence, and erases feelings that should carry. **E′** re-pins.
- **I (bands)** hides the mechanism; **H** worsens it alone.

Watch after install:
1. Whether a genuinely big repeat (a second 强烈 of the same kind) is under-counted. If so, the fix is to discount by expected size, not by count.
2. Whether negatives become visible only through volume.
3. The open-hold limit firing. It should be rare.

## Sources

† = found and checked by web search for this report. Others: standard references cited from knowledge; title, year and venue not re-checked here.

- Baran B. et al. (2012). Processing of emotional reactivity and emotional memory over sleep. *J Neuroscience*. † https://pmc.ncbi.nlm.nih.gov/articles/PMC3548452
- Barrett L.F., Simmons W.K. (2015). Interoceptive predictions in the brain. *Nat Rev Neurosci* 16:419–429. † https://pmc.ncbi.nlm.nih.gov/articles/PMC4731102/
- Baumeister R.F., Bratslavsky E., Finkenauer C., Vohs K.D. (2001). Bad is stronger than good. *Rev Gen Psychol*.
- Beedie C., Terry P., Lane A. (2005). Distinctions between emotion and mood. *Cognition and Emotion*.
- Berridge K.C., Kringelbach M.L. (2015). Pleasure systems in the brain. *Neuron*.
- Blain B., Rutledge R.B. (2020). Momentary subjective well-being depends on learning and not reward. *eLife*. † https://elifesciences.org/articles/57977
- Brickman P., Campbell D.T. (1971). Hedonic relativism and planning the good society.
- Cacioppo J.T., Gardner W.L., Berntson G.G. (1999). The affect system has parallel and integrative processing components. *JPSP* 76:839–855. †
- Carlson M., Charlin V., Miller N. (1988). Positive mood and helping behavior: a test of six hypotheses. *JPSP*.
- Carver C.S., Scheier M.F. (1990). Origins and functions of positive and negative affect: a control-process view. *Psychol Rev*.
- Clark L.A., Watson D., Leeka J. (1989). Diurnal variation in the positive affects. *Motivation and Emotion* 13:205–234. †
- Dantzer R. et al. (2008). From inflammation to sickness and depression. *Nat Rev Neurosci* 9:46–56. † https://pmc.ncbi.nlm.nih.gov/articles/2919277
- Diener E., Diener C. (1996). Most people are happy. *Psychol Sci*.
- Diener E., Lucas R.E., Scollon C.N. (2006). Beyond the hedonic treadmill. *Am Psychol*.
- Eldar E., Rutledge R.B., Dolan R.J., Niv Y. (2016). Mood as representation of momentum. *Trends Cogn Sci* 20:15–24. † https://pmc.ncbi.nlm.nih.gov/articles/PMC4703769/
- Forgas J.P. (1995). Mood and judgment: the affect infusion model. *Psychol Bull*; (1999) On feeling good and being rude. *JPSP*; (2013) Don't worry, be sad! *Curr Dir Psychol Sci*.
- Frederick S., Loewenstein G. (1999). Hedonic adaptation. In *Well-Being*.
- Fredrickson B.L. (2001). The role of positive emotions in positive psychology. *Am Psychol*.
- Gable P., Harmon-Jones E. (2010). The motivational dimensional model of affect. *Cognition and Emotion*.
- Golder S.A., Macy M.W. (2011). Diurnal and seasonal mood vary with work, sleep, and daylength across diverse cultures. *Science*. † https://www.sciencedaily.com/releases/2011/09/110929144632.htm
- Gross J.J. (1998). The emerging field of emotion regulation. *Rev Gen Psychol*.
- Houben M., Van Den Noortgate W., Kuppens P. (2015). The relation between short-term emotion dynamics and psychological well-being: a meta-analysis. *Psychol Bull* 141:901–930. †
- Isen A.M. (1987). Positive affect, cognitive processes, and social behavior; Isen A.M., Patrick R. (1983) on positive affect and risk.
- Kahneman D., Krueger A.B. (2006). Developments in the measurement of subjective well-being. *J Econ Perspect* 20(1):3–24. † (U-index definition; no figures quoted)
- Konjarski M., Murray G., Lee V.V., Jackson M.L. (2018). Reciprocal relationships between daily sleep and mood. *Sleep Med Rev* 42:47–58. † (citation checked; findings not read)
- Kuppens P., Oravecz Z., Tuerlinckx F. (2010). Feelings change: accounting for individual differences in the temporal dynamics of affect. *JPSP* 99:1042–1060. †
- Lerner J.S., Keltner D. (2001). Fear, anger, and risk. *JPSP*; Lerner J.S. et al. (2015). Emotion and decision making. *Annu Rev Psychol*.
- Lieberman M.D. et al. (2007). Putting feelings into words. *Psychol Sci*.
- Lipinska G. et al. (2019). Preferential consolidation of emotional memory during sleep: a meta-analysis. *Front Psychol*. † https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2019.01014/full
- Lucas R.E. (2007). Adaptation and the set-point model of subjective well-being. *Curr Dir Psychol Sci* 16:75–79. †
- Luhmann M., Hofmann W., Eid M., Lucas R.E. (2012). Subjective well-being and adaptation to life events: a meta-analysis. *JPSP* 102:592–615. † https://pmc.ncbi.nlm.nih.gov/articles/PMC3289759
- Lyubomirsky S. (2011). Hedonic adaptation to positive and negative experiences. In *Oxford Handbook of Stress, Health, and Coping*. † https://sonjalyubomirsky.com/wp-content/uploads/2024/03/Lyubomirsky-2011.pdf
- MacCormack J.K., Lindquist K.A. (2019; online 2018). Feeling hangry? *Emotion*. †
- Moncrieff J. et al. (2022). The serotonin theory of depression: a systematic umbrella review. *Mol Psychiatry*. †
- Murray G. et al. (2009). Nature's clocks and human mood: the circadian system modulates reward motivation. *Emotion*. †
- Nolen-Hoeksema S., Wisco B., Lyubomirsky S. (2008). Rethinking rumination. *Perspect Psychol Sci*.
- Palmer C.A. et al. (2024). Sleep loss and emotion: a systematic review and meta-analysis of over 50 years of experimental research. *Psychol Bull* 150:440–463. † https://pubmed.ncbi.nlm.nih.gov/38127505/
- Rankin C.H. et al. (2009). Habituation revisited. *Neurobiol Learn Mem* 92:135–138. † https://pmc.ncbi.nlm.nih.gov/articles/PMC2754195/
- Rimé B. (2009). Emotion elicits the social sharing of emotion. *Emotion Review* 1:60–85. † https://journals.sagepub.com/doi/10.1177/1754073908097189
- Russell J.A. (2003). Core affect and the psychological construction of emotion. *Psychol Rev*.
- Rutledge R.B., Skandali N., Dayan P., Dolan R.J. (2014). A computational and neural model of momentary subjective well-being. *PNAS* 111:12252–12257. † https://pmc.ncbi.nlm.nih.gov/articles/PMC4143018
- Schäfer S.K. et al. (2020). Sleep's impact on emotional recognition memory: a meta-analysis of whole-night, nap, and REM sleep effects. *Sleep Med Rev* 51:101280. †
- Schwarz N., Clore G.L. (1983). Mood, misattribution, and judgments of well-being. *JPSP*.
- Sheldon K.M., Lyubomirsky S. (2012). The challenge of staying happier: testing the Hedonic Adaptation Prevention model. *PSPB*. † https://sonjalyubomirsky.com/wp-content/uploads/2024/07/Sheldon-Lyubomirsky-2012.pdf
- Solomon R.L., Corbit J.D. (1974). An opponent-process theory of motivation. *Psychol Rev*.
- Suls J., Martin R. (2005). The daily life of the garden-variety neurotic. *J Personality* 73:1485–1510. †
- Taquet M., Quoidbach J., de Montjoye Y.-A., Desseilles M., Gross J.J. (2016). Hedonism and the choice of everyday activities. *PNAS* 113:9769–9773. †
- Tomaso C.C., Johnson A.B., Nelson T.D. (2021). The effect of sleep deprivation and restriction on mood, emotion, and emotion regulation: three meta-analyses in one. *Sleep* 44(6). † https://pmc.ncbi.nlm.nih.gov/articles/PMC8193556/
- Torre J.B., Lieberman M.D. (2018). Putting feelings into words: affect labeling as implicit emotion regulation. *Emotion Review* 10:116–124. †
- Trampe D., Quoidbach J., Taquet M. (2015). Emotions in everyday life. *PLoS ONE*. † https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4689475/
- Triantafillou S. et al. (2019). Relationship between sleep quality and mood: ecological momentary assessment study. *JMIR Ment Health* 6(3):e12613. † https://pmc.ncbi.nlm.nih.gov/articles/PMC6456824
- van der Helm E. et al. (2011). REM sleep depotentiates amygdala activity to previous emotional experiences. *Current Biology*. † https://pmc.ncbi.nlm.nih.gov/articles/PMC3237718
- Verduyn P., Lavrijsen S. (2015). Which emotions last longest and why. *Motivation and Emotion* 39. † https://ppw.kuleuven.be/okp/_pdf/Verduyn2015WELLA.pdf
- Verduyn P. et al. (2009). Predicting the duration of emotional experience. *Emotion*. (title from knowledge; the importance–duration finding confirmed through citing sources)
- Walker M.P., van der Helm E. (2009). Overnight therapy? The role of sleep in emotional brain processing. *Psychol Bull* 135:731–748. † https://pmc.ncbi.nlm.nih.gov/articles/PMC2890316
- Wassing R. et al. (2019). Restless REM sleep impedes overnight amygdala adaptation. *Current Biology* 29:2351–2358. †
- Watson D., Tellegen A. (1985). Toward a consensual structure of mood. *Psychol Bull*.
- Webb T.L., Miles E., Sheeran P. (2012). Dealing with feeling: a meta-analysis of the effectiveness of strategies derived from the process model of emotion regulation. *Psychol Bull* 138:775–808. †
- Yoo S.-S., Gujar N., Hu P., Jolesz F.A., Walker M.P. (2007). The human emotional brain without sleep: a prefrontal amygdala disconnect. *Current Biology* 17:R877–878. † https://pubmed.ncbi.nlm.nih.gov/17956744
- Zech E., Rimé B. (2005). Is talking about an emotional experience helpful? *Clin Psychol Psychother* 12:270–287. †
