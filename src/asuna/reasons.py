"""The reasons behind her actions: what she did after each thought, and the thought behind each action.

A thought (`think`, a `monologue` memory) belongs to the turn she wrote it in; what she did after it in that turn,
before her next thought, is what it led to: her words or her silence, and the tool calls with consequences. Read back
from the turn's records, never summarised: her words and her silence's reason as she wrote them (shortened), the
actions in plain first-person words, one per line, with no field names or ids. Lookups (recall, reading a picture,
listing) and her other thoughts are not actions.

The other way round: each call with consequences is recorded with her newest thought in the turn (`reason_ref`), and
that thought comes back, as she wrote it, with what the call made when it returns to her: a plan firing, a task's
result, a reply to her line, the night block (`for_call`, `for_message`). One table decides what has consequences
(`_action`).
"""
from __future__ import annotations

SAID_CHARS = 40
THOUGHT_CHARS = 400        # a thought is at most 360 characters; longer old ones keep the excerpt mark
ARG_CHARS = 30
DOC_WORDS = {'persona': '人格设定', 'voice': '说话方式', 'work_log': '工作记录', 'group_notes': '群笔记'}
DECISIONS = {'adopt': '采纳了', 'defer': '先放着了', 'drop': '不要了'}
RESTART_WHEN = {'now': '马上', 'quiet': '等安静的时候'}
VISIT_WORDS = {'start_topic': '起个话头', 'share_picture': '分享一张图', 'check_in': '露个面', 'write_notes': '记点笔记'}
GROUP_ACTION_WORDS = {'mute': '禁言了一个人', 'unmute': '解了一个人的禁言', 'recall': '撤回了一条消息', 'kick': '把一个人请出了群'}


def _short(value, limit=ARG_CHARS):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit] + '…'


def _doc(name):
    name = str(name or '')
    if name.startswith('group:') or name == 'group_notes':
        return '群笔记'
    if name.startswith('work'):
        return DOC_WORDS.get(name, '工作笔记')
    return DOC_WORDS.get(name, name or '一份文档')


def _action(tool, args):
    """One action in her words, or None when the call is not an action with consequences."""
    from .role_tools import ability
    op = args.get('op')
    can = ability(tool, args)                  # a tool's option ('task.stop'), an old name read as its option
    if tool == 'delegate':
        return '交给行动脑去做「%s」' % _short(args.get('title'))
    if can == 'task.message':
        return '跟行动脑补了一句'
    if can == 'task.stop':
        return '叫停了行动脑手上那件事'
    if tool == 'plan' and (op in ('create', 'update', 'cancel') or (not op and not args.get('plan_id') and args.get('intent'))):
        return {'create': '定了个计划', 'update': '改了计划', 'cancel': '撤了计划'}[op or 'create'] + (
            '：%s' % _short(args['intent']) if args.get('intent') else '')
    if can == 'ask.ask':
        return '问了：%s' % _short(args.get('question'))
    if can == 'ask.close':
        return '结束了一个问题：%s' % _short(args.get('took'))
    if tool == 'note':
        return '写了张便条：%s' % _short(args.get('text'))
    if tool == 'visit':
        return '出门去一个群%s' % VISIT_WORDS.get(args.get('intent'), '看看') + (
            '：%s' % _short(args['topic']) if args.get('topic') else '')
    if tool == 'errand':
        return '替人去带了句话：%s' % _short(args.get('request'))
    if tool == 'group_focus' and op in ('active', 'rest'):
        return '让一个群' + ('常驻' if op == 'active' else '歇着')
    if tool == 'group_action':
        return GROUP_ACTION_WORDS.get(args.get('kind'), '在群里动用了管理权限')
    if tool == 'set_policy':
        return '改了一项设置'
    if tool == 'update_self':
        return '改了对自己的看法'
    if tool == 'understand_person':
        return '更新了对这个人的认识'
    if tool == 'write_document':
        heading = args.get('heading') or args.get('sid')
        return '在%s里写了一笔' % _doc(args.get('doc')) + ('「%s」' % _short(heading) if heading and op != 'set_tags' else '')
    if tool == 'watch' and op in ('on', 'off'):
        return ('开始留意' if op == 'on' else '不再留意') + _short(args.get('person'), 20)
    if tool == 'peer_line' and op in ('open', 'close'):
        return '把那条线' + ('打开了' if op == 'open' else '关了')
    if can == 'ideas.review':
        return '把一个想法%s' % DECISIONS.get(args.get('decision'), '处理了')
    if can == 'ideas.note':
        return '记下一个想法：%s' % _short(args.get('idea'))
    if tool == 'restart' and op in ('request', 'drill', 'cancel'):
        if op == 'cancel':
            return '撤了重启'
        return '挂了个重启%s' % ('演练' if op == 'drill' else '') + (
            '，%s' % RESTART_WHEN[args['when']] if args.get('when') in RESTART_WHEN else '')
    if tool == 'attach_image':
        return '发了一张图'
    if tool == 'sticker' and op in ('keep', 'drop'):
        return '把一个表情' + ('收进了架子' if op == 'keep' else '从架子上拿掉了')
    return None


