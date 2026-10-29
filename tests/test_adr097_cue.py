"""ADR-097 D2: a group turn whose line has a word her other groups know brings one line of presence: the word, how
often it was said elsewhere, the latest day and that place's kind, and that recall finds it. Never more than one, never
twice within the repeat time, never on a templated line, a word already in view or one this place says itself."""
import json

import pytest

from asuna import crossing, memory_pilot, memory_tiers
from asuna.context import ContextBuilder
from asuna.documents import DocumentStore
from asuna.group_admin import notes_slug
from asuna.memory_tiers import AT_HAND, Tiers
from test_adr009_p2 import owner
from test_adr097_crossing import fresh_words, line, rules  # noqa: F401 (fresh_words: autouse)
from test_engineering_m1 import event
from test_memory_pilot import Route
from test_memory_tiers_delivery import Retrieval, write


@pytest.fixture
def turn(store, monkeypatch, tmp_path):
    monkeypatch.setattr(memory_tiers, 'ENABLED', True)
    monkeypatch.setattr(crossing, 'PATH', tmp_path / 'memory-crossing.json')
    owner(store)
    for n in range(5):
        line(store, n + 1, '破甲成功了 %d' % n, n == 0)
    builder = ContextBuilder(store, Retrieval())
    builder.pilot = memory_pilot.Pilot(store, 'P1', Route())
    builder.pilot.sync()

    def prepare(key, text, scene='g1'):
        return builder.prepare(event(key, scene=scene, text=text), 'P1')[1]
    return store, builder, prepare, tmp_path / 'memory-crossing.json'


def cues(context):
    return [m['cue'] for m in context['memories'] if m.get('kind') == 'cue']


def test_a_word_said_five_times_elsewhere_brings_one_line_and_a_fire_row(turn):
    store, builder, prepare, path = turn
    [cue] = cues(prepare('e-1', '破甲是什么意思'))
    assert cue.startswith('破甲：这个词你在别的群见过 5 次，最近 ') and cue.endswith('；recall 写上它能找到')
    assert '，' not in cue.split('最近 ')[1].split('；')[0], 'no kind set: none shown'
    row = store.db[crossing.FIRES].find_one({'kind': 'cue'})
    assert (row['scene_id'], row['word'], row['lines']) == ('g1', '破甲', 5) and row['episode_id']
    assert not cues(prepare('e-2', '破甲又来了')), 'once per word within the repeat time'
    store.db[crossing.FIRES].update_many({}, {'$set': {'at': '2000-01-01T00:00:00+00:00'}})
    assert cues(prepare('e-3', '破甲又来了')), 'after it, again'


def test_too_few_lines_or_a_place_that_lets_nothing_out_gives_no_cue(turn):
    store, builder, prepare, path = turn
    rules(path, {'places': {'g2': 'never'}})
    assert not cues(prepare('e-1', '破甲是什么'))
    rules(path, {'seen_elsewhere': 6})
    assert not cues(prepare('e-2', '破甲是什么')), 'the number is the deployment\'s'
    rules(path, {'kinds': {'g2': '技术局'}})
    assert cues(prepare('e-3', '破甲是什么'))[0].split('；')[0].endswith('，技术局'), 'the kind, when set'


def test_no_cue_on_a_template_or_for_a_word_already_in_view(turn):
    store, builder, prepare, path = turn
    assert not cues(prepare('e-0', '破甲：一\n状态：好\n版本：3\n平台：x')), 'a status record'
    assert not cues(prepare('e-1', '那个很好用')), 'no word that may cross'
    from datetime import datetime, timezone
    line(store, 40, '破甲来了', False, scene='g1')
    store.db.messages.update_one({'_id': 'm-g1-40'}, {'$set': {'received_at': datetime.now(timezone.utc).isoformat()}})
    assert not cues(prepare('e-2', '破甲是什么')), 'in the lines this turn delivers'
    rules(path, {'cue_lines': 'new'})
    store.db[crossing.FIRES].update_one({'_id': 'seen:P1:g1'}, {'$set': {'seq': 40}}, upsert=True)
    assert not cues(prepare('e-3', '破甲是什么')), 'with cue_lines new: an earlier turn delivered it already'


