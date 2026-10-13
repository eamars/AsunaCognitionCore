# ADR-065: Temporary folders inside the sandbox

Status: **Accepted 2026-10-13** (owner: write it; built the same day).

## Context

Her scripts run under DSH's sandbox (ADR-015): a command may write only its own folder (a task's folder for
`sandbox_run`, the candidate for `development_run`), and on Windows that write grant reaches the folder's contents by
inheritance. Two things broke `tempfile` there, found while fixing her sandboxed test runs (fffdc934):

1. A confined command inherited the system's `TEMP`/`TMP`, a folder it may not write; `tempfile.gettempdir()` then
   fails or falls back unpredictably.
2. CPython on Windows turns `mkdir(mode=0o700)` (`tempfile.mkdtemp`, `TemporaryDirectory`, pytest's `tmp_path`) into
   a protected ACL that drops inherited entries, so the folder a confined command just made is one it can neither
   list nor write.

The test harness worked around both for tests; her own scripts still hit them.

## Decision

The fix lives in the confined command's environment, which is Asuna's, not in DSH's runner: the runner grants by
inheritance when the command starts, and the folder is created later by Python, so only code inside that Python, at
creation time, can keep the grant.

- A confined command's `TEMP`, `TMP` and `TMPDIR` are `.tmp` inside its own folder (`sandbox_run`: the task folder;
  `development_run` on a core candidate: the candidate, outside what publishes).
- Its Pythons load `src/asuna/sandbox_site/sitecustomize.py` (the folder is on `PYTHONPATH`): on Windows a 0o700
  folder is made with its parent's permissions instead.
- Channel candidates are left as they were (their files all publish; nothing there has needed a temporary folder).

Considered and not taken: a patch to DSH's Windows runner (it cannot reach folders created after start), and telling
her to avoid `tempfile` (a rule she would have to remember for a fault of the environment).

Cost: no tool, prompt or per-turn change. Test: `test_sandbox_backend.py`, a confined `mkdtemp` and
`TemporaryDirectory` write inside the task folder (fails without the fix).
