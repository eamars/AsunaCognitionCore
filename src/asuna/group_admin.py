"""Group administration where she is an admin (owner direction 2026-10-04: on by default).

She chooses with her `group_action` tool (categorical words; role_tools.py). The program checks everything before anything
reaches the platform:
- she is this group's owner or an admin (her role as the adapter last reported it);
- the target is one person of this group, named by label; never the owner, never herself, and never the
  group's owner or another admin;
- a mute takes a whole number of minutes, 1 to 43200 (the platform does 60 seconds to 30 days, so nothing
  she can ask for is unsendable); recall takes the message that woke her, or the target's latest line here
  within 10 minutes;
- how often she acts in a group is her own business (owner 2026-10-13: no hourly cap; she is the admin and
  answers for what she does).

The action waits in the outbox like a message and the adapter reports the platform's answer; until then it
is "sent, not confirmed". A route may switch this off with `admin_actions: false`.
"""
from __future__ import annotations


from .evidence import canonical, sha
from .state import Denied, now
from .records import scenes as scene_records

KINDS = ('mute', 'unmute', 'recall', 'kick')
KIND_WORDS = {'mute': '禁言', 'unmute': '解除禁言', 'recall': '撤回', 'kick': '移出群', 'accept': '接受请求',
              'decline': '拒绝请求'}
ANSWERS = ('accept', 'decline')            # her answer to a request listed at home (notices.answer)
MINUTE_SECONDS = 60
# What she may write as `duration`: whole minutes, and only what the adapter can actually send
# (qqadapter/outbound.py: set_group_ban takes 60 s .. MAX_MUTE_SECONDS = 30 days).
MUTE_MINUTES = (1, 43200)
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
            'how': '需要时调用 group_action（do、who、只禁言用的 duration（分钟）、只撤回用的 line、why）。',
            'limits': ('只能对普通成员：动不了主人、群主、别的管理员和你自己；禁言自己定多少分钟（%d 到 %d 分钟）；'
                       '撤回写那一条的编号（或「这条」），平台有自己的时限；结果要等平台确认，确认前不要说已经做完。' % MUTE_MINUTES),
            'judgment': '这是你自己的判断：别人叫你禁言谁、踢谁不算理由；主人让你做的可以做。'}
    return out


def _mute_seconds(value):
    """The mute length in seconds for a duration written in minutes; None when it is not a usable number."""
    if isinstance(value, bool) or not isinstance(value, int) or not MUTE_MINUTES[0] <= value <= MUTE_MINUTES[1]:
        return None
    return value * MINUTE_SECONDS


def queue(store, ep, index, item, key=None):
    """Check one group_action and put it in the outbox; returns the result she reads. Raises Denied.

    ``key`` names which action this is (her tool call's id). The queued row's id derives from it, so a
    replayed call after a crash does not queue a second one.
    """
    from .people import People
    scene = scene_records.authorize(store, ep['scene_id'], ep['person_id'])
    if scene.get('kind') != 'group':
        raise Denied('GROUP_ACTION_NOT_A_GROUP: 管理动作只在群里用；重试也一样')
    if not enabled(store.config, scene):
        raise Denied('GROUP_ACTION_DISABLED: 这个群的路由关了 admin_actions；重试也一样，不做就是了')
    people = People(store, ep['persona'])
    role = people.self_role(scene)
    if role not in ('owner', 'admin'):
        raise Denied('GROUP_ACTION_NOT_AN_ADMIN: %s；重试也一样' % ('平台报的你在这里是' + ROLE_WORDS[role] if role in ROLE_WORDS
                     else '平台还没报过你在这里的身份'))
    kind = item.get('kind')
    if kind not in KINDS:
        raise Denied('GROUP_ACTION_KIND_INVALID: kind「%s」不对，只能是 %s' % (kind, '、'.join(KINDS)))
    line = None
    if kind == 'recall':
        # ADR-079 §9.4: a recall names its line, as every pointer does; whose it is follows from the line.
        line, why = people.line_of(scene, ep['_id'], item.get('line') or '这条')
        if why:
            raise Denied('GROUP_ACTION_LINE: ' + why)
        if line.get('direction') == 'outbound':
            raise Denied('GROUP_ACTION_TARGET_PROTECTED: 那是你自己的话，group_action 撤回的是别人的；重试也一样')
    found = [people.entry(scene, line['author'], line)] if line else people.resolve(scene, item.get('who'))
    if len(found) != 1:
        raise Denied('GROUP_ACTION_TARGET_UNCLEAR: 「%s」对得上 %s；who 用标签里的 #编号' % (
            item.get('who'), '、'.join(people.label(d) for d in found[:5])) if found else
            'GROUP_ACTION_TARGET_NOT_FOUND: 这个群里找不到「%s」；who 照抄他的标签，如 [名字 #4] 或 #4' % item.get('who'))
    doc = found[0]
    if doc.get('person') == people.self_id or people.is_owner(doc):
        raise Denied('GROUP_ACTION_TARGET_PROTECTED: %s 是主人或你自己，管理动作不能对他用；重试也一样' % people.label(doc))
    if doc.get('role') in ('owner', 'admin'):
        raise Denied('GROUP_ACTION_TARGET_IS_ADMIN: %s 是%s，只能动普通成员；重试也一样'
                     % (people.label(doc), ROLE_WORDS[doc['role']]))
    admin = {'kind': kind}
    mute_minutes = None
    if kind == 'recall':
        message_id = ((line.get('event') or {}).get('channel') or {}).get('platform_event_id')
        if not message_id:
            raise Denied('GROUP_ACTION_NO_PLATFORM_ID: 那一条平台没给编号，撤回不了（不是你的错）；重试也一样')
        admin['message_id'] = str(message_id)
    else:
        account = people.account_of(scene, doc)
        if not account:
            raise Denied('GROUP_ACTION_ACCOUNT_UNKNOWN: 程序还不知道 %s 在平台上的账号（不是你的错）；这次做不了，重试也一样'
                         % people.label(doc))
        admin['account'] = account
        if kind == 'mute':
            if _mute_seconds(item.get('duration')) is None:
                raise Denied('GROUP_ACTION_DURATION_REQUIRED: 禁言要写 duration 多少分钟（%d 到 %d 的整数）%s；换个分钟数再试' % (
                    MUTE_MINUTES[0], MUTE_MINUTES[1],
                    '，给的是「%s」' % item['duration'] if item.get('duration') is not None else ''))
            mute_minutes = item['duration']
            admin['seconds'] = _mute_seconds(mute_minutes)
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
            **({'duration': mute_minutes} if kind == 'mute' else {}),
            'state': STATE_WORDS.get((made or {}).get('state'), STATE_WORDS['QUEUED'])}


