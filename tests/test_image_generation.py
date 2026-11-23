"""generate_image: the fixed image-service sequence, its validation, and the picture landing as her own."""
import json

import pytest

from asuna import image_generation as gen
from asuna import integration_image as script

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
T2I = {'id': 'demo-t2i', 'ready': True, 'capabilities': {'input_modes': ['text-to-image']},
       'prompting': {'style': 'natural-language English', 'quality_prefix': 'best quality',
                     'examples': [{'prompt': 'a lamp on a windowsill'}]},
       'selection': {'best_for': ['still life'], 'not_for': ['portraits']},
       'parameter_schema': {'properties': {k: {} for k in ('prompt', 'negative_prompt', 'width', 'height', 'seed',
                                                            'steps', 'cfg', 'batch_size')}}}
EDIT = {'id': 'demo-edit', 'ready': True, 'capabilities': {'input_modes': ['image-edit']},
        'parameter_schema': {'properties': {'prompt': {}, 'input_image': {}}, 'required': ['input_image']}}


class FakeService:
    """The image service's agent API, as far as the script uses it."""
    def __init__(self, states=('queued', 'running', 'succeeded'), workflows=(T2I, EDIT)):
        self.states = list(states)
        self.workflows = {w['id']: w for w in workflows}
        self.calls = []
        self.inputs = []                      # the service's uploaded inputs: {name, modified_time}
        self.deleted = []

    def json(self, method, path, body=None):
        self.calls.append((method, path.split('?')[0], body))
        if path == '/project/inputs':
            return {'files': list(self.inputs)}
        if path == '/project/resolve':
            name = 'demo-edit' if body.get('input_mode') == script.EDIT_MODE else 'demo-t2i'
            return {'selected_workflow': name, 'matches': [{'workflow_id': name, 'ready': True}]}
        if path == '/project/workflows':
            return {'workflows': list(self.workflows.values())}
        if path.startswith('/project/workflows/'):
            name = path.rsplit('/', 1)[1]
            if name not in self.workflows:
                raise script.Failure('IMAGE_SERVICE_REFUSED', http_status=404)
            return {'workflow': self.workflows[name], 'prompt': {'1': {'class_type': 'Graph'}}}
        if path == '/project/generate':
            return {'prompt_id': 'job-0001-abcd', 'effective_parameters': {'seed': 7, 'width': 896, 'height': 1152},
                    'warnings': []}
        if path.startswith('/project/jobs/'):
            state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
            outputs = [{'kind': 'images', 'url': '/view?filename=a.png&subfolder=&type=output'}] if state == 'succeeded' else []
            return {'state': state, 'outputs': outputs, 'queued_ms': 1, 'elapsed_ms': 2}
        raise AssertionError(path)

    def request(self, method, path, body=None, *, limit=0, content_type=None):
        self.calls.append((method, path.split('?')[0], body))
        if path == '/upload/image':
            name = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            self.inputs.append({'name': name, 'modified_time': 1e12})
            return 200, {}, json.dumps({'name': name, 'subfolder': '', 'type': 'input'}).encode()
        if method == 'DELETE':
            self.deleted.append(path.rsplit('/', 1)[1])
            return 200, {}, b'{"deleted": true}'
        return 200, {'content-type': 'image/png'}, PNG


def request(**extra):
    value, error = gen.validate({'prompt': 'a quiet reading corner, soft light', **extra})
    assert error is None, error
    return value


def run(service, value, monkeypatch, tmp_path, clock=None):
    monkeypatch.setattr(script, 'BODY_PATH', str(tmp_path / 'artifact.bin'))
    ticks = iter(range(0, 10000, 3))
    return script.run(value, service, clock=clock or (lambda: next(ticks)), sleep=lambda s: None)