def test_a_word_in_any_line_new_to_the_turn_brings_the_cue_and_the_mark_moves(turn):
    """The 23:19 case: the word was in a line before the one her turn came for, new to this turn."""
    store, builder, prepare, path = turn
    from datetime import datetime, timezone
    line(store, 40, '有人问破甲', False, scene='g1')
    store.db.messages.update_one({'_id': 'm-g1-40'}, {'$set': {'received_at': datetime.now(timezone.utc).isoformat()}})
    assert not cues(prepare('e-0', '在吗')), 'by default only the line the turn is for'
    store.db[crossing.FIRES].delete_many({'_id': 'seen:P1:g1'})
    rules(path, {'cue_lines': 'new'})
    store.db.messages.update_one({'_id': 'm-g1-40'}, {'$set': {'received_at': datetime.now(timezone.utc).isoformat()}})
    [cue] = cues(prepare('e-1', '在吗'))
    assert cue.startswith('破甲：'), 'with cue_lines new, every line new to the turn'
    assert store.db[crossing.FIRES].find_one({'kind': 'cue'})['line_seq'] == 40, 'the line the word was in'
    assert store.db[crossing.FIRES].find_one({'_id': 'seen:P1:g1'})['seq'] >= 40


def test_no_cue_for_a_word_this_place_says_itself(turn):
    store, builder, prepare, path = turn
    for n in range(3):
        line(store, 40 + n, '破甲来了', False, scene='g1')         # two days ago: out of view, inside the window
    Tiers(store, 'P1').rerate_all()                                  # the night recount
    assert not cues(prepare('e-1', '破甲是什么')), 'said here three times: its own memories cover it'
    rules(path, {'said_here': 3})
    Tiers(store, 'P1').rerate_all()
    assert cues(prepare('e-2', '破甲是什么')), "the number is the deployment's"


def test_her_own_note_on_the_word_comes_first_and_takes_its_place(turn):
    store, builder, prepare, path = turn
    docs = DocumentStore(store, 'P1')
    slug = notes_slug('g1')
    sid = write(docs, slug, '破甲', '绕过安全锁的意思')
    tiers = Tiers(store, 'P1')
    tiers.sync()
    tiers.store.db['memory_tiers'].update_one({'_id': tiers.item(slug, sid)['_id']}, {'$set': {'place': AT_HAND}})
    builder.pilot.sync()
    context = prepare('e-1', '破甲是什么')
    assert [m.get('kind') for m in context['memories'] if m.get('kind') in ('own_item', 'cue')] == ['own_item']
    assert json.dumps(context, ensure_ascii=False).count('这个词你在别的群见过') == 0


def test_what_came_back_is_counted_and_told_once_a_day_in_words(turn):
    store, builder, prepare, path = turn
    docs = DocumentStore(store, 'P1')
    slug = notes_slug('g1')
    sid = write(docs, slug, '破甲', '绕过安全锁的意思')
    tiers = Tiers(store, 'P1')
    tiers.sync()
    tiers.store.db['memory_tiers'].update_one({'_id': tiers.item(slug, sid)['_id']}, {'$set': {'place': AT_HAND}})
    builder.pilot.sync()
    told = prepare('e-1', '破甲是什么')['things_from_program']['came_back']
    row = store.db[crossing.FIRES].find_one({'kind': 'note'})
    assert (row['ref'], row['word'], row['by']) == ('doc:%s#%s' % (slug, sid), '破甲', 'word') and 'at' in row
    assert told.startswith('最近一天：你的笔记回来 一次（「破甲」一次）；别的群见过的词提醒 没有')
    assert 'came_back' not in prepare('e-2', '今天好')['things_from_program'], 'once a day here'


def test_a_recall_counts_its_lines_from_elsewhere_and_w6(turn):
    store, builder, prepare, path = turn
    from test_adr097_crossing import recall
    found = recall(store, builder, {'query': '破甲'})
    assert found['elsewhere']
    kinds = [row['kind'] for row in store.db[crossing.FIRES].find({'kind': {'$in': list(crossing.FIRE_KINDS)}})]
    assert kinds.count('elsewhere_hers') == 1 and kinds.count('w6') == 1, 'a line the turn itself had not brought'


def test_the_reading_counts_per_place_and_joins_the_compactions(turn):
    store, builder, prepare, path = turn
    from datetime import datetime, timedelta, timezone
    prepare('e-1', '破甲是什么')
    cue_row = store.db[crossing.FIRES].find_one({'kind': 'cue'})
    store.db.episodes.update_one({'_id': cue_row['episode_id']}, {'$set': {'native_session_id': 'session-1'},
                                 '$setOnInsert': {'schema_version': 1, 'scene_id': 'g1', 'episode_kind': 'external'}},
                                 upsert=True)
    at = datetime.fromisoformat(cue_row['at']).timestamp() * 1000
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    read = crossing.report(store, since, {'session-1': [at - 10 * 60000, at + 60000]})
    assert read['all']['cues'] == 1
    assert read['all']['since_compaction'] == {'fires': 1, 'no_compaction_before': 0, 'within_30_minutes': 1,
                                               'median_minutes': 10}, 'the last compaction before the cue'
    assert 'g1' not in json.dumps(read, ensure_ascii=False), 'places by number, never their ids'
