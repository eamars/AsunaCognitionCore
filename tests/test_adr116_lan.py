"""ADR-116: her home tasks reach the LAN; where it is decided (the fetch itself is tested in fetch.test.js)."""
def test_a_task_reaches_the_lan_where_sandbox_run_is_given_and_keeps_its_own_record(store):
    """ADR-116 D1: network by the delegating turn's session class, one source (the task's record)."""
    from asuna import visibility
    from asuna.coordinator import Coordinator
    coordinator = Coordinator(store, None)
    home = {'_id': 'ep-home', 'scene_id': 'local-dm', 'person_id': 'owner',
            'manifest': {'session_class': visibility.OWNER_PRIVATE}}
    group = {'_id': 'ep-group', 'scene_id': 'qq:group:1', 'person_id': 'someone',
             'manifest': {'session_class': visibility.PUBLIC}}
    assert coordinator._grants(home, None)[3] == 'any'
    assert coordinator._grants(group, None)[3] == 'public'
    assert coordinator._grants({**group, 'manifest': {'session_class': 'a class added later'}}, None)[3] == 'public'
