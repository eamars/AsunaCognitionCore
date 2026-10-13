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
it create access (`NtCreateDirectoryObject` `0xC0000022`; the same open succeeds outside the sandbox). Git
starts credential helpers, hooks and `!` aliases through `sh.exe`, so `git credential fill` finds nothing there, although `git-credential-manager.exe get` run directly does
find the Host user's login. `curl.exe` (System32's, and Git's even with `CURL_SSL_BACKEND=openssl`) stays on Schannel and cannot open HTTPS
there; Python's HTTPS works.

Cost: no tool, prompt or per-turn change; the core skill `asuna-self-improvement` states the facts.

## Her own working copy, and pushing with the owner's account (owner, 2026-10-13)

The owner wanted her to work on the project as the coding agents do: commit and push. Three ways were weighed:

- **A, chosen:** her own permanent working copy in her home working folder, which her commands may already write.
- **B, not chosen:** her commands write the whole local checkout. Built and measured on a branch, then dropped: DSH's
  Windows grant labels everything under its root Low integrity, and Windows starts a program whose file is labelled
  Low at Low integrity. The checkout holds `.venv`, whose Python is the worker's: started from it, the test suite could
  no longer write `%TEMP%` or uv's cache, and the Host's worker would have failed the same way at its next start. The
  grant was removed again; the owner account's inherited Full control of the checkout, which it needed, stays (harmless).
- **C, not chosen:** a patch to DSH's Windows runner, kept on the fork for every DSH alpha (ADR-037), for what A gives
  without one.

The owner also decided that she pushes with the owner's GitHub account.

Decisions for the build:

- **The working copy:** `<her home working folder>/working-copy` (`.runtime/work/local-user/working-copy` in a
  checkout's own data folder), the folder her local chat, agent lines and peer line work in. The Host makes it at start
  (`working-copy.js`, called after the worker is up) when it is missing: a clone of the checkout's default branch from
  disk (no network at start; its own object files, no hard links), `origin` set to the checkout's origin, fetching every
  branch. Made beside it and renamed, so a half-made copy is never taken for hers; one that is there is never changed.
  It is never the checkout, and nothing the Host runs is in it. Her author name comes from `character_git` as for every
  command.
- **The login:** git starts a credential helper through `sh.exe` whatever the helper's value: it appends the operation
  (` get`), and a command with a space goes through the shell, so an absolute or 8.3 path to Git Credential Manager does
  not help (tried: both went through `sh.exe`). Git starts its askpass program directly. A confined command on Windows
  gets an empty credential helper list (`credential.helper=` through `GIT_CONFIG_COUNT`, beside `http.sslBackend`), and
  a `sandbox_run` command gets `GIT_ASKPASS` = `asuna/sandbox_site/git-askpass.cmd`, which runs `git_askpass.py` with the
  worker's Python: it asks `git-credential-manager.exe get` (never interactively) for that remote and prints only the
  username or the password git asked for. The token reaches git through a pipe, never a command line or a file.
  Persona jobs and managed integrations do not get it (an adapter handles public input). Verified in the real sandbox
  from a working copy made by `working-copy.js`: `git push --dry-run origin HEAD:refs/heads/probe/askpass-dry-run`
  succeeds (GitHub asks for a login even for a dry run), and without the askpass it fails with "could not read
  Username"; nothing was pushed.
- **Getting her work into what runs** (owner: only on restarts she asks for): nothing synced the checkout from
  `origin` (the launcher installs what the checkout holds). Now the first start of a restart she asked for runs
  `fastForwardCheckout` (`tools/asuna-launch.mjs`, in the fresh `--prepare 0 --fast-forward` process, before it
  installs): fetch `origin main`, then `git merge --ff-only` only when the checkout is on `main`, its tracked files are
  unchanged (untracked ones do not count) and `main` is an ancestor of `origin/main`. It never merges, rebases or
  resets. The supervisor asks for it only on the first start after her request, never on the owner's starts, a crash's
  or a later rung. The outcome goes into the restart record's own `checkout` field ({state, detail}), never the fallback
  notes, so a checkout left as it was does not mark the restart `fell_back`; `restarts.py` words it in one line for her
  (`CHECKOUT_WORDS`). A failed fetch is one of those lines and the start goes on with what is on disk. Cost: one line in
  `restart_from_program` for a day after such a restart; no tool. The resident launcher (the supervisor) takes the change
  at the owner's next full start; the preparation process takes its part at once.
- **Found on the way:** the packer shipped only the worker's top-level modules and `resources/`, so the installed
  package had no `sandbox_site/`: a live Host's confined Pythons ran without the sitecustomize above (its temporary
  folder fix reached only a checkout's own runs and core candidates). `pack_plugins.py` ships `sandbox_site/` now,
  listed in `runtime-manifest.json` (`test_runtime_manifest.py`); it reaches the live Host at its next start.
- Her own push scripts, which read the credential and put it in the push URL, are left as they are; her skill says they
  are no longer needed.

Cost: no new tool and no per-turn line; `sandbox_run`'s description is unchanged (it already said git uses the Host
user's logins).
