# M7a — complete real F01 capacity matrix

`formal-F01-20260920-01` completed all 24 required live samples, exit 0. Both
specified endpoints, the pinned DSH adapter and isolated Mongo databases were
used. All three start/middle/end needles, provider stop, target-length tolerance
and returned prompt-token counts passed for every sample.

| Deployment | Target | Actual input tokens, three repetitions |
| --- | ---: | --- |
| Gemma | 8,192 | 8,196 / 8,172 / 8,177 |
| Gemma | 65,536 | 65,530 / 65,526 / 65,527 |
| Gemma | 196,608 | 196,606 / 196,554 / 196,644 |
| Gemma | 234,000 | 233,967 / 233,963 / 234,032 |
| Qwen | 8,192 | 8,171 / 8,160 / 8,194 |
| Qwen | 65,536 | 65,557 / 65,539 / 65,528 |
| Qwen | 196,608 | 196,627 / 196,583 / 196,644 |
| Qwen | 234,000 | 233,984 / 233,981 / 233,977 |

The frozen matrix began at M6i. `capacity-association-audit-a5867f773264` then
independently checked the exact marker-to-code/value association in every saved
reply: 24/24 verified, exit 0, zero new model calls. Its own frozen checker and
input hashes are retained. This stronger check rejects the swapped-answer
counterexample; it does not rewrite the original source result.

All failures in the previous 23/24 matrix remain available. Model weights,
sampling, server launch flags and declared context limits were not changed.
This run includes the previously documented client transport repair; all
implementation differences are recorded in the two frozen source archives.
F01 explicitly overrides the lower normal working budget to
test capacity; no server capacity is inferred from client metadata.

This establishes these tested lengths and needle retrieval, not arbitrary
262,144-token completion or complex-task quality. Qwen's final rendered OpenAI
token IDs remain unavailable; equivalent server counts match actual usage.
F02 is running separately with no other own model-evaluation workload.
