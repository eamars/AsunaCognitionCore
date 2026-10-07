# Tools

Scripts run from the repository root. Python scripts use the checkout's environment (`.venv\Scripts\python.exe` on
Windows, `.venv/bin/python` elsewhere).

## Install and run

| Script | Does |
|---|---|
| `asuna-launch.mjs` | The entry behind `start-asuna.cmd` / `start-asuna.sh`: installs the checkout when it changed, then starts the DSH Web profile. Options `--profile`, `--config`, `--port` (else the profile's recorded port, else 8780), `--no-sync`, `--dry-run`; `--list` prints the installed profiles. |
| `pack_plugins.py` | Packs the core and the `--persona` / `--channel` packages into content-addressed `.tgz` files under `.runtime/adr008/packages/`. |
| `setup_native_profile.py` | Installs the packed core, `--persona-package` and `--channel-package` packages into a profile, migrates the config into its settings and records the package list (and `--port`) in `launch.json`. |
| `import_native_credentials.mjs` | Writes secrets into DSH's credential store; called by the installer. |
| `build_dsh_inline.mjs` | Builds the optional inline rendering extension ([dsh-inline/README.md](dsh-inline/README.md)). |
| `make_demo_config.py` | Writes the ignored `config/demo.local.json` for the demo profile. |
| `release.py` | Builds and checks the GitHub Release assets (core and channel packages, never a persona). |

## Repository checks

| Script | Does |
|---|---|
| `check_staged_secrets.py` | Scans staged files (or `--all`) for secrets, and with `--personal` for personal data from `config/personal-denylist.local.txt`. Prints only `file:line:category`. Allowed literals: `personal_scan_allow.txt`. |
| `cleanup_test_databases.py` | `--inventory <file>` lists leftover `asuna_v2_test_*` databases into a file; with `--apply`, drops exactly the inventoried ones. |
| `check_dsh_release.py` | Compares the installed DSH version with the public registry's tags. |

## Offline self-checks

`p1c_offline_check.py`, `p2_offline_check.py`, `p3_offline_check.py`, `p5_offline_check.py`,
`integration_import_offline_check.py` and `outbound_image_offline_check.py` run the `tests/*_cases.py` modules
without Mongo or pytest. The character runs them inside her sandbox before publishing a change (her skills name
which one fits).

## Probes

Each probe exercises the real installed DSH or a real MongoDB without calling a model, and prints a JSON verdict.
A probe that creates a test database drops it when it ends.

| Script | Exercises |
|---|---|
| `probe_plugin_install.mjs` | Installs the packed tarballs outside this checkout and imports every Host export through DSH's resolver. |
| `probe_fresh_profile.mjs` | A brand-new DSH home installing the released tarballs with `dsh plugin add` only. |
| `probe_native_schedule.mjs` | DSH's scheduler, loop and durable schedule inbox. |
| `probe_native_image.mjs` | The action scope, tool loop, attachment storage and cold session replay of images. |
| `probe_native_atomicity.mjs <out dir>` | DSH compaction with a failing summarizer: source history is kept. |
| `probe_qq_admission.py <napcat-qq package>` | Adapter → Core → durable-state admission, offline. |
| `probe_host_seam.py` | `--debug` host replay with fake cognition, real Mongo and loopback HTTP. |
| `probe_blob.py` | GridFS blob storage in a throwaway test database. |

`fixtures/inline_brains.mjs` is the synthetic inference used to review the inline extension.
