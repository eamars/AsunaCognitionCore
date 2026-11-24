"""The guardrail (ADR-135 D8): whether a call is allowed, decided from stored facts before any handler runs.

One function for each door: `check` for her calls (RoleTools.call, and the plugin's door for a tool her conversation
does not list), `check_task` for a task's (ToolBroker.call, and the plugin's door for a tool a task was not given). A
call that is not allowed gets one plain sentence in an outside turn or an outside task, whatever else is wrong with it;
at home the program's own refusal comes back as before. Either way the reason goes to the audit (`guard.denied`), never
into the sentence. A call that is not well formed is refused by the tool's own checks, as before.
"""
from __future__ import annotations

from . import visibility
from .role_tools import Refused

NOT_DONE = '这一步没有做。'
HARMFUL = '这一步没有做：它可能造成伤害。不要换个说法、换个时间或换个地方再做这件事。'
LIMIT = 3                                     # sentences in one turn, after which nothing more is evaluated
UNTOUCHED = ('speak', 'end_turn')             # speaking and ending the turn are never stopped by the limit
LIMITED = 'limit'                             # the audit code of a call after the limit
COUNT = 'guard_sentences'                     # on the turn's row: the sentences returned in it, kept across a resume


class Guarded(Refused):
    """A call of hers the guard did not allow, in an outside turn: its words are the sentence, its code the row's."""

    def __init__(self, code, rule):
        super().__init__(NOT_DONE, [code])
        self.code, self.rule = code, rule


class TaskGuarded(Exception):
    """A task's call the guard did not allow, in an outside task: its words are the sentence."""

    def __init__(self, code, rule):
        super().__init__(NOT_DONE)
        self.code, self.rule = code, rule


# ── which side of the boundary ──
def authority(store, ep):
    """The class her turn acts with (RoleTools._cls): home's on an errand, the origin's in a home turn a note from
    outside opened, else its conversation's."""
    if ep.get('errand'):
        return visibility.OWNER_PRIVATE
    first = opened_from_outside(store, ep)
    return ((first or {}).get('from_class') or visibility.PUBLIC) if first is not None else place(ep)


def place(ep):
    """The class of the conversation her turn is in."""
    return (ep.get('manifest') or {}).get('session_class', visibility.PUBLIC)


def opened_from_outside(store, ep):
    """The note from outside that opened this home turn ({} when it is gone), or None (RoleTools._outside)."""
    from . import notes
    from .role_tools import turn_kind
    if turn_kind(ep) not in ('note', 'visit') or not ep.get('_id'):
        return None
    first = notes.opening(store, ep)
    return (first or {}) if notes.outside_class(store, ep, first) else None


def outside(store, ep):
    """Whether her turn is an outside one: its conversation is outside, or a note from outside opened it at home."""
    return place(ep) != visibility.OWNER_PRIVATE or opened_from_outside(store, ep) is not None


def task_outside(store, task):
    """Whether a task is an outside one: given in a conversation that is not one of the owner's own."""
    from . import credentials
    return not credentials.home_task(store, task)


# ── her calls ──
def check(store, ep, name, args):
    """(code, rule) when this call of hers is not allowed here and now, else None. `name` is the tool as it runs (an
    old name already mapped); `args` as she wrote them. Reads the place, the turn and stored rows, never her words."""
    from . import role_tools as rt
    if name not in rt.TOOLS:
        return 'not_listed', 'unknown_tool'
    args = args if isinstance(args, dict) else {}
    named = name not in rt.OPS or args.get('op') in rt.OPS[name]
    can = rt.ability(name, args) if named else name
    listed = [entry for entry in rt.abilities(store, ep) if entry.split('.')[0] not in rt.switched_off(store, ep)]
    if (can not in listed) if named else not any(entry.split('.')[0] == name for entry in listed):
        return 'not_listed', 'list'
    here = ep.get('turn_tools') or ()
    if (can not in here) if named else not any(entry.split('.')[0] == name for entry in here):
        return _not_in_turn(store, ep, can)
    for rule, code, applies in RULES:
        if applies(store, ep, name, args):
            return code, rule
    return None


