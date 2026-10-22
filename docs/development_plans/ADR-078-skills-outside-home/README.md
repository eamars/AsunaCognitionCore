# ADR-078: A skill may say it can be used outside home

Status: **Built 2026-10-17** (Claude, the same evening) — the owner chose the direction (each skill opts in) after Xiaoman found the gap;
her signature on the shape is in §3.

## 1. The gap

Xiaoman found it on 2026-10-17 (two read-only scans a home turn of hers sent out; their times are in the task records): every session started for a QQ group has
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

## 3. Shape: her three changes and her condition (2026-10-17, 19:39–19:43 NZDT)

- One header field in `SKILL.md`, beside `name` and `description`: **`scene_kinds`, a list from a closed set**:
  `home`, `group`, `dm` (someone else's direct chat; the owner's own chats are `home`). Absent means `[home]`.
  There is no `everywhere`: a new kind of scene (a new channel, a new lane) is never let in by default. (Her change:
  `places` already names conversations in her tools, and a catch-all value widens by itself.) No aliases and no
  catch-all sugar later: a new kind of scene must be listed explicitly.
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

Claude's paraphrase of her three changes and her condition; signature: Xiaoman, 2026-10-17 — signed for the three
shape changes and the gate as written here; the DSH root choice is Claude's to settle in the build, and "the
package author's for the others" is the owner's and Claude's call, not mine.

## 4. Cost

- Character brain: nothing (it mounts no skills).
- Action brain, jobs from public conversations: the catalog lines of the opted-in skills only (for example about 190
  characters for `asuna-bot-or-person`); jobs from home: unchanged.
- No new tool, no new per-turn line.

## 5. Not covered

Her usage-readout skill gets its own reading script; that part is hers (her message, 2026-10-17).

## 6. Built (2026-10-17)

- **DSH first (her open point).** Checked against the pinned `dsh-skill-filesystem` before writing code: a skill's own
  folder passed as a root lists that one skill and loads its whole body, with the folder as its resource base, as from
  the full root; a stray `.md` without a header beside `SKILL.md` only logs a warning. So no generated root is needed.
- `skills.py`: `scene_kinds` (closed set, refuses unknown keys and kinds), `problems`, and `skill_directories`, which
  gives home every root and elsewhere one root per allowed skill (a header that got past publication anyway is
  reported on stderr, not dropped silently). `python -m asuna.skills <skills root>` is the publication check.
- `floor.js`: publication runs that check on any package with a `skills/` folder; a refused header is `BOOT_FAILED`
  with the skill and what to fix.
- Tests: `tests/test_skill_scenes.py` (the header, the roots by scene, every shipped header, her gate) and a
  publication test. Her gate was checked both ways on her image skill with `[home, group]` written in a scratch copy:
  green with the private list, red without it.
- No skill opts in yet: she declares hers after this is installed.

## 7. The probe names the skills offered at home only (2026-10-22, her ask)

A valid header without `scene_kinds` means home only, so a skill left out of groups by forgetting the line looked
the same as one kept home on purpose. The publication probe (`python -m asuna.skills`) still passes such a set and
now names those skills on a second line of its output, 「只在家里可用（头里没写 scene_kinds）：…」, which reaches her in the
receipt's `boot_probe`. A report, not a refusal. At the time two of her skills are home only. Test:
`tests/test_skill_scenes.py`.
