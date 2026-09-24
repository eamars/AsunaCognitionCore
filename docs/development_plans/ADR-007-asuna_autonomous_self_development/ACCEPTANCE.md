# ADR-007 Acceptance

Acceptance is deliberately narrow.

The objective is to prove the **foundation mechanics**, not grade the first autonomous improvement.

## A. Opportunity

Show that an internal self-development opportunity reaches the 角色脑 through the existing trusted runtime path.

Valid outcomes:

- it chooses to do something;
- it continues an existing item;
- it chooses to do nothing.

Do not require a patch.

## B. Reflection and self-state

Show that:

- the 角色脑 can read relevant recent experience;
- it can read persistent self-state;
- it can update Character Core or Current Self when it chooses;
- a later role-brain turn can read the updated state.

Do not judge whether the personality change is “good”.

## C. Development autonomy

Show that the 行动脑 can, without Codex editing code for it:

- inspect the effective current project;
- edit a file in the authorized development area;
- run a relevant check/command;
- receive raw results;
- continue after a failed check.

The demonstration change may be trivial. It is not a feature-quality benchmark.

## D. Publish autonomy

Show that the 行动脑 can call publish without Codex manually applying its patch.

For one bootable candidate:

- candidate identity is fixed;
- minimum boot survives;
- candidate becomes active;
- publish result returns to the original development context.

For one intentionally non-bootable mechanical fixture/deterministic probe:

- candidate does not become active;
- the existing runnable development path remains;
- actual boot error returns.

Do not manufacture a real user-facing feature failure just to collect evidence.

## E. Forward correction

No rollback test.

It is sufficient that after a failure, the original development context remains capable of another edit/check/publish attempt.

## F. Codex exit

The completion report must state that ordinary future cycles do **not** require:

- Codex review;
- Codex test execution;
- Codex deploy;
- a new user message;
- output-quality approval.

If those remain mandatory, ADR-007 is not complete.

## Explicitly NOT acceptance criteria

Do not require:

- an important real bug fixed overnight;
- a fixed number of reflections;
- a useful group-chat improvement;
- perfect memory results;
- model-judge PASS;
- full ADR-005 replay;
- separate test DB;
- current-vs-previous release comparison;
- rollback;
- synthetic/live provenance scoring;
- personality quality judged by Codex;
- zero errors.

Errors are allowed. The foundation exists so Asuna can keep working after them.
