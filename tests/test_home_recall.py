"""At home her recall also reaches what she herself thought in her groups (owner 2026-10-12): her monologue there,
never the group's talk, each with the group's name and the time; a group turn's recall does not reach other groups."""




def test_where_speak_speaks_a_picture_is_offered_as_its_part():
    from asuna import outbound_media
    assert 'speak 的 picture' in outbound_media._offer_note({'_id': 'qq:1:group:2'})
    assert 'attach_image' in outbound_media._offer_note({'_id': 'dm-a'})
