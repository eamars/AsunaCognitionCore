"""Whose work a task is (ADR-111): who asked, and where.

Decided once, when a turn opens, from stored rows only (no model call, so a restarted worker and a redelivered event
answer the same), and written on the episode; every task and plan the turn makes copies it, and the development grant
follows it. It is carried along the chain (a result turn has its task's, a plan's firing the plan's, an errand turn
home's) and never across a less trusted step: a turn a note from outside opened takes the writing turn's own place,
never a home conversation's.

    {'by': 'words' | 'standing' | 'own' | 'outside', 'scene_id', 'person_id', 'chosen', 'version'}

`words`: the person whose line asked, in that conversation; `standing`: the owner's standing ask, a self-development
turn; `own`: her own, where she was; `outside`: an outside conversation she named for work she took on at home, which
runs on the Web chat (the home line). The words below are program text for her character brain: 你 is her. Bump
WHOSE_VERSION with any change to them.
"""
from . import visibility
from .records import episodes as episode_records
from .records import messages as message_records
from .records import plans as plan_records
from .records import tasks as task_records

WHOSE_VERSION = 1
BY = ('words', 'standing', 'own', 'outside')
# A walk through stored rows (an old task or plan, a chain of them) stops here and answers `own` where it is: a guard
# against a broken chain, not a measure of a real one (a chain of results begun before ADR-111 is walked once a hop).
STEPS_MOST = 64

TASK = {'words': '这件是%s托你的', 'standing': '这件是你自我改进时交的', 'own': '这件是你自己的事',
        'outside': '这件是%s那边托的'}
PLAN = {'words': '这条计划为的是%s托你的事', 'standing': '这条计划是你自我改进时定的', 'own': '这条计划是你自己的事',
        'outside': '这条计划为的是%s那边托的事'}
RESULT_HERE = '结果回到这里'
RESULT_OUTSIDE = '结果回家里，这边的上下文不跟过去；要给那边，你自己去说'
HANDED = '是你在%s交出去的'
STANDING = {'left': '（%s已经离开这个群了）', 'blocked': '（%s在这里被屏蔽了）', 'closed': '（这条线你关着）'}
BRIEF_ONLY = '新开一份上下文：它只看得到这次的 brief。'
FOR_UNKNOWN_PLACE = ('「%s」不是外面的一处：for 照抄 note_places_from_program 里群或私聊的 place，'
                     '或者不写（就是这一回合叫你的那位）。')
FOR_UNKNOWN_PERSON = '「%s」不是这一回合里的人：for 照抄 people_from_program 里的标签，或者不写（就是叫起这一回合的那位）。'
FOR_UNKNOWN_HERE = ('「%s」不是这一回合里的人，也不是外面的一处：for 照抄 people_from_program 里的标签或'
                    ' note_places_from_program 里群或私聊的 place，或者不写（就是叫起这一回合的那位）。')


def record(by, scene_id, person_id=None, *, chosen=False, **extra):
    return {'by': by, 'scene_id': scene_id, 'person_id': person_id, **({'chosen': True} if chosen else {}),
            'version': WHOSE_VERSION, **extra}


def home(config):
    """The home line, the Web chat, as a place: where work for someone outside runs (ADR-111)."""
    chat = (config or {}).get('chat') or {}
    return chat.get('scene_id'), chat.get('person_id')


def _scene(store, scene_id):
    from .records import scenes as scene_records
    return scene_records.get(store, scene_id) or {'_id': scene_id}


def _private(store, scene_id, person_id):
    return visibility.session_class(store.config, store, _scene(store, scene_id), person_id) == visibility.OWNER_PRIVATE


