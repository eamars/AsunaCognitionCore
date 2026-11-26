"""ADR-120 landing 7 (§6), on ADR-135's fixture world in memory with her real coordinator and the stub classifier lane:
when a crossing the classifier judges carries stored pictures or files, its question gains one program line,
「附带：N 张图、M 个文件」, counts by kind only (a kind with none left out, no line when nothing rides along), counted from
the items the crossing carries: an errand's picture or file, the pictures and files a result's task offered. A note
and an idea carry text only. Text only is asked as before: the same question, one request per crossing."""
from asuna import classifier, places
from asuna.blobs import BlobStore
from asuna.records import artifacts as artifact_records
from asuna.records import tasks as task_records
from test_adr135_classifier import BRIEF, events, home_turn, judged, note_row  # noqa: F401  (judged: a fixture)
from test_adr135_known import F, ask, call, room  # noqa: F401  (room: a fixture)
from test_own_files import PNG, picture
from test_whose import LOCAL, OWNER, coordinator, home  # noqa: F401  (fixtures)

NAME = 'zao-secret-name.txt'


def a_file(store, scope):
    return BlobStore(store).put(b'zao de\n', scope, 'file', media_type='text/plain',
                                source_ids=['task-file:t-x:' + NAME], fields={'name': NAME})['artifact_id']


def offered(store, task, artifact_id, n):
    """A done offer_file call of the task, as the broker records it."""
    artifact_records.save(store, {'_id': 'tool-%s-%d' % (task['_id'], n), 'scope_key': task['scope_key'],
                                  'task_id': task['_id'], 'intent_revision': 1, 'tool': 'offer_file',
                                  'args': {'artifact_id': artifact_id}, 'input_hash': 'h%d' % n, 'state': 'DONE',
                                  'result': {'offered': True, 'artifact_id': artifact_id}})


def lines(asked):
    return asked['text'].splitlines()


def test_the_line_says_counts_by_kind_and_leaves_a_zero_out():
    text = '造的：给你看'
    two_and_one = classifier.question('note_out', text, carried={'image': 2, 'file': 1})
    assert two_and_one.splitlines()[:2] == ['这段文字是：在家里写的、送到外面的便条', '附带：2 张图、1 个文件']
    assert classifier.question('errand', text, carried={'image': 2}).splitlines()[1] == '附带：2 张图'
    assert classifier.question('errand', text, carried={'file': 1, 'image': 0}).splitlines()[1] == '附带：1 个文件'
    # Nothing rides along: no line, the question as it was before this landing, byte for byte.
    assert classifier.question('result', text) == classifier.question('result', text, carried={}) == \
        '这段文字是：一件事的结果，要在外面给人看\n\n文字：\n' + text
    # Beside the reminder: what rides along first, then the program's reminder.
    both = classifier.question('errand', text, '程序的提醒：x', {'file': 1}).splitlines()
    assert both[1:3] == ['附带：1 个文件', '程序的提醒：x']


def test_an_errand_s_picture_or_file_rides_along_counted_never_named(judged):
    store = judged.store
    drawn, notes = picture(store, 'scene:' + LOCAL), a_file(store, 'scene:' + LOCAL)
    sticker = BlobStore(store).put(PNG, 'global-safe', 'image', media_type='image/png')['artifact_id']
    request, turns = '造的：替我去问一句', {}
    for key, artifact_id in (('pic', drawn), ('file', notes), ('sticker', sticker), ('text', None)):
        args = {'place': places.place_id('g1'), 'request': request,
                **({'artifact_id': ' %s ' % artifact_id} if artifact_id else {})}
        ep = home_turn(store, LOCAL, OWNER, 'e-' + key)
        turns[key] = ep['_id']
        classifier.after_call(judged.tools, ep, 'errand', args, {'going_to': 'g1'})
    pic, file, sticker_asked, text_only = judged.lane.asked          # one request per errand, as before
    assert lines(pic)[1] == '附带：1 张图' and lines(file)[1] == '附带：1 个文件'
    assert sticker_asked['text'] == text_only['text'] == classifier.question('errand', request)    # stickers: everyone's
    for asked in (pic, file):
        assert drawn not in asked['text'] and notes not in asked['text'] and NAME not in asked['text']
        assert '/' not in lines(asked)[1] and 'blob-' not in lines(asked)[1]
    assert pic['operation'] != file['operation']                    # one question, one session and receipt
    recorded = {row['episode']: row.get('carried') for row in events(store, 'classifier.asked')}
    assert recorded == {turns['pic']: {'image': 1}, turns['file']: {'file': 1}, turns['sticker']: None,
                        turns['text']: None}


def test_a_result_carries_what_its_task_offered(judged):
    store = judged.store
    task = task_records.get(store, call(judged, ask(store, F, 'rc'), 'delegate', BRIEF)[0]['task'])
    for n, artifact_id in enumerate((picture(store, task['scope_key']), picture(store, task['scope_key']),
                                     a_file(store, task['scope_key']))):
        offered(store, task, artifact_id, n)
    offered(store, task, artifact_id, 3)                            # offered twice: one file
    classifier.after_result(store, task, ask(store, F, 'rc2'), {'text': '造的：画好了，也写好了'})
    bare = task_records.get(store, call(judged, ask(store, F, 'rt'), 'delegate', BRIEF)[0]['task'])
    classifier.after_result(store, bare, ask(store, F, 'rt2'), {'text': '造的：查到了'})
    carried, text_only = judged.lane.asked
    assert lines(carried)[1] == '附带：2 张图、1 个文件' and NAME not in carried['text']
    assert text_only['text'] == classifier.question('result', '造的：查到了')
    recorded = {row['ref']['task']: row.get('carried') for row in events(store, 'classifier.asked')}
    assert recorded == {task['_id']: {'image': 2, 'file': 1}, bare['_id']: None}


def test_a_note_carries_text_only(judged):
    store = judged.store
    at_home = home_turn(store, LOCAL, OWNER, 'nt')
    classifier.after_call(judged.tools, at_home, 'note', {'text': 'x'},
                          note_row(store, 'note-nt', LOCAL, 'g1', 'group', '造的：家里写出去的'))
    [asked] = judged.lane.asked
    assert asked['text'] == classifier.question('note_out', '造的：家里写出去的') and '附带' not in asked['text']
