"""generate_image: the fixed image-service sequence, its validation, and the picture landing as her own."""
import json

import pytest

from asuna import image_generation as gen
from asuna import integration_image as script

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
T2I = {'id': 'demo-t2i', 'ready': True, 'capabilities': {'input_modes': ['text-to-image']},
       'parameter_schema': {'properties': {k: {} for k in ('prompt', 'negative_prompt', 'width', 'height', 'seed',
                                                            'steps', 'cfg', 'batch_size')}}}
EDIT = {'id': 'demo-edit', 'ready': True, 'capabilities': {'input_modes': ['image-to-image']},
        'parameter_schema': {'properties': {'prompt': {}, 'input_image': {}}}}


class FakeService:
    """The image service's agent API, as far as the script uses it."""
    def __init__(self, states=('queued', 'running', 'succeeded'), workflows=(T2I, EDIT)):
        self.states = list(states)
        self.workflows = {w['id']: w for w in workflows}
        self.calls = []

    def json(self, method, path, body=None):
        self.calls.append((method, path.split('?')[0], body))
        if path == '/project/resolve':
            return {'selected_workflow': 'demo-t2i', 'matches': [{'workflow_id': 'demo-t2i', 'ready': True}]}
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

    def request(self, method, path, body=None, *, limit=0):
        self.calls.append((method, path.split('?')[0], body))
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


def test_a_named_workflow_must_draw_from_text(monkeypatch, tmp_path):
    with pytest.raises(script.Failure) as failure:
        run(FakeService(), request(workflow='demo-edit'), monkeypatch, tmp_path)
    assert failure.value.report['error'] == 'IMAGE_WORKFLOW_NOT_TEXT_TO_IMAGE'


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
        self.result, self.requests = result, []

    def generate_image(self, value):
        self.requests.append(value)
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