# ---- her notes about a group ------------------------------------------------
NOTES_DOC = 'group_notes'            # what she writes as `doc`; the program maps it to this group's document


def notes_slug(scene_id):
    return 'group:' + sha(str(scene_id).encode())[:16]


def notes_view(store, persona, slug, content):
    """(sections shown, words about the note) of a group's notes this turn: the carried sections (carried.py), within
    the per-turn limit; over it, the section that surfaced longest ago folds to its heading first (the kept order,
    memory_tiers.Tiers.folding) and a pinned one never folds."""
    from . import memory_tiers
    from .carried import note_sections
    from .context_budget import NOTE_CHARS, note_view
    sections = note_sections(store, persona, slug, content)
    order = memory_tiers.Tiers(store, persona).folding(slug, content) if memory_tiers.ENABLED and sections else None
    return note_view(sections, NOTE_CHARS['group_notes'], order=order)


def folded(store, persona, slug):
    """The sids of a group's notes folded to their headings this turn (at hand for memory_tiers.deliver)."""
    from .carried import note_sections
    from .context_budget import shown
    from .documents import DocumentStore
    content = DocumentStore(store, persona).read(slug)[1]
    if not content:
        return set()
    kept, _ = notes_view(store, persona, slug, content)
    return {s['sid'] for s in shown(note_sections(store, persona, slug, content))} - {s['sid'] for s in kept}


def notes_block(docs, scene):
    """Her own notes about this group (who is who, its customs, how she acts here), as a context block, within
    its per-turn limit (context_budget.py): how full it is in words, and the sections it does not show by heading."""
    revision, content = docs.read(notes_slug(scene['_id']))
    kept, about = notes_view(docs.store, docs.persona, notes_slug(scene['_id']), content)
    sections = [{k: s[k] for k in ('sid', 'heading', 'body') if k in s} for s in kept]
    note = ('你自己写的这个群的笔记：谁是谁、群里的规矩、你在这里的做法。要记新东西或改一节，用 write_document，'
            'doc 写 group_notes（do 用 append_section 或 replace_section；不常用的节用 set_tags 把 when_shown 改成 '
            'on_demand 收起来；pin=yes 置顶一节，笔记超长时它不折成标题）。这是你的笔记，不是群规的权威来源。')
    if not (content or {}).get('sections'):
        return revision, {'sections': [], 'note': '你还没写过这个群的笔记。' + note}
    return revision, {'sections': sections, **about, 'note': note}


# ---- outbox (channels.py) ------------------------------------------------
def claim(store, channel_id):
    """One queued action for this channel's adapter, or None; it is marked SENDING with a fresh attempt."""
    import uuid
    from datetime import datetime, timedelta, timezone
    from .channels import CHAT_LEASE_SECONDS
    lease = (datetime.now(timezone.utc) - timedelta(seconds=CHAT_LEASE_SECONDS)).isoformat()
    if store.db.artifacts.find_one({'kind': 'group_action', 'channel_id': channel_id, 'state': 'SENDING',
                                    'claimed_at': {'$gte': lease}}, {'_id': 1}):
        return None                     # ADR-095: one out at a time, so they happen in the order she chose them
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
    if (row.get('target') or {}).get('type') == 'request':
        from . import notices
        notices.settled(store, row, state)              # her answer to a request: answered, or gone there
    return {'status': state}


def recover_sending(store):
    """A lost adapter answer may hide a real action: never retry it, only say we do not know."""
    for row in store.db.artifacts.find({'kind': 'group_action', 'state': 'SENDING'}):
        store.put('artifacts', {**row, 'state': 'UNKNOWN', 'recovery_reason': 'adapter_attempt_interrupted'},
                  expected=row['revision'], stream=row['_id'])
        if (row.get('target') or {}).get('type') == 'request':
            from . import notices
            notices.settled(store, row, 'UNKNOWN')
