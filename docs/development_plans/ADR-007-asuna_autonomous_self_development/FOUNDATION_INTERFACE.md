# ADR-007 Foundation Interface

This file defines required **capabilities**, not mandatory tool names or a new protocol.

Map them to existing DSH / Asuna primitives whenever possible.

## 1. Self-development opportunity

Needed behavior:

```text
schedule / immediate decision
    ↓
trusted internal event
    ↓
existing role-brain scene/session
    ↓
角色脑 may act or stay silent
```

Requirements:

- use the same durable scheduling/event semantics as other accepted scheduled work;
- not a fake user message;
- not a new permission grant;
- no public speech required;
- can reference unfinished self-development work;
- normal chat remains available.

## 2. Experience read

The role/action system needs access to relevant already-authorized experience.

At minimum:

- recent accepted messages;
- task/tool results and errors;
- recent publish lineage;
- open goals/TODO if present;
- current role self-state.

Reuse current history/retrieval features. Do not build a second memory system.

## 3. Development operations

The 行动脑 needs effective operations equivalent to:

```text
inspect_current_project
edit_current_project
run_command / run_check
inspect_process_output
inspect_logs
```

Prefer native DSH file/bash/job tools.

The key requirement is that the workspace is actually connected to a candidate that can be published.

## 4. Verification operations

Keep them thin.

Possible operations:

```text
run_check(...)
start_boot_probe(...)
inspect_boot_probe(...)
stop_boot_probe(...)
```

Return raw stdout/stderr/exit status/traces.

A failed check is information, not task termination.

No universal checklist.

## 5. Publish operation

Expose one forward-only operation equivalent to:

```text
publish(candidate_snapshot, reason?)
```

Behavior:

1. freeze/identify the exact candidate;
2. record lightweight lineage;
3. perform minimum boot-survivability probe;
4. if minimum startup fails:
   - do not activate candidate;
   - keep current runnable development path;
   - return actual error;
5. if minimum startup succeeds:
   - activate candidate through the existing host/service mechanism;
   - return actual activation result;
6. route result/error back to the same ongoing action-development context.

No rollback selector is part of ADR-007.

## 6. Role self-state operations

If not already available, expose the thinnest equivalents of:

```text
read_character_core()
commit_character_core(text, sources?)
read_current_self()
commit_current_self(text, sources?)
```

Names/schema are implementation-defined.

Important:

- contents are written by the 角色脑;
- revisions may remain as history;
- no Codex-authored personality scoring;
- no per-edit user approval;
- self-state never changes external authorization.

## 7. Minimal mechanics health

Publish bootstrap may answer only questions equivalent to:

```text
host core started?
database/core state reachable?
角色脑 / 行动脑 cognition construction reachable?
self-development/publish path still reachable?
live-consumer ownership not duplicated?
```

It must not check:

```text
answer quality
memory accuracy
style quality
group engagement
correctness of every tool
acceptance-dialogue completion
```

Those belong to future lived experience and self-iteration.