def of_turn(store, ep, event, steps=0):
    """The turn's `whose` (ADR-111 design §2.2), or None: a turn a note from outside opened whose origin is gone or
    would be a home conversation acts for no one, and hands nothing over and plans nothing."""
    event = event or {}
    scene_id, person_id = event.get('scene_id'), event.get('person_id')
    if steps > STEPS_MOST:
        return record('own', scene_id, person_id)
    kind = event.get('episode_kind') or 'external'
    from . import errands
    errand = (ep or {}).get('errand') or errands.carried(store, event)
    if errand:
        sent = episode_records.get(store, errand.get('from'))
        found = of(store, sent, steps + 1) if sent else None
        if found and found.get('scene_id') == errand['scene_id']:
            return found
        return record('own', errand['scene_id'], errand.get('person_id'))
    if kind == 'external':
        return record('words', scene_id, person_id)
    if kind in ('task_feedback', 'consult'):
        task = task_records.get(store, event.get('task_id'))
        return of_task(store, task, steps + 1) if task else record('own', scene_id, person_id)
    if kind == 'scheduled':
        plan = plan_records.get(store, event.get('scheduled_plan_id'))
        return of_plan(store, plan, steps + 1) if plan else record('own', scene_id, person_id)
    if kind in ('note', 'visit'):
        from . import notes
        first = notes.opening_for(store, event)
        cls = visibility.session_class(store.config, store, _scene(store, scene_id), person_id)
        if notes.outside_class(store, {'episode_kind': kind, 'manifest': {'session_class': cls}}, first):
            writer = episode_records.get(store, (first or {}).get('from_episode'))
            if not writer:
                return None
            # The writer's own place: a note written on an errand acts as that conversation, never as home.
            found = (record('own', writer['scene_id'], writer.get('person_id')) if writer.get('errand')
                     else of(store, writer, steps + 1))
            if not found or _private(store, found['scene_id'], found.get('person_id')):
                return None
            return found
        return record('own', scene_id, person_id)
    if kind == 'self_development':
        local, owner = home(store.config)
        return record('standing', local, owner)
    return record('own', scene_id, person_id)


def of(store, ep, steps=0):
    """An episode's `whose`: as stored, else decided from its stored input (a turn in flight across the install); a
    turn that is gone or erased answers `own` where it was."""
    if not ep:
        return None
    if 'whose' in ep:
        return ep['whose']
    row = message_records.get(store, 'in-' + ep['_id'], fields=['event'])
    event = (row or {}).get('event')
    if not event:
        return record('own', ep.get('scene_id'), ep.get('person_id'))
    return of_turn(store, ep, event, steps)


def of_task(store, task, steps=0):
    """A task's `whose`: as stored, else (a task written before ADR-111) read from the turn that made it; either way
    never earning more than the grant the task stored, so its result turn, its continuations and what they hand over
    earn no more than it did (a result turn kept its task's grant before ADR-111 too)."""
    if task.get('whose'):
        found = task['whose']
        if found.get('by') in ('words', 'standing') and not task.get('development_grant'):
            return {**found, 'earns': False}
        return found
    made = episode_records.get(store, task.get('episode_id'))
    found = of(store, made, steps) if made else None
    if not found or found.get('scene_id') != task.get('scene_id'):
        found = record('own', task.get('scene_id'), task.get('requester_id'))
    return {**found, 'unrecorded': True, 'earns': bool(task.get('development_grant'))}


def of_plan(store, plan, steps=0):
    """A plan's `whose`: as stored, else (a plan written before ADR-111) read from the turn that made it, honoured only
    where the plan lives (§3.7)."""
    if plan.get('whose'):
        return plan['whose']
    made = episode_records.get(store, plan.get('source_episode_id'))
    return for_plan(store, of(store, made, steps) if made else None, plan.get('scene_id'), plan.get('person_id'))


def for_plan(store, found, scene_id, person_id):
    """The `whose` a plan living in this conversation records: the turn's when it names this conversation (or is
    `outside`, whose work lives on the Web chat), else her own here (a line plan, a plan made on an errand)."""
    if found and (found.get('scene_id') == scene_id or found.get('by') == 'outside'):
        return found
    return record('own', scene_id, person_id)


def earns_development(store, whose):
    """Whether work for this `whose` may get the development tools (ADR-011 §6.1, ADR-111 §2.4): the owner's own words
    in one of his conversations, an agent's words on its own line, her self-development; nothing else."""
    if not whose or whose.get('earns') is False:
        return False
    if whose.get('by') == 'standing':
        return True
    if whose.get('by') != 'words':
        return False
    from . import integration, scene_links
    config, scene_id, person_id = store.config, whose.get('scene_id'), whose.get('person_id')
    owner = (config.get('chat') or {}).get('person_id')
    if owner and scene_links.canonical_person_id(config, store, person_id) == owner:
        return _private(store, scene_id, person_id)
    return integration.agent_home_scene(config, scene_id) and person_id in _line_people(config, scene_id)


