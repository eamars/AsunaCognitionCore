"""A group turn brings its pictures (owner 2026-10-08, on her ask): the line that started the turn brings its own;
up to two in all, the rest filled from photos (never stickers) in the few lines before it."""
import base64

from asuna import role_tools, vision

GROUP = 'qq:9:group:1'


def line(store, seq, items, rid=None):
    store.put('messages', {'_id': rid or 'in-l%d' % seq, 'scene_id': GROUP, 'direction': 'inbound', 'scene_seq': seq,
                           'policy_epoch': 1, 'text': 'x', 'received_at': '2026-10-08T00:00:%02dZ' % seq,
                           'event': {'event_id': 'e%d' % seq, 'raw': {'asuna_media': {'items': items}}}})


def photo(name):
    return {'type': 'image', 'url': 'https://img.example.invalid/%s.png' % name, 'placeholder': '[图片]'}


def sticker(name):
    return {**photo(name), 'sub_type': '1', 'sticker': 'custom'}


def setup(store, monkeypatch, source_items):
    store.config.update(character={'input_modalities': ['text', 'image']}, vision={'image_hosts': ['img.example.invalid']})
    store.put('scenes', {'_id': GROUP, 'kind': 'group', 'scope_key': 'scene:' + GROUP, 'policy_epoch': 1, 'members': ['A']})
    line(store, 1, [photo('old')])                       # outside the window of lines before the trigger
    line(store, 6, [sticker('meme')])
    line(store, 8, [photo('cat')])
    line(store, 10, source_items, rid='in-ep-1')
    pulled = []

    def read(store_, blobs, scene, config, args, route='executor', offered=()):
        pulled.append(args['ref'])
        return {'ref': args['ref'], 'image': {'media_type': 'image/png', 'data': base64.b64encode(b'png').decode()}}
    monkeypatch.setattr(vision, 'read_image_for_task', read)
    return {'_id': 'ep-1', 'scene_id': GROUP, 'scope_key': 'scene:' + GROUP, 'policy_epoch': 1}, pulled


def test_the_trigger_line_first_then_recent_photos_never_stickers(store, monkeypatch):
    ep, pulled = setup(store, monkeypatch, [photo('trigger')])
    got, shown = role_tools.turn_pictures(store, ep)
    assert [item['line'] for item in shown['items']] == ['触发这一轮的那条', '前面第 2 条']
    assert len(got) == 2 and len(pulled) == 2 and '不用再 read_image' in shown['note']


def test_two_at_most_and_a_line_without_pictures_still_gets_recent_ones(store, monkeypatch):
    ep, _ = setup(store, monkeypatch, [photo('a'), photo('b'), photo('c')])
    assert len(role_tools.turn_pictures(store, ep)[0]) == 2
    store.db.messages.delete_one({'_id': 'in-ep-1'})
    line(store, 10, [], rid='in-ep-1')
    got, shown = role_tools.turn_pictures(store, ep)
    assert [item['line'] for item in shown['items']] == ['前面第 2 条']      # the sticker is not filled in


def test_not_in_a_private_chat_and_not_when_her_route_cannot_see(store, monkeypatch):
    ep, _ = setup(store, monkeypatch, [photo('trigger')])
    store.config['character'] = {'input_modalities': ['text']}
    assert role_tools.turn_pictures(store, ep) == ([], None)
