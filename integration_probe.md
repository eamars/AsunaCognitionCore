# Current integration status

This supersedes the *status summary*, not the preserved evidence, in
`reports/integration_probe.md` (M0). Full acceptance remains in progress.

| Boundary | Observed result | Evidence |
| --- | --- | --- |
| Isolated DSH 0.1.5-rc.2 / matching SDK | Actual character, tool and durable-session probes pass | reports/M0–M5 stage reports; ADR-001 |
| No-tools staged character | Native MONOLOGUE, DECIDE, SPEAK; program advances after stop | M2-20260918T141400Z-e11988 |
| Real task route | Gemma intent → Qwen tools → Gemma feedback → local publish receiver | M3-20260918T144114Z-b9152a |
| Native complete-episode compaction | Actual same-lane summary and DSH brackets, no mock | M5-20260919T091831Z-33280f |
| Embedding weights | Ollama served alias and registry manifest matched; actual GGUF hash verified over authorized SSH | embedding-fingerprint-20260919T091301Z-32b938 |
| Vector retrieval | READY; Recall@6 1.0 across 12 gold queries + 200 distractors; 11 nonliteral vector-only successes; stale-ID fault injection confirmed actually intercepted | formal-L04-20260919T111218Z-41b06a; retrieval-evidence-correction-d1ef4fc146 |
| Scoped erasure | Native summary/session invalidated, new epoch excludes deleted canary | E20-probe-20260919T085340Z-1a4a22 |
| Crash boundaries | Five real process kill points plus idempotent/UNKNOWN checks | check-20260919T092116Z-713138 |
| L01 60 scenarios | Format 60/60, semantic route 55/60; all five P06 runs did not delegate | formal-L01-20260919-01 |
| Real 196k / 234k | Both models passed all three 196k samples; first full matrix 23/24 due to Qwen 234k client timeout; new transport probe at 233984 passed, full rerun pending | formal-F01-20260919T092450Z-ced9f8; capacity-stream-reprobe-4db631d2b7 |
| Deferred compaction | Queue survives interrupted monologue and process restart; actual summary only at completed episode boundary | deferred-compaction-ecd35834ff |
| Intent revision / effect fence | v1 stale after v2; old effects preserved, old evidence rejected; separate process cancellation serializes with real sandbox effect | revision-probe-614d286cdb; effect-fence-probe-8145bf2a25 |
| Independent cognition review | Not completed | COGNITION must remain INCONCLUSIVE |
| In-app Browser | Review pagination, blank ratings, full JSON copy, actual requests, revision diffs and individual compaction input/summary verified; JSON navigation blocked and download receipt unobserved | ui-qa-20260920-01/03/04; ui-qa-correction-20260920-01 |
| Each native summary | Real 72,814-token load; two replacements individually joined to exact provider output and requests | noise-load-probe-7120c99405; compaction-evidence-correction-20260920-01 |
| Long executor task narrow retry | Real Qwen task, injected read failure, native summary, oracle and Gemma delivered feedback passed; full 5+5 matrix pending | formal-L12-20260919T232433Z-38883b |
| Local queue transport | Installed DSH client stayed alive through more than 300 seconds of local queue wait; deterministic local upstream, not a quality evaluation | queue-header-probe-cdb9228406 |

The Python SDK lacks the session lifecycle/compaction operations needed here.
The small native bridge uses actual pinned `agents.create/resume`, `followup`,
`whenIdle`, `sessions.flush`, `sessionPersistence.stat`, `systemPrompt.section`
and `compaction.compactRegion`. The replaceable `Lane` protocol keeps these
details out of the coordinator. Default cloud providers, title generation and
host shell tools are disabled. Auxiliary summary, repair and embedding calls
have distinct purposes and pass through local capture.

The bridge-level provider proxy captures the final outgoing HTTP body, not just
the prompt builder's expected messages. Gemma exposes apply-template and token
IDs. Qwen exposes a token-count endpoint through equivalent Anthropic conversion;
counts matched all 11 requests in the measured M3 probe, but final OpenAI token
IDs are unavailable. Response buffering permits durable audit before DSH sees
success; its transport first byte must not be presented as public-text latency.

Environment fingerprints are in `environment.json`, with prior immutable
versions retained under `reports/environment-*`. Qwen is the deployed
Qwen3.8-Flash-Next-Uncensored-NVFP4 variant, not an assertion about all Qwen
weights. Its qwen4_exp loader excludes MTP tensors; disabled MTP is a source- and
launch-supported inference, not a measured speculative counter. Gemma target
and Q8_0 MTP draft hashes are pinned. No model launch parameters were changed.

User-authorized Mongo nofile repair is documented separately. The running
mongod and its parent received a higher soft limit without restart; the Compose
file carries 64000/64000 for the next container recreation. Old database data,
default DSH profiles and existing Kazusa/小满 application configuration were
not modified.

Remaining scope limitations include global-safe deletion (rejected), external
backup/export recall, explicit rather than automatic compaction, and incomplete
formal matrices. A probe passing is never promoted to full acceptance by this
document. The report compiler preserves all failed attempts and missing tests.
