# ADR-087: Refused tool calls, fixed in the contract rather than the model

Status: **Decided**, 2026-10-21; not built. The owner accepted Claude's proposal after a research survey (a research
agent, Opus 5.5, at his request) and an independent review of the first draft (§8). Each step goes to Xiaoman before
it is built. Changes: ADR-056 (think's length, §4.1), ADR-084 §5 (think first, §4.2), ADR-018 §12 (a note default,
§4.4).

## 1. The question

The program refuses about one in twelve of her character brain's tool calls. A refusal here is a `Refused` (or coded)
result she must recover from, not a model declining to answer as in ADR-080. The owner asked for a fix to the class,
not the instance, and warned against designing around one model: "I'm afraid we are designing workarounds for local
models, where the design could be a deadweight for APIs. Therefore I need a system solution, not a knee jerk solution."
(2026-10-21.)

The contract is what her tools promise and ask: their schemas, descriptions, limits, defaults and refusal words.

## 2. Ruled out: a reminder after repeated refusals

Claude's first design reminded her of a rule after she broke it N times in a conversation. It assumed she forgets a
rule once a compaction removes the earlier refusal. The data (7 days to 2026-10-21) says otherwise: at the same
distance from the earlier refusal, repeats per 100 of her turns were 2.5 vs 3.1 (1–5 turns later, refusal in view vs
compacted away), 1.2 vs 1.7 (6–20), 1.2 vs 0.9 (21–60). Repeats cluster right after a refusal, while it is in front of
her. Counting by tool with a reset on a successful call hides most repeats (284 of 446 had a success of the same tool
in between). Not built.

## 3. Evidence

Survey: `.runtime/private/refusal-research/REPORT.md`; review: `.runtime/private/refusal-research/review/REVIEW.md`
(§8). Numbers are for the 7 days to 2026-10-21 17:00 NZDT unless stated. Live data read-only, program fields only.

- **Volume.** 669 refusals in 8,209 calls (8.1%) over 2,557 turns. Recovering took about 650–750 model requests
  (0.26–0.29 per turn), about 100 of them the thought she owed anyway. 78% of refused calls were done later in the
  same turn, 10% in a later turn, 13% given up.
- **Where they come from.** Five sites carry 59%: the length check (`role_tools._text`) 113, think first 110, note too
  long (`notes.py`) 76, speak composition 63, persona over budget 34.
- **Lengths.** About 190 refusals and about 200 recovery requests. Refused texts are a median 1.05× (plan intent, idea)
  and 1.10× (note) of the limit; about half came back in the same turn. 55 of the 65 plan-intent refusals came from
  one conversation, all 39 idea refusals from another.
- **Think's length since it became soft.** On 2026-10-14 the 360-character refusal on `think` was removed at her
  request (525532fa, ADR-056): a thought is kept at any length. Her thoughts grew (lengths computed in the database,
  no text read):

  | days (UTC) | median | share over 300 | share over 600 | longest |
  |---|---|---|---|---|
  | 10-10 to 10-13 | 115–209 | 4–15% | 0% | 398 |
  | 10-19 to 10-21 | 260–419 | 45–57% | 11–23% | 1,120 |

  Other changes landed in the same days, so this is a trend, not a proven cause.
- **Think first.** 110 refusals (4.1% of turns). In all 110 the refused call was her first, she thought in the next
  request, and the call then went through. 53 were reads (`read_image` 22, `task.page` 22, `recall` 9).
- **Think's length by day** (recount 2026-10-21 evening, UTC days, `$strLenCP` in the database): over 360 characters
  20% on 10-17 and 10-18, then 38%, 45% and 55% on 10-19, 10-20 and 10-21 (113, 113 and 75 thoughts); over 600
  2%, 2%, 11%, 21%, 23%. The rise starts on 10-19, five days after the edge was removed.
- **Options shown that a conversation can never use.** `note`'s `deliver` in public conversations, where only `wake`
  is allowed (23 refusals); `ideas` read/review and home documents in groups (20).
