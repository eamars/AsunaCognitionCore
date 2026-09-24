# ADR-007 foundation: 2026-09-25

Codex implemented the one-time host foundation. Ordinary self-development now belongs to Asuna's 角色脑 and 行动脑; Codex is not a routine reviewer, tester, deployer, or approval step.

## Runtime evidence

- The existing native schedule registered `plan-asuna-self-development` as `ACTIVE`. An immediate trusted internal opportunity appeared in the formal Web UI as an internal event, not a user message. The 角色脑 considered it and chose silence. A later opportunity also committed a silent decision without blocking chat.
- The local owner's one-time development grant let the 角色脑 delegate a small real-project task. The 行动脑 inspected the effective candidate, edited `tests/p3_schedule_cases.py`, ran checks, handled an initial failing check, and called `development_publish` itself. Codex did not write or apply that product patch.
- The bootable candidate received an identified snapshot and minimum boot probe, then the host restarted. Receipt `self-publish-ae088bada9df47a7ea7022f9e587fa5a` reached `ACTIVE`; the activation event carried the original task ID back into the owner's role context. The Web UI showed the 角色脑 reading `ACTIVE` and subsequently delivering its own reply.
- A deliberately non-bootable candidate returned `BOOT_FAILED` with the actual syntax error and `activated=false`; the runnable host/project stayed available.
- The self-state path was tested against the same real database with a dedicated `adr007-mechanical-fixture-20260925` persona: `SelfState.commit` persisted `Current Self`, a new `SelfState.read` recovered it, and a later `ContextBuilder.prepare` injected the same revision into role context. This fixture did not write XiaoMan's personality. XiaoMan may choose whether and when to update her own state.
- The project compiles; the modified DSH runtime and Web client pass `node --check`; `git diff --check` passes. These are supporting checks, not a substitute for the Web and host observations above.

## Host repair found during acceptance

The activation event references the original task for continuity but has no new task intent revision. The local speech publisher initially treated that reference as a delegated intent and raised `KeyError: intent_revision` after the role decision. Codex fixed this foundation wiring in `src/asuna/publish.py`, resumed the existing accepted speech without repeating the action, and observed `COMMITTED` / `COMPLETE` / `DELIVERED` in the same episode and formal Web UI. The error remains in history as an actual failure record.

After that host repair, the persistent development candidate was refreshed from effective project files that had no unpublished edits. The workspace now repeats that reconciliation on access and preserves unpublished candidate edits, so later work starts from the effective current source.

## Operating boundary

The configured schedule and local owner entry can offer opportunities without a new user message. Development file, command, real database read, and publish capabilities are limited to the local owner development grant; no ordinary QQ permission was expanded. There is one real persistent world, no separate test database, no output-quality approval, and no rollback selector. Future ordinary cycles do not require Codex review, Codex test execution, Codex deployment, a new user message, or output-quality approval.

After foundation acceptance, the formal Web host was reloaded on port 8767 and the owner sent XiaoMan a short, open-ended ADR-007 handoff with a one-message local development grant. The Web showed that message accepted into the existing conversation queue. Her subsequent choices are her own.
