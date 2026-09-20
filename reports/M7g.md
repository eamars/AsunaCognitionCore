# M7g — Scenario failure provenance

`tools/diagnose_scenarios.py` indexes observed protocol/route flags, exact generation requests, native outputs and trace references without rating personality or semantic correctness. It reads only completed source experiments and verifies saved sample fields and actual request-body hashes.

The first A03 extraction exited 1 because a trace array was treated as an event object. That failed attempt remains intact. Restricting event extraction to numbered event files produced a new successful attempt: 72 samples checked, all six failed outputs retained, no missing failure traces. Absent-memory and monologue-off each have 15/18 valid protocols; correct and corrected memory each have 18/18. Semantic review is still required in every condition.

No core runtime changed; no model call or database write occurred. These offline diagnostics do not replace source results or imply cognition PASS. The same extractor is ready for the full A01 output after it completes.