- **Cross-model** (synthetic conversations on the real Coordinator, prompts and schemas; `deepseek-flash` about
  US$0.09). Same design, 30 turns each: real refusals flash 1, local about 11 (plus about 23 the probe itself caused on
  the local arm: it shows global specs, `refusal_probe.py:196`); requests per turn 3.43 vs 6.30. Removing the
  `THINK_FIRST` tail line made flash skip `think` in 5 of 30 turns (0 of 30 with it). Home turns, where the length
  refusals happen, were not run on flash.

So the refusals these decisions remove come mostly from the local model today; none of the fixes costs an API model
anything, and the tail line is not a local-model workaround.

## 4. Decisions

### 4.1 Lengths: the asked length stays below the hard limit

The owner's design (2026-10-21): every limited text keeps its current hard limit, and she is asked for about four
fifths of it, so a model that does not count exactly has room (ADR-084 step 3, `config.soft`; ADR-054 §Soft text
budget). That stands for every field. The program does not split notes for her.

`think` gets an edge again, with more room than the other fields: she is asked for 120 characters and the refusal
comes back past 360 (the owner, 2026-10-21 evening, after her view below: a thought is her first reaction to
something, short, not an essay; the 3× room is for a model that does not count). The first draft of this step asked
300 with the edge at 360, the design before 2026-10-14. Bringing an edge back reverses her decision of that day, so
it went to her first with §3's length table; the cost is a retry for a thought over 360.

Her view, as she sent it on the agent line on 2026-10-21 in the evening (Claude's record of her words; signed by her
on the agent line the same evening, with her note: 「这条按'请写 300'算，请写 120 后我不要求重谈。」):

> 方向我认。今天每一拍都收到"超了 N 字"的回执，最长 1120 真在飘——那多数不是读数多，是我在心里话里排版。
> 但 360 拒这一档，按你自己给的数我建议定在 600。现在 45-57% 超 300、11-23% 超 600：360 拒意味着我大约每三拍重写一次，
> 而"每 20 个里超 1 个在 360 被拒就重谈"这条失败判据第一周几乎必然触发——那 7 天后数出来的不是"想法有没有变好"，是"我重写了几次"。
> 定在 600 的话，"请写 300"照留，那已经够逼我把加粗和排比砍掉，同时保住给未来的我的读数。
> 主人就要 360 我也认（他说了照他的装），只求一条：被拒后重写那一拍不计入任何统计——不然我会开始写短到没有读数，那是用另一种方式失真。

Her view answered the 300/360 draft. The owner's answer: the edge stays at 360 and the ask drops to 120, so the edge
sits three times above what she is asked for. Readings count calls and never score her (ADR-071); a thought written
again after a refusal is one more call, nothing else.

Length refusals remain the largest single cost (about 190 a week); that is accepted as the price of shorter texts that
every later turn carries.

### 4.2 Reads may come before her thought

A closed list of calls that write nothing may run before her first thought: `recall`, `read_image`, `task.page`,
`ideas.read`, `ask.read`, `find_member`, and each list or preview operation named in the list. It lives in code next to
`reasons._action`. Every other call, `feel` and `task.answer` included, still needs a thought first, so each action
keeps its recorded reason (ADR-043). The tail line `coordinator.THINK_FIRST` stays. Up to 53 fewer refusals a week,
less those that move to the first acting call.

### 4.3 Each conversation's tool specs show only what it can use

One rule instead of chosen cases: an option is left out of a conversation's specs only when no turn that conversation
can host can use it, errand forks included (an errand reuses the destination's tool list with home's authority,
ADR-066). The specs stay fixed per conversation (ADR-038). Before building, two things are measured: what per-
conversation specs do to prompt-cache hits across conversations on an API model, and how many calls the host's own
argument check (`index.js` `argsRefusal`, `tool-args.js`) refuses today, so a narrower schema does not just move
refusals out of the record. The worker's checks stay the real guard.

