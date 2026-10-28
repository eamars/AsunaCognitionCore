"""Long-lived owner of Application, queues and adapter listeners; Web is a client."""
from bisect import bisect_left, insort
from contextlib import ExitStack
import os
from pathlib import Path
import threading
import time
import traceback
import weakref

from . import channel_kinds
from .application import Application
from .channels import Channels, ChannelServer, route_members
from .chat import Chat, local_settings, prepare_local_scene
from .config import DATA
from .memory_indexer import MemoryIndexer
from . import handover
from .state import Denied, now
from .records import scenes as scene_records
from .records import messages as message_records
from .records import episodes as episode_records
from .records import receipts as receipt_records
from .records import tasks as task_records

# How often the host's existing watch thread also checks that her heartbeat still beats (ADR-012 §4.3), so a
# lost heartbeat is found on a day when nobody talks to her too. It only checks; the clock stays DSH's.
RHYTHM_WATCH_SECONDS = 300

try:                                  # 跨场景只读联动（A2）
    from . import scene_links
except Exception:
    scene_links = None


def _workspace_overlaps(workspace, ordered, known):
    key = os.path.normcase(str(workspace))
    if any(os.path.normcase(str(parent)) in known for parent in (workspace, *workspace.parents)):
        return True
    prefix = key if key.endswith(os.sep) else key + os.sep
    index = bisect_left(ordered, prefix)
    return index < len(ordered) and ordered[index].startswith(prefix)


class ChannelWorkspaces:
    """The resolved workspaces of the local chat and of every channel grant: a new grant's must overlap none of them.
    It belongs to the channels configuration it was built from (`channels`)."""

    def __init__(self, local_workspace, channels):
        self.channels = channels
        self.ordered = [os.path.normcase(str(local_workspace))]
        self.known = set(self.ordered)

    def overlaps(self, workspace):
        return _workspace_overlaps(workspace, self.ordered, self.known)

    def add(self, workspace):
        key = os.path.normcase(str(workspace))
        insort(self.ordered, key)
        self.known.add(key)


# Each store's ChannelWorkspaces: set by every full pass over it (prepare_channels), extended by each admission
# (prepare_admission). A worker start opens a new store, so every start builds it again.
_WORKSPACES = weakref.WeakKeyDictionary()


def channel_workspaces(store):
    """The store's ChannelWorkspaces. When no full pass has run over this channels configuration, one runs dry (it
    writes nothing) to build it."""
    kept = _WORKSPACES.get(store)
    if kept is None or kept.channels is not store.config.get('channels'):
        prepare_channels(store, dry_run=True)
        kept = _WORKSPACES[store]
    return kept


def _writers(store, dry_run):
    def put(collection, document, **kwargs):
        return document if dry_run else store.put(collection, document, **kwargs)

    def save_scene(document, **kwargs):
        return document if dry_run else scene_records.save(store, document, **kwargs)
    return put, save_scene


def _speaks(channel, route, kind, sender):
    """Whether a member of a route is one of its scene's members: not blocked, nor in a blocked group."""
    blocked = kind == 'group' and route['target']['id'] in channel.get('blocked_groups', [])
    return not blocked and sender not in channel.get('blocked_senders', [])


def _checked_workspace(grant, workspaces):
    # A relative path would mean whatever folder the worker happens to run in.
    if not Path(grant['workspace']).is_absolute():
        raise Denied('CHANNEL_WORKSPACE_NOT_ABSOLUTE')
    workspace = Path(grant['workspace']).resolve()
    if not workspace.is_relative_to(DATA / 'channels'):
        raise Denied('CHANNEL_WORKSPACE_OUTSIDE_CHANNEL_ROOT')
    if workspaces.overlaps(workspace):
        raise Denied('CHANNEL_WORKSPACE_OVERLAP')
    return workspace