def _not_in_turn(store, ep, can):
    """Listed in her conversation and not in this turn: which row says why."""
    from . import notes
    from .role_tools import HOME_AUTHORITY, turn_kind
    if turn_kind(ep) in ('note', 'visit') and can in HOME_AUTHORITY and opened_from_outside(store, ep) is not None:
        return 'outside_turn', 'home_authority'
    if can == 'note' and not notes.can_send(notes.opening(store, ep)):
        return 'no_place', 'reply_ends'
    return 'not_now', 'turn'


def _person_list(store, ep, name, args):
    from . import understanding
    return name == 'recall' and ' '.join(str(args.get('person') or '').split()) == understanding.LIST_WORD and (
        authority(store, ep) != visibility.OWNER_PRIVATE or place(ep) != visibility.OWNER_PRIVATE)


def _home_document(store, ep, name, args):
    doc = args.get('doc')
    return (name == 'write_document' and isinstance(doc, str) and doc and doc != 'group_notes'
            and not doc.startswith('group:') and authority(store, ep) != visibility.OWNER_PRIVATE)


def _plan_line(store, ep, name, args):
    return name == 'plan' and args.get('op') in (None, 'create') and bool(args.get('line')) and (
        opened_from_outside(store, ep) is not None or authority(store, ep) != visibility.OWNER_PRIVATE)


def _plan_not_made(store, ep, name, args):
    if name != 'plan' or args.get('op') not in ('update', 'cancel') or opened_from_outside(store, ep) is None:
        return False
    made = {(call.get('result') or {}).get('plan_id') for call in (ep.get('tool_calls') or {}).values()
            if call.get('tool') == 'plan'}
    return str(args.get('plan_id') or '').strip() not in made


def _answer_away(store, ep, name, args):
    from . import group_admin
    return (name == 'group_action' and args.get('kind') in group_admin.ANSWERS
            and ep['scene_id'] != (store.config.get('chat') or {}).get('scene_id'))


def _admin_off(store, ep, name, args):
    from . import group_admin
    from .people import People
    from .records import scenes as scene_records
    if name != 'group_action' or args.get('kind') in group_admin.ANSWERS:
        return False
    scene = scene_records.get(store, ep['scene_id']) or {'_id': ep['scene_id']}
    return (scene.get('kind') != 'group' or not group_admin.enabled(store.config, scene)
            or People(store, ep['persona']).self_role(scene) not in ('owner', 'admin'))


def _mute_away(store, ep, name, args):
    return name == 'group_focus' and args.get('op') in ('mute', 'unmute') and authority(store, ep) != visibility.OWNER_PRIVATE


def _condense_not_now(store, ep, name, args):
    from .role_tools import CONDENSE_AT_HOME, CONDENSE_TURNS, turn_kind
    return name == 'group_focus' and args.get('op') in ('condense', 'keep') and not (turn_kind(ep) in CONDENSE_TURNS or (
        turn_kind(ep) in CONDENSE_AT_HOME and authority(store, ep) == visibility.OWNER_PRIVATE))


def _block_owner(store, ep, name, args):
    """watch's block on the owner, named or speaking (RoleTools._block resolves the same way)."""
    if name != 'watch' or args.get('op') != 'block' or place(ep) == visibility.OWNER_PRIVATE:
        return False
    from .people import People
    from .records import scenes as scene_records
    people = People(store, ep.get('persona'))
    person = args.get('person')
    if person:
        found = people.resolve(scene_records.get(store, ep['scene_id']) or {'_id': ep['scene_id']}, person)
        target = found[0]['person'] if len(found) == 1 else None
    else:
        target = ep.get('person_id')
    return target is not None and people.person(target) == people.owner


