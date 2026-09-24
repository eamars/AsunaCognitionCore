# ADR-007 Architecture

## 1. Responsibilities

### 角色脑

Owns:

- what matters;
- whether to reflect now;
- whether an error is worth fixing;
- whether to continue development or attend to conversation;
- relationship/self interpretation;
- Character Core and Current Self;
- whether to delegate work to the 行动脑.

The host does not replace these judgments with a priority formula or growth score.

### 行动脑

Owns:

- investigation;
- coding;
- debugging;
- tool use;
- verification;
- implementation choices;
- deciding when a candidate is useful enough to publish;
- iterative correction after live failures.

Ordinary implementation failures stay in the existing DSH action loop.

### Host/runtime

Owns only reliable mechanics:

- durable delivery of self-development opportunities;
- existing identity/scope/capability exposure;
- access to current code and state;
- persistence of self-state and publish lineage;
- verification execution transport;
- publish activation;
- minimum boot survivability;
- returning actual results/errors to the correct ongoing context.

The host is not a development manager.

### Codex

Temporary foundation implementer only.

After ADR-007 acceptance, Codex is not part of the routine:

> reflect → code → verify → publish → fix

cycle.

## 2. Self-development opportunity

A due internal event means only:

> You have an opportunity to look back at recent experience and continue any self-directed work if you want.

It must not inject:

- a fixed checklist;
- a required number of mistakes;
- a mandatory patch;
- a performance score;
- “you must improve yourself now”.

The 角色脑 may choose work, defer it, continue older work, update self-understanding, do something personally meaningful, or do nothing.

Scheduled self-development is one entry point. Immediate improvement after an event is also allowed.

## 3. Reflection material

Use already-authorized real state, for example:

- recent conversations;
- recent tool failures/errors;
- task results;
- user corrections/praise;
- group interaction;
- current TODO/goals;
- summaries/preferences/relationships if available;
- Character Core / Current Self;
- recent publish lineage and live errors.

This is context, not a scorecard.

P2 is not a prerequisite; raw recent records are an acceptable baseline.

## 4. Development workspace

The 行动脑 needs a path connected to the effective project.

Avoid detached draft-only environments whose output requires later Codex integration.

Preferred behavior:

- inspect the effective current project;
- edit in the authorized development workspace;
- preserve current working changes rather than silently replacing them;
- freeze/identify the exact candidate the 行动脑 actually tested and chose to publish.

Ordinary Git/worktree/filesystem mechanics are fine, but version management must not become a required cognitive task.

No candidate-vs-previous comparison is required.

## 5. Verification is a capability

Possible primitives:

```text
run_check(...)
start_verification_host(...)
inspect_verification_result(...)
inspect_logs(...)
stop_verification_host(...)
```

Actual names should reuse existing DSH/Asuna mechanisms where possible.

The 行动脑 chooses what evidence is useful:

- focused test;
- real query against current DB;
- host boot probe;
- existing Web/API path;
- or no extra check for a trivial change.

Do not prescribe a universal test matrix.

A failed check returns evidence and lets the same development goal continue.

## 6. One persistent world

There is no separate test-database requirement.

Verification may operate on the same real persistent state where existing capabilities allow it.

ADR-007 does not attempt to prevent experimental mistakes from entering history and does not add mandatory synthetic/live/test memory labels.

If memory pollution later matters, it becomes future lived experience and can be self-improved.

## 7. Forward-only publication

Keep only lightweight lineage sufficient for later causal questions, e.g.:

```json
{
  "revision": "...",
  "published_at": "...",
  "changed_files": ["..."],
  "reason": "..."
}
```

Use existing logs/state if sufficient; do not build release-management infrastructure.

Do not add:

- rollback_to(version);
- automatic comparison to last release;
- release ranking;
- regression scores.

If live behavior is wrong but still runnable:

> diagnose → change → publish again.

## 8. Boot survivability

This is the one protected floor.

A candidate must not erase the only runnable development path before minimum startup is known.

A valid minimal implementation:

1. current host remains live;
2. candidate starts in a non-consuming bootstrap mode;
3. candidate proves minimum logic-core startup;
4. only then does live ownership switch;
5. if bootstrap fails, candidate is not activated;
6. real boot error returns to the original development context.

This is not rollback: the failed candidate never becomes active.

Bootstrap is not staging and does not evaluate feature quality.

## 9. External capability boundary

ADR-007 adds no new safety reviewer.

The current host defines exposed capabilities.

- unexposed resources are unavailable;
- intentionally exposed resources remain usable under existing scope/identity/cancellation semantics;
- self-development does not secretly add credentials.

No Codex approval is inserted after a capability has intentionally been exposed.

## 10. Personality/self-state

If equivalent state already exists, reuse it.

Otherwise expose two thin role-owned persistent surfaces:

### Character Core
Stable self-description:
- values;
- likes/dislikes;
- habitual way of choosing;
- preferred style of working/relating;
- traits the 角色脑 considers “like me”.

### Current Self
More recent:
- current tendencies;
- recent personally important lessons;
- things the 角色脑 believes are changing.

The 角色脑 may revise either.

The 行动脑 may implement storage/tools but does not decide their content.

Do not translate these states into hundreds of host-enforced behavior rules.

## 11. Resource contention

Do not hard-code “foreground always wins” or “background always wins”.

The 角色脑 decides priority.

The runtime should preserve continuity so that choosing to attend to conversation does not unnecessarily destroy an ongoing development goal.

Reuse existing DSH continuation/goal/session mechanisms rather than building another scheduler.
