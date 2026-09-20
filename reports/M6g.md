# M6g — reviewed engineering clauses and preserved observer evidence

The frozen full integration check `check-20260920T002111Z-14dfb6` passed 58 tests
(exit 0). Test teardown now copies temporary loopback requests, independent
observer counts and negative controls into immutable evidence directories.
JUnit properties link each test to its actual Mongo snapshots or auxiliary
evidence. E22 includes the deliberately omitted auxiliary call and terminal
transport timeout, not just the normal-path count.

`engineering-assessment-6683d264640f` maps every E01–E24 contract clause to that
check and the named real companion probes. It verifies the fixed fixture hash,
archived source hashes, command output hashes, selected JUnit outcomes and
evidence files. This is a post-run engineering coverage review, not a new test
harness or a model score. It records 23 PASS and E01 INCONCLUSIVE. E01 lacks a
pre-implementation snapshot of default-profile and old-database metadata; later
isolation probes cannot establish that historical fact. The engineering gate
therefore remains INCONCLUSIVE.

Fresh separately frozen probes verify actual scoped vector/cache invalidation
(`cache-probe-0d1ca97fc100`) and installed native DSH tool-pair/summary-failure
atomicity (`native-atomicity-d035ee56f933`). The latter injects a failing summary
provider and tests actual native session replay; it is not a live cognition test.
Both exited 0. All earlier failures, pause records and UI corrections remain.

A01, A02 and the L02/L03/L12 sequence remain in progress. No human cognition
ratings are available. Current results do not establish absence of character
dilution. Model services and original instances were not changed by this stage.
