# M7b — complete F02 measurements, with deployed-provider failures

`formal-F02-20260920-01` completed its full fixed plan: 166 private turns and two
native summaries. The actual CLI exited 1 because seven Gemma hot-session calls
failed. Gemma completed 76/83 calls normally; Qwen completed 83/83. No failed
sample was replaced or omitted. No other own model evaluation ran during F02;
unrelated traffic on the shared endpoints cannot be excluded.

| Fixed prompt replay | Hot observations after first call | Mean reported reuse |
| --- | ---: | ---: |
| Gemma | 9 | 99.34% |
| Qwen | 9 | 98.32% |

Both fixed-prefix request hashes stayed stable and the measured cache ratios
exceeded 90%. This subset passes; F02 overall remains FAIL. Each model also had
ten real continuations, ten cold A-B-A cycles, ten hot A-B-A cycles, and turns
before/after actual native compaction. Cold means fresh native sessions and
distinct leading prefixes, not a claimed server cache flush. Native compaction
durations were 9.907 seconds (Gemma) and 22.834 seconds (Qwen), with exact summary
request/response joins.

Six Gemma failures had native error termination; their actual HTTP 200 streams
contained server_error code 500 stating that output did not match the expected
peg-gemma4 format. One further call exhausted the 4096-token output budget. All
occurred in the frozen hot-session workload. These observations do not isolate
model generation, MTP or parser root cause. Model/server settings were unchanged.

`f02-format-diagnosis-20260920-03` verifies all seven failures against native lane
sequence bounds, final chat/completions URLs and exact original request-body
hashes. Its executed CLI exited 0 and made zero model calls. Earlier extraction
attempts are retained and explicitly superseded: one included tokenizer calls
and produced stale extraction references, and two used logical-action labels
instead of exact command provenance. The correction does not alter source
model requests, returns or experimental outcomes.

Unknown counters remain null with reasons. Model load/switch times are not
inferred on shared persistent services; private transport/model-content timing
is not public speech latency. Public receiver latencies reference their separate
actual L02 traces and may include the earlier concurrent evaluation load. No
absolute performance SLO was approved before freezing this run, so a latency
experience PASS is not asserted. All raw per-call timings and failures remain
available in the experiment result and provider artifacts.

The combined observed outer command returned F01_exit=0, F02_exit=1. L09's new
hardest-condition probe started only after this measurement sequence finished.
