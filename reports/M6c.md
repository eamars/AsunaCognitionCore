# M6c — runtime boundaries and additional acceptance drivers

This is an intermediate stage report, not a V1 acceptance declaration.

- Engineering regression: 45 tests passed (`check-20260919T101050Z-adc0ee`, actual exit 0).
- Scoped erasure: actual Gemma/native compaction plus private reflection sessions passed (`E20-probe-20260919T094352Z-488dc3`). Ownership is recorded before native delivery and all associated evidence roots are tracked.
- Real GridFS: >1 MiB content stored and independently read back by SHA256; IDOR denied; private-scope erasure removed both file and chunk records (`blob-probe-9bf2ec38d226`). Large provider bodies now obtain GridFS manifests in addition to their full local evidence files. Arbitrary oversized state documents still fail closed and require the explicit BlobStore API.
- Native DSH compaction: invalid tool-pair cut rejected before summarization; injected summary failure retained original surface and survived serialized-log restoration (`native-atomicity-20260919-02`). First attempt's cleanup error and actual exit 1 remain in attempt 01.
- Actual sanitized ZIP probe passed, including nested frozen-input archives, exclusion of private logs, unchanged source bytes, and preserved unrelated float/hash substrings (`export-probe-22ae5b1b47ae`).
- Relationship matrix L05 completed 36 real Gemma scenarios. All protocol paths completed; human relationship/naturalness votes are still missing, so L05 is INCONCLUSIVE. L06 returned three valid no_change reflections and resumed native processes; rationale assessment remains INCONCLUSIVE.
- F01 completed 24 real requests; 23 passed. Both deployments passed all 8k/65k/196k repetitions; Gemma passed all 234k repetitions; Qwen passed two of three at 234k. First failed at the adapter idle timeout although the upstream later returned. A second narrow probe exposed another request timeout. Both remain failures. The next transport probe explicitly sets supported timeoutMs/streamIdleTimeoutMs and sends only a transport comment after upstream acceptance, withholding model content until evidence is durable.
- L07/L08/L10 include real failures (reasoning-only/empty content, silent-episode compaction boundary, and transport timeout). They are not overwritten or promoted by mock tests.
- New L09, L11 and A02 drivers are undergoing narrow runtime probes. Their presence is not completion of their matrices. A01 and L02 are still running under their original frozen configurations.

Independent review transport is available through `asuna review-pack` and `review-import`; missing ratings remain null, source alterations and invalid scores are rejected, and import never declares cognition PASS. The 60-item protocol review page is `blind-review-probe-20260919-01/review.html`.

No shared model launch parameters, default DSH profile, old database or messaging connector were changed. The DSH bridge TypeScript is unchanged during the original active A01 experiment.
