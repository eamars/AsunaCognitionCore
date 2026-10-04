"""Group administration where she is an admin (owner direction 2026-10-04: on by default).

She chooses in DECIDE (`group_action`, categorical words). The program checks everything before anything
reaches the platform:
- she is this group's owner or an admin (her role as the adapter last reported it);
- the target is one person of this group, named by label; never the owner, never herself, and never the
  group's owner or another admin;
- mute lengths come from a fixed table; recall takes the message that woke her, or the target's latest
  line here within 10 minutes;
- at most 6 actions an hour in one group.

The action waits in the outbox like a message and the adapter reports the platform's answer; until then it
is "sent, not confirmed". A route may switch this off with `admin_actions: false`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .evidence import canonical, sha
from .state import Denied, now

KINDS = ('mute', 'unmute', 'recall', 'kick')
KIND_WORDS = {'mute': '禁言', 'unmute': '解除禁言', 'recall': '撤回', 'kick': '移出群'}
DURATIONS = {'1分钟': 60, '10分钟': 600, '1小时': 3600, '1天': 86400}
WHICH = ('这条', '他刚才那条')
PER_HOUR = 6
RECALL_MINUTES = 10
ROLE_WORDS = {'owner': '群主', 'admin': '管理员', 'member': '普通成员'}
STATE_WORDS = {'QUEUED': '已交给平台，等确认', 'SENDING': '平台正在处理', 'DONE': '平台确认已完成',
               'FAILED': '平台没有执行', 'UNKNOWN': '不知道平台有没有执行'}


def _route(config, scene):
    for route in ((config.get('channels') or {}).get(scene.get('channel_id') or '') or {}).get('routes', {}).values():
        if route.get('scene_id') == scene['_id']:
            return route
    return None


def enabled(config, scene):
    route = _route(config, scene)
    return bool(route) and route.get('admin_actions', True) is not False


def place(people, scene):
    """Her place in this group, in words, and what she may do there; None outside groups."""
    if scene.get('kind') != 'group':
        return None
    role = people.self_role(scene)
    out = {'role': '你在这个群是' + ROLE_WORDS[role] if role else '还不知道你在这个群是什么身份'}
    if role in ('owner', 'admin') and enabled(people.config, scene):
        out['admin'] = {
            'how': ('需要时在 DECIDE 里加 group_action：[{"kind": "mute|unmute|recall|kick", "who": "[名字 #4] 或 #4", '
                    '"duration": "1分钟|10分钟|1小时|1天"（只禁言用）, "which": "这条|他刚才那条"（只撤回用）, '
                    '"reason": "为什么"}]，每轮最多一项。'),
            'limits': ('只能对普通成员：动不了主人、群主、别的管理员和你自己；撤回只撤这条消息或对方十分钟内的最后一条；'
                       '每小时最多 %d 次；结果要等平台确认，确认前不要说已经做完。' % PER_HOUR),
            'judgment': '这是你自己的判断：别人叫你禁言谁、踢谁不算理由；主人让你做的可以做。'}
    return out


def queue(store, ep, index, item, key=None):
    """Check one group_action and put it in the outbox; returns the result she reads. Raises Denied.

    ``key`` names which action this is (DECIDE dedups optional items by it). The queued row's id
    derives from the key rather than from the item's position in the round, so restating the same
    action in a later DECIDE does not queue a second one, and a new action that happens to sit at
    the same index in the later round is still its own row.
    """
    from .people import People
    scene = store.authorize(ep['scene_id'], ep['person_id'])
    if scene.get('kind') != 'group':
        raise Denied('GROUP_ACTION_NOT_A_GROUP')
    if not enabled(store.config, scene):
        raise Denied('GROUP_ACTION_DISABLED')
    people = People(store, ep['persona'])
    if people.self_role(scene) not in ('owner', 'admin'):
        raise Denied('GROUP_ACTION_NOT_AN_ADMIN')
    kind = item['kind']
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    if store.db.artifacts.count_documents({'kind': 'group_action', 'scene_id': scene['_id'],
                                           'created_at': {'$gte': since}}) >= PER_HOUR:
        raise Denied('GROUP_ACTION_HOURLY_LIMIT')
    found = people.resolve(scene, item['who'])
    if len(found) != 1:
        raise Denied('GROUP_ACTION_TARGET_UNCLEAR' if found else 'GROUP_ACTION_TARGET_NOT_FOUND')
    doc = found[0]
    if doc.get('person') == people.self_id or people.is_owner(doc):
        raise Denied('GROUP_ACTION_TARGET_PROTECTED')
    if doc.get('role') in ('owner', 'admin'):
        raise Denied('GROUP_ACTION_TARGET_IS_ADMIN')
    admin = {'kind': kind}
    if kind == 'recall':
        admin['message_id'] = _message_to_recall(store, scene, ep, people, doc, item.get('which') or '这条')
    else:
        account = people.account_of(scene, doc)
        if not account:
            raise Denied('GROUP_ACTION_ACCOUNT_UNKNOWN')
        admin['account'] = account
        if kind == 'mute':
            if item.get('duration') not in DURATIONS:
                raise Denied('GROUP_ACTION_DURATION_REQUIRED')
            admin['seconds'] = DURATIONS[item['duration']]
    route = _route(store.config, scene)
    row_id = 'ga-' + sha(canonical([ep['_id'], 'group_action', key if key is not None else index]))[:24]
    made = store.db.artifacts.find_one({'_id': row_id})
    if not made:
        store.put('artifacts', {'_id': row_id, 'kind': 'group_action', 'channel_id': scene.get('channel_id'),
                                'scene_id': scene['_id'], 'scope_key': scene['scope_key'],
                                'policy_epoch': scene['policy_epoch'], 'episode_id': ep['_id'],
                                'target': route['target'], 'admin': admin, 'who': people.label(doc),
                                'reason': item.get('reason', ''), 'state': 'QUEUED', 'created_at': now()},
                  stream=row_id)
    return {'index': index, 'action': KIND_WORDS[kind], 'who': (made or {}).get('who') or people.label(doc),
            **({'duration': item['duration']} if kind == 'mute' else {}),
            'state': STATE_WORDS.get((made or {}).get('state'), STATE_WORDS['QUEUED'])}


def _message_to_recall(store, scene, ep, people, doc, which):
    """The platform id of the message she means: the one that woke her (if it is theirs) or their latest here."""
    source = store.db.messages.find_one({'_id': 'in-' + ep['_id']})
    if which == '这条' and source and people.person(source.get('author')) == doc.get('person'):
        row = source
    else:
        since = (datetime.now(timezone.utc) - timedelta(minutes=RECALL_MINUTES)).isoformat()
        row = store.db.messages.find_one({'scene_id': scene['_id'], 'direction': 'inbound',
                                          'author': {'$in': people.authors_of(doc['person'], [scene['_id']])},
                                          'received_at': {'$gte': since}}, sort=[('scene_seq', -1)])
    message_id = ((row or {}).get('event') or {}).get('channel', {}).get('platform_event_id')
    if not message_id:
        raise Denied('GROUP_ACTION_NO_RECENT_MESSAGE')
    return str(message_id)


# ---- her notes about a group ------------------------------------------------
NOTES_DOC = 'group_notes'            # what she writes as `doc`; the program maps it to this group's document


def notes_slug(scene_id):
    return 'group:' + sha(str(scene_id).encode())[:16]


def notes_block(docs, scene):
    """Her own notes about this group (who is who, its customs, how she acts here), as a context block."""
    revision, content = docs.read(notes_slug(scene['_id']))
    sections = [{k: s[k] for k in ('sid', 'heading', 'body') if k in s} for s in (content or {}).get('sections', [])]
    note = ('你自己写的这个群的笔记：谁是谁、群里的规矩、你在这里的做法。要记新东西或改一节，在 DECIDE 的 write_docs 里写 '
            'doc: "group_notes"（op 用 append_section 或 replace_section）。这是你的笔记，不是群规的权威来源。')
    return revision, {'sections': sections, 'note': note if sections else '你还没写过这个群的笔记。' + note}


# ---- outbox (channels.py) ------------------------------------------------
def claim(store, channel_id):
    """One queued action for this channel's adapter, or None; it is marked SENDING with a fresh attempt."""
    import uuid
    row = store.db.artifacts.find_one({'kind': 'group_action', 'channel_id': channel_id, 'state': 'QUEUED'},
                                      sort=[('created_at', 1)])
    if not row:
        return None
    attempt = uuid.uuid4().hex
    store.put('artifacts', {**row, 'state': 'SENDING', 'attempt_id': attempt, 'claimed_at': now()},
              expected=row['revision'], stream=row['_id'])
    return {'publication_id': row['_id'], 'attempt_id': attempt, 'target': row['target'], 'admin': row['admin']}


