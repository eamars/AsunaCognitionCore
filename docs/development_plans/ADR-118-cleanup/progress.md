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

## L2, 2026-11-09: the digest cases on a real Store, gates that do not pass on nothing (`436f25fc`)

- Landed `436f25fc6abf` with `land.py`, no restart. Suite: 962 passed, 13 skipped; node 307 passed, 0 failed;
  prepared start 153 modules, 0 problems; `docs/map` current; pushed.
- `pytest integration`: 133 passed. Adapter `--selftest --offline`: pass 423, fail 0, skip 5. Her 14 `check_skill.py`:
  rc 0. `tools/p1c_offline_check.py` on main: 20/20; a direct run of `tests/discussion_digest_cases.py`: 20/20; with
  `asuna.people` blocked it fails at import (ImportError), not green.
- Removed: `sys.modules["asuna.people"] = None` is gone from the tree, except the line in her own
  `asuna-offline-selfchecks/SKILL.md:42`, which she changes herself (told on her line at the landing).
  `_lookup`/`_match`/`_project`/`FakeCollection` are gone from `tests/discussion_digest_cases.py`; the copies in
  `outbound_image_cases.py` and `p2_summary_loop_cases.py` are their own fakes (§6, one fake for the offline checks).

## L3 to L5, 2026-11-09 18:23 to 18:48: three restarts one after another, in the window she gave

She gave the window on her line (18:22 to 19:30) and asked for one line per landing with its commit and the
launcher's `loaded.commit` and `loaded.packages`; she checked each on her side. Each landed with
`land.py --restart`: the suite, `pytest integration` and a prepared start first, then the restart and the check of
every installed `src/asuna` file; then the byte check of §5 (the installed plugin's `src/*.js` and the running
adapter snapshot against the commit's blobs). The QQ lane needed no start (her call each time).

| Landing | Commit | Suite | Node | Integration | Restart | `loaded.commit` | cognition-core | Python files | JS / adapter |
|---|---|---|---|---|---|---|---|---|---|
| L3 | `1bb712469c69` | 962 passed | 307 / 0 | 133 passed | 18:29:17, back 18:30:02 | `1bb71246` | `fe40d0625b33` | 169, 0 differing | 47 / 26, 0 differing |
| L4 | `6476cf543fd3` | 962 passed | 307 / 0 | 133 passed | 18:37:01, back 18:37:54 | `6476cf54` | `3e633ffb28ce` | 169, 0 differing | 47 / 26, 0 differing |
| L5 | `a092ca73d9c8` | 962 passed | 308 / 0 | 133 passed | 18:47:33, back 18:48:19 | `a092ca73` | `0fcb21faa416` | 169, 0 differing | 47 / 26, 0 differing |

Before them, at `3b694041`, the byte check gave 47 / 26 files, 0 differing. Every landing: adapter
`--selftest --offline` pass 423, fail 0, skip 5; her 14 `check_skill.py` rc 0 (her own run after L3: 57/57 and 50/50,
her 31 code anchors all resolve).

Removed names, `git grep` outside `docs/development_plans`, 0 each:
- L3 (`1bb71246`): `"affect.import"`, `reconcile_calls`, `document_title`, `scene_id_filter`, `readable_scope`
  (word match; the substring hits are `heads.py`'s own `readable_scopes`), `DirectLauncher`, `StaleRevision`,
  `over_budget_words`, `NOTES_DOC`, `FORWARD_TEXT_FIELD`, `memory_tiers.MEMORIES`, `FACT_AUTHORS`, `PLACE_WORDS`,
  `DEVELOPMENT_GRANT`, `understanding.LAYERS`, `SHADOW_PILOT`, `RECORD_ABOVE`, `memory_pilot_report`, `VARIANT_OF`,
  `STICKER_SEGMENTS`, `_summarise`, `read_health`, `members_of`, `LOOSE_GROUP`, `MAX_CARD_HISTORY`,
  `MAX_NICKNAME_HISTORY`.
- L4 (`6476cf54`): `平铺加载` in `src`: 0; `summary_scene=`: 0; one `except ImportError` is left in `src/asuna`
  (`animated.py:197`, an optional library, not a flat load).
- L5 (`a092ca73`): `provider_idle_timeout_seconds`, `transport_read_timeout_seconds`, `publish_adapter`,
  `prompts_dir`, `__import__('time')`. `legacy_database` stays where it guards something (the test-database cleanup
  protects a configured legacy database); only its card label went.
  The live deployment's `config/local.json` still holds `provider_idle_timeout_seconds`, and she started on L5
  (18:48, result running): a saved deployment that keeps the key loads, as B8 says.

K1, checked by her on the installed tree and by the lead from the code: `identity_status()` is always complete, the
two "身份解析没接上" texts have no live path, and a real identity failure still reads as the row's
"身份块没通过校验：<reason>" or a tool failure, never an empty result (§6 names what she keeps).

Closed 2026-11-09: index row Built.
