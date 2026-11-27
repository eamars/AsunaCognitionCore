"""ADR-137 D2: a group turn's pictures come in a message of their own, each under the head of the line it came from;
the head is the first line her conversation shows for that line."""
from asuna import role_tools, vision
from asuna.people import People
from test_people import SCENE, row
from test_woken_by_program import setup


def _line(store, number, seq, text, card, picture=True):
    line = {**row(number, text, card=card, at='2026-10-04T01:%02d:00+00:00' % seq), '_id': 'in-ep-%d' % seq,
            'episode_id': 'ep-%d' % seq, 'scene_seq': seq, 'scope_key': 'scene:' + SCENE}
    if picture:
        line['event']['raw']['asuna_media'] = {'items': [{'type': 'image', 'url': 'https://example.invalid/%d.png' % seq}]}
    store.put('messages', line)
    return line


def test_each_picture_brings_the_head_of_its_line_as_her_conversation_shows_it(store, monkeypatch):
    scene = setup(store)
    store.config['character'] = {'input_modalities': ['image']}
    store.config['vision'] = {'image_hosts': ['example.invalid']}
    monkeypatch.setattr(vision, 'read_image_for_task',
                        lambda *args, **kwargs: {'image': {'media_type': 'image/png', 'data': 'eA=='}})
    # Each line is written into her conversation as it arrives (native_worker.channel_input: People.transcript).
    lines = [_line(store, 20003, 10, '先发一张', '阿杰'), _line(store, 20004, 11, '没图的话', '路人', picture=False),
             _line(store, 20002, 12, '看这张', '七号')]
    written = {line['_id']: People(store).transcript(scene, line).split('\n')[0] for line in lines}
    pulled, shown = role_tools.turn_pictures(store, {'_id': 'ep-12', 'scene_id': SCENE, 'scope_key': 'scene:' + SCENE,
                                                     'policy_epoch': 1})
    heads = [written['in-ep-12'], written['in-ep-10']]
    assert [head for _, _, head in pulled] == heads, 'the calling line first, then the earlier one, as she reads them'
    assert '〔12〕' in heads[0] and '〔10〕' in heads[1]
    assert [item['ref'] for item in shown['items']] == [ref for ref, _, _ in pulled], 'the order pictures_from_program says'
    assert [item['line'] for item in shown['items']] == ['触发这一次的那条', '前面第 2 条']
