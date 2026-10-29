# Tools

Scripts run from the repository root. Python scripts use the checkout's environment (`.venv\Scripts\python.exe` on
Windows, `.venv/bin/python` elsewhere).

## Install and run

| Script | Does |
|---|---|
| `asuna-launch.mjs` | The entry behind `start-asuna.cmd` / `start-asuna.sh`: installs the checkout when it changed, then starts the DSH Web profile. Options `--profile`, `--config`, `--port` (else the profile's recorded port, else 8780), `--no-sync`, `--dry-run`; `--list` prints the installed profiles. |
| `pack_plugins.py` | Packs the core and the `--persona` / `--channel` packages into content-addressed `.tgz` files under `.runtime/adr008/packages/`, and removes earlier ones that no installed profile or `activation.json` names. The core carries every tracked file of `src/asuna` except `cli.py` and `native_ui.py`; packing fails, with the import error, when that copy does not import from itself. |
| `setup_native_profile.py` | Installs the packed core, `--persona-package` and `--channel-package` packages into a profile, migrates the config into its settings and records the package list (and `--port`) and the checkout's commit in `launch.json`. |
| `check_prepared_start.py` | Runs a start's preparation (rung 0) for `--commit` in a scratch worktree with a synthetic profile and config (the worktree borrows `.venv` and `node_modules` from this checkout, else from the main checkout, and the script runs with that `.venv`), then checks the install: every file the core ships from `src/asuna` byte-identical to the commit, the packed core identical to the installed one, and every worker package and module importing from the installed copy with the `requirements.lock` environment and with the profile's worker interpreter. Exit 0 only when all of it holds; the scratch folder is removed (`--keep` leaves it). |
| `import_native_credentials.mjs` | Writes secrets into DSH's credential store; called by the installer. |
| `build_dsh_inline.mjs` | Builds the optional patched DSH packages: the inline rendering extension and the compaction engine ([dsh-inline/README.md](dsh-inline/README.md)). |
| `make_demo_config.py` | Writes the ignored `config/demo.local.json` for the demo profile. |
| `release.py` | Builds and checks the GitHub Release assets (core and channel packages, never a persona). |

## Repository checks

| Script | Does |
|---|---|
| `check_staged_secrets.py` | Scans staged files (or `--all`) for secrets, and with `--personal` for personal data from `<data>/private/personal-denylist.txt`. Prints only `file:line:category`. Allowed literals: `personal_scan_allow.txt`. |
| `publication_scan.py` | The checks that guard main (the private list and private addresses everywhere; in what the release ships, `check_staged_secrets.py --personal` and the persona names), on a candidate's changed files; her publication runs it before anything is published. Prints only path, line and category. |
| `cleanup_test_databases.py` | `--inventory <file>` lists leftover `asuna_v2_test_*` databases into a file; with `--apply`, drops exactly the inventoried ones. |
| `adr104_equivalence.py` | `b1b`, `b2`, `b3`, `b4`, `b5`, `b6`, `b7`, `b8`: read only, numbers only, on the configured database (`--config`): what the store's `ensure` would create, make, drop or refuse there, whether each validator is the one it creates, the stored records by BSON type of every field the batch declares (and of a list's elements), (`b4` to `b8`) the records whose BSON and JSON sizes fall on different sides of 1 MiB, and (`b3` to `b8`) each moved read (`b6`: the context's task aggregate against its reads on 20 conversations too; `b7`: the Web memory page's aggregate against its reads, and retrieval's whole search on 40 queries, the same final six and 24 vector candidates) old against new (ids in order, records, rows each side answered, plan stages, times), and per declared field the records its declaration refuses (counted in reads of at most 20,000 records and 10 fields, each bounded by `--max-ms`; one over its limit leaves its fields unchecked and named); to `<data>/private/adr104-evidence/<batch>/`. `b8` also writes and reads a synthetic blob through the blob interface on a throwaway database of the same server (its only writes, dropped after) and opens up to 20 of her stored files, their size and sha256 against their rows. Collections to create, indexes to make and validators count for the batch's own collections; a plan difference the lead accepted is reported with its reason, not failed; a read whose new p50 is more than twice the old and more than 5 ms above it, still so when timed again, fails the run unless the lead accepted it (reported with its times, reason and recheck). The report holds the `--max-ms` used; a query stopped by that limit is `TIMED OUT`, named with where it was and the limit (a read case so marked, the others go on); `UNREACHABLE` is only a server that cannot be reached. Exit 0 clean, 1 something differs, 2 not checked. |
| `check_dsh_release.py` | Compares the installed DSH version with the public registry's tags. |
| `memory_fires_report.py` | What came back, from the count rows (`crossing.report`), in counts only: per place (numbered, with its kind) and in all, turns, cues and cues a turn, her recalls in a cue's turn or the next, notes back by word and by meaning, recall's lines from elsewhere and past versions, W6, and the minutes from each cue's and note's last compaction in its DSH session (read from the profile's session logs; `--no-sessions` leaves it out). `--days` sets the window (14). |
| `memory_pilot_report.py` | The shadow pilot's reading in counts (`memory_pilot.py`): would-be surfacings of her own items per day by turn kind, the floor that keeps them at or under one a turn and none in heartbeats, near-duplicate pairs, recall hits, the cost. `--since` limits it; `--drop` removes the pilot's collection, which is also tiered memory's item index (her items stop coming up until it is rebuilt). |
| `carried_check.py` | Her install checks, read only (`carried.install_checks`): the latest turn's `system_ref` sections are what `carried()` gives, each place's refusal says `carried()`'s number, a write gets its room line, every tier/`inject` difference is said. One PASS or FAIL line per check, numbers only. `--model` names the persona package's `persona-model.json`. |

## Offline self-checks

`p1c_offline_check.py`, `p2_offline_check.py`, `p5_offline_check.py`,
`integration_import_offline_check.py` and `outbound_image_offline_check.py` run the `tests/*_cases.py` modules
without Mongo or pytest; `tests/test_schedule_rules.py` runs the same way on its own (`PYTHONPATH=src`). `tests/test_offline_checks.py` runs each of them under pytest as well. The character runs them inside her sandbox before publishing a change (her skills name
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

## Refusal probe

`refusal_probe.py` answers one question for one model: can it do what the character brain needs, with the design at
this commit, without being refused? It prints **PASS**, **FAIL** with the reasons, or **NO RESULT**. Its exit status
is 0, 1 or 2.

- **What runs:** synthetic, safe-for-work conversations (`fixtures/refusal_probe/sequences/*.json`: groups, and one
  at home in her local chat, kind `home`) and a made-up persona (`fixtures/refusal_probe/persona.md`). They go through
  the real Coordinator, context, system prompt, tool list and tool handlers in a throwaway test database; each
  conversation is offered its own tool specs, as a live turn there is (`role_tools.session_specs`). Only the model call
  goes to the provider.
- **Nothing leaves the probe:** `speak` queues where no adapter claims it, and `delegate` makes a task that no worker
  runs. The database is dropped at the end.
- **FAIL** means at least one turn was:
  - stopped by the provider (`stop_reason: "refusal"`, or `content_filter`);
  - declined in the model's own words, caught by a fixed phrase list;
  - or missing the tool its step `needs`.
- **NO RESULT** is a dry run, or a fault of the probe itself.
- **The report** (`reports/refusal-probe-<time>.json`) holds counts, stop reasons, tool names and the steps that
  missed, never the model's words. `--keep-text <folder>` keeps the words.

```
python tools/refusal_probe.py --dry-run
python tools/refusal_probe.py --provider anthropic --model <model id>            # key in ANTHROPIC_API_KEY
python tools/refusal_probe.py --provider openai-compatible --base-url <url>/v1 --model <model id> --key-env <VAR>
```

- `--repeat N` runs every conversation N times (default 3).
- `--sequences` takes other files or folders.
- `--effort <level>` (anthropic) sends a request shaped as the character route sends it to a model whose effort is
  set per turn: adaptive thinking and an effort marker on each turn. The thinking is passed back; with
  `--thoughts tool` it is never read.
- `--thoughts tool|thinking` (default `tool`) runs the turns with that deployment setting. With `thinking` the
  model is offered no `think`, her thought is recorded from the summary of its first thinking in each turn, and the
  report counts the turns that recorded one and those that did not, by why; with `--keep-text` the recorded
  summaries go to `refusal-probe-<run>-thoughts.jsonl` beside the words.

A sequence file looks like this:

```json
{"id": "research-1", "kind": "research", "people": ["阿杰", "小雨"],
 "memories": ["optional: a memory she holds in this group"],
 "filler": 0,
 "history": [{"who": "小雨", "text": "周末想去爬山"}, {"who": "你", "text": "a line she said before"}],
 "steps": [{"who": "阿杰", "text": "帮我查查周六会不会下雨", "mention": true, "needs": "delegate"},
           {"who": "小雨", "text": "a line that does not call her", "mention": false}]}
```

- `history` is in place before the first step. A `你` line is one she said, and `filler` repeats the history up to
  that many lines.
- Each step that calls her (`mention: true`) is one turn and names the tool it `needs`, or a list of acceptable tools.