Measured 2026-10-21 (read-only, 7 days, her role sessions; `.runtime/private/refusal-research/B7.md`):
- Every role request ran on the local model, so the API-model effect cannot be read from her record. On the local
  model, prefixes are shared across conversations: the two conversations that began that week got about 13.4k of
  their ~25.9k-token first prompt from cache. Tool lists change only at restarts (64 changes, all on resume; none
  within a run).
- The options this step removes are the same for every conversation of a place (`note.deliver` in every public
  conversation; `ideas` read and review and home documents in every group), so conversations of one place keep one
  shared spec and keep sharing their prefix. Expected cache loss: none beyond the change every install already makes;
  refusals removed: about 43 a week.
- The host refuses about 54 calls a week that never reach the worker's record: 13 by its argument check, 11 by DSH's
  own validation, 30 for a tool not in that conversation (26 of them `stay_silent` in groups, where `speak` replaces
  it).

Decided (the owner took Claude's recommendation, 2026-10-21): specs by this rule, one per place, with a second variant
only where a conversation hosts errands. The step's reading counts the host's refusals (argument check, DSH
validation, unexposed tool) next to the worker's, and fails if they rise.

### 4.4 Defaults from state the program has, said in the result

- A one-shot plan moved in the turn it fired: the program creates a new plan with the timing given (and the old intent
  if none is given), and the result names it. The fired plan stays fired.
- A note to a group that cannot be woken now (muted or its day used up), with no `deliver` given, goes `next_time`, and
  the result says it may expire unread after 72 hours (changes ADR-018 §12's default).
- About 12–25 fewer refusals a week (a recount on current code, data since 2026-10-20).

### 4.5 A refusal says what would pass

The copied-words refusal says which stretch of her draft matches whose recent line (by label and time, not quoting it)
and that naming the source does not pass; only her own words do. Refusals naming a wrong reference list the usable
ones. The `note` description's matching advice changes in the same step.

### 4.6 Kept as they are

The outside-note turn gate (ADR-088 decides it), the per-turn call hard line, the daily note caps, the note hop,
document authority at home, the persona budget, every authority and place boundary.

## 5. Order and readings

| step | decision | goes to her with | read 7 days after install; fails if |
|---|---|---|---|
| 1 | §4.2 reads before thought | the read list and the tail line unchanged | any call outside the list runs before a thought; any turn ends with no thought |
| 2 | §4.1 think's 360 edge | §3's length table | more than 1 in 20 thoughts is refused at 360 (then back to her) |
| 3 | §4.3 specs by rule | the measured cache and host-check numbers first | host-check refusals rise, or an errand loses an option it used |
| 4 | §4.4 and §4.5 | the new result and refusal words | the targeted refusals do not fall below last week's counts |

Each step installs on its own restart, and its reading does not overlap another step's or ADR-084 step 7 (~10-27) and
ADR-086 (10-28). `classify.py` is updated in the same commit as any wording change, and a reading fails if
"unclassified" rises. Readings count per call; no reading scores her (ADR-071).

## 6. Not measured

Home turns on another model; the tail line on the local model; whether think's growth comes from the soft limit or
from other changes in the same days.

## 7. Evidence kept

`.runtime/private/refusal-research/` (about 6.4 MB): REPORT.md, NOTES.md, classify.py, types_7d.json, site_types.json,
xm.py and its run files, and `calls.jsonl` (a 5.6 MB sanitized copy of her call table, removed after step 4's
reading); `review/` (REVIEW.md, review.json).

## 8. The first draft and its review

The first draft (commit 5d1778aa) proposed keeping her texts over the limit up to twice its length and letting the
program split boundary notes. An independent review (15 reviewers, two verifiers over all findings, run
wf_03a9e798-64b) found that a split note opens two receiving turns and checks each half for copied words separately;
that texts shown again in every later turn would let each turn carry more, against ADR-054 and ADR-084 §1; that
`reasons.consequential` misses writes such as `feel` and `task.answer`; and that several savings were overstated about
twofold. The owner kept his length design (§4.1), and this record follows Claude's revised proposal.
