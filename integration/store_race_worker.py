"""One process of a race of the store's contract (test_store_contract.py, class R): it opens the MongoDB adapter on the
throwaway database it is given, waits for the common start, does its part and prints what it got as JSON.

  python store_race_worker.py <race> <database> <start epoch seconds> <worker number>

The settings come from the environment (ASUNA_RACE_SETTINGS, JSON); no address is printed.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from asuna.store import Checked, mongodb  # noqa: E402
from asuna.store.errors import DuplicateKey  # noqa: E402
from asuna.store.words import And, Increase, Now, Or, Range, Set, Unset  # noqa: E402
from store_contract import CATALOG  # noqa: E402


def main(race, database, start, number):
    store = Checked(mongodb.open(json.loads(os.environ['ASUNA_RACE_SETTINGS']), database), CATALOG)
    try:
        time.sleep(max(0.0, start - time.time()))
        got = []
        if race == 'counter':
            for _ in range(50):
                got.append(store.collection('things').claim({'_id': 'counter'}, Increase('rank'))['rank'])
        elif race == 'claim':
            keyed = store.collection('keyed')
            while True:
                taken = keyed.claim({'state': 'queued'}, Set({'state': 'taken:%d' % number}), sort=[('order', 1)])
                if taken is None:
                    break
                got.append(taken['_id'])
        elif race == 'lease':
            leases, me = store.collection('leases'), 'holder-%d' % number
            take = [Set({'instance': me, 'since': Now(), 'expires_at': Now(30)}), Unset('planned_stop')]
            free_or_mine = And({'_id': 'host'}, Or({'expires_at': Range(lt=Now())}, {'instance': me}))
            if leases.update(free_or_mine, take).matched:
                got.append('taken')
            else:
                try:
                    leases.insert({'_id': 'host', 'instance': me, 'since': Now(), 'expires_at': Now(30)})
                    got.append('inserted')
                except DuplicateKey:
                    got.append('refused')
        elif race == 'revision':
            keyed = store.collection('keyed')
            record = {'_id': 'k', 'platform': 'p', 'account': '1', 'revision': 2, 'state': 'writer-%d' % number}
            got.append(keyed.replace(record, expected=1))
        else:
            raise SystemExit('unknown race ' + race)
        print(json.dumps(got))
    finally:
        store.close()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]))
