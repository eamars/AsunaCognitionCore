"""Parts of a turn in the fixture world that several integration tests share: a line from someone, the owner's local
scene, an ordinary or delegating turn, a chat over a lane, a task set up to run and one returned, records written
through the driver, the schedule service, and a memory route and retrieval that give fixed vectors."""
import threading
import types
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from asuna.chat import Chat, SceneQueue
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, FakeTurn
from asuna.records import tasks as task_records
from asuna.router import Router
from asuna.schedule import ScheduleService
from asuna.state import now
from asuna.tasks import TaskService, ToolBroker


def event(key='e', scene='dm-a', person='A', text='我回来了。', **extra):
    return {'event_id': key, 'scene_id': scene, 'person_id': person, 'text': text, **extra}


def run(store, *turns):
    lane = FakeLane(store, list(turns))
    return Coordinator(store, lane), lane


def owner(store, scene='dm-a', person='A'):
    """Make (scene, person) the owner's local scene: its turns are owner_private."""
    store.config['chat'] = {**store.config.get('chat', {}), 'scene_id': scene, 'person_id': person,
                            'persona': 'P1', 'display_name': '示例角色'}
    return store


def turn(thought, speech):
    """One ordinary character turn: her private thought, then what she says."""
    return FakeTurn([('think', {'thought': thought})], speech)


def delegating(thought, title):
    """A turn that hands work to the action brain and says nothing yet."""
    return FakeTurn([('think', {'thought': thought}), ('delegate', {'title': title, 'brief': title + '：照原话去做。'}),
                     ('stay_silent', {'why': '等结果回来再说'})])


def make_chat(store, tmp_path, lane):
    output = []
    settings = {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    return Chat(app, settings, output.append), output


def returned(store, task, text, refs):
    """A task returned the way tasks.Executor returns it: natural language plus program-attached receipts."""
    current = task_records.get(store, task['_id'])
    result = {'task_id': task['_id'], 'intent_revision': current['intent_revision'], 'text': text,
              'finish_reason': 'stop', 'artifact_refs': list(refs), 'diagnostic': None,
              'facts': [{'text': text, 'evidence_refs': list(refs)}], 'uncertainties': []}
    return task_records.save(store, {**current, 'state': 'RETURNED', 'result': result, 'finished_at': now(),
                                     'feedback_state': 'READY'}, expected=current['revision'], stream=task['_id'])


def raw_insert(store, collection, *records):
    """Records written beside the code under test, through the driver, as a stored record is (`schema_version`)."""
    store.raw[collection].insert_many([{'schema_version': 1, **record} for record in records])


def granted_workspace(store):
    """The fixture grant's workspace (tests/fixture_grant.py); delegation is workspace mode only."""
    return Path(store.config['channels']['fixture']['routes']['dm-a']['workspace'])


def task_setup(store):
    # She hands the copy to the action brain and says nothing until the result is back.
    lane = FakeLane(store, [FakeTurn([('think', {'thought': '先核实。'}),
                                      ('delegate', {'title': 'copy fixture', 'brief': '复制受控文件，保留原件。'}),
                                      ('stay_silent', {'why': '等结果'})])])
    # Running commands is for the owner's own scenes: dm-a is the owner's DM (A is the owner by account).
    store.config['canonical_persons'] = {'A': store.config['chat']['person_id']}
    ep = Coordinator(store, lane).ingest({'event_id': 'copy', 'scene_id': 'dm-a', 'person_id': 'A',
                                          'text': '复制受控文件，保留原件。'})
    assert ep['state'] == 'WAITING_TASK' and len(ep['task_ids']) == 1
    service = TaskService(store)
    task = service.claim(ep['task_ids'][0])
    work = granted_workspace(store)
    (work / 'a.txt').write_text('controlled original', encoding='utf-8')
    broker = ToolBroker(service)
    broker.bind('s-test', task, work)
    return service, task, broker, work


class NativeLane:
    scheduler_session = 's-p5'

    def __init__(self):
        self.events, self.calls, self.created = [], [], 0

    def schedule(self, path, payload=None):
        self.calls.append((path, payload))
        if path == '/schedule/events':
            return [dict(e) for e in self.events]
        if path == '/schedule/create':
            self.created += 1
            kind = next(k for k in ('every', 'daily', 'weekly', 'after') if k in payload or k + '_seconds' in payload)
            record = {'id': 'n%d' % self.created, 'prompt': 'ASUNA_PLAN:' + payload['plan_id'], 'kind': kind,
                      'scheduledAt': datetime.now(timezone.utc).isoformat(),
                      **{k: v for k, v in payload.items() if k not in ('plan_id', 'every_seconds')}}
            if 'every_seconds' in payload:                # DSH stores an interval as everySeconds
                record['everySeconds'] = payload['every_seconds']
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'create', 'schedule': record}})
            return record
        if path == '/schedule/update':
            record = dict([e['data']['schedule'] for e in self.events
                           if e['data'].get('schedule', {}).get('id') == payload['id']][-1])
            change = payload.get('change')
            if change:                                    # DSH: exactly kind and its own selector
                selector = {'every': 'every_seconds', 'daily': 'daily', 'weekly': 'weekly', 'at': 'at'}.get(change['kind'])
                assert selector and set(change) == {'kind', selector}, change
                record.update({'everySeconds': change['every_seconds']} if change['kind'] == 'every'
                              else {selector: change[selector]}, kind=change['kind'])
            if payload.get('title'):
                record['title'] = payload['title']
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'update', 'schedule': record}})
            return record
        if path == '/schedule/delete':
            self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'delete', 'id': payload['id']}})
            return {'deleted': True}
        raise AssertionError(path)

    def fire(self, native_id):
        self.events.append({'seq': len(self.events) + 1, 'data': {'operation': 'dispatch', 'id': native_id}})
        return self.events[-1]['seq']


