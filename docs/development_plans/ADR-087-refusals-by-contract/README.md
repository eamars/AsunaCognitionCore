# ADR-087: Refusals that cost any model, fixed in the contract

Status: **Proposed**, 2026-10-21 (draft for the owner's review; nothing built). Asked by the owner after Claude's first
design (a reminder after repeated refusals) failed on the data. The survey is by a research agent (Opus 5.5) at the
owner's request, reviewed by Claude. Each decision goes to Xiaoman after the owner and Claude agree, before it is built.

## 1. The question

Her character brain refuses about one tool call in twelve. The owner asked for a solution to the class, not the
instance, and warned against designing around the local model: "I'm afraid we are designing workarounds for local
models, where the design could be a deadweight for APIs. Therefore I need a system solution, not a knee jerk solution."

## 2. What was ruled out first

**A reminder after N repeated refusals** (Claude's design, refined with the owner: count by rule since the last
reminder, remind once, no turn window). It rested on "she forgets the rule after a compaction". The data says no:

- 354 repeats of the same refusal in one conversation in the 7 days to 10-21; 75% had a compaction between the two
  hits, but 89% of all her turns after a refusal lie after a compaction, so that share says nothing on its own.
- At the same distance from the earlier refusal, repeats per 100 of her turns there, refusal still in view vs
  compacted away: 1–5 turns 2.5 vs 3.1; 6–20 1.2 vs 1.7; 21–60 1.2 vs 0.9; 61+ 0 vs 0.5. Visibility makes little
  difference; repeats cluster right after a refusal, while it is in front of her.
- Counting by tool with a reset on a successful call (the owner's variant) hides most repeats: 284 of 446 repeats of
  a rule on a tool had a success of that tool in between; one tool carries up to 13 different rules.

Scripts: Claude's scratch scripts `refusal_*.py`, `inview_hazard.py`, `tool_counter_sim.py` (session scratchpad, not
kept). The counter is not built.

## 3. Evidence

Report: `.runtime/private/refusal-research/REPORT.md` (local, about 20 KB, with `classify.py`, `types_7d.json`,
`site_types.json`, `xm.py` and the run results in the same folder). Live data read-only, program wording only; no
thoughts, arguments or ids read.

- **Volume.** 669 refusals in 8,209 calls (8.1%) over 2,557 turns, 7 days to 10-21 17:00. About 1,100 model requests
  went into recovering (0.43 per turn). 78% were done later in the same turn, 10% in a later turn, 13% given up.
- **Sites.** 133 `raise Refused` sites in `role_tools.py` and about 230 coded raises in the modules her tools call.
  Five sites carry 58% of the week: length (`role_tools` `_text`) 113, think first 110, note too long (`notes.py`) 76,
  speak composition 63, persona over budget 34.
- **Lengths (189 refusals, about 430 of the recovery requests).** Refused texts are a median 1.03× (plan intent), 1.04×
  (idea) and 1.10× (note) of the limit; the same refusal came back in the same turn in about half (plan 36 of 65, idea
  26 of 39, note 34 of 76). After the 10-20 change that asks for 0.8× of each limit (ADR-084 step 3), plan refusals rose
  from 17.7% to 34.2% of plan calls. Every plan-intent refusal was at home; most note refusals were long reports
  sent home through the 300-character boundary note.
- **Think first (110 refusals, 4.1% of turns).** The refused call was her first call; she thought in the next request
  (median 2.8 s) and the call then went through, 110 of 110. 53 of the 110 were reads (`read_image` 22, `task.page`
  22, `recall` 9). Highest on turns whose input asks for action (task hand-backs 11.1% at home).
- **Options shown but never usable.** `note`'s `deliver` choice in public conversations, where only `wake` is allowed
  (`notes.MODES`, checked): 23 refusals, 23 of 23 resent with `wake`. `ideas` read/review and home-only documents in
  groups: 18.
- **Refusals where the program already knows the answer.** A just-fired one-shot plan moved (22, 7 given up); a note to
  a group that cannot be woken now (17, 16 resent as `next_time`); `feel` without `ref` (17).
- **Gates doing their job.** The outside-note turn gate (19; its own ADR-088), the per-turn call cap, the daily note
  caps, the note hop, document authority, the persona budget.
- **Cross-model** (synthetic conversations, `xm.py` on the real Coordinator, prompts and schemas; deepseek-flash about
  US$0.09):
  - CM-1, same design, two models, 30 turns each: real refusals flash 1, local about 11; requests per turn 3.43 vs
    6.30; plan intents median 56 vs 90 characters.
  - CM-2, the THINK_FIRST tail line on flash: removed, 5 of 30 turns broke think-first (3 of 3 task hand-backs); on,
    0 of 30. The line carries weight on the API model too.
  - The probe gives the model global tool specs (`refusal_probe.py:196`, `all_specs()`, checked), not the
    per-conversation ones, so its speak results include options a live conversation never shows; a separate fix.

## 4. Decisions proposed

Each is model-agnostic: it removes a cost every model pays (a refusal and a retry), not a habit of one model. None adds
prompt or per-turn text. None adds stored state. Where a conversation's tool specs change, the cache changes once at
deploy; the tool list stays fixed per conversation.

### D1. Texts she writes for herself are kept; boundary notes are split by the program

- **Her own texts** (`plan.intent`, `ideas.idea`/`why`, notes home → home, `restart.why`, `ask.question`,
  `delegate.title`): over the asked length, the text is kept and the result says by how much (as `think` does since
  10-14, which has had no refusal since). A hard edge stays only for runaway output, at **2× the asked length**
  (the research agent's proposal; the owner sets the number, and its source is recorded here).
- **Notes that cross into another conversation** (the 300-character boundary note, ADR-018 §4): over the limit but
  within the turn's two notes, the program sends it as `1/2` and `2/2` (the option the refusal now asks her to do by
  hand) and says so. Over two notes is still refused: the boundary is the point.
- Retires the 0.8× ask of ADR-084 step 3, which changed nothing on either model.
- One field at a time, as ADR-084 steps: plan intent, then ideas, then notes.
- Expected: about 180 fewer refusals and 430 fewer requests a week.

### D2. Think first applies to calls that act or speak

- Reads run before her thought: `recall`, `read_image`, `task.page`, `ideas.read`, `ask.read`, `find_member`, and list
  operations. A look before the thought makes the thought better informed and protects no action.
- The refusal stays for every call `reasons.consequential` names, plus `speak` and `stay_silent`: the owner's rule that
  each action carries its recorded reason (ADR-043) is unchanged.
- The tail line `coordinator.THINK_FIRST` stays (CM-2).
- Expected: about 53 fewer refusals a week.

### D3. Each conversation's tool specs show only what it can use

- Built per conversation, as `speak_spec` already is: no `deliver` on `note` in public conversations; in groups,
  `ideas` offers only `note`, and `write_document` only the group's own notes.
- The specs stay fixed for the conversation (cache-first, ADR-038); a smaller schema also lowers the tool budget.
- Expected: about 41 fewer refusals a week.

### D4. Defaults from state the program has, said in the result

- A note to a group that cannot be woken now, with no `deliver` given, goes `next_time`.
- `plan update` on a one-shot plan that fired in this very turn re-arms it.
- `feel` without `ref` uses the line that opened the turn ("never mark required what the program infers").
- Each result says what the program chose, so nothing happens unseen.
- Expected: about 55 fewer refusals a week.

### D5. A refusal says what would pass

- The copied-words refusal names the matched run and says plainly that naming the source does not pass; only her own
  words do (today it implies naming the source is enough; 13 of 23 came back in the same turn).
- Applied wherever a refusal leaves her guessing; found by the same per-type count after D1–D4.

### D6. Kept as they are

The outside-note turn gate (ADR-088 decides it), the per-turn call hard line, the daily note caps, the note hop,
document authority at home, the persona budget, every authority and place boundary.

## 5. Verification

- Each step is read 7 days after install with `classify.py` against this week's table (`types_7d.json`): the refusals
  of its type, the recovery requests, and whether the intent was achieved or given up.
- D1 fails if any field's kept-over texts grow past the hard edge more than rarely (say 1 in 50 calls) or her notes
  home lose parts; then the edge goes back for that field only. D2 fails if acting calls lose their recorded reason
  (`reason_ref` present on every consequential call, as today). D3/D4 fail if a removed option is missed (a refusal
  naming it, or her saying so).
- No reading scores her (ADR-084, owner 2026-10-16).

## 6. Not measured

Home turns on another model (the probe has no home scene, where the length refusals happen); the tail line on the local
model (not run, her evening); the length of her successful calls (arguments are stored hashed); seconds per extra
request.

## 7. For the owner to decide

1. D1–D5 as a set, and the order (Claude's: D1 plan intent first, then D2, then D3–D5).
2. D1's hard edge (2× the asked length) or another number.
3. Then each step goes to Xiaoman before it is built.