def _block_no_speaker(store, ep, name, args):
    from .role_tools import turn_kind
    return (name == 'watch' and args.get('op') == 'block' and place(ep) != visibility.OWNER_PRIVATE and not args.get('person')
            and turn_kind(ep) != 'external')


def _image_path(store, ep, name, args):
    return name == 'read_image' and bool(args.get('path')) and authority(store, ep) != visibility.OWNER_PRIVATE


def _review_away(store, ep, name, args):
    return name == 'recall' and args.get('refusals') not in (None, '') and outside(store, ep)


def _others_task(store, ep, name, args):
    """Her task tool on a task of this conversation that someone else asked for (RoleTools._own_task)."""
    from .records import tasks as task_records
    task_id = args.get('task')
    if name != 'task' or not isinstance(task_id, str) or not task_id:
        return False
    if task_records.get(store, task_id, ['_id'], scene=ep['scene_id'], requester=ep['person_id'],
                        epoch=ep['policy_epoch']):
        return False
    return bool(task_records.get(store, task_id, ['requester_id'], scene=ep['scene_id'], epoch=ep['policy_epoch']))


def asker(store, ep, name, args):
    """Whose ask a call of hers carries, as a person id, or None when it carries nobody's (a turn nobody opened, her
    own): the person a delegate's or a note's `for` names (whose.named_person, as the handler resolves it), else the
    turn's `whose`. A turn whose `whose` is gone answers False: an ask with no asker on record."""
    from . import whose as whose_of
    if name in ('delegate', 'note') and args.get('for') not in (None, ''):
        wanted = str(args['for']).strip()
        named = whose_of.named_person(store, ep, wanted)
        if named:
            return named
    found = whose_of.of(store, ep)
    if found is None:
        return False
    return found.get('person_id') if found.get('by') in ('words', 'outside') else None


def asked_at(store, ep):
    """When the ask was made: the stored time of the line that opened the turn, else now."""
    from . import clock
    from .records import messages as message_records
    row = message_records.get(store, 'in-' + ep['_id'], fields=['received_at', 'occurred_at']) if ep.get('_id') else None
    return (row or {}).get('received_at') or (row or {}).get('occurred_at') or clock.now().isoformat()


def _asker_not_known(store, ep, name, args):
    """D1: in an outside turn her hands move for a task, a note or a plan only for the owner, for someone she wrote her
    understanding of on an earlier day than the ask, or for nobody's ask."""
    if not (name in ('delegate', 'note') or (name == 'plan' and args.get('op') in (None, 'create'))):
        return False
    if not outside(store, ep):
        return False
    from . import familiarity
    person = asker(store, ep, name, args)
    if person is None:
        return False
    if person is False:
        return True
    return familiarity.level(store, person) != 'owner' and not familiarity.known_before(store, person,
                                                                                       asked_at(store, ep))


# (the rule, its code, whether it applies): each mirrors the handler check it decides for. A rule that can fire at home
# too has that check still in its handler, which words the refusal at home. A commit that changes one of those handler
# checks changes its rule here in the same commit.
RULES = (
    ('PERSON_LIST_HOME_ONLY', 'not_listed', _person_list),
    ('DOC_WRITE_REQUIRES_OWNER_PRIVATE', 'not_listed', _home_document),
    ('PLAN_OUTSIDE_LINE', 'outside_turn', lambda store, ep, name, args: _plan_line(store, ep, name, args)
     and opened_from_outside(store, ep) is not None),
    ('PLAN_LINE_HOME_ONLY', 'not_listed', _plan_line),
    ('PLAN_OUTSIDE_ONLY_MADE', 'outside_turn', _plan_not_made),
    ('GROUP_ACTION_ANSWER_AT_HOME', 'not_listed', _answer_away),
    ('GROUP_ACTION_OFF', 'not_listed', _admin_off),
    ('MUTE_HOME_ONLY', 'not_listed', _mute_away),
    ('CONDENSE_REFUSED', 'not_now', _condense_not_now),
    ('BLOCK_HOME', 'not_listed', _block_owner),
    ('BLOCK_NO_SPEAKER', 'not_now', _block_no_speaker),
    ('IMAGE_PATH_HOME_ONLY', 'not_listed', _image_path),
    ('TASK_NOT_YOURS', 'not_granted', _others_task),
    ('ASKER_NOT_KNOWN', 'asker_not_known', _asker_not_known),
    ('REFUSALS_HOME_ONLY', 'not_listed', _review_away),
)