class Controller:
    def __init__(self):
        self.settings = {'persona': 'P1', 'scene_id': 'dm-a', 'person_id': 'A'}
        self.pending, self.active, self.active_task, self.offers, self.texts = SceneQueue(), None, None, [], []
        self.envelopes = []

    def offer_internal(self, kind, event_id, scene_id, person_id, text, **visit):
        self.offers.append((kind, event_id, scene_id, person_id))
        self.texts.append(text)
        self.envelopes.append(visit)

    def offer_self_development(self, event_id, *, text=None, **_):
        self.offers.append(('self_development', event_id, self.settings['scene_id'], self.settings['person_id']))
        self.texts.append(text)
        self.envelopes.append({})


def scheduler(store, rhythm=None):
    owner(store)
    store.config['persona_model'] = {'model_version': 1, 'persona': {'id': 'P1', 'display_name': 'x'},
        # The gates are under test here, not the die (ADR-058): it always rolls interesting.
        'heartbeat': {'enabled': True, 'every_min': 30, 'min_gap_min': 20,
                      'dice_awake': '有趣 1', 'dice_asleep': '有趣 1'},
        'rhythm': rhythm or {},
        'memory': {'promotion': {'daily_quota': 2, 'min_roots': 2, 'min_dates': 2, 'window_days': 7}}}
    store.config['persona_runtime'] = {'P1': {'heartbeat_target': 'dm-a'}}
    service = ScheduleService.__new__(ScheduleService)
    service.store, service.lane, service.controller = store, NativeLane(), Controller()
    service.deliver_lock, service.rhythm_lock = threading.RLock(), threading.RLock()
    service.app = types.SimpleNamespace(config=store.config)
    return service


TOPICS = ('松饼', '登山', '星星')


def vector(text, purpose):
    """One direction per topic: items on one topic score 1.0 against it, 0.5 against the others and the rest."""
    rest = 0.0 if any(t in text for t in TOPICS) else 1.0
    return [1.0 if topic in text else 0.0 for topic in TOPICS] + ([rest, 0.0] if purpose == 'document' else [0.0, rest])


class Route:
    revision = 'fake-route'

    def __init__(self):
        self.calls = []

    def embed(self, texts, purpose):
        self.calls.append(purpose)
        return [vector(text, purpose) for text in texts]


class Retrieval:
    """No memories of her conversations; the query's vector as the memory route would give it."""
    def __init__(self, memories=()):
        self.memories, self.route = list(memories), Route()

    def search(self, scope, epoch, query, **kwargs):
        found = [] if query == '天气' else [dict(m) for m in self.memories]       # nothing she said is about it
        return found, {'path': 'stub', 'coverage': 'sufficient'}

    def query_vector(self, query):
        return None

    def own_thoughts(self, scopes, query, limit=3):
        return []

    def embed(self, texts, purpose):
        return self.route.embed(texts, purpose)
