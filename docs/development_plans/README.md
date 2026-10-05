# Development plans

This directory preserves Asuna's ADRs and development plans, including their original design context and dates. These documents record decisions and future direction; they are not the source of current runtime status.

For current behavior, see the root [README](../../README.md), [runbook](../../RUN_ASUNA.md), and [runtime API](../../RUNTIME_API.md).

## Where each plan stands (2026-10-05)

Handoff packages keep the status line they were delivered with; this table is the current answer.

| ADR | Plan | Status |
|---|---|---|
| 001 | V1 architecture and Codex package | Delivered and run; superseded by the later plans (its eval commands were removed). |
| 002 | Core-first reset: local entry and autonomous QQ access | Superseded (QQ is implemented through 003/005/008). |
| 003, 003.1 | V2.2 NapCat native flow; DSH extension correction | Implemented in later forms; historical. |
| 004 | UI elements V1 kit | Superseded by 006, then 008. |
| 005 | QQ functional | Implemented: P1, P2, P5 and P3 deployed; P4 dropped. |
| 006 | Native UI reuse | Superseded by 008. |
| 007 | Autonomous self-development foundation | Implemented (foundation report 2026-09-25). |
| 008 | DSH native plugin | Implemented. |
| 009 | Persona residency | Implemented, merged 2026-10-05; person files retired the same day. |
| 010 | DSH distributable plugin | Approved 2026-10-05 (GitHub Release .tgz, uv, MongoDB, local inline patch, GPLv3); not implemented. |
| 011 | Her two brains on native tools | Implemented; live acceptance completed 2026-10-05. |
| 012 | Heartbeat and places | Implemented 2026-10-05. |
