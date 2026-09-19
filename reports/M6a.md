# M6a — operator CLI and erasure boundary

The production CLI, fixture router and acceptance scenario driver use the same
Coordinator, TaskService and PublishService. Quiet group input is persisted
without waking a model; queued scenes receive at most two consecutive episodes
while a peer is waiting. The executable check is in test_engineering_m6.py.

E20 probe `E20-probe-20260918T145112Z-c0d9e7` failed: redaction removed fields
needed by the compound episode uniqueness index. Its failure and raw evidence
remain. The new attempt `E20-probe-20260919T085340Z-1a4a22` passed actual Gemma
generation, native compaction, scope erasure, chain rebase, session invalidation
and a new-epoch request without the deleted canary. The chain rebase is explicitly
declared and preserves prior roots; it does not claim the original chain survived
redaction unchanged. This is conservative scope-wide derived-content erasure,
not selective semantic unlearning. Global-safe deletion is currently rejected;
downloaded exports and external backups cannot be recalled.

Validation `check-20260919T085628Z-bd013d`: 31 real-Mongo engineering tests passed,
including bounded subprocess output, literal shell arguments, expired leases,
owner-only task cancellation, duplicate feedback and the erasure regression.
This is still partial coverage of E01–E24, not a full ENGINEERING PASS.

The sandbox now enforces its output limit while reading the child process and
kills the process group on excess or timeout. `M0-sandbox-59bc88ea` repeats the
actual WSL namespace probe after this change. Provider success headers are sent
only after the complete response is durably captured. Native lane receipt reuse
requires an identical semantic request; older receipts without this check are
rejected instead of silently trusted.

Formal L01/A01 runners are now present, after the M0–M5 integration probes.
No cognition result is claimed here. Human review remains mandatory. The CLI
report/export implementation and additional formal matrices remain in progress.
