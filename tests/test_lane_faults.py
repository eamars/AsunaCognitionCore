"""ADR-095 step 1: the channel lanes' faults, counted by signature and hour (lane_faults.py)."""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from asuna import lane_faults
from asuna.channels import ChannelServer
from test_voice import TOKEN, world

NOW = datetime.now(timezone.utc)
HOUR, EARLIER = lane_faults.hour_of(NOW), lane_faults.hour_of(NOW - timedelta(hours=1))


def row(**over):
    return {'lane': 'inbound', 'stage': 'post', 'error': 'host_error:500', 'hour': HOUR, 'count': 1, **over}


def test_counts_add_up_by_signature_and_hour_and_carry_no_message(store):
    # record() stamps the hour it runs in, so this test reads the clock when it runs, not when the module loaded.
    now = datetime.now(timezone.utc)
    hour, earlier = lane_faults.hour_of(now), lane_faults.hour_of(now - timedelta(hours=1))
    assert lane_faults.receive(store, 'qq', {'counts': [row(hour=hour, count=2)]}) == {'status': 'recorded', 'rows': 1}
    lane_faults.receive(store, 'qq', {'counts': [row(hour=hour, count=3), row(hour=earlier, count=2)]})
    lane_faults.record(store, 'qq', 'inbound', 'post', 'host_error:500')
    docs = {doc['hour']: doc for doc in store.db.lane_faults.find({'channel_id': 'qq'})}
    assert docs[hour]['count'] == 6 and docs[earlier]['count'] == 2
    assert set(docs[hour]) == {'_id', 'schema_version', 'channel_id', 'lane', 'stage', 'error', 'hour', 'hour_at',
                               'count', 'first_posted_at', 'last_posted_at'}
    assert docs[hour]['hour_at'].strftime(lane_faults.HOUR_FORMAT) == hour


def test_counts_leave_after_their_days_on_the_next_write(store):
    now = datetime.now(timezone.utc)
    lane_faults.record(store, 'qq', 'inbound', 'post', 'old', moment=now - timedelta(days=lane_faults.KEEP_DAYS, hours=2))
    lane_faults.record(store, 'qq', 'inbound', 'post', 'kept', moment=now - timedelta(days=lane_faults.KEEP_DAYS - 1))
    assert [doc['error'] for doc in store.db.lane_faults.find()] == ['kept']
    assert not [index for index in store.db.lane_faults.list_indexes() if 'expireAfterSeconds' in index]


@pytest.mark.parametrize('body, code', [
    ({}, 'FAULTS_INVALID'),
    ({'counts': [], 'more': 1}, 'FAULTS_INVALID'),
    ({'counts': [row(lane='nowhere')]}, 'FAULTS_LANE_UNKNOWN'),
    ({'counts': [row(hour=HOUR.replace('T', ' '))]}, 'FAULTS_HOUR_INVALID'),
    ({'counts': [row(hour='1900-01-01T00')]}, 'FAULTS_HOUR_INVALID'),
    ({'counts': [row(hour=lane_faults.hour_of(NOW + timedelta(hours=3)))]}, 'FAULTS_HOUR_INVALID'),
    ({'counts': [row(count=0)]}, 'FAULTS_COUNT_INVALID'),
    ({'counts': [row(stage='')]}, 'FAULTS_FIELD_INVALID'),
    # words of an answer never come in: a class is a name, and no `|` can join two signatures
    ({'counts': [row(error="host_rejected:400:INVALID_X: Expecting ',' delimiter: line 1 column 345")]}, 'FAULTS_FIELD_INVALID'),
    ({'counts': [row(stage='a|b')]}, 'FAULTS_FIELD_INVALID'),
    ({'counts': [row(text='x')]}, 'FAULTS_ROW_INVALID'),
])
def test_a_count_out_of_shape_is_refused_and_nothing_is_counted(store, body, code):
    with pytest.raises(ValueError, match=code):
        lane_faults.receive(store, 'qq', body)
    assert store.db.lane_faults.count_documents({}) == 0


def test_a_post_is_counted_whole_or_not_at_all(store):
    with pytest.raises(ValueError, match='FAULTS_COUNT_INVALID'):
        lane_faults.receive(store, 'qq', {'counts': [row(), row(stage='spool', count=-1)]})
    assert store.db.lane_faults.count_documents({}) == 0


def test_the_endpoint_takes_the_adapters_counts_and_a_route_key_is_refused(store):
    channels = world(store)
    server = ChannelServer(channels, 0)

    def post(body):
        request = urllib.request.Request('http://127.0.0.1:%d/v1/channels/qq/faults' % server.server.server_port,
                                         data=json.dumps(body).encode(), method='POST',
                                         headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=30) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())
    try:
        assert post({'counts': [row(lane='receipts', stage='replay', error='abandoned:None')]}) == (
            200, {'status': 'recorded', 'rows': 1})
        channels.authenticate = lambda channel_id, authorization: (None, 'g')      # as a route key of route g
        assert post({'counts': [row()]}) == (403, {'error': 'ROUTE_KEY_ENDPOINT_DENIED'})
    finally:
        server.close()
    assert store.db.lane_faults.find_one({'lane': 'receipts'})['count'] == 1
    assert store.db.lane_faults.count_documents({}) == 1