def _line_people(config, scene_id):
    from .channels import route_members
    return {grant.get('person_id') for channel in (config.get('channels') or {}).values() if isinstance(channel, dict)
            for route in (channel.get('routes') or {}).values()
            if isinstance(route, dict) and route.get('scene_id') == scene_id
            for grant in route_members(route).values()}


def standing(store, whose):
    """Whether the person can still be reached where the work is: 'here', 'left' (their admission ended, ADR-107),
    'blocked' (the channel's list or her block switch) or 'closed' (a line she has closed)."""
    if not whose:
        return 'here'
    from . import lines, switches
    from .channels import route_members
    scene_id, person_id = whose.get('scene_id'), whose.get('person_id')
    if lines.is_closed(store, scene_id):
        return 'closed'
    if whose.get('by') != 'words' or not person_id:
        return 'here'
    if switches.blocked(store, person_id):
        return 'blocked'
    for channel in (store.config.get('channels') or {}).values():
        for route in (channel.get('routes') or {}).values() if isinstance(channel, dict) else ():
            if not isinstance(route, dict) or route.get('scene_id') != scene_id:
                continue
            for sender, grant in route_members(route).items():
                if grant.get('person_id') == person_id:
                    if sender in (channel.get('blocked_senders') or ()):
                        return 'blocked'
                    if grant.get('ended_at'):
                        return 'left'
    return 'here'


def _who(store, persona, whose):
    from .people import People
    people = People(store, persona)
    if whose.get('by') == 'outside':
        return people.scene_title(_scene(store, whose.get('scene_id')))
    return people.speaker(_scene(store, whose.get('scene_id')), whose.get('person_id'))


def words(store, persona, whose, table=TASK):
    """Whose it is, in her words (TASK or PLAN), with where the person stands when they can no longer be reached."""
    if not whose:
        return None
    text = table.get(whose.get('by'), table['own'])
    if '%s' in text:
        text %= _who(store, persona, whose)
    state = standing(store, whose)
    if state == 'closed':
        text += STANDING['closed']
    elif state != 'here':
        text += STANDING[state] % _who(store, persona, whose)
    return text


def result_words(store, persona, task):
    """`for` on a result item: whose it is, and where it was handed over when that is another conversation."""
    found = of_task(store, task)
    text = words(store, persona, found)
    made = episode_records.get(store, task.get('episode_id'), fields=['scene_id'])
    if text and made and made.get('scene_id') != task.get('scene_id') and not task.get('errand_place'):
        from .people import People
        text += '，' + HANDED % People(store, persona).scene_title(_scene(store, made['scene_id']))
    return text


def moved(task, made):
    """Whether a task runs on the Web chat for outside work she took on in another conversation (`made`: the turn
    that handed it over, whose task would otherwise run there, or at its errand's home): the one case, besides an
    errand's, of a task running elsewhere than its turn (§3.5)."""
    made = made or {}
    return ((task.get('whose') or {}).get('by') == 'outside'
            and (made.get('errand') or made).get('scene_id') != task.get('scene_id'))


def named_person(store, ep, label):
    """The person a group turn's `for` names: one whose line is in this turn (people_from_program), by label."""
    from .people import People
    people = People(store, ep.get('persona'))
    scene = _scene(store, ep['scene_id'])
    for person_id in ((ep.get('manifest') or {}).get('people_shown') or {}):
        if people.speaker(scene, person_id) == label:
            return person_id
    return None


def named_outside(store, ep, place):
    """The outside conversation a home turn's `for` names: a group or a DM from her note places that is not a home
    one (a home group is listed among the outside places, `places.errand_targets`)."""
    from . import notes
    found = notes.targets(store, ep['scene_id'], visibility.OWNER_PRIVATE).get(place)
    if not found or found[1] not in ('group', 'dm') or visibility.home_group(store.config, found[0]):
        return None
    return found[0]


def line_in_turn(store, ep, person_id):
    """A person's line in this group turn, the input of a task she names for them: their first line to her waiting
    behind the one that opened it, as `people_from_program` found them (understanding.group_people); never one that
    came after."""
    from .understanding import EXPLICIT
    opened = message_records.get(store, 'in-' + ep['_id'], fields=['scene_seq'])
    if (opened or {}).get('scene_seq') is None:
        return None
    row = message_records.inbound(store, ep['scene_id'], ep['policy_epoch'], author=person_id,
                                  after=opened['scene_seq'], wakes=EXPLICIT).first(fields=['_id'])
    return (row or {}).get('_id')
