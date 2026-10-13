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

## Git over HTTPS (2026-10-13)

She reported that `git` over HTTPS failed in her confined commands (Schannel: `SEC_E_NO_CREDENTIALS`, `curl.exe` the
same) and worked around it each time with `-c http.sslBackend=openssl` and certifi's CA file.

Cause, measured on the owner's Windows Host: LSA gives no SSPI credentials handle to a token with restricting SIDs.
DSH's runner makes a `WRITE_RESTRICTED` token with restricting SIDs (logon SID, Everyone, the write SIDs), and every
package fails there, not only Schannel: impersonating such a token, `AcquireCredentialsHandle` for Schannel and NTLM
returns `0x8009030e`; the same token without restricting SIDs (only `DISABLE_MAX_PRIVILEGE` or `LUA_TOKEN`) gets one.
Git for Windows defaults to Schannel in its system config, so every HTTPS git call failed.

Decision: a confined command's environment on Windows carries `http.sslBackend=openssl` as git configuration
(`GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_0`/`GIT_CONFIG_VALUE_0`), in `sandbox_backend.environment` and in `floor.js`'s
`commandEnvironment` for every candidate. Git's bundled `ca-bundle.crt` is readable there (reads are not restricted),
so no `http.sslCAInfo` is set. Only on Windows: elsewhere git may be built with one TLS backend and refuses an
unknown one. Verified: `git ls-remote https://github.com/eamars/deepseek-harness HEAD` fails confined before and
succeeds after; `test_git_in_a_command_uses_a_tls_that_works_inside_the_sandbox` reads the effective setting in a
confined command without a network call.

Considered and not taken: patching DSH's runner (the restriction is what the sandbox is; dropping restricting SIDs
would undo the write confinement), certifi's bundle (git's own is readable), and a rule in her skill to add the flag
herself (a fault of the environment she would have to remember).

Found on the way, not changed: MSYS programs (Git for Windows' `sh.exe`) do not start in a confined command. The
token has Low integrity, and the MSYS shared object folder, already made by the Host user's own MSYS processes, refuses
it create access (`NtCreateDirectoryObject` `0xC0000022`; the same open succeeds outside the sandbox). Git starts credential helpers, hooks and `!` aliases through
`sh.exe`, so `git credential fill` finds nothing there, although `git-credential-manager.exe get` run directly does
find the Host user's login. Whether her confined git may push with the Host user's login, and how, is the owner's
decision. `curl.exe` (System32's, and Git's even with `CURL_SSL_BACKEND=openssl`) stays on Schannel and cannot open HTTPS
there; Python's HTTPS works.

Cost: no tool, prompt or per-turn change; the core skill `asuna-self-improvement` states the facts.
