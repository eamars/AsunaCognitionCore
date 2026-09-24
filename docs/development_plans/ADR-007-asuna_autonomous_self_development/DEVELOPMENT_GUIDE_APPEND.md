# Development Guide Addition — Autonomous Self-Development

This section is intended to become a long-lived project rule.

## Codex is not the resident developer

After ADR-007 foundation completion:

- the 角色脑 decides what it cares about and what to improve;
- the 行动脑 performs ordinary implementation, verification and forward publication;
- Codex is not the routine reviewer, tester, deployer or completion judge.

Codex returns only by explicit user request or when the self-development foundation itself is unreachable/broken.

## Verification is capability, not permission

A check gives Asuna evidence.

A failed check does not revoke the right to continue developing.

A passing check does not prove the feature is globally correct.

Do not turn tests into a new host-level task termination gate.

## Prefer lived iteration over pre-emptive governance

Do not add new:

- hard step limits;
- mandatory completion reports;
- retry-count termination rules;
- growth scores;
- TODO limits;
- output-quality gates;
- persona compliance gates;
- test/prod memory split;
- release-quality approval stages;

unless a future concrete problem demonstrates a real need and the user explicitly adopts the new restriction.

## Forward-only default

When a live implementation problem is discovered:

> diagnose → change → verify as useful → publish again

Do not default to version comparison or rollback.

The sole protected floor is that a candidate unable to reach minimum logic-core startup does not replace the runnable development path.

## Character ownership

Persistent personality is not a static prompt owned by developers.

The 角色脑 may evolve its own Character Core / Current Self.

The host preserves persistence/availability; it does not decide who Asuna should become.

## Naming

Architecture and project documentation should use:

- **角色脑**
- **行动脑**

Model/provider names belong only in deployment/configuration facts, not as enduring architecture-role names.