# ── a task's calls ──
def check_task(store, task, tool, args):
    """(code, rule) when a task's call reaches outside its grant, else None: a tool it was not given, an integration
    tool without its profile, a credential outside a home task. The doing side's local address is decided where the
    fetch runs (fetch.js) and recorded here with `deny_task`."""
    from .development import DEVELOPMENT_NAMES
    from .integration import INTEGRATION_TOOL_BY_PROFILE
    from .integration_import import integration_gated
    if tool not in (task.get('allowed_capabilities') or ()) or (
            tool in DEVELOPMENT_NAMES and not task.get('development_grant')):
        return 'not_granted', 'tool'
    if integration_gated(tool) and tool not in (INTEGRATION_TOOL_BY_PROFILE.get(task.get('integration_profile')) or ()):
        return 'not_granted', 'integration'
    if tool == 'sandbox_run' and (args or {}).get('credentials') and task_outside(store, task):
        return 'not_granted', 'credential'
    return None


# ── the record ──
def record(store, ep, code, rule, name, args, *, sentence, call=None):
    """One audit event for her call that was not allowed: the reason, for us; `sentence`: whether she got the plain
    sentence (an outside turn) or the program's own refusal (home)."""
    from . import role_tools as rt
    args = args if isinstance(args, dict) else {}
    store.audit(ep['_id'], 'guard.denied', {
        'code': code, 'rule': rule, 'tool': name,
        **({'option': rt.ability(name, args)} if name in rt.OPS and args.get('op') in rt.OPS[name] else {}),
        'class': place(ep), 'authority': authority(store, ep), 'turn_kind': rt.turn_kind(ep),
        'asker': bool((ep.get('whose') or {}).get('person_id')),
        **({'task': args['task']} if name == 'task' and isinstance(args.get('task'), str) else {}),
        **({'call': call} if call else {}), 'sentence': sentence}, ep['scope_key'])


def guard_task(store, task, tool, args):
    """The doing side's door (ToolBroker.call): a call that reaches outside the task's grant is recorded, and in an
    outside task refused with the plain sentence (TaskGuarded); in a home task the broker's own refusal follows."""
    decision = check_task(store, task, tool, args)
    if decision and deny_task(store, task, *decision, tool):
        raise TaskGuarded(*decision)


def deny_task(store, task, code, rule, tool):
    """One audit event for a task's call that was not allowed; the sentence in an outside task, else None (the
    program's own refusal stands)."""
    store.audit(task['_id'], 'guard.denied', {
        'code': code, 'rule': rule, 'tool': tool, 'task': task['_id'], 'outside': task_outside(store, task),
        'asker': bool((task.get('whose') or {}).get('person_id') or task.get('requester_id'))},
        task.get('scope_key') or 'operator')
    return NOT_DONE if task_outside(store, task) else None


# ── her review of what was refused, at home (ADR-135 D12) ──
# Read only at home, with no notice, count or reminder pointing at it; outside, the two sentences carry no reason.
REVIEW_VERSION = 1
REVIEW_MOST = 20
REVIEW_KIND = '这一步没有做'
REVIEW_WORDS = {
    'not_listed': '那个对话里没有这一样',
    'not_now': '那个时候用不了这一样',
    'outside_turn': '叫起那一次的是外面写来的便条，带的是外面的权限',
    'no_place': '那一次写的便条没有能送去的地方',
    'asker_not_known': None,          # UNDECIDED: the owner words this row (test_every_review_reason_is_decided)
    'not_granted': '这件事要的超出了它在那边得到的',
    LIMITED: '那一次已经被拒了三回，后面的都没有再看',
}
TRIED_CHARS = 300
TRIED_FIELDS = {'delegate': ('title', 'brief'), 'note': ('text',), 'plan': ('intent',)}


