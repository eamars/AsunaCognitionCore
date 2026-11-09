# ADR-118 progress

Each landing's evidence, in the order they land: the commit, the suite and integration counts, the adapter's offline
selftest, the greps for removed names, her skills' checks, and for a restart the install checks.

## L1, 2026-11-09: dead tests and tools out (`19df4df0`), with this page (`62dd8d21`)

- Landed `62dd8d21207c` with `land.py`, no restart. Suite on the commit: 962 passed, 13 skipped; node 307 passed, 0
  failed; the prepared start imported 153 modules, 0 problems; `docs/map` current; pushed.
- `pytest integration` at the commit: 133 passed.
- Adapter `--selftest --offline`: pass 423, fail 0, skip 5. Her 14 `check_skill.py`: rc 0, before (`3b694041`) and
  after.
- Removed names, `git grep -nF` outside `docs/development_plans`: `qq_face_census`, `test_adr009_p0`,
  `test_adr009_p1`, `tests/reply_parts`, `import reply_parts`, `HOST_SANDBOX`, `preserve_temporary_evidence`,
  `--baseline`, `--hooks`: 0 each.
- A first run stopped on one failing test: its label had a space, which went into the suite's worktree path, and the
  sandbox test splits its output on spaces. The re-run with `ADR-118-L1` was green. Nothing landed from the first run.
