# ADR-078: A skill may say it can be used outside home

Status: **Proposed 2026-10-17** — the owner chose the direction (each skill opts in) after Xiaoman found the gap;
waiting for her agreement on the shape.

## 1. The gap

Xiaoman found it on 2026-10-17 (her two read-only scans, about 18:30 NZDT): every session started for a QQ group has
an empty `skill_directories`. `skills.skill_directories` returns the skill roots only for the owner's private
conversations (`visibility.session_class == OWNER_PRIVATE`); a group is public by place (`visibility.PLACE_CLASS`),
and the napcat-qq channel kind is not a home kind.

What it means in practice: only the action brain mounts skills (the plugin's executor lane, `skill` capability); the
character brain has none anywhere. So **an action-brain job handed over from a group or from someone else's chat runs
without any of her skills**, while the same job handed over at home has all of them. The owner had said in a group
that her action brain should have a skill of its own for such work.

The rule dates from 2026-10-05 (ADR-011 M4), when the only skill was the core self-improvement one and development was
the owner's alone. Nobody revisited it as her own skills grew: there are 11 skills now (core 3, channel 1, hers 7),
whose descriptions add up to about 4,600 characters, most of them about development and diagnostics.

## 2. Decision (owner, 2026-10-17)

**Each skill opts in.** A skill whose `SKILL.md` header says it may be used outside home is offered to action-brain
jobs from public conversations; every other skill stays home-only, as now. Diagnostic and development skills stay at
home: her runtime environment belongs to internal diagnostics, not to public conversations (AGENTS.md).

## 3. Shape (to agree with Xiaoman)

- One header field in `SKILL.md`, beside `name` and `description`; proposed `places: everywhere` (absent means home
  only). The program reads it; a typo in it means home only.
- A job from a home conversation sees every skill, as now. A job from a public conversation sees only the opted-in
  ones.
- How DSH is given the narrower set (it discovers skills by root directory) is settled in the build: a root of only
  the opted-in skills, generated at start and marked as generated, or one root per opted-in skill. Her open point is
  checked there first: whether DSH lists and loads skills from the narrower set.
- Which skills opt in is hers for her skills, and the package author's for the others. Candidates she might consider:
  `asuna-bot-or-person` and, when it exists, her become-human skill.

## 4. Cost

- Character brain: nothing (it mounts no skills).
- Action brain, jobs from public conversations: the catalog lines of the opted-in skills only (for example about 190
  characters for `asuna-bot-or-person`); jobs from home: unchanged.
- No new tool, no new per-turn line.

## 5. Not covered

Her usage-readout skill gets its own reading script; that part is hers (her message, 2026-10-17).
