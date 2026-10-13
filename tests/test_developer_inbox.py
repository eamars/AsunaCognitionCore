"""The program's notes to the developer agent: kept, read and marked by the developer, recorded without their text.
Her own questions and reports to the developer are `ask` (test_questions.py)."""
from asuna import developer_inbox, role_tools, visibility


def ep(store, cls, kind='external'):
    if not store.db.scenes.find_one({'_id': 'dm-x'}):
        store.put('scenes', {'_id': 'dm-x', 'kind': 'dm', 'scope_key': 'scene:dm-x', 'policy_epoch': 1, 'members': ['A']})
    return {'_id': 'ep-1', 'scene_id': 'dm-x', 'episode_kind': kind, 'persona': 'demo',
            'manifest': {'session_class': cls}, 'context': {}}


def test_her_old_tool_is_not_listed_anywhere(store):
    assert 'message_developer' not in role_tools.exposed(store, ep(store, visibility.OWNER_PRIVATE))
    assert 'message_developer' not in role_tools.TOOLS


def test_a_program_note_is_kept_once_read_and_marked(store):
    source = {'by': 'program', 'task_id': 't1'}
    first = developer_inbox.leave(store, 'demo', 'note', '[程序] 交不回', key=['t1'], source=source)
    assert developer_inbox.leave(store, 'demo', 'note', '[程序] 交不回', key=['t1'], source=source) == first
    assert [row['_id'] for row in developer_inbox.unread(store)] == [first['_id']]
    developer_inbox.mark(store, first['_id'], 'answered')
    assert developer_inbox.unread(store) == []
    audit = store.db.audit_events.find_one({'type': 'developer.message'})
    assert audit and 'text' not in audit['payload']
