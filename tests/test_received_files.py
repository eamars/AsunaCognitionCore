"""ADR-102 section 5: a file someone sent her is stored in its own kind, its bytes live 3 days from the last fetch or
let_go, a kept one keeps them within 20 MiB or 50 files, and a keep over that is refused in words she can act on."""
from datetime import datetime, timedelta, timezone

import pytest

from asuna import local_time, media_life, received_files as rf
from asuna.blobs import BlobStore
from asuna.state import Denied

MIB = 1024 * 1024


def scopes(store):
    rows = list(store.db.scenes.find({}, {'_id': 1, 'scope_key': 1}).sort('_id', 1))
    return rows[0], rows[1]


def a_file(store, scope, n, body=None, **origin):
    origin = {'name': 'notes-%d.txt' % n, 'sender': 'a sender', **origin}
    return rf.stash(store, body or ('line %d\n' % n).encode(), scope, message_id='in-ep-%d' % n, index=0,
                    **origin)['artifact_id']


def row(store, artifact_id):
    return store.db.artifacts.find_one({'_id': artifact_id})


def ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


# ── the cycle ───────────────────────────────────────────────────────
def test_a_received_file_is_gone_after_3_days_and_its_row_stays(store):
    """The pin against a prefix missing from POLICY: a source not listed reads as a record and would be kept for good."""
    here, _ = scopes(store)
    old, young = a_file(store, here['scope_key'], 1), a_file(store, here['scope_key'], 2)
    assert rf.KEEP_DAYS == 3 and media_life.life(row(store, old)) == media_life.RECEIVED
    store.db.artifacts.update_one({'_id': old}, {'$set': {'days_from': ago(days=3, minutes=1)}})
    store.db.artifacts.update_one({'_id': young}, {'$set': {'days_from': ago(days=2, hours=23)}})
    removed = media_life.sweep(store)
    gone = row(store, old)
    assert gone['storage'] == 'removed' and gone['bytes_removed_at'] and 'gridfs_id' not in gone
    assert gone['name'] == 'notes-1.txt' and gone['source_ids'] == ['received-file:in-ep-1:0'], 'the origin stays'
    assert row(store, young)['storage'] == 'gridfs'
    assert removed['received'] == 1 and removed['files'] == 0 and removed['bytes'] == len(b'line 1\n')
    assert store.db['artifact_blobs.files'].count_documents({'filename': old}) == 0


def test_a_kept_file_keeps_its_bytes_and_let_go_gives_it_3_days_from_then(store):
    here, _ = scopes(store)
    reach = [here['scope_key']]
    file = a_file(store, here['scope_key'], 1)
    rf.keep(store, file, 'the setup notes', reach)
    store.db.artifacts.update_one({'_id': file}, {'$set': {'days_from': ago(days=30), 'created_at': ago(days=30)}})
    media_life.sweep(store)
    assert row(store, file)['storage'] == 'gridfs', 'a kept file is not removed whatever its age'
    moment = datetime.now(timezone.utc)
    rf.let_go(store, file, reach, moment=moment.isoformat())
    assert 'kept_at' not in row(store, file)
    media_life.sweep(store, moment + timedelta(days=2, hours=23))
    assert row(store, file)['storage'] == 'gridfs'
    media_life.sweep(store, moment + timedelta(days=3, minutes=1))
    assert row(store, file)['storage'] == 'removed'


def test_a_row_whose_time_cannot_be_read_is_kept_and_counted(store):
    here, _ = scopes(store)
    missing, not_a_time = a_file(store, here['scope_key'], 1), a_file(store, here['scope_key'], 2)
    store.db.artifacts.update_one({'_id': missing}, {'$unset': {'days_from': '', 'created_at': ''}})
    store.db.artifacts.update_one({'_id': not_a_time}, {'$set': {'days_from': 'a while ago'}})
    removed = media_life.sweep(store, datetime.now(timezone.utc) + timedelta(days=30))
    assert row(store, missing)['storage'] == 'gridfs' and row(store, not_a_time)['storage'] == 'gridfs'
    assert removed['undated'] == 2 and removed['received'] == 0


