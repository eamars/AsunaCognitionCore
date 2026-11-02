# ADR-115: Only secrets are hidden

Status: **Decided** 2026-11-02 by the owner (option B, below); built by the lead (Claude Code, big sis) the same day.

## 1. The ask

The owner, 2026-11-02, after his GitHub name reached the action brain as 「[凭据已隐藏]」: "I'd like B. I'm working on
relaxing the over built security measure and I'd like to take the risk." In scope: what the credential scrub hides.
Out of scope: the private-word list, the root table (ADR-098), the error-text redaction in `config.py`.

## 2. What happened

The vault's scrub (`credentials.scrub`, built 2026-10-07 in `2b6f6908`) replaced every stored value of 4 characters or
more, not only secrets. Her record `oldhome-ssh` keeps the SSH login in `OLDSH_USER`, and that login is the owner's
GitHub name, so the name was hidden wherever it appeared: in two of her tasks on 2026-11-02 at 00:16 and 00:27 NZDT
it stood as `https://github.com/[凭据已隐藏]/…` and in a commit author line, and the action brain had to guess it. To cope, Xiaoman put the name on her private-word list (entry line 92), which in turn fails
`tests/test_personal_words.py` on the committed files that name the public fork (14 hits, all that entry).

The broken invariant: the ask (2026-10-07) was that no model holds a secret; the build hid every value.

## 3. The decision

A value is hidden when its variable's name says it is secret: it contains `pass`, `token`, `secret` or `key`
(`credentials.SECRET_WORDS`). Every other value (a user name, an email, a host) stays readable. Option A, the reverse
default (hide all but named identifiers), was offered; the owner chose B and takes its risk: a secret filed under a
name without those words is not hidden.

On her vault: `ENLIGHTEN_PASSWORD` and `OLDSH_PASS` hidden; `ENLIGHTEN_EMAIL`, `OLDSH_HOST` and `OLDSH_USER` readable.

## 4. Built

- `src/asuna/credentials.py`: `_refresh` collects only the values of secret-named variables; the docstring says so.
- `tests/test_credentials.py`: the existing test also asserts that a login email survives the scrub, in a URL; red
  without the rule.
- `RUNTIME_API.md` (Credentials) and the core skill `asuna-credentials` say what is hidden.
- Checked before the install on the real vault through the branch code: the fork URL and the name come through; both
  passwords are hidden.

## 5. Landing and what is left

One planned restart (worker code), in a slot she gives. After it: the same check through the installed code. Then she
removes entry 92 from her list herself (the list is hers), and `tests/test_personal_words.py` runs on main.
