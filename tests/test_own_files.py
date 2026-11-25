"""ADR-120 landing 2, on the fixture world in memory (test_whose's home: the Web chat and an agent line at home, g1 an
outside group, g2 a home group, dm-a someone else's chat): a conversation's own files, the reads by origin (another
conversation's file outside answers exactly as a missing one, and is recorded), the sends by origin and target, the
outside list and a going-out that carries a picture there, erasure, and her review of the
table's refusals."""
import pytest

from asuna import access, guard, media_life, outbound_media, own_files, received_files, role_tools, vision, whose
from asuna.blobs import BlobStore
from asuna.records import artifacts as artifact_records
from asuna.records import scenes as scene_records
from asuna.store.words import Set
from test_whose import AGENT, LINE, LOCAL, OWNER, PERSONA, home, turn  # noqa: F401  (home: a fixture)


PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')
MADE = 'integration:image:/x.png'          # her own drawing's source


def picture(store, scope, source=MADE):
    return BlobStore(store).put(PNG, scope, 'image', media_type='image/png', source_ids=[source])['artifact_id']


def where(scene_id):
    return {'scene_id': scene_id, 'scope_key': 'scene:' + scene_id, 'policy_epoch': 1}


def denied_rows(store):
    from asuna import audit
    return [row['payload'] for row in audit.events(store, 'access.denied').rows()]


def a_line_with_a_picture(store, scene_id, key, received_at=None, item=None):
    """An inbound line carrying one picture (or `item`), as an adapter posts it; its ref."""
    from asuna import ingress
    from asuna.records import messages as message_records
    item = item or {'type': 'image', 'url': 'https://example.invalid/p.png', 'placeholder': '[图片]'}
    event = {'event_id': key, 'scene_id': scene_id, 'person_id': 'A', 'text': '看', 'adapter_id': 'fixture',
             'raw': {'asuna_media': {'count': 1, 'items': [item]}}}
    ingress.persist_input(store, event)
    row = message_records.get(store, 'in-' + ingress.episode_id(event))
    if received_at:
        store.collection('messages').update({'_id': row['_id']}, Set({'received_at': received_at}))
    return vision.ref_of(row['_id'], 0)


def test_a_conversation_s_own_files(home):
    store = home
    store.config['context_links'] = {'g1': ['dm-a']}
    g1 = scene_records.get(store, 'g1')
    own = own_files.scopes(store.config, g1)
    assert own == ['scene:g1', 'scene:dm-a']                       # its own first, then what the owner linked to it
    row = lambda artifact_id: artifact_records.get(store, artifact_id)
    made_here, linked, at_home = picture(store, 'scene:g1'), picture(store, 'scene:dm-a'), picture(store, 'scene:' + LOCAL)
    sticker = BlobStore(store).put(PNG, own_files.STICKERS, 'image', media_type='image/png')['artifact_id']
    edit = picture(store, 'scene:' + LOCAL, 'edit:scene:g1|integration:image:/e.png')    # goes back to g1
    assert [own_files.holds(row(a), own) for a in (made_here, linked, sticker, edit)] == [True] * 4
    assert not own_files.holds(row(at_home), own)
    # Sent or carried there, it is the group's own from then on: one set-add, never twice, never on its own row.
    assert own_files.share(store, at_home, 'scene:g1') and not own_files.share(store, at_home, 'scene:g1')
    assert not own_files.share(store, made_here, 'scene:g1') and not own_files.share(store, sticker, 'scene:g1')
    assert row(at_home)['shared_scopes'] == ['scene:g1'] and own_files.holds(row(at_home), own)
    assert 'shared_scopes' not in row(made_here) and 'shared_scopes' not in row(sticker)


def test_outside_another_conversation_s_file_answers_as_a_missing_one_and_is_recorded(home):
    store = home
    at_home, here = picture(store, 'scene:' + LOCAL), picture(store, 'scene:g1')
    by = {'turn': 'ep-outside', 'scope': 'scene:g1'}

    def refused(ref, kind=ValueError):
        with pytest.raises(kind) as caught:
            vision.read_image_for_task(store, BlobStore(store), where('g1'), store.config, {'ref': ref}, look=False,
                                       origin='outside', by=by)
        return caught.value
    elsewhere, missing = refused(at_home), refused('blob-' + '0' * 32)
    assert str(elsewhere) == str(missing) == vision.NOT_HERE
    assert role_tools.words(elsewhere) == role_tools.words(missing) == '这个对话里没有这个文件。'
    assert vision.read_image_for_task(store, BlobStore(store), where('g1'), store.config, {'ref': here}, look=False,
                                      origin='outside')['artifact_id'] == here
    # A message's picture of another conversation: the same words as a ref that names nothing.
    theirs = a_line_with_a_picture(store, 'g2', 'p-g2')
    other, none = str(refused(theirs)), str(refused('att-ffffffffffff'))
    assert other.replace(theirs, '<ref>') == none.replace('att-ffffffffffff', '<ref>')
    # A received file's ref of another conversation, the same.
    their_file = a_line_with_a_picture(store, 'g2', 'f-g2', item={'type': 'file', 'file': 'a.txt', 'size': '9',
                                                                  'url': 'https://example.invalid/a.txt'})
    with pytest.raises(Exception) as file_elsewhere:
        received_files.run(store, where('g1'), store.config, {'ref': their_file}, persona=PERSONA, origin='outside',
                           by=by)
    with pytest.raises(Exception) as file_missing:
        received_files.run(store, where('g1'), store.config, {'ref': 'att-ffffffffffff'}, persona=PERSONA,
                           origin='outside', by=by)
    assert str(file_elsewhere.value).replace(their_file, '<ref>') == str(file_missing.value).replace(
        'att-ffffffffffff', '<ref>')
    # Three refusals of another conversation's file recorded, none of a missing one; none names whose the file is.
    rows = denied_rows(store)
    assert [(row['resource'], row['origin']) for row in rows] == [('all_files', 'outside')] * 3
    assert all(set(row) <= {'resource', 'origin', 'tool', 'call', 'task', 'send'} for row in rows)