def test_the_same_bytes_are_stored_once_in_their_own_kind_and_never_as_hers(store):
    """Posted again, the same bytes are the row already stored, its 3 days counted from this fetch; equal to a file of
    hers, they are two rows of two kinds, so neither comes back as the other."""
    here, _ = scopes(store)
    first = a_file(store, here['scope_key'], 1, body=b'same text\n')
    store.db.artifacts.update_one({'_id': first}, {'$set': {'days_from': ago(days=2)}})
    again = a_file(store, here['scope_key'], 2, body=b'same text\n')
    assert again == first and row(store, first)['days_from'] > ago(minutes=1)
    assert row(store, first)['source_ids'] == ['received-file:in-ep-1:0'], 'the first origin is the row\'s for good'
    hers = BlobStore(store).put_once(b'same text\n', here['scope_key'], 'file', source_ids=['task-file:t:a.txt'])
    assert hers['artifact_id'] != first and not hers.get('deduplicated')
    assert a_file(store, here['scope_key'], 3, body=b'same text\n') == first


# ── keeping ─────────────────────────────────────────────────────────
def test_keeping_and_listing_stay_inside_the_fence(store):
    here, there = scopes(store)
    mine, theirs = a_file(store, here['scope_key'], 1), a_file(store, there['scope_key'], 2)
    with pytest.raises(Denied, match='RECEIVED_FILE_NOT_FOUND'):
        rf.keep(store, theirs, 'why', [here['scope_key']])
    rf.keep(store, theirs, 'theirs', [there['scope_key']])
    note = rf.keep(store, mine, 'mine', [here['scope_key']])['note']
    assert note.startswith('留下了') and '现在留着 2 个' in note
    listing = rf.kept(store, [here['scope_key']], here['_id'])
    assert [entry['name'] for entry in listing['kept']] == ['notes-1.txt'] and listing['kept'][0]['why'] == 'mine'
    assert listing['elsewhere'] == rf.OTHERS_ELSEWHERE % 1 and 'notes-2' not in str(listing)
    home = rf.kept(store, [here['scope_key'], there['scope_key']], here['_id'])
    assert [entry['name'] for entry in home['kept']] == ['notes-1.txt', 'notes-2.txt'] and 'elsewhere' not in home


def test_a_keep_after_the_bytes_expired_says_when_and_what_to_do(store):
    here, _ = scopes(store)
    file = a_file(store, here['scope_key'], 1)
    store.db.artifacts.update_one({'_id': file}, {'$set': {'days_from': ago(days=4)}})
    media_life.sweep(store)
    with pytest.raises(Denied, match='RECEIVED_FILE_BYTES_GONE') as refused:
        rf.keep(store, file, 'why', [here['scope_key']])
    assert '先 read 一次' in str(refused.value)
    assert 'kept_at' not in row(store, file)


def test_the_quota_20_mib_comes_before_50_files_and_the_refusal_names_three_never_the_list(store):
    """Twenty kept files of 1 MiB fill 20 MiB exactly; one byte more is refused with the total and the three files this
    call can let go that were read least recently, the files kept elsewhere counted, never named."""
    here, there = scopes(store)
    reach = [here['scope_key']]
    for n in range(20):
        scope = there['scope_key'] if n < 2 else here['scope_key']
        file = a_file(store, scope, n)
        rf.keep(store, file, 'why %d' % n, [scope])
        store.db.artifacts.update_one({'_id': file}, {'$set': {'size': MIB, 'last_read_at': ago(days=20 - n)}})
    one_more = a_file(store, here['scope_key'], 99)
    with pytest.raises(Denied, match='RECEIVED_FILE_OVER_QUOTA') as refused:
        rf.keep(store, one_more, 'why', reach)
    words = str(refused.value)
    assert '已经留着 20 个文件，共 20.0 MB' in words and '加上这个（%d 字节）' % len(b'line 99\n') in words
    named = [n for n in range(20) if '「notes-%d.txt」' % n in words]
    assert named == [2, 3, 4], 'the three read least recently that can be let go from here'
    assert rf.OTHERS_ELSEWHERE % 2 in words and 'notes-0' not in words and 'notes-1.txt' not in words
    assert 'kept_at' not in row(store, one_more)
    rf.let_go(store, store.db.artifacts.find_one({'name': 'notes-2.txt'})['_id'], reach)
    assert rf.keep(store, one_more, 'why', reach)['kept']


def test_the_51st_small_file_is_refused_by_count(store):
    here, _ = scopes(store)
    reach = [here['scope_key']]
    for n in range(rf.QUOTA_FILES):
        rf.keep(store, a_file(store, here['scope_key'], n), '', reach)
    with pytest.raises(Denied, match='已经留着 50 个文件'):
        rf.keep(store, a_file(store, here['scope_key'], 50), '', reach)


