# M6b — formal baseline and runtime hardening

The frozen L01 baseline completed 60 scenarios: first decision valid 60/60,
post-repair valid 60/60, expected route 55/60. Every P06 response acknowledged
unknown weight without requesting verification. This specific behavior failure
is retained even though aggregate route accuracy exceeds the preregistered 90%
threshold. The outer CLI exited 1 after persisting results because Windows
stdout could not encode Chinese; invocation.json records the actual exit and
the CLI now explicitly uses UTF-8.

L04 passed twice. The second experiment includes the newly verified embedding
weight pin: actual Ollama blob SHA256 matches its manifest and served alias,
and fresh embedding clients reject a changed digest. Recall@6 is 1.0, all
critical cases hit, 11 queries succeed with vector ranking alone, unauthorized
scope text is excluded, and pending/stale index paths are explicitly tested.

The initial L03 one-task design probe and its Qwen-only control both hit the
former 300-second whole-workflow timeout. The task instruction also ambiguously
protected the working stats.py; the next experiment explicitly distinguishes
the editable task copy from the immutable original fixture. The timeout is now
1800 seconds for the complete bridge operation, with existing per-model/tool
bounds retained. Neither change alters server model flags or scoring thresholds.

The first F01 reduced probe found all three needles for both lanes around 8k;
its result was labelled FAIL by the full 24-request completeness check. That
instrumentation failure remains, and reduced probe status is now separate from
full acceptance. The full F01 matrix is running; no 196k/234k claim is made here.

`check-20260919T092116Z-713138`: 38 engineering tests passed, including five
actual process crash points, read-only source mounts and an independent local
HTTP observer that detects one deliberately unaudited auxiliary stub call.
`M5-20260919T091831Z-33280f` passed actual complete-episode native compaction
after the bridge update. Mid-task compaction remains under executable probe.

Further changes include a per-home process lease, rejection of erasure while
another runtime owns the home, preserved initial system prefixes with appended
version updates, read-only task inputs, terminal UNKNOWN on interrupted executor
work, and explicit operator-only transient-read fault injection. These require
the next regression run; this document does not extend the earlier test result
to code changed after it.

No independent human ratings exist. COGNITION is INCONCLUSIVE. L05–L12,
A01–A03, F02 and several engineering subclauses remain incomplete; report
compilation must preserve those gaps. Startup instructions, migrations,
dedicated real-task/capacity/retrieval drivers and a redacting exporter are
implemented, with export verification still pending.
