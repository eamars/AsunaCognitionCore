# M6e — retained attempts, transport audit, state recovery and Browser evidence

V1 remains INCONCLUSIVE as an implementation milestone. The approximate 70%
completion estimate describes work remaining, not acceptance pass rate. The
immutable fixture and thresholds are unchanged. Exact artifact SHA256 references
are in M6e.json; individual result files retain commands and process exit codes.

- Full regression: `check-20260919T235416Z-75d1d3`, 58 passed, exit 0. Includes
  real Mongo, scoped revision fencing, replay, process crashes and WSL sandbox.
- Installed DSH survives more than 300 seconds of local queue admission in
  `queue-header-probe-cdb9228406`. The loopback upstream is deterministic; this
  proves transport, not model quality. The preceding probe failed the genuine
  minimum-system guard and was not a queue-timeout failure.
- Provider failures now have terminal `provider.error` records with call IDs,
  request references and partial-body accounting. Default local read/idle/workflow
  deadlines resolve to 1800 seconds in the frozen configuration. Earlier v3
  aggregate timeout claims were too broad; v4 records that correction. No model
  service launch parameter changed.
- A real narrow L12 retry passed its file oracle, actual injected read failure,
  native summary, task completion and delivered Gemma feedback. The full 5+5
  matrix remains separate. Matched L12 controls now receive the same fault and
  compaction schedule; previous controls lacked both, recorded append-only in
  `trial-evidence-correction-c070f74b5b`.
- Retrieval's stale-vector-ID injection now intercepts the actual collection
  aggregate call. Corrected full L04 passed, Recall@6 1.0, 11 nonliteral vector-only
  queries. Earlier ineffective injection and failed attempts remain available.
- Scope, rollback and erased-session probes passed their stated boundaries.
  Operator rollback appends a CAS revision and retains source processing; it
  does not erase history. Legacy-isolation evidence covers the observed probe
  interval, not an unavailable pre-implementation database snapshot.
- User-requested suspension preserved partial A01/L02/L03/L12 attempts and stopped
  this project's processes. New formal attempts have new experiment IDs. Earlier
  A01 partial counts were clarified: 51 protocol-valid of 52, four route mismatches,
  47 combined passes. No partial run is presented as a full matrix.
- In-app Browser now renders and exercises the review and audit pages. It verified
  paging/retained edits, missing-reply labels, full JSON copy export, actual hashed
  provider request display and native compaction range/summary display, with no
  console errors at observed widths 1265 and 486. Download receipt is unobserved.
  Synthetic UI scores were rejected by the independent-human import guard and the
  visible form was reset. This supplies zero human cognition votes.
- The exporter accepts only explicitly reviewed images with exact hashes;
  unreviewed and changed images are rejected. Real screenshot bytes were tested
  through archive I/O alongside synthetic ordinary/nested-archive redaction. Image
  review is visual and cannot be described as automatic exhaustive credential
  scanning. Complete repository export remains pending.

Failures retained include L08 output-budget exhaustion, L10 unsolicited delegation
on chat inputs, the original F01 234k timeout, L09 incomplete executor output,
noise protocol failures, and noise summaries that occurred before the actual
73k-token log. The noise read-order retry is a new frozen probe; old runs stand.
These failures must not be attributed generically to model weakness.
The new `noise-load-probe-828cf4480a` passed: 72,814 server-counted tool data
tokens, actual later summary containing the noise, and a completed task. This
validates load delivery only; it does not replace the full A02 comparison.

Remaining work includes complete formal matrices, full cache/latency evaluation,
audit revision diffs and complete before/after content presentation, final report
and sanitized archive, and independent human cognition ratings. COGNITION remains
INCONCLUSIVE. Source, environment, failed attempts and operator limitations remain
auditable rather than selecting only successful outputs.