def test_the_service_picks_the_workflow_and_the_picture_is_written(monkeypatch, tmp_path):
    service = FakeService()
    report = run(service, request(width=512, height=640, options={'steps': 20}), monkeypatch, tmp_path)
    assert report['workflow'] == 'demo-t2i' and report['prompt_id'] == 'job-0001-abcd' and report['seed'] == 7
    assert report['view_path'].startswith('/view?') and report['bytes'] == len(PNG)
    assert (tmp_path / 'artifact.bin').read_bytes() == PNG
    queued = next(body for method, path, body in service.calls if path == '/project/generate')
    assert queued['parameters'] == {'prompt': 'a quiet reading corner, soft light', 'batch_size': 1,
                                    'width': 512, 'height': 640, 'steps': 20}
    resolve = next(body for method, path, body in service.calls if path == '/project/resolve')
    assert resolve['content_mode'] == 'sfw' and resolve['input_mode'] == 'text_to_image'


def test_a_named_workflow_must_fit_the_request(monkeypatch, tmp_path):
    with pytest.raises(script.Failure) as failure:
        run(FakeService(), request(workflow='demo-edit'), monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_WORKFLOW_NEEDS_SOURCE' and 'source_image' in failure.value.report['note']
    with pytest.raises(script.Failure) as failure:
        run(FakeService(), {**request(workflow='demo-t2i'), 'source': SOURCE}, monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_WORKFLOW_TAKES_NO_SOURCE'
    other = {**T2I, 'id': 'demo-vary', 'capabilities': {'input_modes': ['image-to-image']}}
    with pytest.raises(script.Failure) as failure:
        run(FakeService(workflows=(T2I, other)), request(workflow='demo-vary'), monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_WORKFLOW_NOT_TEXT_TO_IMAGE'


SOURCE = {'file': 'source.png', 'name': 'asuna-edit-0123456789ab-a1b2c3.png'}


def edit(monkeypatch, tmp_path, service, **extra):
    monkeypatch.setattr(script, '__file__', str(tmp_path / 'integration_image.py'))
    (tmp_path / 'source.png').write_bytes(PNG)
    return run(service, {**request(**extra), 'source': SOURCE}, monkeypatch, tmp_path)


def test_a_source_picture_is_uploaded_edited_by_an_edit_route_and_removed_again(monkeypatch, tmp_path):
    service = FakeService()
    report = edit(monkeypatch, tmp_path, service)
    assert report['workflow'] == 'demo-edit' and report['bytes'] == len(PNG)
    resolve = next(body for method, path, body in service.calls if path == '/project/resolve')
    assert resolve == {'input_type': 'image', 'input_mode': 'image-edit'}
    upload = next(body for method, path, body in service.calls if path == '/upload/image')
    assert PNG in upload and b'asuna-edit-0123456789ab-a1b2c3.png' in upload
    queued = next(body for method, path, body in service.calls if path == '/project/generate')
    assert queued['parameters']['input_image'] == SOURCE['name']
    assert service.deleted == [SOURCE['name']], 'the source does not stay on the service'


def test_a_source_stays_while_its_job_is_queued_and_a_later_call_clears_it(monkeypatch, tmp_path):
    slow = FakeService(states=('running',))
    with pytest.raises(script.Failure) as failure:
        edit(monkeypatch, tmp_path, slow, timeout=30)
    assert failure.value.report['error'] == 'IMAGE_JOB_STILL_RUNNING' and slow.deleted == []
    later = FakeService(states=('succeeded',))
    later.inputs = [{'name': SOURCE['name'], 'modified_time': 0}, {'name': 'someone-elses.png', 'modified_time': 0}]
    run(later, gen.validate({'job': 'job-0001-abcd'})[0], monkeypatch, tmp_path)
    assert later.deleted == [SOURCE['name']], "only this client's old uploads are cleared"


def test_a_failed_edit_removes_its_source_too(monkeypatch, tmp_path):
    failed = FakeService(states=('failed',))
    with pytest.raises(script.Failure) as failure:
        edit(monkeypatch, tmp_path, failed)
    assert failure.value.report['error'] == 'IMAGE_JOB_FAILED' and failed.deleted == [SOURCE['name']]


def test_an_option_the_workflow_does_not_declare_is_refused_before_queueing(monkeypatch, tmp_path):
    service = FakeService(workflows=({**T2I, 'parameter_schema': {'properties': {'prompt': {}}}},))
    with pytest.raises(script.Failure) as failure:
        run(service, request(options={'steps': 20}), monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_OPTION_NOT_IN_WORKFLOW'
    assert not any(path == '/project/generate' for _m, path, _b in service.calls)


def test_a_slow_job_is_reported_with_its_id_and_collected_later_without_drawing_again(monkeypatch, tmp_path):
    slow = FakeService(states=('running',))
    with pytest.raises(script.Failure) as failure:
        run(slow, request(timeout=30), monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_JOB_STILL_RUNNING'
    assert failure.value.report['prompt_id'] == 'job-0001-abcd'
    later, error = gen.validate({'job': 'job-0001-abcd'})
    assert error is None
    done = FakeService(states=('succeeded',))
    report = run(done, later, monkeypatch, tmp_path)
    assert report['state'] == 'succeeded'
    assert not any(path == '/project/generate' for _m, path, _b in done.calls)


@pytest.mark.parametrize('args, error', [
    ({}, 'PROMPT_REQUIRED'),
    ({'prompt': 'x', 'width': 500}, 'INVALID_WIDTH'),
    ({'prompt': 'x', 'workflow': 'http://elsewhere/x'}, 'INVALID_WORKFLOW'),
    ({'prompt': 'x', 'options': {'input_image': 'a.png'}}, 'OPTION_NOT_OFFERED'),
    ({'prompt': 'x', 'options': {'steps': 500}}, 'INVALID_OPTION'),
    ({'prompt': 'x', 'timeout': 900}, 'INVALID_TIMEOUT'),
    ({'job': '../../etc'}, 'INVALID_JOB'),
])
def test_what_the_namespace_may_be_asked_is_decided_on_the_host(args, error):
    value, failure = gen.validate(args)
    assert value is None and failure['error'] == error


class FakeRunner:
    def __init__(self, result):
        self.result, self.requests, self.sources = result, [], []

    def generate_image(self, value, source=None):
        self.requests.append(value)
        self.sources.append(source)
        return self.result


GOOD = {'report': {'generated': True, 'workflow': 'demo-t2i', 'prompt_id': 'job-0001-abcd', 'seed': 7,
                   'view_path': '/view?filename=a.png&subfolder=&type=output', 'bytes': len(PNG)}, 'body': PNG}


def test_the_picture_lands_in_the_workspace_and_is_registered_as_her_own(tmp_path):
    seen = []
    def register(data, meta):
        seen.append((data, meta))
        return {'registered': True, 'artifact_id': 'blob-demo'}
    runner = FakeRunner(GOOD)
    value = gen.generate({'prompt': 'a cat on a windowsill'}, runner=runner, workspace=tmp_path, register=register)
    assert value['generated'] and value['artifact']['artifact_id'] == 'blob-demo'
    assert (tmp_path / value['target_relative_path']).read_bytes() == PNG
    assert value['target_relative_path'].startswith('images/') and value['target_relative_path'].endswith('.png')
    assert seen[0][1]['endpoint'] == 'image' and seen[0][1]['artifact_path'].startswith('/view?')
    assert runner.requests[0]['endpoint'] == 'image' and runner.requests[0]['limit'] == gen.MAX_IMAGE_BYTES


def test_an_existing_file_is_never_overwritten_and_nothing_is_drawn(tmp_path):
    (tmp_path / 'mine.png').write_bytes(b'old')
    runner = FakeRunner(GOOD)
    value = gen.generate({'prompt': 'x', 'target_relative_path': 'mine.png'}, runner=runner, workspace=tmp_path)
    assert value['error'] == 'TARGET_EXISTS' and runner.requests == []
    assert (tmp_path / 'mine.png').read_bytes() == b'old'


def test_the_service_refusal_is_returned_as_it_was(tmp_path):
    refused = {'report': {'generated': False, 'error': 'IMAGE_SERVICE_REFUSED', 'http_status': 429}, 'body': b''}
    value = gen.generate({'prompt': 'x'}, runner=FakeRunner(refused), workspace=tmp_path)
    assert value == {'generated': False, 'error': 'IMAGE_SERVICE_REFUSED', 'http_status': 429}
    assert not list(tmp_path.iterdir())


def test_bytes_that_are_not_a_picture_are_not_written(tmp_path):
    odd = {'report': {**GOOD['report'], 'bytes': 4}, 'body': b'oops'}
    value = gen.generate({'prompt': 'x'}, runner=FakeRunner(odd), workspace=tmp_path)
    assert value['error'] == 'IMAGE_NOT_A_PICTURE' and not list(tmp_path.iterdir())


def test_the_tool_exists_only_with_an_image_endpoint(monkeypatch):
    from asuna import sandbox_backend
    monkeypatch.setattr(sandbox_backend, 'available', lambda config: True)
    endpoint = {'name': 'image', 'host': '127.0.0.1', 'port': 18191, 'target_port': 8191}
    assert gen.available({'integration': {'enabled': True, 'endpoints': [endpoint]}})
    assert not gen.available({'integration': {'enabled': True, 'endpoints': [{**endpoint, 'name': 'other'}]}})
    assert not gen.available({'integration': {'enabled': False, 'endpoints': [endpoint]}})


def test_the_script_reports_one_json_line_and_never_a_url_fetch(monkeypatch, tmp_path, capsys):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'endpoints': {'napcat': {'host': '127.0.0.1', 'port': 9001}}}), encoding='utf-8')
    monkeypatch.setattr(script, 'CONFIG_PATH', str(config))
    script.main(['x', json.dumps({'endpoint': 'image', 'limit': 1024, 'timeout': 30, 'prompt': 'x'})])
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert report == {'generated': False, 'error': 'ENDPOINT_NOT_CONFIGURED', 'endpoint': 'image'}


def test_the_plugin_learns_the_tool_from_the_broker_list():
    from asuna.tasks import ToolBroker
    names = [spec['name'] for spec in ToolBroker.specs.fget(None)]
    assert gen.GENERATE_IMAGE_TOOL_NAME in names and 'import_integration_artifact' in names
    source = open(__import__('asuna.native_worker', fromlist=['x']).__file__, encoding='utf-8').read()
    assert "return self.app.broker.specs" in source


def test_every_object_parameter_says_whether_it_takes_more_keys():
    """DSH refuses a tool schema whose object has no explicit additionalProperties (the whole action run fails)."""
    from asuna.tasks import ToolBroker
    def walk(schema, where):
        if isinstance(schema, dict):
            if schema.get('type') == 'object':
                assert isinstance(schema.get('additionalProperties'), bool), where
            for key, value in schema.items():
                walk(value, where + '.' + str(key))
    for spec in ToolBroker.specs.fget(None):
        walk(spec.get('parameters'), spec['name'])


def test_the_workflows_are_listed_with_their_guidance_and_nothing_is_drawn(monkeypatch, tmp_path):
    service = FakeService()
    value, error = gen.validate({'workflows': True})
    assert error is None and value['list']
    report = run(service, value, monkeypatch, tmp_path)
    assert [(w['workflow'], w.get('source_image')) for w in report['workflows']] == [
        ('demo-t2i', None), ('demo-edit', 'required')], 'ready ones, an edit route marked'
    listed = report['workflows'][0]
    assert listed['style'] == 'natural-language English' and listed['best_for'] == ['still life']
    assert listed['example'] == 'a lamp on a windowsill'
    assert not any(path == '/project/generate' for _m, path, _b in service.calls)


def test_a_drawn_picture_comes_back_with_the_guidance_of_its_workflow(monkeypatch, tmp_path):
    report = run(FakeService(), request(), monkeypatch, tmp_path)
    assert report['guidance']['not_for'] == ['portraits'] and report['guidance']['quality_prefix'] == 'best quality'


def test_the_host_returns_the_listing_and_says_how_to_use_it(tmp_path):
    listed = {'report': {'listed': True, 'workflows': [{'workflow': 'demo-t2i'}]}, 'body': b''}
    value = gen.generate({'workflows': True}, runner=FakeRunner(listed), workspace=tmp_path)
    assert value['workflows'] == [{'workflow': 'demo-t2i'}] and 'workflow' in value['note']
    assert not list(tmp_path.iterdir())


def test_the_result_says_to_look_before_reporting(tmp_path):
    value = gen.generate({'prompt': 'x'}, runner=FakeRunner(GOOD), workspace=tmp_path)
    assert 'read_image' in value['note'] and 'read_image' in gen.GENERATE_IMAGE_TOOL['description']


def test_a_source_is_read_with_the_tasks_own_fence_and_its_edit_registered_where_it_may_go(tmp_path):
    asked, kept = [], []
    def source(ref):
        asked.append(ref)
        return {'data': PNG, 'register': lambda data, meta: kept.append(meta) or {'registered': True}}
    runner = FakeRunner(GOOD)
    value = gen.generate({'prompt': 'make the sky orange', 'source_image': 'att-abc'}, runner=runner,
                         workspace=tmp_path, source=source, register=lambda data, meta: 1 / 0)
    assert value['generated'] and asked == ['att-abc'] and runner.sources == [PNG] and kept
    sent = runner.requests[0]['source']
    assert sent['file'] == 'source.png' and sent['name'].startswith(script.SOURCE_PREFIX) and sent['name'].endswith('.png')


def test_a_source_the_task_may_not_see_is_refused_in_its_own_words(tmp_path):
    def source(ref):
        raise PermissionError('IMAGE_ATTACHMENT_NOT_IN_SCENE: att-x 不在这个对话最近 7 天的图里')
    runner = FakeRunner(GOOD)
    value = gen.generate({'prompt': 'x', 'source_image': 'att-x'}, runner=runner, workspace=tmp_path, source=source)
    assert value['error'] == 'SOURCE_IMAGE_NOT_READABLE' and 'NOT_IN_SCENE' in value['detail'] and not runner.requests
    value = gen.generate({'prompt': 'x', 'source_image': 'att-x'}, runner=runner, workspace=tmp_path)
    assert value['error'] == 'SOURCE_IMAGE_UNAVAILABLE' and not runner.requests


def test_a_service_warning_keeps_its_code_and_the_sizes_it_used():
    said = script.warning({'code': 'input_downscaled', 'parameter': 'input_image', 'original_size': [2232, 4000],
                           'used_size': [1120, 2048], 'message': 'input image downscaled to fit the route'})
    assert said == 'input_downscaled: input image downscaled to fit the route (2232x4000 → 1120x2048)'
    assert script.warning('plain words') == 'plain words'


def test_a_route_that_needs_a_picture_this_tool_cannot_give_is_not_listed_and_is_refused(monkeypatch, tmp_path):
    inpaint = {**EDIT, 'id': 'demo-inpaint', 'parameter_schema': {
        'properties': {'prompt': {}, 'input_image': {}, 'mask_image': {}}, 'required': ['input_image', 'mask_image']}}
    service = FakeService(workflows=(T2I, EDIT, inpaint))
    listed = run(service, gen.validate({'workflows': True})[0], monkeypatch, tmp_path)
    assert [w['workflow'] for w in listed['workflows']] == ['demo-t2i', 'demo-edit']
    with pytest.raises(script.Failure) as failure:
        edit(monkeypatch, tmp_path, service, workflow='demo-inpaint')
    assert failure.value.report['error'] == 'IMAGE_WORKFLOW_NEEDS_MORE_PICTURES'
    assert failure.value.report['needs'] == ['mask_image'] and not service.deleted, 'refused before any upload'


CHARACTER = {**T2I, 'id': 'demo-character', 'parameter_schema': {'properties': {
    **T2I['parameter_schema']['properties'],
    'loras': {'type': 'object', 'additionalProperties': False,
              'properties': {'character': {'type': 'number', 'minimum': -2, 'maximum': 2, 'default': 0.9}}},
    'pose': {'type': 'string'}, 'pose_strength': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 1.0}}}}
NO_STRENGTH = {**T2I, 'id': 'demo-pose-only', 'parameter_schema': {'properties': {
    **T2I['parameter_schema']['properties'], 'pose': {'type': 'string'}}}}
POSE_USED = {'source': 'library', 'id': 'full_single_P003_front', 'angle': 'front', 'people_detected': 1,
             'skeleton_url': '/view?filename=s.png&subfolder=_poses&type=input'}


class PoseService(FakeService):
    def __init__(self, **kw):
        super().__init__(workflows=(T2I, CHARACTER, NO_STRENGTH), **kw)
        self.pose_reply = POSE_USED

    def json(self, method, path, body=None):
        if path.startswith('/project/poses'):
            self.calls.append((method, path, body))
            return {'query': 'sit', 'total_matches': 1, 'results': [
                {'id': 'full_single_P003', 'name': 'Sitting', 'name_zh': 'x', 'category': 'sitting', 'people': 1,
                 'views': {'front': 'full_single_P003_front'}}]}
        value = super().json(method, path, body)
        if path == '/project/generate':
            sent = body['parameters']
            value['applied_parameters'] = {k: sent[k] for k in ('loras', 'pose_strength') if k in sent}
            value['pose'] = self.pose_reply if 'pose' in sent else None
        return value


def test_loras_pose_and_strength_are_checked_for_type_and_range_only():
    ok, error = gen.validate({'prompt': 'x', 'loras': {'character': 0.4}, 'pose': 'full_single_P003_front', 'pose_strength': 0.5})
    assert error is None and ok['loras'] == {'character': 0.4} and ok['pose'] == 'full_single_P003_front'
    assert gen.validate({'prompt': 'x', 'loras': {'character': 0}})[1] is None, 'zero is a valid strength: it turns it off'
    for args, code in (({'loras': [1]}, 'INVALID_LORAS'), ({'loras': {'character': 3}}, 'INVALID_LORA_STRENGTH'),
                       ({'loras': {'character': True}}, 'INVALID_LORA_STRENGTH'), ({'loras': {'a b': 1}}, 'INVALID_LORAS'),
                       ({'pose': 5}, 'INVALID_POSE'), ({'pose_strength': 1.5}, 'INVALID_POSE_STRENGTH'),
                       ({'poses_angle': 'x'}, 'POSES_FILTER_WITHOUT_QUERY')):
        assert gen.validate({'prompt': 'x', **args})[1]['error'] == code, args


def test_loras_and_pose_are_forwarded_whole_and_the_receipt_says_what_the_service_applied(monkeypatch, tmp_path):
    service = PoseService()
    report = run(service, request(workflow='demo-character', loras={'character': 0.4}, pose='full_single_P003_front',
                                  pose_strength=0.7), monkeypatch, tmp_path)
    queued = next(body for _m, path, body in service.calls if path == '/project/generate')
    assert queued['parameters']['loras'] == {'character': 0.4} and queued['parameters']['pose'] == 'full_single_P003_front'
    assert queued['parameters']['pose_strength'] == 0.7
    assert report['pose']['people_detected'] == 1 and report['loras'] == {'character': 0.4} and report['pose_strength'] == 0.7
    plain = run(PoseService(), request(workflow='demo-character'), monkeypatch, tmp_path)
    assert plain['pose'] is None, 'no pose used is said as null'


def test_the_receipt_keeps_pose_null_when_no_pose_was_used(tmp_path):
    good = {'report': {**GOOD['report'], 'pose': None}, 'body': PNG}
    value = gen.generate({'prompt': 'x'}, runner=FakeRunner(good), workspace=tmp_path)
    assert 'pose' in value and value['pose'] is None
    used = {'report': {**GOOD['report'], 'pose': POSE_USED, 'loras': {'character': 0.4}}, 'body': PNG}
    (tmp_path / 'second').mkdir()
    value = gen.generate({'prompt': 'x'}, runner=FakeRunner(used), workspace=tmp_path / 'second')
    assert value['pose']['people_detected'] == 1 and value['loras'] == {'character': 0.4}
    (tmp_path / 'third').mkdir()
    picked = gen.generate({'job': 'job-0001-abcd'}, runner=FakeRunner(good), workspace=tmp_path / 'third')
    assert 'pose' not in picked, 'a job pick-up carries no pose, so it must not say null'


def test_a_lora_id_the_route_does_not_declare_is_refused_with_the_ids_it_has(monkeypatch, tmp_path):
    service = PoseService()
    with pytest.raises(script.Failure) as failure:
        run(service, request(workflow='demo-character', loras={'nope': 0.5}), monkeypatch, tmp_path)
    report = failure.value.report
    assert report['error'] == 'IMAGE_LORA_NOT_IN_WORKFLOW' and report['allowed'] == ['character'] and report['loras'] == ['nope']
    assert report['defaults'] == {'character': 0.9} and 'character' in report['note']
    with pytest.raises(script.Failure) as failure:
        run(service, request(workflow='demo-t2i', loras={'character': 0.5}), monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_OPTION_NOT_IN_WORKFLOW' and failure.value.report['options'] == ['loras']
    with pytest.raises(script.Failure) as failure:
        run(service, request(workflow='demo-pose-only', pose_strength=0.5), monkeypatch, tmp_path)
    assert failure.value.report['options'] == ['pose_strength']
    assert not any(path == '/project/generate' for _m, path, _b in service.calls)


def test_the_route_list_reads_loras_and_pose_from_the_schema_not_from_a_fixed_table(monkeypatch, tmp_path):
    listed = {w['workflow']: w for w in run(PoseService(), gen.validate({'workflows': True})[0], monkeypatch, tmp_path)['workflows']}
    assert listed['demo-character']['loras'] == {'character': 0.9} and 'loras_note' in listed['demo-character']
    assert listed['demo-character']['pose'] is True and listed['demo-character']['pose_strength'] == 1.0
    assert listed['demo-pose-only']['pose'] is True and 'pose_strength' not in listed['demo-pose-only']
    assert listed['demo-t2i']['pose'] is False and 'loras' not in listed['demo-t2i']


def test_the_pose_search_draws_nothing_and_returns_ids_names_people_and_views(monkeypatch, tmp_path):
    value, error = gen.validate({'poses': 'sit', 'poses_people': 1, 'poses_angle': 'front', 'poses_limit': 3})
    assert error is None and value['pose_search'] == {'q': 'sit', 'people': 1, 'angle': 'front', 'limit': 3}
    service = PoseService()
    report = run(service, value, monkeypatch, tmp_path)
    assert report['poses'][0]['views'] == {'front': 'full_single_P003_front'} and report['poses'][0]['people'] == 1
    assert report['poses'][0]['id'] == 'full_single_P003' and report['total_matches'] == 1
    path = next(path for _m, path, _b in service.calls if path.startswith('/project/poses'))
    assert path == '/project/poses?q=sit&people=1&angle=front&limit=3'
    assert not any(p == '/project/generate' for _m, p, _b in service.calls)
    assert gen.validate({'poses': ''})[1]['error'] == 'INVALID_POSES'
    assert gen.validate({'poses': 'x', 'poses_limit': 99})[1]['error'] == 'INVALID_POSES_LIMIT'
    host = gen.generate({'poses': 'sit'}, runner=FakeRunner({'report': {'listed': True, 'query': 'sit', 'poses': []}, 'body': b''}),
                        workspace=tmp_path)
    assert host == {'query': 'sit', 'poses': []} and not list(tmp_path.iterdir())


def test_a_pose_search_with_no_match_says_what_to_try_next(monkeypatch, tmp_path):
    class Empty(PoseService):
        def json(self, method, path, body=None):
            if path.startswith('/project/poses'):
                return {'query': 'x', 'total_matches': 0, 'results': []}
            return super().json(method, path, body)
    report = run(Empty(), gen.validate({'poses': '坐'})[0], monkeypatch, tmp_path)
    assert report['poses'] == [] and 'sit' in report['note']


def test_the_tool_description_points_at_list_routes_then_poses():
    text = gen.GENERATE_IMAGE_TOOL['description']
    assert 'list_routes=yes also shows each route' in text and 'poses=<words>' in text
    assert {'loras', 'pose', 'pose_strength', 'poses', 'poses_people', 'poses_angle', 'poses_limit'} <= set(
        gen.GENERATE_IMAGE_TOOL['parameters'])