def test_home_reads_any_stored_file_with_no_age_check_and_message_pictures_of_seven_days(home):
    store = home
    theirs = picture(store, 'scene:g1', 'upload:someone')          # not hers, in an outside group, long stored
    store.collection('artifacts').update({'_id': theirs}, Set({'created_at': '2026-01-01T00:00:00+00:00'}))
    for origin in ('home', 'home_from_outside'):
        read = vision.read_image_for_task(store, BlobStore(store), where(LOCAL), store.config, {'ref': theirs},
                                          look=False, origin=origin)
        assert read['artifact_id'] == theirs
    # A message's picture is reachable from any conversation for its last 7 days, as long as its pulled copy lives,
    # and no further: neither a home read nor an outside miss's check reads a conversation's older lines.
    recent = a_line_with_a_picture(store, 'g1', 'p-recent')
    old = a_line_with_a_picture(store, 'g2', 'p-old', received_at='2026-01-01T00:00:00+00:00')
    assert vision.REF_DAYS == media_life.PULLED_DAYS
    assert vision.attachment_by_ref(store, where(LOCAL), store.config, recent, wide=True)[0]['ref'] == recent
    assert vision.attachment_by_ref(store, where(LOCAL), store.config, old, wide=True)[0] is None
    assert not vision.elsewhere(store, where('g1'), store.config, old)
    assert received_files.reach(store, where(LOCAL), store.config, 'home_from_outside') >= {'scene:g1', 'scene:g2'}
    assert received_files.reach(store, where('g1'), store.config, 'outside') == {'scene:g1'}
    # A narrowed table: home reads only its own conversation's then.
    store.config['access'] = {'all_files': 'none'}
    with pytest.raises(ValueError):
        vision.read_image_for_task(store, BlobStore(store), where(LOCAL), store.config, {'ref': theirs}, look=False,
                                   origin='home')


def test_who_may_send_what_where(home):
    store = home
    g1, dm_a, local = (scene_records.get(store, scene) for scene in ('g1', 'dm-a', LOCAL))
    at_home = artifact_records.get(store, picture(store, 'scene:' + LOCAL))
    of_g1 = artifact_records.get(store, picture(store, 'scene:g1', 'upload:someone'))
    mine = own_files.scopes(store.config, local)

    def refused(origin, row, place, asker=None, own=mine):
        return own_files.send_refused(store, origin, row, place, own, asker)
    # Home sends any file anywhere; work from outside sends any file only to the conversation it is for.
    assert refused('home', at_home, g1) is None and refused('home', of_g1, dm_a) is None
    assert refused('home_from_outside', at_home, g1, asker='g1') is None
    assert refused('home_from_outside', at_home, dm_a, asker='g1') == 'send_any'
    # Outside sends only its own conversation's files there.
    g1_own = own_files.scopes(store.config, g1)
    assert refused('outside', of_g1, g1, own=g1_own) is None
    assert refused('outside', at_home, g1, own=g1_own) == 'all_files'            # not its own: it cannot read it
    store.config['access'] = {'all_files': 'everywhere'}
    assert refused('outside', at_home, g1, own=g1_own) == 'send_any'
    store.config.pop('access')
    # Into a home conversation is no crossing: whatever the work may read.
    for origin, asker in (('home', None), ('home_from_outside', 'g1')):
        assert refused(origin, of_g1, local, asker) is None
    assert refused('outside', of_g1, local, own=g1_own) is None
    # Her speak's refusal is one sentence, recorded as a send.
    ep = turn(store, 'g1', 'A', 'send-1')
    from asuna.coordinator import Coordinator
    tools = role_tools.RoleTools(Coordinator(store, None))
    with pytest.raises(Exception) as caught:
        tools._may_send(ep, 'call-send', g1, at_home['_id'])
    assert str(caught.value) == access.SEND_REFUSED and role_tools.words(caught.value) == access.NOT_TO_SEND
    assert denied_rows(store)[-1] == {'resource': 'all_files', 'origin': 'outside', 'tool': 'speak',
                                      'call': 'call-send', 'send': True}


