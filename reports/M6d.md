# M6d — durable compaction, task revision and retained failures

This is an intermediate implementation milestone. Formal matrices remain active;
no stage probe is a substitute for all 41 acceptance cases or independent ratings.

- Deferred compaction probe `deferred-compaction-8da71ec9d5` failed because the
  post-summary Gemma SPEAK exhausted 4096 tokens. Its partial episode resumed,
  and exactly one real summary ran at the next complete boundary. The new narrow
  plan in `deferred-compaction-ecd35834ff` separates mechanical assertions from
  role quality; it passed and the subsequent real episode also COMMITTED.
- `runtime-v2.ts` validates committed silent DECIDE boundaries. The original
  bridge remains unchanged for previously frozen active experiments. Pending
  compaction survives restart and is not consumed in the middle of an episode.
- Actual query cache `cache-probe-2c474a7b8304` passed: IDs/scores only, separate
  scope/epoch/revision keys, authority recheck after deletion.
- `revision-probe-614d286cdb` passed with real Mongo and sandbox: B cannot revise
  A's task, revision 2 retains task identity, old tools/results/evidence are denied,
  two concurrent workers cannot revive revision 1, and existing effects remain.
- `effect-fence-probe-8145bf2a25` passed with separate Windows processes: a cancel
  acknowledgement waits for a currently committed effect, then denies old-worker
  effects. This is a single-controller-host lock, not multi-host HA.
- Old-worker exception handling cannot mark a new worker's revised task UNKNOWN.
  `check-20260919T105249Z-67f033` passed both new targeted regression tests.
- `check-20260919T104913Z-1d2774`: 52 existing tests passed, including real Mongo,
  five process crash points, WSL isolation and state-only replay.
- Actual L12 probe `formal-L12-20260919T101321Z-27055a` passed its file oracle with
  one injected read error and one native executor summary. Full L03/L12 runs started
  separately, with matched Qwen-only controls.
- Noise attempt `noise-load-probe-c522950888` read the complete 73KB log but failed
  strict result parsing twice due to Markdown fences. The repair instruction now
  explicitly repeats the raw-JSON constraint; no response text is rewritten or
  accepted by stripping fences. New attempts measure tool load even on failure.
- First full F01 was 23/24, including genuine 196k requests on both models. A
  Qwen 234k request exceeded the old client 300s deadline. Supported provider
  HTTP/idle deadlines and a transport-only SSE comment address this; the separate
  `capacity-stream-reprobe-4db631d2b7` passed at 233984 input tokens. Full repeat
  remains required. No server launch parameters or model weights were changed.
- Retrospective audit `finish-reason-audit-4d4fa958d7` found zero native-completed
  versus provider-finish mismatches in 632 turns. Additional provider finish checks
  are defense in depth, not evidence of an observed historical truncation bug.
- Offline review import validation passes; browser rendering is BLOCKED because
  the configured browser runtime lists zero available browsers. See
  `review-ui-check-20260919.json`. No human scores have been invented.

Commands, raw returns, actual process exit codes and SHA references are preserved
in each attempt. Environment aggregate v3 retains its predecessor and fingerprints
the new bridge/transport defaults. Root `report.json`, final complete matrices and
the sanitized full evidence archive are still pending at this milestone.
