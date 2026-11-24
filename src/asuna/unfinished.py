"""What a restart leaves unfinished (ADR-134): every input that ends ends its turn, and a cut turn is resumed or ended.

A restart resumes her turns through their inputs (chat.recover_inputs puts each unfinished input back in the queue).
Two rules keep that promise:

- `without_turn`: an input that ends without a turn (the line was seen in another turn, the errand was cut, the
  proactive gate closed) ends the turn it already has, if any, so no turn is left resumable with nothing to resume it.
- `cut`: a turn the Host's stop cut keeps its input for the resume; cut a second time, it ends and is told.

A turn about a task (its consult and time-up turns) has no input of its own: `task_cancelled` ends the ones still open
when the task is cancelled, whoever cancels it (D5).
"""
from __future__ import annotations

from .ingress import input_state
from .records import episodes as episode_records

ENDED = 'SUPPRESSED'                      # the program decided this turn does not run (as for a stale task result)
CUT_TWICE = 'TURN_CUT_TWICE'              # its readable word is hers (faults.CAUSES)
CUTS_TO_END = 2
TASK_CANCELLED = 'TASK_CANCELLED'         # ended_by: TASK_CANCELLED:<the task's cancel_reason>
TASK_TURNS = ('consult', 'task_time')     # her turns about a running task, opened by it (coordinator._task_turn)


def _scope(ep):
    return ep.get('scope_key') or 'scene:' + str(ep.get('scene_id'))


def without_turn(store, episode, result_state):
    """The input `episode` ends without a turn, as `result_state` says. Its turn, if one was already made (a restart
    came after it was written), ends with it: `SUPPRESSED`, `ended_by` the result state, one audit row. Returns the
    ended turn, or None when there was none to end."""
    from .coordinator import RESUMABLE
    ep = episode_records.get(store, episode)
    ended = None
    if ep and ep.get('state') in RESUMABLE:
        ended = episode_records.save(store, {**ep, 'state': ENDED, 'ended_by': result_state},
                                     expected=ep['revision'], stream=episode)
        store.audit(episode, 'episode.ended_without_turn', {'ended_by': result_state, 'was': ep['state']}, _scope(ep))
    input_state(store, episode, 'COMPLETE', result_state=result_state)
    return ended



def task_cancelled(store, task, reason, besides=None):
    """D5: a cancelled task ends the turns it opened that are still open (its consult and time-up turns), each as
    `without_turn` ends one, `ended_by` naming the cancel; never `besides`, the turn that cancelled it. Returns the
    ended turns' ids."""
    from .coordinator import RESUMABLE
    ended = []
    for kind in TASK_TURNS:
        for ep in episode_records.open(store, RESUMABLE, kind=kind).rows(fields=['_id', 'task_id']):
            if ep.get('task_id') == task['_id'] and ep['_id'] != besides \
                    and without_turn(store, ep['_id'], '%s:%s' % (TASK_CANCELLED, reason)):
                ended.append(ep['_id'])
    return ended

def cut(store, ep, error):
    """The Host's stop cut the turn `ep` (not finished). The first cut keeps its input `PROCESSING` for the resume at the
    start and writes the turn `INTERRUPTED`. The second ends it: `FAILED_RUNTIME` with CUT_TWICE as the failure's last
    line (faults.cause reads it there), its input `FAILED`. Returns (episode, ended)."""
    cuts = int(ep.get('cuts') or 0) + 1
    if cuts < CUTS_TO_END:
        input_state(store, ep['_id'], 'PROCESSING')
        return episode_records.save(store, {**ep, 'state': 'INTERRUPTED', 'cuts': cuts, 'failure': error},
                                    expected=ep['revision'], stream=ep['_id']), False
    failure = '%s\n%s: the Host stopped during this turn %d times' % (error.rstrip(), CUT_TWICE, cuts)
    input_state(store, ep['_id'], 'FAILED', failure=failure)
    return episode_records.save(store, {**ep, 'state': 'FAILED_RUNTIME', 'cuts': cuts, 'failure': failure},
                                expected=ep['revision'], stream=ep['_id']), True