def _bind_identity(put, identities_by_id, channel_id, route, kind, sender, person):
    identity = identities_by_id.get(person)
    if identity is None:
        created = put('identities', {'_id': person, 'person_id': person, 'platform': channel_id,
                                          'account_id': sender}, stream='host:setup')
        identities_by_id[person] = created
    elif (identity['platform'], identity['account_id']) != (channel_id, sender):
        raise Denied('CHANNEL_IDENTITY_BINDING_CONFLICT')
    # A line's own name for whoever speaks there (an agent line names the agent, ADR-033 D3). Only a
    # one-person line names its speaker: a group's name is the group's, and an id is no name.
    display = route.get('display_name') if kind == 'dm' and route.get('display_name') != route['target']['id'] else None
    if display is not None and (not isinstance(display, str) or not 1 <= len(display) <= 40):
        raise ValueError('CHANNEL_DISPLAY_NAME_INVALID')
    if display and identities_by_id[person].get('display_name') != display:
        current = identities_by_id[person]
        identities_by_id[person] = put('identities', {**current, 'display_name': display},
            **({'expected': current['revision']} if 'revision' in current else {}), stream='host:setup')
    # No relationship record is seeded: everyone starts with none, which her context says in
    # words, and her first written understanding creates it (familiarity.py, memory.py).


def _route_scene(store, local, channel_id, channel, scene_id, kind, people, save_scene):
    # The owner joins a line of a kind that lets him (ADR-051): he writes there from the Web.
    joins = channel_kinds.owner_joins(scene_id) and local.get('person_id') not in people
    if joins:
        people.append(local['person_id'])
    scene = scene_records.get(store, scene_id)
    if scene is None:
        save_scene({'_id': scene_id, 'scene_id': scene_id, 'kind': kind,
                       'members': people, 'scope_key': 'scene:' + scene_id,
                       'policy_epoch': 1, 'sequence': 0, 'channel_id': channel_id,
                       'channel_account_id': channel['account_id']}, stream='host:setup')
    else:
        if (scene.get('channel_id') != channel_id or scene.get('channel_account_id') != channel['account_id'] or scene['kind'] != kind
                or scene['scope_key'] != 'scene:' + scene_id):
            raise Denied('CHANNEL_SCENE_BINDING_CONFLICT')
        if set(scene['members']) != set(people):
            # In automatic mode, another participant in the same QQ
            # group is covered by the existing admission policy.
            revoked = set(scene['members']) - set(people)
            # The owner joining his own home line opens it to nobody else: the conversation goes on.
            joined = set(people) - set(scene['members']) - ({local['person_id']} if joins else set())
            bump = bool(revoked) or (channel.get('admission') != 'automatic' and bool(joined))
            save_scene({**scene, 'members': people,
                'policy_epoch': scene['policy_epoch'] + int(bump)},
                expected=scene['revision'], stream='channel-membership:' + scene_id)


