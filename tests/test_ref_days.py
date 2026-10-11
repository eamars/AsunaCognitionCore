"""A picture ref she copied stays readable for REF_DAYS days, though the listing a turn shows is the newest few;
the fence is the same: another conversation's ref is never found."""
from datetime import datetime, timedelta, timezone

from asuna.vision import REF_DAYS, attachment_by_ref, ref_of


def picture(store, scene_id, seq, days):
    scene = store.db.scenes.find_one({'_id': scene_id})
    message_id = 'pic-%s-%d' % (scene_id, seq)
    store.db.messages.insert_one({
        '_id': message_id, 'schema_version': 1, 'scene_id': scene_id, 'scene_seq': 10_000 + seq,
        'policy_epoch': scene['policy_epoch'], 'direction': 'inbound',
        'received_at': (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
        'event': {'event_id': message_id, 'channel': {'id': 'qq'}, 'raw': {'asuna_media': {
            'items': [{'type': 'image', 'url': 'https://multimedia.nt.qq.com.cn/download?appid=1407&rkey=K',
                       'placeholder': '[图片]'}]}}}})
    return ref_of(message_id, 0)


def test_an_older_picture_is_found_by_its_ref_within_the_days_and_never_across_the_fence(store):
    scene = store.db.scenes.find_one({'_id': 'dm-a'})
    task = {'scene_id': 'dm-a', 'scope_key': scene['scope_key'], 'policy_epoch': scene['policy_epoch']}
    three_days = picture(store, 'dm-a', 1, 3)
    too_old = picture(store, 'dm-a', 2, REF_DAYS + 1)
    for seq in range(3, 13):                              # ten newer pictures fill the listing
        picture(store, 'dm-a', seq, 0.01)
    elsewhere = picture(store, 'g1', 1, 1)
    entry, listing = attachment_by_ref(store, task, store.config, three_days)
    assert three_days not in [item['ref'] for item in listing['attachments']], 'not among the newest few'
    assert entry and entry['ref'] == three_days and entry['scene_id'] == 'dm-a'
    assert attachment_by_ref(store, task, store.config, too_old)[0] is None
    assert attachment_by_ref(store, task, store.config, elsewhere)[0] is None
