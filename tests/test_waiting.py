"""Who she is still waiting for (Xiaoman's request 2026-10-11): her lines of the last day that @ someone or asked
with wait=yes, whose people have not spoken since; computed, never stored; a plain reply does not count."""
from datetime import datetime, timedelta, timezone

from asuna import waiting
from asuna.config import character_id

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
G1, G2 = 'qq:bot:group:1001', 'qq:bot:group:1002'


def world(store):
    store.config['channels'] = {'qq': {'account_id': 'bot', 'routes': {
        g: {'scene_id': g, 'sender_id': '*', 'person_id': 'qq:A', 'target': {'type': 'group', 'id': g[-4:]}}
        for g in (G1, G2)}}}
    for g in (G1, G2):
        store.put('scenes', {'_id': g, 'kind': 'group', 'scope_key': 'scene:' + g, 'policy_epoch': 1,
                             'members': [], 'sequence': 0}, stream=g)
        for handle, who in ((1, 'A'), (2, 'B')):
            store.db.scene_people.insert_one({'_id': '%s|qq:%s' % (g, who), 'schema_version': 1, 'scene_id': g,
                                              'person': 'qq:' + who, 'handle': handle, 'card': who + '同学'})


def line(store, scene, seq, text, minutes_ago, episode=None, choice=None, mine=True):
    at = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    row = {'_id': '%s-%d' % (scene[-4:], seq), 'schema_version': 1, 'scene_id': scene, 'scene_seq': seq, 'text': text,
           'policy_epoch': 1}
    if mine:
        row.update(direction='outbound', delivery_state='DELIVERED', author=character_id(store.config),
                   receipt_at=at, episode_id=episode or 'ep-%s-%d' % (scene[-4:], seq))
        if choice is not None:
            store.db.episodes.insert_one({'_id': row['episode_id'], 'schema_version': 1, 'scene_id': scene,
                                          'source_event_id': row['episode_id'], 'await_answer': choice})
    else:
        row.update(direction='inbound', author=mine is False and 'qq:B' or mine, received_at=at)
    store.db.messages.insert_one(row)


def test_she_sees_who_she_still_waits_for_and_nobody_else(store):
    world(store)
    line(store, G1, 1, '@[A同学 #1] 你周末来吗', 120)                 # called A: A never spoke since
    line(store, G1, 2, '@[B同学 #2] 那本书呢', 90)                   # called B: B answered
    line(store, G1, 3, '好的', 80, mine=False)                        # B speaks (author qq:B)
    line(store, G1, 4, '随口一句 @[A同学 #1]', 60, choice={'off': True})  # wait=no: never counts
    line(store, G1, 5, '这只是一句回话', 30)                           # a plain reply/remark: no call, no wait
    line(store, G1, 6, '有人知道吗', 26 * 60, choice={'why': '想问路'})    # older than a day: gone
    line(store, G2, 7, '谁有空帮个忙', 10, choice={'why': '找人帮忙'})     # wait=yes, nobody called: anyone here
    here = waiting.block(store, [G1], NOW, 'P1')
    assert [(i['who'], i['waiting']) for i in here['items']] == [('[A同学 #1]', '挂了 2 小时')]
    assert here['items'][0]['your_line'] == '@A同学 你周末来吗'
    home = waiting.block(store, [G1, G2], NOW, 'P1', home=True)
    assert [(i['group'] != '', i['who']) for i in home['items']] == [(True, waiting.ANYONE), (True, '[A同学 #1]')]
    line(store, G2, 8, '我可以', 5, mine=False)                        # someone speaks in G2: no longer waiting there
    assert waiting.block(store, [G2], NOW, 'P1') is None
    assert store.db.list_collection_names().count('waiting') == 0      # nothing stored
