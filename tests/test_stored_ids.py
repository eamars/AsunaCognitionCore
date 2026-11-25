"""ADR-120 landing 3, on the fixture world in memory (test_whose's home: the Web chat at home, g1 an outside group, g2 a
home group): a stored thing by its id (`received_file` read and copy, both fences), a conversation's list by name from
home, an old picture or file offered onto the list by id (`offer_file`) and listed first in the turn about the task,
and speak at home sending what it may read without the list. Only what would fail silently and costly: a fence that
lets another conversation's file through or tells that it exists, a copy left behind after its bytes were erased, an
offer the turn that follows does not list."""
import pytest

from asuna import (access, local_time, outbound_files, outbound_media, own_files, received_files, role_tools, visibility,
                   whose)
from asuna.blobs import BlobStore
from asuna.records import artifacts as artifact_records
from asuna.records import scenes as scene_records
from asuna.state import Denied
from asuna.store.words import Set
from test_own_files import PNG, denied_rows, picture, where
from test_whose import LOCAL, OWNER, PERSONA, home, turn  # noqa: F401  (home: a fixture)

MISSING = 'blob-' + 'f' * 32
OLD = '2026-01-01T00:00:00+00:00'


def text_file(store, scope, text=b'first line\nsecond line\n', name='notes.txt'):
    """A task's file, as offer_file registers one."""
    return BlobStore(store).put(text, scope, 'file', media_type='text/plain', source_ids=['task-file:t-x:' + name],
                                fields={'name': name})['artifact_id']


def received(store, scope, text=b'hello from someone\n'):
    return received_files.stash(store, text, scope, message_id='m-' + scope, index=0, name='r.txt',
                                sender='A')['artifact_id']


def run(store, scene_id, args, origin, task_dir=None, by=None):
    return received_files.run(store, where(scene_id), store.config, args, persona=PERSONA, origin=origin,
                              task_dir=task_dir, by=by)


def refused(call):
    with pytest.raises(Denied) as caught:
        call()
    return str(caught.value)


def task(store, task_id, scene_id, origin, who=None, requester=OWNER):
    return store.put('tasks', {'_id': task_id, 'request_key': task_id, 'scene_id': scene_id, 'requester_id': requester,
                               'scope_key': 'scene:' + scene_id, 'policy_epoch': 1, 'origin': origin,
                               'whose': who or whose.record('own', scene_id, requester), 'state': 'RUNNING'})


def offered(store, row, args):
    """offer_file by id, and its receipt as the broker writes it (a done call of the task)."""
    result = outbound_files.register(store, row, '.', args)
    artifact_records.save(store, {'_id': 'tool-' + row['_id'] + str(args), 'scope_key': row['scope_key'],
                                  'task_id': row['_id'], 'intent_revision': 1, 'tool': 'offer_file', 'args': args,
                                  'input_hash': 'h', 'state': 'DONE', 'result': result})
    return result


def test_a_stored_thing_is_read_and_copied_by_its_id_where_the_origin_may(home, tmp_path):
    store = home
    notes, drawing, theirs = text_file(store, 'scene:g1'), picture(store, 'scene:' + LOCAL), received(store, 'scene:g2')
    # Home reads any conversation's: a text body in pages, a picture said for what it is.
    read = run(store, LOCAL, {'ref': notes}, 'home')
    assert read['text'] == 'first line\nsecond line\n' and read['id'] == notes
    assert run(store, LOCAL, {'ref': theirs}, 'home_from_outside')['text'] == 'hello from someone\n'
    seen = run(store, LOCAL, {'ref': drawing}, 'home')
    assert 'text' not in seen and seen['note'].startswith('这是一张图（PNG 图片，') and 'read_image' in seen['note']
    # Outside reads its own; another conversation's answers exactly as one that does not exist, and is recorded.
    assert run(store, 'g1', {'ref': notes}, 'outside')['text'].startswith('first line')
    by = {'turn': 'ep-outside', 'scope': 'scene:g1'}
    elsewhere = refused(lambda: run(store, 'g1', {'ref': drawing}, 'outside', by=by))
    none = refused(lambda: run(store, 'g1', {'ref': MISSING}, 'outside', by=by))
    assert elsewhere == none == 'RECEIVED_FILE_NOT_FOUND: ' + own_files.GONE_HERE
    assert role_tools.words(Denied(elsewhere)) == '这个对话里没有这个文件。'
    assert [(row['resource'], row['origin']) for row in denied_rows(store)] == [('all_files', 'outside')]
    # The doing side copies any kind into /task/stored/, and the copy goes with the bytes when they are erased.
    copied = run(store, LOCAL, {'op': 'copy', 'ref': drawing}, 'home', task_dir=tmp_path)
    assert copied['path'] == '/task/stored/%s.png' % drawing
    assert (tmp_path / 'stored' / ('%s.png' % drawing)).read_bytes() == PNG
    assert run(store, 'g1', {'op': 'copy', 'ref': notes}, 'outside', task_dir=tmp_path)['path'] == '/task/stored/notes.txt'
    BlobStore(store).erase_scope('scene:' + LOCAL, 'erase-test')
    assert not (tmp_path / 'stored' / ('%s.png' % drawing)).exists() and (tmp_path / 'stored' / 'notes.txt').exists()