def test_with_nothing_kept_here_the_refusal_names_no_file(store):
    here, there = scopes(store)
    for n in range(rf.QUOTA_FILES):
        rf.keep(store, a_file(store, there['scope_key'], n), '', [there['scope_key']])
    with pytest.raises(Denied) as refused:
        rf.keep(store, a_file(store, here['scope_key'], 50), '', [here['scope_key']])
    assert str(refused.value).endswith(rf.NONE_HERE) and 'notes-' not in str(refused.value)


def test_let_go_says_how_long_the_bytes_stay_and_how_the_ref_is_found(store):
    here, _ = scopes(store)
    reach = [here['scope_key']]
    moment = datetime.now(timezone.utc)
    zone = local_time.zone_of(store, here['_id'])
    recent = a_file(store, here['scope_key'], 1, message_at=(moment - timedelta(days=1)).isoformat())
    old = a_file(store, here['scope_key'], 2, message_at=(moment - timedelta(days=9)).isoformat())
    undated = a_file(store, here['scope_key'], 3)
    for file in (recent, old, undated):
        rf.keep(store, file, '', reach)
    stay = rf.LET_GO % (3, local_time.stamp((moment + timedelta(days=3)).isoformat(), zone))
    assert rf.let_go(store, recent, reach, here['_id'], moment.isoformat())['note'] == stay + rf.REF_BY_MESSAGE % (
        local_time.stamp((moment + timedelta(days=6)).isoformat(), zone))
    assert rf.let_go(store, old, reach, here['_id'], moment.isoformat())['note'] == stay + rf.REF_LOST % 7
    assert rf.let_go(store, undated, reach, here['_id'], moment.isoformat())['note'] == \
        stay + rf.REF_BY_MESSAGE_UNDATED % 7
    assert rf.let_go(store, recent, reach)['note'] == rf.NOT_KEPT


def test_an_erased_kept_file_is_listed_with_the_sentence_until_she_lets_it_go(store):
    """ADR-105: the erasure takes kept files too; `kept` and `keep` say so, and let_go takes it off her list."""
    here, _ = scopes(store)
    reach = [here['scope_key']]
    file = a_file(store, here['scope_key'], 1)
    rf.keep(store, file, 'why', reach)
    BlobStore(store).erase_scope(here['scope_key'], 'erase-test')
    sentence = rf.erased_words(store, row(store, file), here['_id'])
    assert '这个文件存在过' in sentence
    [entry] = rf.kept(store, reach, here['_id'])['kept']
    assert entry['erased'] == sentence and entry['name'] == 'notes-1.txt'
    assert rf.kept(store, reach, here['_id'])['quota'].startswith('留着 0 个'), 'erased bytes count nothing'
    with pytest.raises(Denied, match='ARTIFACT_ERASED'):
        rf.keep(store, file, 'again', reach)
    assert rf.let_go(store, file, reach, here['_id'])['note'] == sentence + rf.LET_GO_ERASED
    assert rf.kept(store, reach, here['_id'])['kept'] == []


def test_marking_a_read_stays_inside_the_fence(store):
    """The time a quota refusal sorts by is written only inside the fence: another conversation's id leaves it as it
    was (Xiaoman's review of db192bdff79e)."""
    here, there = scopes(store)
    theirs = a_file(store, there['scope_key'], 1)
    rf.mark_read(store, theirs, [here['scope_key']], ago(days=1))
    assert 'last_read_at' not in row(store, theirs)
    rf.mark_read(store, theirs, [there['scope_key']], ago(days=1))
    assert row(store, theirs)['last_read_at']


def test_kept_counts_what_is_elsewhere_with_the_quota_ruler(store):
    """The two counts on one screen come from one set: a kept file erased elsewhere counts in neither."""
    here, there = scopes(store)
    gone, stays = a_file(store, there['scope_key'], 1), a_file(store, there['scope_key'], 2)
    mine = a_file(store, here['scope_key'], 3)
    for file, scope in ((gone, there), (stays, there), (mine, here)):
        rf.keep(store, file, '', [scope['scope_key']])
    store.db.artifacts.update_one({'_id': gone}, {'$set': {'storage': 'erased'}, '$unset': {'gridfs_id': ''}})
    listing = rf.kept(store, [here['scope_key']], here['_id'])
    assert listing['quota'].startswith('留着 2 个') and listing['elsewhere'] == rf.OTHERS_ELSEWHERE % 1
