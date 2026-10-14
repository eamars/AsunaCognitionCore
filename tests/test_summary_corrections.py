"""A correction stated to the dialogue summary as fact is one whose target is known (owner 2026-10-14): a line that
quotes another, or points back at its author's own earlier line. A cue word anywhere in a long message is not one."""
from asuna import summary_attribution

SCENE = {'_id': 'g', 'policy_epoch': 1}


def line(key, seq, author, text, reply=None):
    return {'_id': key, 'schema_version': 1, 'scene_id': 'g', 'policy_epoch': 1, 'scene_seq': seq, 'author': author, 'text': text,
            'direction': 'inbound', 'event': {'group_context': {'reply_message_id': reply}}}


def test_only_a_correction_with_a_known_target_is_listed(store):
    rows = [line('a', 1, 'A', '周三开会'),
            line('b', 2, 'B', '我把你说的那个方案改成了新的版本，第一次写错的地方也顺手修了，后面再看'),
            line('c', 3, 'A', '更正：是周四', reply='a'),
            line('d', 4, 'B', '刚才那句说错了，应该是下午')]
    store.db.messages.insert_many([dict(row) for row in rows])
    found = summary_attribution.corrections(store, SCENE, rows)
    assert [(item['message_id'], item['corrects']) for item in found] == [('c', 'a'), ('d', 'b')]
