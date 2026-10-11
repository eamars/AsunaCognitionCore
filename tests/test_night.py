"""What her night turns changed (Xiaoman's request 2026-10-11): the first heartbeat after them lists it, with the
reason she wrote then; night by turn kind, not by the clock; her work log by section name only; computed."""
from datetime import datetime, timedelta, timezone

from asuna import night
from asuna.schedule_rules import scene_timezone

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)


def episode(store, ep_id, kind):
    store.db.episodes.insert_one({'_id': ep_id, 'schema_version': 1, 'scene_id': 'local', 'source_event_id': ep_id,
                                  'episode_kind': kind})


def event(store, ep_id, kind, hours_ago, payload=None):
    store.audit(ep_id, kind, payload or {}, 'scene:local')
    row = store.db.audit_events.find_one({'stream_id': ep_id, 'type': kind}, sort=[('seq', -1)])
    store.db.audit_events.update_one({'_id': row['_id']}, {'$set': {
        'occurred_at': (NOW - timedelta(hours=hours_ago)).isoformat()}})


def tool(store, ep_id, hours_ago, name, args, refused=False):
    event(store, ep_id, 'role_tool', hours_ago, {'call_id': 'c%s' % hours_ago, 'tool': name, 'args': args,
                                                 **({'refused': 'no'} if refused else {'result': 'ok'})})


def test_the_first_heartbeat_after_the_night_shows_what_the_night_changed(store):
    zone = scene_timezone(store.config, {'_id': 'local'})
    episode(store, 'ep-beat-evening', 'presence'); event(store, 'ep-beat-evening', 'turn.started', 12)
    episode(store, 'ep-dusk', 'external')                                  # an evening chat: not a night turn
    tool(store, 'ep-dusk', 11, 'set_policy', {'key': 'x', 'value': 1, 'reason': '傍晚改的'})
    episode(store, 'ep-night', 'self_development')
    tool(store, 'ep-night', 8, 'plan', {'intent': '明早看看群', 'at': '2026-10-12T09:00', 'why': '怕忘'})
    tool(store, 'ep-night', 7.5, 'plan', {'plan_id': 'p1'})                 # a lookup: not a change
    tool(store, 'ep-night', 7, 'watch', {'op': 'on', 'person': '[甲 #3]'}, refused=True)
    tool(store, 'ep-night', 6, 'write_document', {'doc': 'work_log', 'op': 'append_section', 'heading': '夜里记一笔'})
    tool(store, 'ep-night', 5.9, 'write_document', {'doc': 'voice', 'op': 'replace_section', 'sid': 'tone',
                                                    'reason': '语气改软一点'})
    out = night.block(store, 'P1', zone, NOW, 'ep-beat-morning')
    assert [i['what'] for i in out['items']] == ['定了计划：明早看看群', 'voice 的「tone」：replace_section']
    assert out['items'][0]['why'] == '怕忘' and out['work_log'] == ['夜里记一笔']
    # the next heartbeat starts after this one: the block does not come back
    episode(store, 'ep-beat-morning', 'presence'); event(store, 'ep-beat-morning', 'turn.started', 1)
    assert night.block(store, 'P1', zone, NOW, 'ep-beat-noon') is None


def test_a_group_is_named_by_its_title_not_its_slug(store):
    from asuna import group_admin, places
    g = 'qq:bot:group:7001'
    store.config['channels'] = {'qq': {'account_id': 'bot', 'routes': {'r': {
        'scene_id': g, 'sender_id': '*', 'person_id': 'qq:A', 'target': {'type': 'group', 'id': '7001'}}}}}
    store.put('scenes', {'_id': g, 'kind': 'group', 'scope_key': 'scene:' + g, 'policy_epoch': 1, 'members': [],
                         'sequence': 0}, stream=g)
    store.db.messages.insert_one({'_id': 'm-g', 'schema_version': 1, 'scene_id': g, 'direction': 'inbound',
                                  'received_at': '2026-10-11T01:00:00Z', 'event': {'raw': {'group_name': '读书会'}}})
    title = night._what(store, 'P1', 'group_focus', {'op': 'rest', 'place': places.place_id(g)})
    notes = night._what(store, 'P1', 'write_document', {'doc': group_admin.notes_slug(g), 'op': 'set_tags', 'sid': 's'})
    assert 'g' + group_admin.notes_slug(g)[6:12] == places.place_id(g)          # slug and place share the hash
    assert (title, notes) == ('让群聊「读书会」歇着', '群聊「读书会」的群笔记 的「s」：set_tags')
