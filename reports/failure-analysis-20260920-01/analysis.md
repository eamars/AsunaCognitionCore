# Failure observations, before completion of the remaining matrices

These are engineering observations from named frozen attempts, not independent
human ratings or claims about an underlying model's inherent personality.

| Attempt | Observation and classification |
| --- | --- |
| formal-L01-20260919-01 | All 60 decisions were structurally valid; five P06 outputs did not choose the expected delegation route. Route 55/60 still meets the fixed 90% L01 threshold. This is a recorded semantic-routing weakness, not proof of diluted personality. |
| formal-L08-20260919-02 | Two g2 warmup SPEAK calls returned native max-tokens with no content (10,949 reasoning characters each). This is an output-budget/protocol failure under the frozen 4096-token deployment configuration. Missing later continuity answers cannot be counted correct. Completed silent episodes also require semantic review. |
| formal-L10-20260919-02 | The actual file task, feedback, fair routing and scope checks passed, but five of twenty fixed greeting episodes ended WAITING_TASK rather than COMMITTED. The failed assertion is model route behavior under these inputs; it is not evidence of scheduler starvation or private-scope leakage. |
| formal-A03-20260919-01 | Six of 72 samples entered FAILED_PROTOCOL. In sample-0001 the model requested recall with an empty recall_query, then repeated the same invalid decision during its allowed repair. Valid JSON syntax did not satisfy the decision schema. No public message was delivered for that sample. Human memory-quality conclusions remain unresolved. |
| formal-F01-20260919T092450Z-ced9f8 | One Qwen 234k sample hit the former client timeout; the remaining 23 passed. Independent exact-marker reassessment verified correct START/MIDDLE/END associations in all 23 passing returns. This old failure does not establish a lower server context ceiling. The new full live matrix is still running. |
| formal-L11-20260920-01 | The first wrong-argument task encountered the intended missing-file error, then lost its native HTTP stream during a long upstream queue. Its task became UNKNOWN with no committed copy receipt. The later upstream response did not retroactively make the task successful. A >400-second real-client probe separately verifies the transport repair. |
| performance-probe-74d249d8c7ab | Native DSH rejected summaries larger than a 47-token history. The bridge's NO_CAUSAL_TURN_RESULT obscured that native cause. Both the guard and the adapter error mapping now have executable evidence. |
| performance-probe-0cb467f846b4 | The synthetic measurement instruction requested both summarization and brief confirmation. Gemma exhausted its output budget while reconsidering those requirements. The revised measurement instruction and every failed response are preserved; this was not a change to a truth fixture or acceptance threshold. |

The missing pre-implementation isolation snapshot remains an evidence gap (E01).
Later interval probes cannot establish a historical fact that was not captured.
No human cognition vote has been supplied. Full matrices and source-specific
reports remain necessary; these observations do not promote probes to V1 PASS.