def test_a_conversation_lists_its_own_and_home_lists_a_group_by_its_name(home):
    store = home
    scene_records.next_seq(store, 'g1', name='造的群')            # a name of its own, as a named line writes it
    old, new = text_file(store, 'scene:g1', name='old.txt'), picture(store, 'scene:g1')
    store.collection('artifacts').update({'_id': old}, Set({'created_at': OLD}))
    text_file(store, 'scene:' + LOCAL, name='home.txt')
    listed = run(store, 'g1', {'op': 'list'}, 'outside')['items']
    assert [item['id'] for item in listed] == [new, old]              # its own, newest first, nothing of home's
    assert (listed[0]['kind'], listed[0]['type'], listed[0]['bytes']) == ('图', 'PNG 图片', '还在')
    assert (listed[1]['name'], listed[1]['at']) == ('old.txt', local_time.stamp(OLD, local_time.her_zone(store)))
    assert [item['name'] for item in run(store, LOCAL, {'op': 'list'}, 'home')['items']] == ['home.txt']
    for origin in ('home', 'home_from_outside'):
        there = run(store, LOCAL, {'op': 'list', 'place': '群聊「造的群」'}, origin)
        assert there['place'] == '群聊「造的群」' and [item['id'] for item in there['items']] == [new, old]
    unknown = refused(lambda: run(store, LOCAL, {'op': 'list', 'place': '造的：没有这个群'}, 'home'))
    assert unknown.startswith('GROUP_UNKNOWN: 没有叫「造的：没有这个群」的群；place 照抄这些里的一个：')
    scene_records.next_seq(store, 'g2', name='造的群')
    assert refused(lambda: run(store, LOCAL, {'op': 'list', 'place': '群聊「造的群」'}, 'home')).startswith(
        'GROUP_AMBIGUOUS: ')
    # Outside, a name is refused by the table whatever it names: one answer for a group and for none, recorded.
    by = {'turn': 'ep-outside', 'scope': 'scene:g1'}
    named = refused(lambda: run(store, 'g1', {'op': 'list', 'place': '群聊「造的群」'}, 'outside', by=by))
    nothing = refused(lambda: run(store, 'g1', {'op': 'list', 'place': '造的：没有'}, 'outside', by=by))
    assert named == nothing == access.refusal('outside', 'list_files')
    assert [row['resource'] for row in denied_rows(store)] == ['list_files', 'list_files']


