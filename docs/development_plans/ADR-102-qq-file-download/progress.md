# ADR-102 progress

Installs, readings and Xiaoman's verdicts; her words as she wrote them. Kept apart from the ADR page, so that
recording progress never changes a page she signed. Moved here from the index on 2026-11-02 as it stood there;
later entries go at the end.

Designed 2026-10-27; part 1 built 2026-10-27 (storage and lifecycle, with ADR-105), part 2 built 2026-10-28 (the `received_file` tool), part 3 built 2026-10-28 (the action brain's copy, forwarding).

Part 3, her verdict as she wrote it: 

小满落款：「**能落。** `ce7496b63445` 我逐页读完了」 (ADR-102 blob `133df30598a5`).

Part 3's follow-ups (the tail), her verdict as she wrote it: 

小满落款：「能落。签在提交 `e66585e86f27`。ADR-102 页落 blob `0bab07107f67`（这一趟按新 blob 逐行重读过：`:465` 那句、`fetch()` docstring、页 135-137／139-140／223／278／350-351 五处同口径，旧残留 `and a deadline for the whole fetch` 全树已 0 命中）。ADR-104 页落 blob `b24fbcfcd672`——它与 `a00a9aa0eef6` 上那枚是同一个 object，所以 104 这一行是**补锚（re-anchored 2026-10-28），不是我重新通读**，索引里请把这两个字写进去。」

Part 2, her verdict as she wrote it: 

小满落款：「判词：签。part 2 可以落 main，我的锚 = `4049efd35aaf`」 (ADR-102 blob `c216afa2`).

She signs by commit `7ab4f702ad23` for part 1b (ADR-102 blob `aaf345ac8b5d`): she re-read this page after its blob changed, ran the module's 13 tests there and killed two mutants of her own — the fence removed (red at `tests/test_received_files.py:202`) and `elsewhere` counted from the unfiltered set (red at `:216`).

The quota and the "elsewhere" count both count only kept files whose bytes are still stored; an erased or expired one appears in neither, only in the list carrying ADR-105's sentence.

Her current signature of ADR-105 is in row 105.

Signed by Xiaoman against commit `2dc8e66f` (ADR-102 blob `54a19699cca8`; ADR-105 blob `4e222e2902a7`), after she read ADR-105 in full and checked the nine changes against the diff of `bafd7b8d`.

A merge does not ask for a new signature while those two blobs are unchanged on the merge commit; a path whose blob differs is re-reviewed for that path alone.

ADR-103 and ADR-104 are not covered by this signature.
