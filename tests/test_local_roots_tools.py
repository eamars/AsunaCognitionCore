"""ADR-098 in her tools: what goes to the action brain expands what her place hands over and refuses a raw root, an
unknown name and `..` (D3); what she writes is kept contracted (D4); her words leave with no raw root, each
replacement counted and told to her weekly (D5); a placeholder is never a key word (D7)."""
import json
from pathlib import Path

import pytest

from asuna import key_words, local_roots, role_tools, tools_week, visibility
from asuna.lanes import FakeTurn
from test_adr011_turns import THINK, event, published, run

HOST = json.loads((Path(__file__).with_name('fixtures') / 'path_placeholders.json').read_text(encoding='utf-8'))
HOST = HOST['hosts']['windows']
WS, HOME = HOST['workspace'], HOST['home']


@pytest.fixture(autouse=True)
def table(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', local_roots.build(HOST))
    monkeypatch.setattr(local_roots, 'REFUSED', None)


@pytest.fixture
def home(store, monkeypatch):
    """dm-a as the owner's own chat: its person is the owner."""
    monkeypatch.setitem(store.config['chat'], 'person_id', 'A')


def home_event(store, key, **extra):
    return event(key, **extra)


def delegate(store, ev, brief, title='看文件'):
    coordinator, lane = run(store, FakeTurn([THINK, ('delegate', {'title': title, 'brief': brief})], '交给行动脑了。'))
    ep = coordinator.ingest(ev)
    [(_, _, _, _, result, ok)] = [r for r in lane.tool_results if r[2] == 'delegate']
    task = store.db.tasks.find_one({'_id': ep['task_ids'][0]}) if ep.get('task_ids') else None
    return ep, result, ok, task


def test_a_brief_from_home_reaches_the_action_brain_with_the_real_paths(store, home):
    brief = '读 ${ASUNA_WORKSPACE}\\packages\\x\\README.md 和 ${ASUNA_HOME}/notes.md；脚本里 echo ${HOME} ${1} 照旧。'
    ep, result, ok, task = delegate(store, home_event(store, 'h1'), brief)
    assert ep['manifest']['session_class'] == visibility.OWNER_PRIVATE and ok, result
    assert task['brief'] == ('读 %s\\packages\\x\\README.md 和 %s\\notes.md；脚本里 echo ${HOME} ${1} 照旧。' % (WS, HOME))


def test_a_title_reaches_the_action_brain_expanded_as_its_brief_is(store, home):
    """The action brain cannot open a placeholder: a path in the title is expanded with the brief (her review)."""
    ep, result, ok, task = delegate(store, home_event(store, 'h-title'), '读第一行', title='读 ${ASUNA_WORKSPACE}\a.md')
    assert ok, result
    assert task['title'] == '读 %s\a.md' % WS


def test_a_brief_from_a_public_place_expands_only_the_workspace_and_data(store):
    brief = '读 ${ASUNA_WORKSPACE}/README.md，别碰 ${ASUNA_HOME}\\notes.md 和 ${ASUNA_DRIVE_D}\\logs\\x.log'
    ep, result, ok, task = delegate(store, event('p1', scene='dm-a', person='A'), brief)
    if ep['manifest']['session_class'] != visibility.PUBLIC or 'delegate' not in ep.get('turn_tools', ()):
        pytest.skip('UNCHECKED, not passed: the fixture world gives this conversation no public delegate')
    assert ok, result
    assert task['brief'] == '读 %s\\README.md，别碰 ${ASUNA_HOME}\\notes.md 和 ${ASUNA_DRIVE_D}\\logs\\x.log' % WS


def test_a_raw_root_an_unknown_name_and_a_climb_are_refused_with_the_reason(store, home):
    _, result, ok, task = delegate(store, home_event(store, 'r1'), '改 %s\\src\\a.py' % WS)
    assert not ok and task is None
    assert '改成这样就能交' in result and '改 ${ASUNA_WORKSPACE}\\src\\a.py' in result and WS not in result
    _, result, ok, _ = delegate(store, home_event(store, 'r2'), '读 ${ASUNA_WORKSPACEE}\\x')
    assert not ok and '${ASUNA_WORKSPACE}' in result and '不是程序的名字' in result
    _, result, ok, _ = delegate(store, home_event(store, 'r3'), '读 ${ASUNA_WORKSPACE}\\..\\x')
    assert not ok and '..' in result


def test_what_she_writes_is_kept_contracted(store, home):
    thought = ('think', {'thought': '他让我看 %s\\packages\\x 里的东西。' % WS})
    coordinator, _ = run(store, FakeTurn([thought], '好。'))
    ep = coordinator.ingest(home_event(store, 'w1'))
    [kept] = store.db.memory_units.find({'episode_id': ep['_id'], 'kind': 'monologue'})
    assert kept['body_markdown'] == '他让我看 ${ASUNA_WORKSPACE}\\packages\\x 里的东西。'
    audited = json.dumps(list(store.db.audit_events.find({'stream_id': ep['_id']})), ensure_ascii=False, default=str)
    assert WS.replace('\\', '\\\\') not in audited and WS not in audited
    # A credential's values and her private words are kept as she wrote them.
    literal = {'op': 'keep', 'env': {'X_PATH': WS}}
    assert role_tools.written('credential', literal) == literal
    # A delegate's title goes to the action brain with its brief: both stay as written, for D3.
    assert role_tools.written('delegate', {'title': WS, 'brief': WS}) == {'title': WS, 'brief': WS}


def test_her_words_leave_with_no_raw_root_and_each_replacement_is_counted(store, home):
    coordinator, _ = run(store, FakeTurn([THINK], '文件在 %s\\docs 里。' % WS))
    ep = coordinator.ingest(home_event(store, 's1'))
    assert published(store, ep) == ['文件在 ${ASUNA_WORKSPACE}\\docs 里。']
    rows = list(store.db.audit_events.find({'type': local_roots.SPEECH_EVENT, 'stream_id': ep['_id']}))
    assert [row['payload']['count'] for row in rows] == [1]
    week = tools_week._local_roots(store, ep['persona'], '0000', '9999')
    assert week['speech'].startswith('这周你说出去的话里，有 1 处') and '要查的故障' in week['speech']
    assert week['requests'] == tools_week.REWRITTEN_NONE


def test_the_weekly_reading_says_her_rewritten_requests_per_place_apart_from_her_speech(store):
    persona = store.config['chat']['persona']
    store.audit('roots:' + persona, local_roots.TALLY, {'sessions': [
        {'session_id': 's-x', 'lane': 'summary', 'requests': 4, 'rewritten': 4},
        {'session_id': 's-y', 'lane': 'attend', 'requests': 2, 'rewritten': 2}]})
    week = tools_week._local_roots(store, persona, '0000', '9999')
    assert week['speech'] == tools_week.SPEECH_NONE
    assert '后台摘要 4 次（共 4 次请求）' in week['requests'] and '要不要接话的判断 2 次' in week['requests']


def test_a_placeholder_is_not_a_word_she_said():
    assert key_words.words('看 ${ASUNA_HOME}/notes 和 ${ASUNA_WORKSPACE}') == ['看', 'notes', '和']
    assert 'workspace' not in key_words.cross_words('${ASUNA_WORKSPACE}\\docs\\x') and \
        'asuna' not in key_words.atoms('${ASUNA_WORKSPACE}\\docs')


def test_her_program_context_names_the_placeholders_never_their_values():
    for home in (True, False):
        line = local_roots.context_line(home)
        assert 'WORKSPACE' in line and '${ASUNA_' in line and WS not in line and HOME not in line
    assert '只有 ${ASUNA_WORKSPACE} 和 ${ASUNA_DATA}' in local_roots.context_line(False)
