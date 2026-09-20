# M6j — exact capacity-marker verification and failure display

The capacity checker now requires each START/MIDDLE/END code and value to match
its own expected record. A synthetic swapped-association counterexample contains
all six expected literals but is rejected. Duplicate JSON keys are also rejected;
unsupported answer formatting is explicitly unverified, not assumed correct.

The frozen offline reassessment `capacity-association-audit-838dddedc144` passed:
all 23 previously passing actual replies in the old 24-sample F01 matrix have
correct associations. The timeout sample remains a failed live attempt. This
reassessment made no model call and does not replace the source experiment. The
ongoing F01 matrix started under M6i and will receive its own appended association
audit after completion; no in-flight sample or original score is rewritten.

In-app Browser displayed the preserved failed L11 execution and UNKNOWN task
state. DOM and two visually reviewed screenshots are in ui-qa-20260920-06's
evidence manifest. The page demonstrates the recorded failure and final task
state; the exact raw native cause remains in the original lane receipt. No new
download success or human cognition score is claimed.

The latest regression `check-20260920T014425Z-afabff` passed 58 tests, exit 0.
The exact marker audit also exited 0. A source-specific failure analysis separates
invalid protocol, output budget, route behavior, transport and missing evidence
from unreviewed natural-language quality. Fixed fixture and model hashes are
unchanged. Formal F01/F02 and other complete matrices remain in progress.
