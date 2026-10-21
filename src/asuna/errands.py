"""An errand carries home (ADR-066).

A turn opened by `errand` is a home turn that speaks into another place. It runs in its own copy of the destination's
conversation: a DSH fork at that conversation's last completed turn, so the model server resumes from the cached
prefix (same system prompt, same tool list). The tools that conversation lists act with home's authority in it
(`authority`); what she says goes out there like any of her lines, and what she read, thought and was given stays in
the copy, which is retired when the errand ends. The destination's next turn hears once that home sent her and what
she said there (`told_block`); the request itself never goes there.
"""
from datetime import datetime, timedelta, timezone

from .evidence import sha
from .state import now

SESSION_PREFIX = 'asuna-errand-'
# Waiting behind that conversation's own turns: past this the talk there has moved on (her review, 2026-10-15).
PATIENCE_MINUTES = 20
# The errand turn's own opening, and the end of each tool result in it (her question: which layer of her acted).
OPENING = '家里交代的，带着家里的全部权限；你说出口的话那边都看得到。'
MARK = '差事回合，家里的权限'
# Her own lines sent on an errand, wherever she reads them back.
LINE_MARK = '差事：家里托你来说的'
# A task begun on an errand is home's (owner and her, 2026-10-20): home's authority lasts this turn only, so its report
# comes home, where that authority holds, and she carries the result back with another errand.
HOME_TASK = ('这件算家里的：结果回到家里那一拍，这个会话的上下文不跟过去；要说给这边，回家后再跑一趟差事。'
             '在那之前不要说已经做完。')
# The tasks listed on an errand are that conversation's, which home's authority does not reach.
NO_STEER = ('差事回合不给任务补话、叫停：这里列的是这边的任务，家里的权限管不到，等交代它的人在这边叫你时再补；'
            '家里的任务回家里再补。')
STATES = {'late': '没赶上：那边排着的事办完时已经过了 %d 分钟，话题过去了，没发' % PATIENCE_MINUTES,
          'interrupted': '中途断了（重启）：%s'}
TOLD_NOTE = ('这是你从家里出门来这里办的事：不是这里有人叫你，托你的话留在家里。这里列的是你当时在这里说的，'
             '这边的人看到的就是这些。')
TOLD_SHOWN = 3


def of(ep):
    """The errand this turn runs on, or None: {from, scene_id, scope_key, policy_epoch, person_id, by}."""
    return (ep or {}).get('errand')


def carried(store, event):
    """At ingest: the home turn an errand visit came from, whose authority its turn carries; None otherwise."""
    visit = event.get('visit') or {}
    if event.get('episode_kind') != 'visit' or visit.get('intent') != 'errand':
        return None
    home = store.db.episodes.find_one({'_id': visit.get('from')},
                                      {'scene_id': 1, 'scope_key': 1, 'policy_epoch': 1, 'person_id': 1})
    if not home:
        return None
    return {'from': home['_id'], 'scene_id': home['scene_id'], 'scope_key': home['scope_key'],
            'policy_epoch': home['policy_epoch'], 'person_id': visit.get('author') or home['person_id'],
            'by': visit.get('by')}


def home_turn(store, ep):
    """The turn whose authority an errand turn carries: the home turn that sent it (ADR-066); any other turn, itself.
    What grants or authorizes for work begun on an errand (a task's grants, its input, its consult, where its result
    is said) reads this turn, never the errand's; the errand turn stays the record of what she did and thought there."""
    if not (ep or {}).get('errand'):
        return ep
    return store.db.episodes.find_one({'_id': ep['errand']['from']}) or ep


def session_id(episode_id):
    """The errand's own session: named, so the launcher retires it like the other one-shot sessions."""
    return SESSION_PREFIX + sha(episode_id.encode())[:32]


def is_errand_visit(event):
    return (event or {}).get('episode_kind') == 'visit' and ((event or {}).get('visit') or {}).get('intent') == 'errand'


def late(row, moment=None):
    """Whether an errand waited past its patience before its turn came (row: its input message)."""
    if not is_errand_visit((row or {}).get('event')):
        return False
    try:
        queued = datetime.fromisoformat(str(row.get('received_at')).replace('Z', '+00:00'))
    except ValueError:
        return False
    return (moment or datetime.now(timezone.utc)) - queued > timedelta(minutes=PATIENCE_MINUTES)


def skipped(event, source, previous, moment=None):
    """An errand's turn come up in the queue that does not run: 'ERRAND_INTERRUPTED' when a restart cut it (what it
    sent stands, and home hears what that was: redoing it would send twice), 'ERRAND_LATE' when it waited past its
    patience (the talk there moved on); None for any other input."""
    if not is_errand_visit(event):
        return None
    if previous and previous.get('state') not in ('COMMITTED', 'WAITING_TASK'):      # finished: nothing was cut
        return 'ERRAND_INTERRUPTED'
    return 'ERRAND_LATE' if late(source, moment) else None


def sent_lines(store, episode_id):
    """What she said on the errand, as sent: delivered lines and whether a picture went with one."""
    rows = store.db.messages.find({'episode_id': episode_id, 'direction': 'outbound', 'phase': 'SPEAK'},
                                  {'text': 1, 'delivery_state': 1, 'attachment': 1, 'scene_seq': 1, 'receipt_at': 1}).sort('scene_seq', 1)
    return [row for row in rows if row.get('delivery_state') == 'DELIVERED']


def interrupted_words(store, episode_id):
    """What an errand cut by a restart had already done: interrupted is not undone (her review)."""
    sent = sent_lines(store, episode_id)
    if not sent:
        return STATES['interrupted'] % '那边一句也没发出去'
    pictures = sum(1 for row in sent if row.get('attachment'))
    return STATES['interrupted'] % ('已经发出去 %d 句%s；别重办，会发两遍' % (len(sent), '（带 %d 张图）' % pictures if pictures else ''))


def told_block(store, scene_id, *, mark=True):
    """errand_from_program, once, in the destination's next turn of its own: that home sent her, and what she said."""
    from .local_time import stamp, zone_of
    zone = zone_of(store, scene_id)
    # Every turn of every platform conversation asks: by the inputs' platform index, only this conversation's errands.
    rows = list(store.db.messages.find({'adapter_id': 'visit', 'scene_id': scene_id,
                                        'platform_event_id': {'$type': 'string', '$regex': '^visit:errand:'},
                                        'ingress_state': 'COMPLETE', 'errand_told': {'$exists': False}},
                                       {'episode_id': 1, 'received_at': 1, 'event.visit.by': 1}).sort('received_at', 1))
    if not rows:
        return None
    items = []
    for row in rows:
        sent = sent_lines(store, row['episode_id'])
        if sent:
            items.append({'at': stamp(sent[-1].get('receipt_at') or row['received_at'], zone),
                          'from': '%s在家里托你来的' % ((row.get('event') or {}).get('visit', {}).get('by') or '主人'),
                          'you_said': [str(line.get('text') or '') + ('（带了一张图）' if line.get('attachment') else '')
                                       for line in sent]})
    if mark:
        store.db.messages.update_many({'_id': {'$in': [row['_id'] for row in rows]}}, {'$set': {'errand_told': now()}})
    return {'items': items[-TOLD_SHOWN:], 'note': TOLD_NOTE} if items else None
