"""Her messages to the developer agent (owner 2026-10-08): left from home turns only, limited per day, and what
came of them shown back to her in words."""
import pytest

from asuna import developer_inbox, role_tools, visibility


def ep(store, cls, kind='external'):
    if not store.db.scenes.find_one({'_id': 'dm-x'}):
        store.put('scenes', {'_id': 'dm-x', 'kind': 'dm', 'scope_key': 'scene:dm-x', 'policy_epoch': 1, 'members': ['A']})
    return {'_id': 'ep-1', 'scene_id': 'dm-x', 'episode_kind': kind, 'persona': 'demo',
            'manifest': {'session_class': cls}, 'context': {}}


def test_the_tool_exists_only_at_home(store):
    assert 'message_developer' in role_tools.exposed(store, ep(store, visibility.OWNER_PRIVATE))
    assert 'message_developer' in role_tools.exposed(store, ep(store, visibility.OWNER_PRIVATE, 'self_development'))
    assert 'message_developer' not in role_tools.exposed(store, ep(store, visibility.PUBLIC))


def test_a_message_is_kept_counted_and_shown_back(store):
    source = {'scene_id': 'dm-x', 'episode_id': 'ep-1', 'turn': 'external'}
    first = developer_inbox.leave(store, 'demo', 'wake', '入站断了一段', key=['ep-1', 'c1'], source=source)
    assert developer_inbox.leave(store, 'demo', 'wake', '入站断了一段', key=['ep-1', 'c1'], source=source) == first
    for n in range(2, 4):
        developer_inbox.leave(store, 'demo', 'wake', 'x', key=['ep-1', 'c%d' % n], source=source)
    with pytest.raises(ValueError, match='DEVELOPER_MESSAGE_LIMIT: 24 小时内的 wake 已经 3 条（上限 3）；不急的改用 level=note'):
        developer_inbox.leave(store, 'demo', 'wake', 'x', key=['ep-1', 'c9'], source=source)
    developer_inbox.leave(store, 'demo', 'note', '验收报告', key=['ep-1', 'n1'], source=source)
    assert [row['_id'] for row in developer_inbox.unread(store, 'wake')][0] == first['_id']
    developer_inbox.mark(store, first['_id'], 'answered')
    items = developer_inbox.block(store, 'demo')['items']
    assert items[0]['level'] == 'note' and items[0]['state'] == '还没看'
    assert any(item['state'] == '回了（回话在本机聊天里）' for item in items)
    audit = store.db.audit_events.find_one({'type': 'developer.message'})
    assert audit and 'text' not in audit['payload']