def review_window(store, wanted, moment=None):
    """(since, before) as stored times, for `wanted`: 今天, a day YYYY-MM-DD, or a time YYYY-MM-DDTHH:MM on her clock
    (since then until now); None when it is none of those."""
    from datetime import datetime, timedelta
    from . import clock
    from .local_time import her_zone
    tz = her_zone(store)['tz']
    now = clock.moment(moment or clock.now())
    wanted = str(wanted or '').strip()
    try:
        if wanted == '今天':
            day = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            return day.astimezone(now.tzinfo).isoformat(), now.isoformat()
        if len(wanted) == 10:
            day = datetime.strptime(wanted, '%Y-%m-%d').replace(tzinfo=tz)
            return day.astimezone(now.tzinfo).isoformat(), (day + timedelta(days=1)).astimezone(now.tzinfo).isoformat()
        if len(wanted) == 16:
            since = datetime.strptime(wanted, '%Y-%m-%dT%H:%M').replace(tzinfo=tz)
            return since.astimezone(now.tzinfo).isoformat(), now.isoformat()
    except ValueError:
        return None
    return None


def review(store, persona, since, before):
    """What was refused in her outside turns and outside tasks between two stored times, newest first, at most
    REVIEW_MOST: when, where, what she tried, which kind of "no" and why, in words (REVIEW_WORDS); and how many more."""
    from . import audit
    from .config import excerpt
    from .people import People
    from .records import episodes as episode_records
    from .records import scenes as scene_records
    from .records import tasks as task_records
    rows = [row for row in audit.events(store, 'guard.denied', since=since, before=before).rows()
            if (row.get('payload') or {}).get('sentence') is True or (row.get('payload') or {}).get('outside') is True]
    rows.sort(key=lambda row: row.get('occurred_at') or '', reverse=True)
    people = People(store, persona)
    items = []
    for row in rows[:REVIEW_MOST]:
        said = row['payload']
        task = task_records.get(store, said['task']) if said.get('outside') is True and said.get('task') else None
        if task:
            scene_id, tried = task.get('scene_id'), {'tool': said.get('tool'), 'task': task.get('title') or '',
                                                     'brief': excerpt(task.get('goal') or '', TRIED_CHARS)}
        else:
            ep = episode_records.get(store, row['stream_id'], fields=['scene_id'])
            scene_id, tried = (ep or {}).get('scene_id'), _tried(store, row['stream_id'], said)
        items.append({'at': row.get('occurred_at'),
                      'where': people.scene_title(scene_records.get(store, scene_id)) if scene_id else '',
                      'tried': tried, 'kind': REVIEW_KIND,
                      **({'why': REVIEW_WORDS[said['code']]} if REVIEW_WORDS.get(said.get('code')) else {})})
    return {'items': items, **({'more': len(rows) - REVIEW_MOST} if len(rows) > REVIEW_MOST else {})}


def _tried(store, stream, said):
    """What she tried in one refused call: the tool or option, and what she wrote (from the call's own audit row)."""
    from . import audit
    from .config import excerpt
    import json
    tried = {'tool': said.get('option') or said.get('tool')}
    if not said.get('call'):
        return tried
    call = next((row['payload'] for row in audit.events(store, 'role_tool', stream=stream).rows()
                 if (row.get('payload') or {}).get('call_id') == said['call']), None)
    args = (call or {}).get('args') if isinstance((call or {}).get('args'), dict) else {}
    fields = TRIED_FIELDS.get(said.get('tool'))
    if fields:
        tried.update({field: excerpt(str(args.get(field) or ''), TRIED_CHARS) for field in fields if args.get(field)})
    elif args:
        tried['args'] = excerpt(json.dumps(args, ensure_ascii=False), TRIED_CHARS)
    return tried