def prepare_channels(store, *, dry_run=False):
    """Explicit DM/group identities and disjoint per-member resource grants."""
    scene_ids, tokens = set(), set()
    put, save_scene = _writers(store, dry_run)
    local = store.config['chat']
    workspaces = ChannelWorkspaces(Path(local['workspace']).resolve(), store.config.get('channels'))
    identities_by_id = {row['_id']: row for row in store.db.identities.find({})}
    for channel_id, channel in store.config.get('channels', {}).items():
        token = channel.get('token', '')
        if not isinstance(token, str) or not token.isascii() or len(token) < 24 or token in tokens:
            raise ValueError('CHANNEL_TOKEN_MUST_BE_UNIQUE_AND_AT_LEAST_24_CHARS')
        tokens.add(token)
        if not isinstance(channel.get('account_id'), str) or not channel['account_id']:
            raise ValueError('CHANNEL_ACCOUNT_REQUIRED')
        targets = set()
        for route in channel['routes'].values():
            scene_id = route['scene_id']
            if scene_id == local['scene_id'] or scene_id in scene_ids:
                raise Denied('CHANNEL_SCENE_MUST_BE_DISTINCT')
            scene_ids.add(scene_id)
            kind = route['target']['type']
            members = route_members(route)
            if not members or not isinstance(route['target'].get('id'), str) or not route['target']['id']:
                raise Denied('CHANNEL_TARGET_OR_MEMBERS_REQUIRED')
            if kind == 'dm' and route['target']['id'] != route['sender_id']:
                raise Denied('CHANNEL_DM_TARGET_MISMATCH')
            target = (kind, route['target']['id'])
            if target in targets:
                raise Denied('CHANNEL_TARGET_ALREADY_BOUND')
            targets.add(target)
            people, all_people = [], set()
            for sender, grant in members.items():
                person = grant['person_id']
                if not isinstance(sender, str) or not sender or not isinstance(person, str) or not person or person in all_people:
                    raise Denied('CHANNEL_MEMBER_BINDING_INVALID')
                all_people.add(person)
                if _speaks(channel, route, kind, sender):
                    people.append(person)
                workspace = _checked_workspace(grant, workspaces)
                workspaces.add(workspace)
                _bind_identity(put, identities_by_id, channel_id, route, kind, sender, person)
                if not dry_run:
                    workspace.mkdir(parents=True, exist_ok=True)
            _route_scene(store, local, channel_id, channel, scene_id, kind, people, save_scene)
    if scene_links and not dry_run:
        # 派生投影：联动边写进 scenes，只为可观察；读路径每次现算自配置。
        scene_links.sync_scene_docs(store, store.config, sorted(scene_ids | {local['scene_id']}))
    _WORKSPACES[store] = workspaces
    return scene_ids


def prepare_admission(store, channel_id, route_id, route, sender, *, dry_run=False):
    """One admitted member: `sender` on `route`, which becomes `route_id` of `channel_id` once this succeeds. The
    full pass's rules, for this grant only: its workspace (absolute, under <data>/channels, overlapping none of
    channel_workspaces), its member and identity bindings, its route, the route's scene (created, or its members
    and epoch set as the full pass sets them) and that scene's links. A dry run writes nothing."""
    put, save_scene = _writers(store, dry_run)
    local = store.config['chat']
    channels = store.config.get('channels', {})
    channel = channels[channel_id]
    scene_id, kind = route['scene_id'], route['target']['type']
    others = [(other_id, other_route_id, other) for other_id, other_channel in channels.items()
              for other_route_id, other in other_channel['routes'].items() if (other_id, other_route_id) != (channel_id, route_id)]
    if scene_id == local['scene_id'] or any(other['scene_id'] == scene_id for _, _, other in others):
        raise Denied('CHANNEL_SCENE_MUST_BE_DISTINCT')
    members = route_members(route)
    if not members or not isinstance(route['target'].get('id'), str) or not route['target']['id']:
        raise Denied('CHANNEL_TARGET_OR_MEMBERS_REQUIRED')
    if kind == 'dm' and route['target']['id'] != route['sender_id']:
        raise Denied('CHANNEL_DM_TARGET_MISMATCH')
    if any(other_id == channel_id and other['target']['type'] == kind and other['target']['id'] == route['target']['id']
           for other_id, _, other in others):
        raise Denied('CHANNEL_TARGET_ALREADY_BOUND')
    grant = members[sender]
    person = grant['person_id']
    if (not isinstance(sender, str) or not sender or not isinstance(person, str) or not person
            or person in {other['person_id'] for other_sender, other in members.items() if other_sender != sender}):
        raise Denied('CHANNEL_MEMBER_BINDING_INVALID')
    workspaces = channel_workspaces(store)
    workspace = _checked_workspace(grant, workspaces)
    identity = store.db.identities.find_one({'_id': person})
    _bind_identity(put, {person: identity} if identity else {}, channel_id, route, kind, sender, person)
    if not dry_run:
        workspace.mkdir(parents=True, exist_ok=True)
    people = [other['person_id'] for other_sender, other in members.items() if _speaks(channel, route, kind, other_sender)]
    _route_scene(store, local, channel_id, channel, scene_id, kind, people, save_scene)
    if not dry_run:
        if scene_links:
            scene_links.sync_scene_docs(store, store.config, [scene_id])
        workspaces.add(workspace)
    return route


