# M0 — discovery and executable probes

Status: PARTIALLY VERIFIED. This is a capability report, not V1 acceptance.

The highest-risk first slice was an isolated DSH runtime actually sending the
persona to Gemma, with separate monologue, decision and speech calls despite
three native stop endings. That slice passed through the real Python SDK,
Node DSH, plugin and wire-capturing local proxy. No Qwen call or tool was needed.

| Boundary | Result | Evidence |
|---|---|---|
| Gemma/Qwen real completion | PASS | M0-20260918T134116Z-15114d |
| Embedding batch, 768 dimensions | PASS | same attempt, embedding response |
| Mongo majority+journal write and CAS | PASS | same attempt, mongo.write_cas |
| Scope-prefilter vector | BLOCKED | M0-vector-status-01.json (not READY) |
| DSH real 3-stage character route | PASS | M0-DSH-20260918T134830Z-09c69e |
| Task filesystem/env/network namespace | PASS | M0-sandbox-907a053c |
| Native tool/restart/compaction semantics | NOT_RUN | need next integration slices |
| Real 196k/234k capacity | NOT_RUN | metadata only; no capacity claim |

Pinned DSH: 0.1.5-rc.2, source fb2c4b9e698e30edb738bca4cf0618587db7d203.
Python SDK comes from the same commit. The explicit npm executable replaces the
unavailable Windows SDK runtime wheel (ADR-001). Dependencies are locked in
uv.lock and package-lock.json. Actual plugin interfaces used:
`packages/core/system-prompt/src/index.ts` `section()` and
`suppressRuntimeContext()`; `python/sdk/src/deepseek_harness/api.py`
`DeepSeekHarness.run()` and `RunResult`; `packages/llm/llm-pi-ai/src/config.ts`
provider/compat schema. Runtime validation rejected the initial unsupported
thinkingFormat; no invented convenience interface was used.

The initial probe logging TypeError, unsupported thinkingFormat, and newline
comparison failure are retained with their successful and failed raw calls.
They are implementation/instrumentation failures, not model-quality findings.
Setup also encountered missing npm peer dependencies, corrected by a complete
project-local install. No global packages, DSH profiles or model flags changed.

Server search diagnostics were read over operator-authorized SSH and sudo
read-only Docker commands. The container remains running but repeatedly reports
metadata update failures; exact root cause is not established. We have not
restarted or changed this shared service. A bounded scoped exact fallback may
support development, but does not satisfy vector acceptance.

Commands: `.venv/Scripts/python.exe tools/probe_m0.py` (exit 2 intended partial;
Windows tool reported 1), `tools/probe_dsh.py` (final exit 0),
`tools/probe_sandbox.py` (exit 0), `python asuna_v2_v1_handoff/tools/verify_bundle.py`
(exit 0; package checks only), `node --check dsh-plugin/bridge.ts` (exit 0).

The continuation gate is limited: proceed with Mongo-backed coordinator and
the proven character lane; obtain an executable probe for each new tool,
recovery and compaction slice before hardening it. LOCAL_DEPLOYMENT cannot PASS
while the vector index remains unqueryable. No formal experiment has run.