def then(store, unit):
    """What she did after this thought, in her words, one line each; [] when it was not followed by anything."""
    episode_id = unit.get('episode_id')
    call_id = str(unit.get('_id') or '').rsplit(':', 1)[-1]
    if not episode_id or not call_id:
        return []
    calls = list(store.db.audit_events.find({'stream_id': episode_id, 'type': 'role_tool'},
                                            {'payload': 1}).sort('seq', 1))
    names = [(c['payload'].get('call_id'), c['payload'].get('tool')) for c in calls]
    position = next((i for i, (cid, _) in enumerate(names) if cid == call_id), None)
    if position is None:
        return []
    lines, last_thought = [], True
    for call in calls[position + 1:]:
        payload = call['payload']
        if payload.get('tool') == 'think' and 'refused' not in payload:
            last_thought = False              # what follows belongs to her next thought
            break
        if 'refused' in payload or not isinstance(payload.get('args'), dict):
            continue
        if payload.get('tool') == 'stay_silent':
            reason = _short(payload['args'].get('reason'), SAID_CHARS)
            lines.append('所以我没说话' + ('：%s' % reason if reason else ''))
            continue
        words = _action(payload.get('tool'), payload['args'])
        if words:
            lines.append('所以我' + words)
    if last_thought:
        episode = store.db.episodes.find_one({'_id': episode_id}, {'speech': 1}) or {}
        said = _short(episode.get('speech'), SAID_CHARS)
        if said:
            lines.append('所以我说了「%s」' % said)
    return lines


def consequential(tool, args):
    """Whether a call has consequences (the one table: _action)."""
    return isinstance(args, dict) and _action(tool, args) is not None


# ADR-087 §4.2: the calls that write nothing and may run before her first thought in a turn, by tool or option. Every
# other call, `feel` and `task.answer` included, needs a thought first, so each action keeps its recorded reason.
READS = frozenset(('recall', 'read_image', 'task.page', 'ideas.read', 'ask.read', 'find_member', 'restart.preview',
                   'group_focus.list', 'place_timezone.list', 'private_words.summary'))


def before_thought(tool, args):
    """Whether a call may run before her first thought in the turn: a read on the closed list READS."""
    from .role_tools import ability
    can = ability(tool, args)
    op = args.get('op') if isinstance(args, dict) else None
    return can in READS or bool(op) and '%s.%s' % (can, op) in READS


def newest(episode, before=None):
    """The id of her newest thought in this turn (before the call at seq `before`), or None; a refused thought left
    no memory."""
    calls = sorted((episode.get('tool_calls') or {}).items(), key=lambda item: item[1].get('seq', 0))
    for call_id, call in reversed(calls):
        if before is not None and call.get('seq', 0) >= before:
            continue
        if call.get('tool') == 'think' and 'refused' not in call:
            return 'mono-%s:%s' % (episode['_id'], call_id)
    return None


def reason_of(episode, call_id):
    """The thought a call came from: as recorded, or by the same rule for a call recorded before reasons were."""
    call = ((episode or {}).get('tool_calls') or {}).get(call_id) or {}
    return call.get('reason_ref') or (newest(episode, call.get('seq', 0)) if call else None)


def thought(store, ref):
    """Her thought as she wrote it (the excerpt mark if ever cut), or None."""
    from .config import excerpt
    unit = store.db.memory_units.find_one({'_id': ref, 'kind': 'monologue'}, {'body_markdown': 1}) if ref else None
    return excerpt(unit['body_markdown'], THOUGHT_CHARS) if unit and unit.get('body_markdown') else None


def for_call(store, episode_id, field, value):
    """The thought behind the call in that turn whose result carries field=value (a plan, a task), or None."""
    episode = store.db.episodes.find_one({'_id': episode_id}, {'tool_calls': 1}) if episode_id else None
    for call_id, call in ((episode or {}).get('tool_calls') or {}).items():
        if isinstance(call.get('result'), dict) and call['result'].get(field) == value:
            return thought(store, reason_of(episode, call_id))
    return None


def for_message(store, message_id):
    """The thought behind a line she delivered: her last thought in the turn that spoke it, or None."""
    row = store.db.messages.find_one({'_id': message_id, 'direction': 'outbound'}, {'monologue_refs': 1})
    refs = (row or {}).get('monologue_refs') or []
    return thought(store, refs[-1]) if refs else None

