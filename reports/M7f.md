# M7f — Per-case requirements in the report

Every started acceptance row now includes its original required actions, outcome and evidence, linked to the exact result. Listing a requirement does not establish that it passed. Completed protocol samples remain distinct from missing natural-language ratings.

The original package report validator and seven focused report checks pass. The full existing regression suite passes again after the reporting change: 58 tests in 65.18 seconds. Current engineering clause review remains 23 PASS / E01 INCONCLUSIVE.

The bounded dispatcher in `continuation-queue-20260920-01/run.py` only invokes existing dedicated drivers. It waits for the already-running L02/A01 results, then runs L03 → L12 → L11 → L09 in the task lane and A02 after A01 in the cognition lane. Each invocation is recorded separately, creates a fresh experiment directory and freezes its real inputs. No automatic sample retry or scoring is implemented by the dispatcher. There are at most two own model workflows; a driver exit without a final result stops its queue. Dispatcher PASS, when it exists, means only dispatch completion.

This is still a checkpoint: ongoing matrices, final human review pack, final report and final evidence export remain pending.