def test_offer_file_puts_a_stored_id_on_the_list_of_the_turn_about_the_task(home, monkeypatch):
    store = home
    monkeypatch.setattr(outbound_media, 'target_allowed', lambda *args: (True, ''))
    monkeypatch.setattr(outbound_files, 'sends_here', lambda store, scene: True)
    g1, local = scene_records.get(store, 'g1'), scene_records.get(store, LOCAL)
    theirs = picture(store, 'scene:g1', 'upload:someone')           # someone sent it in g1, long ago
    store.collection('artifacts').update({'_id': theirs}, Set({'created_at': OLD}))
    for _ in range(outbound_media.MAX_ITEMS_OFFERED):
        picture(store, 'scene:' + LOCAL)                            # newer drawings fill her home list
    # A home task offers it into her home chat: shared there, and first on the list of the turn about the task.
    at_home = task(store, 'task-home', LOCAL, 'home')
    result = offered(store, at_home, {'artifact_id': theirs})
    assert (result['as'], result['artifact_id']) == ('picture', theirs)
    assert 'scene:' + LOCAL in artifact_records.get(store, theirs)['shared_scopes']
    picked = outbound_files.offered_by(store, 'task-home')
    listed = outbound_media.offer(store, store.config, local, visibility.OWNER_PRIVATE, OWNER, picked=picked)
    assert listed['items'][0]['artifact_id'] == theirs
    # An outside task in g1 offers only g1's own; another conversation's id answers as a missing one.
    outside = task(store, 'task-g1', 'g1', 'outside', whose.record('words', 'g1', 'A'), requester='A')
    drawn_at_home = picture(store, 'scene:' + LOCAL)
    assert refused(lambda: outbound_files.register(store, outside, '.', {'artifact_id': drawn_at_home})) == \
        refused(lambda: outbound_files.register(store, outside, '.', {'artifact_id': MISSING})) == \
        'FILE_NOT_FOUND: ' + own_files.GONE_HERE
    notes = text_file(store, 'scene:g1', name='old.txt')
    store.collection('artifacts').update({'_id': notes}, Set({'created_at': OLD}))
    for index in range(outbound_files.MAX_OFFERED):
        text_file(store, 'scene:g1', name='new-%d.txt' % index)
    assert offered(store, outside, {'artifact_id': theirs})['as'] == 'picture'
    assert offered(store, outside, {'artifact_id': notes})['as'] == 'file'
    picked = outbound_files.offered_by(store, 'task-g1')
    pictures = outbound_media.offer(store, store.config, g1, visibility.PUBLIC, 'A', picked=picked, origin='outside')
    files = outbound_files.offer(store, g1, origin='outside', picked=picked)
    assert pictures['items'][0]['artifact_id'] == theirs and files['items'][0]['artifact_id'] == notes
    # A received file becomes a file of the task, its sender kept.
    forwarded = offered(store, outside, {'artifact_id': received(store, 'scene:g1')})
    row = artifact_records.get(store, forwarded['artifact_id'])
    assert (row['kind'], row['scope_key'], row['received_from']['sender']) == ('file', 'scene:g1', 'A')
    # A send the owner narrowed is refused with her sentence, recorded as a send.
    store.config['access'] = {'send_own': 'home_from_outside'}
    assert refused(lambda: outbound_files.register(store, outside, '.', {'artifact_id': notes})) == access.SEND_REFUSED
    assert denied_rows(store)[-1] == {'resource': 'send_own', 'origin': 'outside', 'tool': 'offer_file',
                                      'task': 'task-g1', 'send': True}


def test_speak_at_home_sends_what_it_may_read_and_outside_only_what_is_listed(home, monkeypatch):
    store = home
    from asuna.coordinator import Coordinator
    tools = role_tools.RoleTools(Coordinator(store, None))
    theirs = picture(store, 'scene:g1', 'upload:someone')
    at_home, outside = turn(store, LOCAL, OWNER, 'speak-home'), turn(store, 'g1', 'A', 'speak-outside')
    sent = tools._picture(at_home, scene_records.get(store, LOCAL), theirs, 'call-1')       # on no list of this turn
    assert sent['artifact_id'] == theirs
    monkeypatch.setattr(outbound_media, 'target_allowed', lambda *args: (True, ''))
    with pytest.raises(role_tools.Refused, match='不在你能发的图里'):
        tools._picture(outside, scene_records.get(store, 'g1'), theirs, 'call-2')
    monkeypatch.setattr(outbound_files, 'sends_here', lambda store, scene: True)
    notes, g2 = text_file(store, 'scene:g1'), scene_records.get(store, 'g2')
    assert outbound_files.check(store, at_home, g2, notes, gate=tools._listed_only(at_home))[0]['artifact_id'] == notes
    assert outbound_files.check(store, outside, g2, notes, gate=tools._listed_only(outside))[1].startswith('不在能发的文件里')


def test_a_home_group_lists_her_drawings_from_anywhere_and_an_outside_group_does_not(home, monkeypatch):
    """Her 0689: the positive side of HOME_GROUP_NOTE's list."""
    store = home
    monkeypatch.setattr(outbound_media, 'target_allowed', lambda *args: (True, ''))
    drawn_at_home = picture(store, 'scene:' + LOCAL)

    def listed(scene_id):
        scene = {**scene_records.get(store, scene_id), 'channel_id': 'fixture'}      # routed: a group's list
        cls = visibility.session_class(store.config, store, scene, 'A')
        found = outbound_media.offer(store, store.config, scene, cls, 'A', origin='home' if cls == visibility.OWNER_PRIVATE
                                     else 'outside')
        return found or {}
    in_home_group = listed('g2')
    assert drawn_at_home in [item['artifact_id'] for item in in_home_group['items']]
    assert outbound_media.HOME_GROUP_NOTE in in_home_group['note']
    assert drawn_at_home not in [item['artifact_id'] for item in listed('g1').get('items') or ()]
