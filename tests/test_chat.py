"""Local adapter regressions; live model evidence is recorded separately in P1-A."""
import threading
from types import SimpleNamespace


from asuna.chat import Chat, prepare_local_scene, redact
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence
from asuna.lanes import FakeLane, FakeTurn
from asuna.state import content_ref
from fixture_grant import returned
from asuna.router import Router


def make_chat(store, tmp_path, lane):
    output = []
    settings = {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1', 'display_name': '演示'}
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    return Chat(app, settings, output.append), output


def turn(thought, speech):
    """One ordinary character turn: her private thought, then what she says."""
    return FakeTurn([('think', {'thought': thought})], speech)


def delegating(thought, title):
    """A turn that hands work to the action brain and says nothing yet."""
    return FakeTurn([('think', {'thought': thought}), ('delegate', {'title': title, 'brief': title + '：照原话去做。'}),
                     ('stay_silent', {'reason': '等结果回来再说'})])


def test_local_owner_can_delegate_with_both_configured_capabilities(store, tmp_path):
    settings = {'scene_id': 'dm-a', 'person_id': 'A', 'persona': 'P1',
                'display_name': '演示', 'workspace': str(tmp_path)}
    store.config.update(task_mode='workspace', chat=settings,
                        integration={'enabled': True, 'scene_id': 'dm-a', 'person_id': 'A'},
                        self_development={'enabled': True})
    lane = FakeLane(store, [delegating('我来处理。', '检查可用工具'), turn('先聊聊。', '我在。')])
    app = SimpleNamespace(store=store, config=store.config, evidence=Evidence(tmp_path / 'evidence'),
                          character=lane, router=Router(store, Coordinator(store, lane)))
    chat = Chat(app, settings, lambda _: None)

    accepted = chat.submit('帮我处理这件事。')
    source = store.db.messages.find_one({'_id': 'in-' + accepted['episode_id']})
    assert source['event']['integration_profile'] == 'owner'
    assert source['event']['development_profile'] == 'owner'
    episode = app.router.receive(source['event'])
    assert 'delegate' in lane.calls[0]['tools'] and len(episode['task_ids']) == 1
    task = store.db.tasks.find_one({'_id': episode['task_ids'][0]})
    assert task['integration_profile'] == 'owner' and task['development_grant'] is True
    assert {'integration_status', 'development_read'} <= set(task['allowed_capabilities'])
    ordinary = chat.submit('今天过得怎么样？')
    source = store.db.messages.find_one({'_id': 'in-' + ordinary['episode_id']})
    reply = app.router.receive(source['event'])
    assert reply['state'] == 'COMMITTED' and not reply.get('task_ids')


def test_input_queue_accepts_while_generating_and_emits_only_new_speech(store, tmp_path):
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()

    class SlowLane(FakeLane):
        def generate(self, *args, **kwargs):
            if not self.calls:
                entered.set()
                assert release.wait(10)
            return super().generate(*args, **kwargs)

    lane = SlowLane(store, [turn('PRIVATE_1', '第一句'), turn('PRIVATE_2', '第二句')])
    chat, output = make_chat(store, tmp_path, lane)
    original_emit = chat.emit

    def emit(text):
        original_emit(text)
        if text == '演示：第二句':
            completed.set()

    chat.emit = emit
    chat.worker.start()
    try:
        chat.submit('第一条输入')
        assert entered.wait(10)
        chat.submit('生成期间收到的第二条输入')
        assert chat.pending.qsize() == 1
        assert not output
        release.set()
        assert completed.wait(20)
        chat.pending.join()
        assert output == ['演示：第一句', '演示：第二句']
        assert len(lane.histories) == 1
        incoming = list(store.db.messages.find({'direction': 'inbound'}).sort('scene_seq', 1))
        assert [m['text'] for m in incoming] == ['第一条输入', '生成期间收到的第二条输入']
        # Her private thought is kept (audited and stored as a monologue), never published.
        thoughts = [e['payload']['args']['thought'] for e in store.db.audit_events.find(
            {'type': 'role_tool', 'payload.tool': 'think'})]
        assert thoughts == ['PRIVATE_1', 'PRIVATE_2']
        assert store.db.memory_units.count_documents({'kind': 'monologue', 'body_markdown': 'PRIVATE_2'}) == 1
        outputs = [e['payload']['content_sha256'] for e in store.db.audit_events.find({'type': 'turn.output'})]
        assert outputs == [content_ref('第一句')['content_sha256'], content_ref('第二句')['content_sha256']]
        assert store.db.messages.count_documents({'direction': 'outbound', 'text': 'PRIVATE_2'}) == 0
    finally:
        release.set()
        chat.stop()


def test_runtime_error_preserves_traceback_and_worker_accepts_next_message(store, tmp_path):
    completed = threading.Event()

    class FailingOnce(FakeLane):
        fail = True

        def generate(self, *args, **kwargs):
            if self.fail:
                self.fail = False
                raise RuntimeError('original diagnostic detail')
            return super().generate(*args, **kwargs)

    lane = FailingOnce(store, [turn('PRIVATE', '继续交流')])
    chat, output = make_chat(store, tmp_path, lane)
    original_emit = chat.emit

    def emit(text):
        original_emit(text)
        completed.set()

    chat.emit = emit
    chat.worker.start()
    try:
        chat.submit('这一轮遇到运行时错误')
        assert completed.wait(10)
        chat.pending.join()
        failed = store.db.episodes.find_one({'state': 'FAILED_RUNTIME'})
        assert failed and 'Traceback (most recent call last)' in failed['failure']
        assert 'RuntimeError: original diagnostic detail' in failed['failure']
        completed.clear()
        chat.submit('之后还能聊天吗')
        assert completed.wait(10)
        chat.pending.join()
        assert output[-1] == '演示：继续交流'
    finally:
        chat.stop()


def test_diagnostics_redact_credentials(store, tmp_path):
    config = {'mongo_uri': 'mongodb://user:secret@127.0.0.1', 'character': {'api_key': 'sensitive-key'}}
    result = redact('failure mongodb://user:secret@127.0.0.1 sensitive-key original-error', config)
    assert 'secret' not in result and 'sensitive-key' not in result
    assert 'original-error' in result


def test_local_setup_does_not_reset_existing_persona_or_load_fixture_memories(store, tmp_path):
    persona = tmp_path / 'persona.md'
    persona.write_text('角色原文', encoding='utf-8')
    settings = {'scene_id': 'local-new', 'person_id': 'local-new-user', 'persona': 'local-new',
                'persona_file': str(persona)}
    memories = store.db.memory_units.count_documents({})
    prepare_local_scene(store, settings)
    first = store.head('persona:local-new', 'global-safe')
    persona.write_text('不能覆盖已保存人物', encoding='utf-8')
    prepare_local_scene(store, settings)
    assert store.head('persona:local-new', 'global-safe') == first
    assert store.db.memory_units.count_documents({}) == memories


def test_chat_continues_while_action_waits_and_result_returns_once(store, tmp_path):
    from asuna.tasks import TaskService
    started, release, social_done, result_done = (threading.Event() for _ in range(4))
    lane = FakeLane(store, [delegating('需要查资料。', '读取资料'),
                           turn('等待时继续交流。', '继续聊。'),
                           turn('结果已到。', '查到了。')])
    chat, output = make_chat(store, tmp_path, lane)
    service = TaskService(store)
    chat.app.service = service
    chat.app.coordinator = chat.app.router.coordinator
    chat.settings['workspace'] = str(tmp_path)
    store.config['chat'] = {**store.config['chat'], **chat.settings}

    class WaitingAction:
        def run(self, task_id, workspace):
            task = service.claim(task_id)
            started.set()
            assert release.wait(20)
            # Explicit action double: the test targets scheduling and publication.
            ref = 'test-action-observation'
            store.put('artifacts', {'_id': ref, 'task_id': task_id, 'intent_revision': 1, 'tool': 'read_file',
                                   'result': {'text': 'observed'}, 'scope_key': task['scope_key'], 'state': 'DONE'}, stream=task_id)
            return returned(store, task, '执行侧报告', [ref])

    chat.app.executor = WaitingAction()
    chat.app.executor_lane = SimpleNamespace(sdk=SimpleNamespace(close=release.set))
    original_emit = chat.emit

    def emit(text):
        original_emit(text)
        if text == '演示：继续聊。':
            social_done.set()
        if text == '演示：查到了。':
            result_done.set()

    chat.emit = emit
    chat.worker.start()
    chat.task_worker.start()
    try:
        chat.submit('帮我查资料。')
        assert started.wait(10)
        chat.submit('不急，我们继续聊天。')
        assert social_done.wait(10)
        assert not result_done.is_set()
        assert store.db.tasks.find_one({})['state'] == 'RUNNING'
        release.set()
        assert result_done.wait(10)
        chat.pending.join()
        task = store.db.tasks.find_one({})
        assert task['feedback_state'] == 'DELIVERED'
        assert service.feedback(task, chat.app.router.coordinator) is None
        assert [x for x in output if x.startswith('演示：')] == ['演示：继续聊。', '演示：查到了。']
        assert all('执行侧报告' not in x for x in output)
    finally:
        release.set()
        chat.stop()
