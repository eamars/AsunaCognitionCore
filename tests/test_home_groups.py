"""A group the owner trusts as home (config `home_groups`, owner 2026-10-18: the owner, her older sister and her):
it reads as his own conversations do (the development tools only for his own words there, ADR-111), and it is still a group (her two
conditions): each speaker stays who they are, it is still a place errands go and notes come from, and its group
sections and tools stay. The scene id is matched whole, never by prefix (her condition)."""
from asuna import grants, notes, places, visibility

HOME_GROUP = 'qq:900000001:group:900000101'
LOOKALIKE = HOME_GROUP + '9'                       # the same prefix: must stay public


def config():
    return {'chat': {'scene_id': 'local-dm', 'person_id': 'local-user', 'workspace': {'root': 'w'}},
            'home_groups': [HOME_GROUP],
            'channels': {'qq': {'routes': {
                'family': {'scene_id': HOME_GROUP, 'target': {'type': 'group', 'id': '900000101'}},
                'other': {'scene_id': LOOKALIKE, 'target': {'type': 'group', 'id': '9000001019'}}}}}}


def test_every_speaker_in_a_home_group_is_at_home_and_a_lookalike_is_not():
    cfg = config()
    for person in ('qq:900000002', 'qq:900000003'):          # the owner's account and her sister's: themselves
        assert visibility.session_class(cfg, None, {'_id': HOME_GROUP, 'kind': 'group'}, person) == visibility.OWNER_PRIVATE
    assert visibility.session_class(cfg, None, {'_id': LOOKALIKE, 'kind': 'group'}, 'qq:900000002') == visibility.PUBLIC
    assert visibility.session_class({**cfg, 'home_groups': []}, None, {'_id': HOME_GROUP, 'kind': 'group'},
                                    'qq:900000002') == visibility.PUBLIC


def test_a_home_group_is_still_a_group():
    cfg = config()
    scene = {'_id': HOME_GROUP, 'kind': 'group'}
    assert visibility.place(cfg, None, scene, 'qq:900000002') == 'group'      # its group sections and tools stay
    assert visibility.place_of(cfg, {'_id': 'local-dm', 'kind': 'dm'}, visibility.OWNER_PRIVATE) == 'home'
    assert HOME_GROUP in [sid for sid, _, _ in places.errand_targets(cfg)]    # errands still go there
    assert HOME_GROUP not in notes.owner_chats(cfg)                           # it is not one of his private chats


def test_work_can_be_handed_over_in_a_home_group_with_the_owners_workspace():
    cfg = config()
    assert grants.conversation_workspace(cfg, HOME_GROUP)
    assert grants.workspace_grant(cfg, HOME_GROUP, 'qq:900000003') == cfg['chat']
    assert not grants.conversation_workspace(cfg, LOOKALIKE)
