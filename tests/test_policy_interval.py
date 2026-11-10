"""Her daytime self-development interval through set_policy, a retime per change, and null clearing a parameter
(ADR-119 F14). On the fixture world of test_adr087_step4; the native scheduler is a stand-in that rebuilds an `every`
record from now, as DSH does."""
import threading
from datetime import datetime, timedelta

import pytest

from asuna import role_tools, schedule
from asuna.policy import PolicyStore
from asuna.records import plans as plan_records
from asuna.render import model_and_policy
from test_adr087_step4 import PERSONA, call, her as her_world, refused, turn  # noqa: F401  (her_world: the fixture)
from test_plan_zone_service import NOW, NativeStandIn

DAY = 'plan-asuna-self-development'


class RebuildingStandIn(NativeStandIn):
    """DSH rebuilds an `every` task whose timing changes from the moment of the change: now plus the interval."""

    def schedule(self, path, payload=None):
        if path == '/schedule/update' and (payload or {}).get('change', {}).get('kind') == 'every':
            self.calls.append((path, payload))
            return {'id': payload['id'], 'kind': 'every', 'scheduledAt': (NOW + timedelta(
                seconds=payload['change']['every_seconds'])).isoformat()}
        return super().schedule(path, payload)


@pytest.fixture
def her(her_world, monkeypatch):
    monkeypatch.setattr(schedule, 'now', lambda: NOW.isoformat())
    service = her_world.service
    service.lane = RebuildingStandIn()
    service.deliver_lock, service.rhythm_lock = threading.RLock(), threading.RLock()
    service.controller.settings.update({'scene_id': 'dm-a', 'person_id': 'A'})
    service.app.config['self_development'] = {'enabled': True}
    service.ensure_self_development()                      # her daytime plan at the default, 1,440 min
    return her_world


def audits(store, kind):
    return list(store.collection('audit_events').find({'type': kind}))


def set_policy(her, value, key='self_development.every_min', n=0):
    ep_id = turn(her, ['set_policy'])
    return call(her, ep_id, 'set_policy', {'key': key, 'value': value, 'why': 'test'}, n)


def test_the_interval_is_hers_within_its_bounds_and_a_falsy_value_is_refused_by_name(her):
    for value in (359, 10081, 0, '', False):
        no = refused(her, turn(her, ['set_policy']), 'set_policy',
                     {'key': 'self_development.every_min', 'value': value, 'why': 'test'})
        assert 'self_development.every_min' in str(no), (value, str(no))
        assert '没有可以改的参数' not in str(no), 'refused for its value, the key itself is hers'
    assert 'self_development.every_min' not in PolicyStore(her.store, PERSONA, model_and_policy(her.store, PERSONA)[0]).params()


def test_a_change_retimes_the_live_plan_once_from_the_moment_of_the_change(her):
    assert plan_records.get(her.store, DAY)['rule'] == {'every_seconds': 86400}
    shorter = set_policy(her, 360)
    plan = plan_records.get(her.store, DAY)
    assert shorter['now'] == 360 and shorter['from'] == 'policy'
    assert plan['rule'] == {'every_seconds': 21600}, 'retimed at once, not at the watch'
    assert plan['next_fire_at'] == (NOW + timedelta(hours=6)).isoformat(), 'the change plus the new interval'
    longer = set_policy(her, 10080)
    plan = plan_records.get(her.store, DAY)
    assert longer['now'] == 10080 and plan['next_fire_at'] == (NOW + timedelta(days=7)).isoformat()
    rows = [row['payload'] for row in sorted(audits(her.store, 'rhythm.retimed'), key=lambda row: row['seq'])]
    assert rows == [{'from': {'every_seconds': 86400}, 'to': {'every_seconds': 21600}},
                    {'from': {'every_seconds': 21600}, 'to': {'every_seconds': 604800}}], 'no drift key'
    updates = len([c for c in her.service.lane.calls if c[0] == '/schedule/update'])
    set_policy(her, 10080)
    her.service.ensure_self_development()
    assert len(audits(her.store, 'rhythm.retimed')) == 2, 'an equal value does not retime'
    assert len([c for c in her.service.lane.calls if c[0] == '/schedule/update']) == updates


def test_null_clears_the_interval_back_to_the_default_and_a_second_null_changes_nothing(her):
    set_policy(her, 720)
    cleared = set_policy(her, None)
    assert (cleared['now'], cleared['from']) == (1440, 'core'), 'SELF_DEVELOPMENT_DEFAULT_MIN'
    params = PolicyStore(her.store, PERSONA, model_and_policy(her.store, PERSONA)[0]).params()
    assert 'self_development.every_min' not in params, 'the key is gone, not stored as null'
    assert plan_records.get(her.store, DAY)['rule'] == {'every_seconds': 86400}
    again = set_policy(her, None)
    assert again['done'] == role_tools.POLICY_NOT_SET == '本来就没设，无改动'
    assert (again['now'], again['from']) == (1440, 'core')


def test_a_boolean_false_is_a_value_and_null_clears_it(her):
    put = set_policy(her, False, key='rhythm.public_clock')
    assert (put['now'], put['from']) == (False, 'policy')
    cleared = set_policy(her, None, key='rhythm.public_clock')
    assert (cleared['now'], cleared['from']) == (False, 'core'), 'the same value, another source'
