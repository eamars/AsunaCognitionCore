"""Her active and resting groups (ADR-039): she stays present in a few groups and lets the others rest.

An active group works as it always has. In a resting group only what is meant for her wakes her: an @ or a reply to
her (no gate), and through the gate an @ caught up after a gap, the answer to a question she just asked there, and
someone on her watchlist. Nobody's other talk opens a turn, the proactive chance does not come, and its lines are
kept and searchable but not summarized. An @ there brings the group's recent lines with it (context.catch_up).

She chooses with `group_focus`. A group where she is an admin is always active. The configured number of active
groups (`active_groups`, default 4) is a soft limit: going past it works and says what it costs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

ACTIVE_GROUPS = 4
# What still wakes her in a resting group: words addressed to her, and the people she is waiting for.
RESTING_WAKES = frozenset({'mentioned_account', 'reply_to_character', 'catchup_mention', 'awaited_answer', 'watched'})
DAY = timedelta(days=1)


def soft_limit(config):
    return int(config.get('active_groups') or ACTIVE_GROUPS)


def admin_here(store, scene, persona=None):
    from .people import People
    try:
        return People(store, persona or (store.config.get('chat') or {}).get('persona')).self_role(scene) in ('owner', 'admin')
    except Exception:
        return False


def active(store, scene, persona=None):
    """Whether she is present in this group: her own choice, or her admin role there. Not a group: always."""
    if (scene or {}).get('kind') != 'group':
        return True
    return bool(scene.get('focus_active')) or admin_here(store, scene, persona)


def wake(store, scene, reason):
    """The wake reason a line keeps in this group: unchanged when active; in a resting group only RESTING_WAKES."""
    if reason is None or reason in RESTING_WAKES or active(store, scene):
        return reason
    return None


def _lines_today(store, scene, moment):
    return store.db.messages.count_documents({'scene_id': scene['_id'], 'direction': 'inbound',
                                              'received_at': {'$gte': (moment - DAY).isoformat()}})


def listing(store, persona, moment=None):
    """Her groups by state, with the last day's lines, in words for her."""
    from .people import People
    from . import places
    moment = moment or datetime.now(timezone.utc)
    people, rows = People(store, persona), {'active': [], 'resting': []}
    for scene_id, _, _ in places.groups(store.config):
        scene = store.db.scenes.find_one({'_id': scene_id})
        if not scene:
            continue
        item = {'place': places.place_id(scene_id), 'group': people.scene_title(scene),
                'last_day': '这一天 %d 句' % _lines_today(store, scene, moment)}
        if admin_here(store, scene, persona):
            item['why'] = '你在这里是管理员，一直常驻'
        rows['active' if active(store, scene, persona) else 'resting'].append(item)
    return rows


def set_focus(store, ep, scene, on, persona):
    """She makes a group active or lets it rest. Returns what she reads; raises ValueError(words) to refuse."""
    from .state import Conflict
    if not on and admin_here(store, scene, persona):
        raise ValueError('你在这个群是管理员，它一直常驻（管理员要看得见群里的事）；要少花在这里的心思，可以少说话，不必让它歇。')
    if bool(scene.get('focus_active')) == on:
        state = '常驻' if active(store, scene, persona) else '歇着'
        return {'unchanged': '这个群本来就是%s。' % state, 'groups': listing(store, persona)}
    changed = {**scene, 'focus_active': on}
    if on:
        # Summaries start from now: the resting days stay as kept, searchable lines, not a backlog of summaries.
        changed['summary_start_seq'] = max(scene.get('summary_start_seq') or 0, scene.get('sequence') or 0)
    try:
        store.put('scenes', changed, expected=scene['revision'], stream=scene['_id'])
    except Conflict:
        raise ValueError('这个群的记录刚被别处改过，没改成；再来一次就行。') from None
    groups = listing(store, persona)
    result = {'done': ('这个群现在常驻：跟以前一样，群里的话会照常叫你。' if on else
                       '这个群现在歇着：只有 @ 你、回你的话、你在等的回话和 watch 的人会叫你；群里的话照存照能查，不再整理成小结。'),
              'groups': groups}
    limit = soft_limit(store.config)
    if on and len(groups['active']) > limit:
        result['over_the_usual'] = (
            '现在常驻 %d 个群，平常是 %d 个以内。每多一个常驻群，群里的闲聊就多占模型那边存对话的位置，'
            '你家里和别处的大对话更容易被挤出去，下回开口要整段重读（大约半分钟）。看看 groups 里常驻的那些，'
            '有哪个可以歇了，就用 group_focus 让它歇。' % (len(groups['active']), limit))
    return result
