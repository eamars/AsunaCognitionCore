# M7d — Hash-bound report interpretation

The report now attaches source-specific engineering observations to exact result hashes, including the independent exact-marker F01 audit and F02 provider error bodies. An observation never changes an attempt status and is not a human cognition vote. A stale evidence hash or wrong test ID fails report generation.

The real report preview passed the original 41-ID package validator with `--allow-incomplete`. Two invalid-annotation counterexamples were rejected; six report checks passed. The preview command returned exit 1 because its overall acceptance status is FAIL, not because generation failed.

The complete existing regression suite passed: 58 tests in 65.64 seconds, exit 0. Updated clause review yields 23 PASS / E01 INCONCLUSIVE; the missing historical isolation baseline is still missing. These observations do not change frozen model inputs for ongoing A01/L02 runs.

See `M7d.json` for exact evidence paths and hashes. A01/L02 are still running; this preview is not the final deliverable.
