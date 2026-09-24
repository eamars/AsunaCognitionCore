# ADR-007｜Autonomous Self-Development Foundation

**Status:** Implementation instruction  
**Scope:** Codex builds the one-time foundation; routine self-development is then owned by Asuna itself.  
**Terminology:** Architecture uses **角色脑** and **行动脑**. Model/provider names are deployment facts, not enduring role names.

## 0. One sentence

Build the minimum mechanisms that let Asuna repeatedly do:

> experience → role-brain reflection/choice → action-brain development → self-verification → publish → live experience → next iteration

After those mechanisms work, **Codex leaves the ordinary development loop**.

ADR-007 is not a new agent harness, CI/CD platform, quality-approval service, or autonomous “growth manager”.

## 1. What Codex builds

Codex implements only the reusable foundation Asuna cannot currently provide to itself:

1. **Self-development wake opportunity**
   - reuse existing DSH/native scheduling and Asuna event/queue paths;
   - allow scheduled or immediate internal self-development opportunities to reach the 角色脑;
   - every opportunity may legitimately result in no work.

2. **Reflection context access**
   - expose already-authorized recent experience: errors, tool results, user feedback, interaction history, unfinished work, current self/relationship state;
   - no scoring, judge model, or mandatory reflection schema.

3. **Writable effective project environment**
   - the 行动脑 can inspect/edit the actual current project within the already-authorized development boundary;
   - avoid detached draft-only directories that require Codex to rewrite/integrate work later.

4. **Callable verification**
   - the 行动脑 can run relevant checks and inspect stdout/stderr/traces/results itself;
   - verification is a capability, **not a permission gate**.

5. **Forward-only publish**
   - the 行动脑 can publish its chosen candidate without routine Codex intervention;
   - no rollback-selection workflow and no current-vs-previous quality comparison;
   - retain only lightweight lineage useful for later causal debugging.

6. **Boot survivability**
   - a candidate that cannot reach minimum logic-core startup is simply not activated;
   - the existing runnable development path remains available and the real boot error returns to the ongoing development context;
   - this is not application rollback.

7. **Persistent role self-state**
   - reuse existing persona/state persistence if present;
   - otherwise provide the thinnest persistent surfaces for **Character Core** and **Current Self**;
   - Codex does not author the personality. The 角色脑 owns and may revise it.

When these mechanisms are callable and survive the required host restart/reload boundary, Codex stops.

## 2. What Codex must NOT build

Do not add:

- ReflectionManager / ImprovementPlanner / GrowthScore / PatchReviewer / DeploymentApprover;
- a second agent loop or scheduler;
- a separate test database or production/test memory split;
- rollback orchestration, release ranking, automatic best-version selection;
- mandatory reflection output or mandatory patch generation;
- output-quality grading or model judges;
- mandatory synthetic/live/test memory categories;
- TODO governors or growth backlogs;
- a fixed foreground-vs-background priority policy: the **角色脑 decides**;
- new QQ/user/admin permissions.

Do not turn ADR-007 into babysitting.

## 3. Safety model

Safety is by **capability exposure**.

- If the runtime does not expose a resource/action, Asuna cannot use it.
- If a capability is intentionally exposed, ordinary mistakes inside that capability are allowed to become experience.
- ADR-007 adds no Codex approval step around normal self-development.
- Existing identity/scope/cancellation/external-resource semantics remain the current host's source of truth.

Only the minimal boot-survivability floor sits outside the code being activated.

## 4. Data philosophy

This is an experimental resident system.

- There is **one real persistent world**, not separate test/prod databases.
- Errors, failed experiments, wrong memories and later corrections may remain part of Asuna's history.
- Do not build a sanitizer whose job is to make state “correct”.
- Do not add special destructive-migration governance in ADR-007.
- The system may learn from consequences over time.

The one foundation requirement: a bad candidate must not remove the minimum runnable logic needed for Asuna to continue developing.

## 5. Personality ownership

Model weights must not be the only source of “who Asuna is”.

The 角色脑 may maintain and revise:

- **Character Core** — slower-changing self-description, values, preferences, habitual interpretation/choice;
- **Current Self** — more recent self-understanding and tendencies;
- existing relationship state;
- existing mood/episodic state.

These are not host-enforced if/else rules.

Codex exposes persistence/injection if missing, but does not write a detailed personality and does not freeze it after initial creation.

## 6. Normal self-development loop

A valid cycle is:

1. scheduled, immediate or manually requested opportunity reaches the 角色脑;
2. the 角色脑 decides whether anything is worth attention;
3. it may do nothing, reflect only, update self-state, defer work, continue old work, or delegate an improvement;
4. the 行动脑 uses the normal DSH loop to inspect/edit/test/debug;
5. the 行动脑 chooses when a change is useful enough to publish;
6. publish performs only minimum boot-survivability activation;
7. live use creates new experience;
8. later reflection may revise the result.

No step needs Codex approval.

If a feature behaves badly but the system still runs, leave it live until Asuna notices and iterates forward.

## 7. Integration with ADR-005

ADR-005 P2/P3/P5 are useful inputs, not prerequisites for ADR-007 completion.

- P2 can enrich reflection context with summaries/preferences/relationship/self state.
- P3 can provide user-facing scheduling semantics.
- P5 can provide richer interaction experience.
- Use whatever is actually present at implementation time; current ADR-005 source is not assumed complete.

Do not revalidate unrelated ADR-005 behavior merely to build ADR-007.

## 8. Implementation order

1. self-development opportunity through existing schedule/event path;
2. role-brain access to recent experience and persistent self-state;
3. action-brain writable current-project path;
4. self-callable verification/results;
5. forward-only publish + minimum boot survivability;
6. return publish/boot errors to the same ongoing development context;
7. lightweight publish lineage;
8. stop.

Do not first build a dashboard, policy engine, evaluator, release manager, or separate memory environment.

## 9. Codex exit condition

ADR-007 is complete when the **mechanisms are callable**.

Codex does not need to prove Asuna's first autonomous improvement is correct, elegant or useful.

The completion report answers only:

- can the 角色脑 receive a self-development opportunity and choose what to do?
- can it delegate to the 行动脑 without a new user message?
- can the 行动脑 edit the effective project, run checks, inspect failure, and continue?
- can it publish without Codex?
- can a non-bootable candidate fail activation while leaving the development path runnable?
- do publish/boot results return to the original ongoing development context?
- can the 角色脑 persist and re-read its own self-state?
- did Codex avoid becoming a permanent reviewer/operator?

If yes, stop extending ADR-007.
