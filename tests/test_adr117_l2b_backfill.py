"""ADR-117 L2b's one-off backfill (tools/adr117_l2b_backfill.py; deleted with it): on rows written before the landing it
fills each field as the new writes make it, its dry run and its limit write nothing past what they say, and a second
run changes nothing. On the unit run's store holding the fixture world (conftest.py)."""
import copy
import sys

from asuna.config import ROOT
from asuna.documents import DocumentStore
from asuna.ingress import persist_input
from asuna.records import scenes as scene_records
from asuna.records import tasks as task_records
from asuna.store.words import Set, Unset
from asuna.tasks import TaskService

sys.path.insert(0, str(ROOT / 'tools'))
import adr117_l2b_backfill  # noqa: E402

COLLECTIONS = ('state_heads', 'tasks', 'scenes')


def stored(world):
    return {name: {row['_id']: copy.deepcopy(row) for row in world.collection(name).find({})} for name in COLLECTIONS}


def test_the_backfill_fills_each_field_once(world):
    docs = DocumentStore(world, 'P1')
    docs.apply('ledger-a', {'op': 'append_section', 'kind': 'ledger', 'heading': '账', 'reason': 'r'}, '一笔',
               base_revision_id=None, author='character', mutation_id='m-ledger')
    scene = scene_records.get(world, 'dm-a')
    service = TaskService(world)
    for task_id in ('t-1', 't-2'):
        task_records.save(world, {'_id': task_id, 'request_key': task_id, 'state': 'READY', 'scene_id': 'dm-a',
                                  'scope_key': scene['scope_key'], 'policy_epoch': 1, 'requester_id': 'A',
                                  'intent_revision': 1, 'fencing_token': 0, 'goal': 'g'}, stream=task_id)
        service.claim(task_id)
        service.interrupted_by_restart(task_id)
    for scene_id, name in (('g1', 'One'), ('g2', 'Two')):
        persist_input(world, {'event_id': 'e-' + scene_id, 'scene_id': scene_id, 'person_id': 'A', 'text': 'hi',
                              'raw': {'group_name': name}})
    written = stored(world)
    # As the rows stood before the landing: no head kind, no stored size, no name; and a name gone stale.
    heads = world.collection('state_heads')
    for row in heads.find({}):
        heads.update({'_id': row['_id']}, Unset('kind'))
    for task_id in ('t-1', 't-2'):
        world.collection('tasks').update({'_id': task_id}, Unset('result.chars', 'result.pages'))
    world.collection('scenes').update({'_id': 'g1'}, Unset('name'))
    world.collection('scenes').update({'_id': 'g2'}, Set({'name': 'Two before'}))
    before = stored(world)

    counted = adr117_l2b_backfill.run(world, dry_run=True)
    assert stored(world) == before, 'a dry run writes nothing'
    assert (counted['heads']['missing_kind'], counted['tasks']['missing_pages'], counted['scenes']['missing_name'],
            counted['scenes']['differs']) == (len([key for key in written['state_heads'] if key.startswith('doc:')]),
                                              2, 1, 1)
    assert adr117_l2b_backfill.run(world, limit=1)['tasks']['left'] == 1, 'a limit fills that many tasks'

    adr117_l2b_backfill.run(world)
    filled = stored(world)
    assert filled == written, 'each field as the new writes make it'
    again = adr117_l2b_backfill.run(world)
    assert stored(world) == filled, 'a second run changes nothing'
    assert (again['heads']['filled'], again['tasks']['filled'], again['scenes']['filled']) == (0, 0, 0)
