# M6k — retained native events from paused experiments

`capture_paused_native.py` copied nine native session JSONL files after matching
the previously persisted database, evidence root, exact session ID and isolated
DSH home. The header ID and two identical source reads were checked; all nine
files parsed completely. The probe exited 0 and made no model call or database
mutation. Configuration files, bearer-token endpoints and unrelated sessions
were excluded.

`paused-native-capture-55ab36ed16ef` records eight completed native summaries in
the paused L09 sample: three character and five executor. Its executor session
ends at step/start and its task remained RUNNING. The earlier Mongo projection
contained only three summaries because the executor operation had not returned.
The raw events establish that the summaries occurred; they do not establish a
finished task, correct final answer or completed L09 matrix.

The generic Git whitespace check flagged the intentionally preserved CRLF audit
bytes, exiting 2. Its output is retained in `git-whitespace-observation-a63ae11dff`.
The scoped source check with `core.whitespace=cr-at-eol` exited 0. No source or
evidence was normalized to suppress the diagnostic.

Formal F01/F02 continue separately. All paused attempts retain their original
status; the new native snapshots supplement their evidence without resuming them.