def test_the_outside_list_has_no_home_drawing_until_a_going_out_carries_it(home, monkeypatch):
    store = home
    monkeypatch.setattr(outbound_media, 'target_allowed', lambda *args: (True, ''))
    g1 = scene_records.get(store, 'g1')
    drawn_at_home, drawn_here = picture(store, 'scene:' + LOCAL), picture(store, 'scene:g1')
    received_here = picture(store, 'scene:g1', 'upload:someone')

    def listed(scene, cls='public', origin='outside'):
        found = outbound_media.offer(store, store.config, scene, cls, picked=None, origin=origin)
        return [item['artifact_id'] for item in (found or {}).get('items') or ()]
    assert listed(g1) == [drawn_here]                       # 2026-11-24: a home drawing on no group's list
    assert received_here not in listed(g1)                 # received there: sendable, not listed
    # A home turn's errand picks it: it may send it there, so it is shared there at the pick.
    sender = turn(store, LOCAL, OWNER, 'errand-1')
    own_files.carry(store, sender, drawn_at_home, g1, 'errand')
    assert drawn_at_home in listed(g1)
    # Work from outside picks only for the conversation it is for.
    for_g2 = turn(store, LINE, AGENT, 'errand-2', episode={'whose': whose.record('outside', 'g2', chosen=True)})
    store.put('tasks', {'_id': 'task-for-g2', 'request_key': 'task-for-g2', 'scene_id': LOCAL, 'requester_id': OWNER,
                        'episode_id': for_g2['_id'], 'whose': whose.record('outside', 'g2', chosen=True),
                        'origin': 'home_from_outside', 'state': 'RETURNED'})
    result = turn(store, LOCAL, OWNER, 'errand-3', episode={'episode_kind': 'task_feedback', 'task_id': 'task-for-g2',
                                                            'whose': whose.record('outside', 'g2', chosen=True)})
    other = picture(store, 'scene:' + LOCAL)
    with pytest.raises(Exception) as caught:
        own_files.carry(store, result, other, g1, 'errand')
    assert str(caught.value) == access.SEND_REFUSED and other not in listed(g1)
    with pytest.raises(ValueError, match='ARTIFACT_NOT_FOUND'):
        own_files.carry(store, sender, 'blob-' + '1' * 32, g1, 'visit')
    # A message written into a conversation shares what it carries, before its row.
    from asuna.coordinator import Coordinator
    coordinator = Coordinator(store, None)
    coordinator.publisher = type('Publisher', (), {'publish': lambda self, key: {'delivery_state': 'READY'},
                                                   'cancel_after': lambda self, row: None})()
    dm_a = scene_records.get(store, 'dm-a')
    speaking = turn(store, 'dm-a', 'A', 'speak-1')
    row = artifact_records.get(store, other)
    coordinator.queue_reply(speaking, [{'kind': 'picture', 'text': '', 'shown': 'picture', 'fields': {'attachment': {
        'artifact_id': other, 'media_type': 'image/png', 'sha256': row['sha256'], 'size': row['size']}}}])
    assert other in listed(dm_a)


def test_an_erasure_takes_its_conversation_out_of_every_shared_row(home):
    store = home
    shared = picture(store, 'scene:' + LOCAL)
    own_files.share(store, shared, 'scene:g1')
    own_files.share(store, shared, 'scene:g2')
    BlobStore(store).erase_scope('scene:g1', 'erase-test')
    assert artifact_records.get(store, shared)['shared_scopes'] == ['scene:g2']
    BlobStore(store).erase_scope('scene:g1', 'erase-test')                 # run again after a stop: the same
    assert artifact_records.get(store, shared)['shared_scopes'] == ['scene:g2']


def test_her_review_lists_a_refusal_by_the_table_with_its_row_and_column(home, tmp_path):
    store = home
    path = tmp_path / 'p.png'
    path.write_bytes(PNG)
    outside = turn(store, 'g1', 'A', 'r1')
    with pytest.raises(Exception):
        vision.read_image_for_task(store, None, where('g1'), store.config, {'ref': str(path)}, look=False,
                                   origin='outside', by={'turn': outside['_id'], 'call': 'c1', 'scope': 'scene:g1'})
    task = store.put('tasks', {'_id': 'task-r', 'request_key': 'task-r', 'scene_id': LOCAL, 'requester_id': OWNER,
                               'scope_key': 'scene:' + LOCAL, 'title': '造的', 'origin': 'home_from_outside'})
    access.record(store, {'task': task['_id'], 'scope': task['scope_key']}, 'home_from_outside', 'commands', 'sandbox_run')
    own_files.refuse_send(store, {'turn': outside['_id'], 'scope': 'scene:g1'}, 'outside', 'send_own', 'speak')
    seen = guard.review(store, PERSONA, '2000-01-01T00:00:00+00:00', '2999-01-01T00:00:00+00:00')['items']
    assert [item['kind'] for item in seen] == ['这里不许：把这个文件发到这里（外面）', '这里不许：跑命令（外面托、家里办）',
                                              '这里不许：盘上的路径（外面）']
    assert seen[1]['tried']['task'] == '造的' and all(item['where'] for item in seen)
