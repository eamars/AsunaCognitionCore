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

**Each skill opts in.** A skill whose `SKILL.md` header lists the scene kinds it may be used in is offered to action-brain
jobs from public conversations; every other skill stays home-only, as now. Diagnostic and development skills stay at
home: her runtime environment belongs to internal diagnostics, not to public conversations (AGENTS.md).

## 3. Shape (agreed with Xiaoman, 2026-10-17 about 18:50 NZDT)

- One header field in `SKILL.md`, beside `name` and `description`: **`scene_kinds`, a list from a closed set**:
  `home`, `group`, `dm` (someone else's direct chat; the owner's own chats are `home`). Absent means `[home]`.
  There is no `everywhere`: a new kind of scene (a new channel, a new lane) is never let in by default. (Her change:
  `places` already names conversations in her tools, and a catch-all value widens by itself.)
- **A wrong declaration is never silently home-only.** An unknown key spelling, a value outside the set or a malformed
  list is refused when the skill is published, and a repository test fails on it. (Her change: a declaration that
  quietly does nothing is worse than none, because she cannot see it failed.)
- A job from a home conversation sees every skill, as now. A job from a group sees the skills that list `group`; from
  someone else's chat, those that list `dm`.
- How DSH is given the narrower set (it discovers skills by root directory) is settled in the build: a root of only
  the allowed skills, generated at start and marked as generated, or one root per allowed skill. Her open point is
  checked there first: whether DSH lists and loads skills from the narrower set.
- **The gate, as a test (her condition):** a skill that lists anything besides `home` must carry a self-check with a
  private-words leak criterion; without one the test fails. Separately, every tracked skill is already scanned by
  `tests/test_personal_words.py`; a skill listing more than `home` fails when the private list is absent, instead of
  passing unchecked.
- Order: the gate is built first; she declares her skills after it is in. Which skills open is hers for her skills
  and the package author's for the others. Her first: `asuna-image-generation-and-display` (on 2026-10-17 a real job
  from a group drew seven pictures without it).

Claude's paraphrase of her three changes and her condition; signature: ____

## 4. Cost

- Character brain: nothing (it mounts no skills).
- Action brain, jobs from public conversations: the catalog lines of the opted-in skills only (for example about 190
  characters for `asuna-bot-or-person`); jobs from home: unchanged.
- No new tool, no new per-turn line.

## 5. Not covered

Her usage-readout skill gets its own reading script; that part is hers (her message, 2026-10-17).