def write_route_keys(config, root):
    """Each route of a ROUTE_KEYS channel gets its key in <data>/private/route-keys/<channel>-<route>.json, ignored
    by git, for the agent on that line to read (ADR-033 D4). Keys of routes no longer configured are removed."""
    import json
    from .channels import route_key, route_keys_allowed
    folder = Path(root) / 'private' / 'route-keys'
    wanted = {}
    for channel_id, channel in (config.get('channels') or {}).items():
        if not route_keys_allowed(channel_id):
            continue
        for route_id, route in channel['routes'].items():
            wanted['%s-%s.json' % (channel_id, route_id)] = {
                'url': 'http://127.0.0.1:%d/v1/channels/%s' % (config.get('channel_port', 8766), channel_id),
                'route_id': route_id, 'account_id': channel['account_id'], 'sender_id': route['sender_id'],
                'key': route_key(channel['token'], route_id)}
    if wanted:
        folder.mkdir(parents=True, exist_ok=True)
    for name, value in wanted.items():
        (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for stale in (folder.glob('*.json') if folder.is_dir() else ()):
        if stale.name not in wanted:
            stale.unlink()
    return sorted(wanted)


class RuntimeHost:
    def __init__(self, config, evidence, database=None, *,
                 lane_factory=None, schedule_lane=None,
                 configure_controller=None, development_factory=None, awaits_activation=False):
        self.config, self.evidence, self.database = config, evidence, database
        # Under the native Host, a new worker learns which publications it actually loaded only after
        # initialization (publication.activated). Until then a publication it is about to activate still
        # reads APPLIED and must not request yet another restart.
        self.activation_settled = threading.Event()
        if not awaits_activation:
            self.activation_settled.set()
        self.lane_factory = lane_factory
        self.schedule_lane, self.configure_controller = schedule_lane, configure_controller
        self.development_factory = development_factory
        self.stack = ExitStack()
        self.shutdown_requested = threading.Event()
        self.restart_requested = threading.Event()
        self.restart_pending = threading.Event()
        self._restart_watch_stop = threading.Event()
        self._restart_blocked_logged = False

    def __enter__(self):
        try:
            from .visibility import without_link_downgrades
            self.config, rejected_links = without_link_downgrades(self.config)
            self.app = self.stack.enter_context(Application(
                self.config, self.evidence, self.database,
                lane_factory=self.lane_factory,
                development_factory=self.development_factory))
            for rejected in rejected_links:
                # A public scene may never read an owner-private scene (ADR-009 §2.3).
                self.app.store.audit('config', 'config.link_rejected', rejected)
                self.evidence.record('host.link_rejected', rejected)
            self.evidence.record('host.recovery.start', {})
            recovery_start = time.perf_counter()
            self.settings = local_settings(self.config)
            # Owner-local persona source roots must be well formed before any job can use them.
            from .persona_data import persona_sources
            persona_sources(self.config, self.settings['persona'])
            prepare_local_scene(self.app.store, self.settings)
            local_ready = time.perf_counter()
            from .channel_admission import restore_admissions
            restore_admissions(self.app.store)
            try:
                from .stickers import remember_shelf
                remember_shelf(self.app.store, self.settings['persona'])     # her shelf is always known
            except Exception:
                self.evidence.record('sticker.memory_error', {'traceback': traceback.format_exc()[-800:]})
            scenes = prepare_channels(self.app.store)
            channel_scenes_ready = time.perf_counter()
            self.integration = None
            from . import sandbox_backend
            # The managed integration process runs only in the sandbox; without one it stays off (ADR-010 D5).
            if self.config.get('integration', {}).get('enabled') and sandbox_backend.available(self.config):
                from .integration import IntegrationRunner
                self.integration = IntegrationRunner(self.config)
                self.app.broker.integration = self.integration
                self.stack.callback(self.integration.close)
            self.controller = Chat(self.app, self.settings, emit=lambda text: self.evidence.record('host.notice', {'text': text}))
            self.controller.on_turn_finished = self._after_turn
            self.controller.restart_pending = self.restart_pending
            if self.configure_controller:
                self.configure_controller(self)
            self.voice = None
            # Voice and video are decoded in child processes of their own, each on or off by the profile's settings
            # (ADR-095 §5.3.1, media_children.py); a child that is killed, dies or will not start is a lane fault.
            from . import lane_faults, media_children
            media = self.config.get('media') or {}
            store = self.app.store

            def fault(kind):
                # Counted in a thread of its own: a slow database never holds a voice or a video.
                return lambda stage, error: threading.Thread(target=lane_faults.record, daemon=True, args=(
                    store, 'host', media_children.FAULT_LANES[kind], stage, error)).start()
            if self.config.get('channels'):
                # A channel's voices become text within the request that brings them (voice.py).
                from . import voice
                self.voice = voice.Transcriber(self.evidence, enabled=media.get('voice', True),
                                               fault=fault('voice')).start()
                self.stack.callback(self.voice.close)
            media_children.start_video(enabled=media.get('video', True), fault=fault('video'))
            self.stack.callback(media_children.stop_video)
            channels = Channels(self.controller)
            channels.recover_sending()
            self._recover_tasks()
            tasks_ready = time.perf_counter()
            self.controller.recover_inputs()
            inputs_ready = time.perf_counter()
            self.evidence.record('host.recovery.ready', {
                'local_seconds': round(local_ready - recovery_start, 3),
                'channel_scene_seconds': round(channel_scenes_ready - local_ready, 3),
                'task_seconds': round(tasks_ready - channel_scenes_ready, 3),
                'input_seconds': round(inputs_ready - tasks_ready, 3)})
            self.indexer = MemoryIndexer(self.app.store, self.evidence, [self.settings['scene_id'], *sorted(scenes)],
                                         summary_lane=self.app.summary_lane,
                                         summary_scenes=[self.settings['scene_id'], *sorted(scenes)],
                                         summary_can_run=lambda: self.controller.active_task is None
                                             and not self.controller.reconfiguring
                                             and self.controller.task_queue.empty()).start()
            self.app.memory_indexer = self.indexer
            self.stack.callback(self.indexer.close)
            from . import memory_pilot
            from .retrieval import Retrieval
            # ADR-062 phase 1: measures which of her own items a turn would surface; delivers nothing.
            self.pilot = memory_pilot.attach(getattr(getattr(self.app, 'coordinator', None), 'context', None),
                                             self.app.store, self.settings.get('persona'),
                                             lambda: Retrieval(self.app.store, self.evidence))
            if self.pilot:
                self.stack.callback(self.pilot.close)
            if self.config.get('channels'):
                self.channel_server = ChannelServer(channels, self.config.get('channel_port', 8766))
                self.stack.callback(self.channel_server.close)
                write_route_keys(self.config, DATA)
                self.evidence.record('host.channels_started', {'port': self.channel_server.server.server_port})
            self.evidence.record('host.channels.ready', {})
            if self.integration:
                self.integration.restore()
            self.evidence.record('host.integration.ready', {})
            # ADR-034: her restart requests go to the supervisor; a restart that fell back calls her once.
            from . import restarts
            restarts.DESK = restarts.Desk(self.app, self.controller)
            self.stack.callback(restarts.DESK.close)
            try:
                restarts.call_after_fallback(self.app.store, self.controller, self.config)
            except Exception as exc:
                self.evidence.record('restart.call_failed', {'error': str(exc)[:300]})
            if self.config.get('channels'):
                from . import notices
                try:
                    notices.remind_open(self.app.store, self.controller)   # requests still waiting on her
                except Exception as exc:
                    self.evidence.record('notices.remind_failed', {'error': str(exc)[:300]})
            self.schedule = None
            if self.schedule_lane is not False:          # False: the native Host has no Schedule (mountSchedule=false)
                from .schedule import ScheduleService
                self.schedule = ScheduleService(self.app, self.controller, lane=self.schedule_lane)
                self.app.coordinator.scheduler = self.schedule
            self.evidence.record('host.schedule.ready', {'active': self.schedule is not None})
            self.controller.worker.start()
            self.controller.task_worker.start()
            self.controller.watchdog.start()
            self.stack.callback(self.controller.stop)
            if self.schedule:
                self.stack.callback(self.schedule.close)
            self._complete_activations()
            self._restart_watch = threading.Thread(target=self._watch_published_restart,
                                                   name='asuna-restart-watch', daemon=True)
            self._restart_watch.start()
            self.evidence.record('runtime.ready', {})
            return self
        except BaseException:
            indexer = getattr(self, 'indexer', None)
            if indexer:
                indexer.request_stop()
            self.stack.close()
            raise

    def _after_turn(self):
        self._maybe_restart_after_publish()
        schedule = getattr(self, 'schedule', None)
        if schedule:
            schedule.watch_rhythm()

    def _maybe_restart_after_publish(self):
        """Switch code only after the original action/feedback turn has settled."""
        if not self.activation_settled.is_set():
            return
        # Only a core publication replaces this worker. Persona and channel ones apply in place, and one
        # still APPLIED would otherwise ask for a restart after every turn, forever.
        applied=receipt_records.sink_of_kind(self.app.store,'self_development_publish',state='APPLIED',
                                             project='core').first()
        if applied:
            with self.controller.state_lock:
                if not self.restart_pending.is_set():
                    self.evidence.record('restart.pending', {'receipt_id': applied['_id']})
                    self.restart_pending.set()
                if self.controller.active or self.controller.active_task:
                    if not self._restart_blocked_logged:
                        self.evidence.record('restart.blocked', {
                            'active_task': self.controller.active_task,
                            'active_role': self.controller.active,
                            'pending_queue': self.controller.pending.qsize(),
                            'task_queue': self.controller.task_queue.qsize()})
                        self._restart_blocked_logged = True
                    return
                if self.restart_requested.is_set():
                    return
                self.evidence.record('restart.requested', {'receipt_id': applied['_id']})
                self.restart_requested.set()
                self.shutdown_requested.set()

    def _watch_published_restart(self):
        # APPLIED may occur inside a still-running action. Mark the lifecycle
        # pending before that action returns, so the queues stop taking work.
        checked = time.monotonic()
        while not self._restart_watch_stop.wait(.5) and not self.shutdown_requested.is_set():
            if self.controller.active or self.controller.active_task:
                self._maybe_restart_after_publish()
            if self.schedule and time.monotonic() - checked >= RHYTHM_WATCH_SECONDS:
                checked = time.monotonic()
                self.schedule.watch_rhythm(deep=True)

    def _complete_activations(self):
        """A successfully constructed live host supplies the actual boot result."""
        store=self.app.store
        for row in receipt_records.sink_of_kind(store,'self_development_publish',states=['APPLIED','ACTIVE']).each():
            current=receipt_records.sink_get(store, row['_id'])
            # Native publications are activated only by the worker that actually
            # loaded the selected artifact, after its initialization succeeds.
            if current.get('artifact') and current['state'] != 'ACTIVE':
                continue
            active=(receipt_records.save_sink(store, {**current,'state':'ACTIVE','activated_at':now()},
                              expected=current['revision'],stream=current['task_id'])
                    if current['state']=='APPLIED' else current)
            self.controller.offer_self_development('self-development:publish:'+active['_id'],
                text='自我开发候选已由当前宿主实际启动。这里是上一行动目标的发布结果；你可决定继续观察、修正或不处理。',
                task_id=active['task_id'],
                trusted_context_events=[{'kind':'development_publish_result',
                    'task_id':active['task_id'],'candidate':active['candidate'],
                    'state':'ACTIVE','activated_at':active['activated_at'],
                    'changed_files':active['changed_files'],'boot_probe':active['boot_probe']}])

    def _recover_tasks(self):
        store = self.app.store
        for task in task_records.in_states(store, ['READY', 'RUNNING', 'RETURNED', 'DONE', 'PARTIAL', 'BLOCKED',
                                                   'NEEDS_CHARACTER_DECISION', 'UNKNOWN']).each():
            source = message_records.get(store, task['raw_input_refs'][0])
            seen = set()
            while source and source.get('event', {}).get('episode_kind') == 'task_feedback':
                if source['_id'] in seen:
                    raise Denied('TASK_SOURCE_CYCLE')
                seen.add(source['_id'])
                parent = task_records.get(store, source['event']['task_id'])
                source = message_records.get(store, parent['raw_input_refs'][0]) if parent else None
            if not source or not source.get('host_managed'):
                continue
            if self._settle_received(task):
                continue
            if task['state'] in handover.FINISHED:
                continue        # ADR-030 D6: its work is done; the watchdog's first sweep hands its result over
            # Approved restart policy: unfinished actions/results remain
            # durable, but do not run or call the role model on startup.
            # A new explicit local DECIDE may continue their native context.
            paused = self.app.service.pause_for_restart(task['_id'])
            self.evidence.record('host.task_paused', {'task_id': task['_id'],
                'previous_state': task['state'], 'state': paused['state']})
        # A finished task whose result she had already taken was once paused here when her turn on it handed
        # the work on to another task (its feedback stayed WAITING_TASK): it read as open work. Give it back.
        for task in task_records.paused(store, 'host_restart', states=['RETURNED', 'BLOCKED', 'DONE', 'PARTIAL',
                                                                    'UNKNOWN', 'NEEDS_CHARACTER_DECISION']).each():
            if not self._feedback_taken(task):
                continue
            restored = {key: value for key, value in task.items()
                        if key not in ('pause_reason', 'paused_at', 'paused_state', 'paused_feedback_state')}
            restored = task_records.save(store, {**restored, 'state': task['paused_state'],
                                           'feedback_state': task.get('paused_feedback_state')},
                                 expected=task['revision'], stream=task['_id'])
            self._settle_received(restored)
            self.app.service.collab(restored, 'status', {'state': 'done' if restored['state'] == 'RETURNED' else 'failed'},
                                    'status:' + task['_id'] + ':restored:' + str(restored['revision']))
            self.evidence.record('host.task_unpaused', {'task_id': task['_id'], 'state': restored['state']})

    def _feedback_taken(self, task):
        """Her turn on this task's result ran: it committed, or it handed the work on to another task."""
        feedback = episode_records.get(self.app.store, task['feedback_episode']) if task.get('feedback_episode') else None
        return feedback if feedback and feedback['state'] in ('COMMITTED', 'WAITING_TASK') else None

    def _settle_received(self, task):
        """A task whose result she took is finished work; once her turn on it committed, so is the turn that asked."""
        store = self.app.store
        feedback = self._feedback_taken(task)
        if not feedback:
            return False
        if feedback['state'] == 'COMMITTED':
            if task.get('feedback_state') != 'DELIVERED':
                task_records.save(store, {**task, 'feedback_state': 'DELIVERED'}, expected=task['revision'], stream=task['_id'])
            original = episode_records.get(store, task['episode_id'])
            if original and original['state'] == 'WAITING_TASK':
                episode_records.save(store, {**original, 'state': 'COMMITTED', 'feedback_episode': feedback['_id']},
                          expected=original['revision'], stream=original['_id'])
        return True

    def __exit__(self, *args):
        try:
            self.evidence.record('host.stop.started', {})
        finally:
            self._restart_watch_stop.set()
            watcher = getattr(self, '_restart_watch', None)
            if watcher:
                watcher.join(timeout=2)
            indexer = getattr(self, 'indexer', None)
            if indexer:
                indexer.request_stop()
            self.stack.close()
            self.evidence.record('host.stop.finished', {})