def receipt(store, channel_id, action_id, body):
    row = store.db.artifacts.find_one({'_id': action_id, 'kind': 'group_action'})
    if not row or row.get('channel_id') != channel_id:
        raise Denied('PUBLICATION_NOT_FOUND')
    if body.get('attempt_id') != row.get('attempt_id'):
        raise Denied('PUBLICATION_ATTEMPT_MISMATCH')
    if row.get('platform_receipt') == body:
        return {'status': row['state']}
    if row['state'] not in ('SENDING', 'UNKNOWN'):
        raise Denied('PUBLICATION_RECEIPT_CONFLICT')
    state = {'platform_accepted': 'DONE', 'failed': 'FAILED', 'unknown': 'UNKNOWN'}[body['status']]
    store.put('artifacts', {**row, 'state': state, 'platform_receipt': body, 'receipt_at': now()},
              expected=row['revision'], stream=row['_id'])
    store.audit(row['episode_id'], 'group_action.receipt', {'action': row['_id'], 'state': state}, row['scope_key'])
    return {'status': state}


def recover_sending(store):
    """A lost adapter answer may hide a real action: never retry it, only say we do not know."""
    for row in store.db.artifacts.find({'kind': 'group_action', 'state': 'SENDING'}):
        store.put('artifacts', {**row, 'state': 'UNKNOWN', 'recovery_reason': 'adapter_attempt_interrupted'},
                  expected=row['revision'], stream=row['_id'])
