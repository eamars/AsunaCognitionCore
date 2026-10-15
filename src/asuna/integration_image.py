"""Trusted one-shot image generation, run only inside the managed integration namespace.

The action brain supplies a prompt and a few choices; this script supplies the
sequence of the image service's own agent API (project-comfyui-agent/v1): pick a
ready text-to-image workflow (the one named, or POST /project/resolve), check the
options against that workflow's parameter_schema, POST /project/generate, poll
GET /project/jobs/{prompt_id}, then GET the first /view output. Only the alias
named in the request is reachable, over its relay; no URL is ever accepted. The
picture is written to /data/artifact.bin and the report is one JSON line on
stdout; the host re-reads the file and verifies count and SHA-256 itself.
Stdlib only.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time


CONFIG_PATH = os.environ.get('ASUNA_INTEGRATION_CONFIG', '/integration/config.json')
BODY_PATH = os.path.join(os.environ.get('ASUNA_INTEGRATION_DATA', '/data'), 'artifact.bin')
CHUNK = 65536
POLL_SECONDS = 2.0
TEXT_TO_IMAGE = 'text-to-image'
EDIT_MODE = 'image-edit'                 # the service's input mode for an instruction edit of one picture
SOURCE_PARAMETER = 'input_image'         # a workflow that works from an uploaded picture declares it
SOURCE_PREFIX = 'asuna-edit-'            # the name of every source this client uploads (content-addressed)
SOURCE_KEPT_SECONDS = 3600               # a source older than this has outlived any job that used it


class Failure(Exception):
    def __init__(self, error, **detail):
        super().__init__(error)
        self.report = {'error': error, **detail}


class Service:
    def __init__(self, host, port, timeout, connect=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.connect = connect

    def request(self, method, path, body=None, *, limit=4 * 1024 * 1024, content_type=None):
        """One request; returns (status, headers, bytes). Never follows a redirect. A body is JSON unless it is
        bytes with its own content type (the source picture's upload)."""
        import http.client
        connection = None
        try:
            connection = (self.connect or http.client.HTTPConnection)(self.host, self.port, timeout=self.timeout)
            headers = {'Host': '%s:%d' % (self.host, self.port), 'Accept': '*/*', 'Connection': 'close',
                       'User-Agent': 'asuna-generate-image/1'}
            data = None
            if isinstance(body, bytes):
                data = body
                headers['Content-Type'] = content_type
            elif body is not None:
                data = json.dumps(body).encode('utf-8')
                headers['Content-Type'] = 'application/json'
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            chunks, total = [], 0
            while total < limit + 1:
                piece = response.read(CHUNK)
                if not piece:
                    break
                chunks.append(piece)
                total += len(piece)
            return response.status, {k.lower(): v for k, v in response.getheaders()}, b''.join(chunks)[:limit + 1]
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise Failure('IMAGE_SERVICE_UNREACHABLE', detail=(type(exc).__name__ + ': ' + str(exc))[:200],
                          step='%s %s' % (method, path.split('?')[0]))
        finally:
            if connection is not None:
                try:
                    connection.close()
                except OSError:
                    pass

    def json(self, method, path, body=None):
        status, _headers, data = self.request(method, path, body)
        try:
            value = json.loads(data.decode('utf-8')) if data else None
        except ValueError:
            value = None
        if status != 200:
            error = (value or {}).get('error') if isinstance(value, dict) else None
            raise Failure('IMAGE_SERVICE_REFUSED', http_status=status, step='%s %s' % (method, path.split('?')[0]),
                          service_error=error if isinstance(error, dict) else data.decode('utf-8', 'replace')[:400])
        if not isinstance(value, dict):
            raise Failure('IMAGE_SERVICE_BAD_RESPONSE', step='%s %s' % (method, path.split('?')[0]))
        return value


def clip(value, chars=300, items=8):
    if isinstance(value, str):
        return value[:chars]
    if isinstance(value, list):
        return [clip(item, chars, items) for item in value[:items]]
    return value


def guidance(workflow):
    """How this workflow wants to be prompted and what it is for, in the service's own words."""
    prompting = workflow.get('prompting') or {}
    selection = workflow.get('selection') or {}
    hints = workflow.get('agent_hints') or {}
    recommended = prompting.get('recommended') or {}
    examples = [e.get('prompt') for e in prompting.get('examples') or () if isinstance(e, dict) and e.get('prompt')]
    value = {'style': prompting.get('style'), 'structure': prompting.get('structure'),
             'quality_prefix': prompting.get('quality_prefix'), 'prompt_scope': hints.get('prompt_scope'),
             'best_for': selection.get('best_for'), 'not_for': selection.get('not_for'),
             'size': ([recommended['width'], recommended['height']]
                      if 'width' in recommended and 'height' in recommended else None),
             'example': examples[0] if examples else None}
    return {key: clip(item) for key, item in value.items() if item}


def list_workflows(service):
    listing = service.json('GET', '/project/workflows')
    out = []
    for workflow in listing.get('workflows') or ():
        if isinstance(workflow, dict) and workflow.get('ready') and (text_to_image(workflow) or takes_source(workflow)):
            out.append({'workflow': workflow.get('id'), 'description': clip(workflow.get('description') or '', 200),
                        **({'source_image': 'required' if needs_source(workflow) else 'optional'}
                           if takes_source(workflow) else {}),
                        **guidance(workflow)})
    return out


def text_to_image(workflow):
    modes = (workflow.get('capabilities') or {}).get('input_modes') or ()
    return TEXT_TO_IMAGE in modes


def takes_source(workflow):
    """The workflow declares the uploaded picture it works from (parameter_schema input_image)."""
    return SOURCE_PARAMETER in ((workflow.get('parameter_schema') or {}).get('properties') or {})


def needs_source(workflow):
    return SOURCE_PARAMETER in ((workflow.get('parameter_schema') or {}).get('required') or ())


def choose_workflow(service, request):
    """The named workflow when it is ready and fits the request (a source picture or none); otherwise the service's
    own choice: an edit route for a source picture, a text-to-image one without."""
    name, source = request.get('workflow'), bool(request.get('source'))
    if not name:
        query = ({'input_type': 'image', 'input_mode': EDIT_MODE} if source else
                 {'domain': 'general', 'content_mode': 'sfw', 'input_type': 'text', 'input_mode': 'text_to_image',
                  'prompt_granularity': 'detailed'})
        if request.get('style'):
            query['style'] = request['style']
        resolved = service.json('POST', '/project/resolve', query)
        ready = [m.get('workflow_id') for m in resolved.get('matches') or () if isinstance(m, dict) and m.get('ready')]
        name = resolved.get('selected_workflow') if resolved.get('selected_workflow') in ready else (ready or [None])[0]
        if not name:
            raise Failure('IMAGE_NO_READY_WORKFLOW', note='服务没有给出可用（ready）的%s路线。' % ('改图' if source else '文生图'))
    from urllib.parse import quote
    detail = service.json('GET', '/project/workflows/' + quote(name, safe=''))
    # The detail is {"workflow": <description>, "prompt": <graph>}; the description is what is checked.
    workflow = detail['workflow'] if isinstance(detail.get('workflow'), dict) else detail
    if not workflow.get('ready'):
        raise Failure('IMAGE_WORKFLOW_NOT_READY', workflow=name)
    if source and not takes_source(workflow):
        raise Failure('IMAGE_WORKFLOW_TAKES_NO_SOURCE', workflow=name,
                      note='这条路线只从文字画，不收原图；改图换一条 list_routes=yes 里标着 source_image 的路线，'
                           '或不写 workflow 让服务挑。')
    if not source and needs_source(workflow):
        raise Failure('IMAGE_WORKFLOW_NEEDS_SOURCE', workflow=name,
                      note='这条路线要一张原图：写 source_image（图旁标的 ref 或一张图的 artifact_id）；只想从文字画就换一条路线。')
    if not source and not text_to_image(workflow):
        raise Failure('IMAGE_WORKFLOW_NOT_TEXT_TO_IMAGE', workflow=name,
                      input_modes=(workflow.get('capabilities') or {}).get('input_modes'))
    return name, workflow


def upload(service, source):
    """The source picture uploaded under its content name; returns the name the workflow takes as input_image."""
    data = Path(__file__).with_name(source['file']).read_bytes()
    boundary = 'asuna' + hashlib.sha256(data).hexdigest()[:24]
    head = ('--%s\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n'
            '--%s\r\nContent-Disposition: form-data; name="image"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (boundary, boundary, source['name'])).encode('utf-8')
    body = head + data + ('\r\n--%s--\r\n' % boundary).encode('utf-8')
    status, _headers, answer = service.request('POST', '/upload/image', body,
                                               content_type='multipart/form-data; boundary=' + boundary)
    try:
        value = json.loads(answer.decode('utf-8'))
    except ValueError:
        value = None
    if status != 200 or not isinstance(value, dict) or not value.get('name'):
        raise Failure('IMAGE_SOURCE_UPLOAD_REFUSED', http_status=status,
                      service_error=answer.decode('utf-8', 'replace')[:400])
    return (value['subfolder'] + '/' if value.get('subfolder') else '') + value['name']


def forget(service, name):
    """The uploaded source removed from the service again; a failure is said, never raised."""
    from urllib.parse import quote
    try:
        status, _headers, _body = service.request('DELETE', '/project/inputs/' + quote(name, safe=''))
        return status == 200
    except Failure:
        return False


def parameters(request, workflow, source_name=None):
    """Only the fields the workflow declares; anything else is refused here, as the service would."""
    wanted = {'prompt': request['prompt'], 'batch_size': 1, **({SOURCE_PARAMETER: source_name} if source_name else {})}
    for key in ('negative_prompt', 'width', 'height', 'seed'):
        if key in request:
            wanted[key] = request[key]
    wanted.update(request.get('options') or {})
    allowed = ((workflow.get('parameter_schema') or {}).get('properties') or {})
    unknown = sorted(key for key in wanted if key not in allowed and key != 'batch_size')
    if unknown:
        raise Failure('IMAGE_OPTION_NOT_IN_WORKFLOW', workflow=workflow.get('id'), options=unknown,
                      allowed=sorted(k for k in allowed if k not in ('subject', 'filename_prefix')))
    if 'batch_size' not in allowed:
        wanted.pop('batch_size')
    return wanted


def warning(item):
    """A service warning in its own words: its code and message, and the sizes when it changed the source
    (input_downscaled, input_first_frame, over_pixel_budget…)."""
    if not isinstance(item, dict):
        return clip(str(item))
    sizes = ' (%s → %s)' % ('x'.join(map(str, item['original_size'])), 'x'.join(map(str, item['used_size']))) \
        if isinstance(item.get('original_size'), list) and isinstance(item.get('used_size'), list) else ''
    return clip(('%s: ' % item['code'] if item.get('code') else '') + str(item.get('message') or '') + sizes)


def first_view(job):
    for item in job.get('outputs') or ():
        url = item.get('url') if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith('/view?') and item.get('kind', 'images') == 'images':
            return url
    return None


def run(request, service, *, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + request['timeout']
    report = {}
    if request.get('list'):
        return {'workflows': list_workflows(service)}
    sweep(service)
    if request.get('job'):
        report['prompt_id'] = request['job']
        return collect(service, request, report, deadline, clock, sleep)
    name, workflow = choose_workflow(service, request)
    uploaded = upload(service, request['source']) if request.get('source') else None
    waiting = False
    try:
        queued = service.json('POST', '/project/generate', {'workflow': name, 'client_id': 'asuna',
                                                            'parameters': parameters(request, workflow, uploaded)})
        effective = queued.get('effective_parameters') or queued.get('applied_parameters') or {}
        report.update({'workflow': name, 'prompt_id': queued.get('prompt_id'),
                       'seed': effective.get('seed'), 'width': effective.get('width'),
                       'height': effective.get('height'),
                       'warnings': [warning(w) for w in queued.get('warnings') or ()][:5],
                       'guidance': guidance(workflow)})
        if not report['prompt_id']:
            raise Failure('IMAGE_SERVICE_BAD_RESPONSE', step='POST /project/generate')
        return collect(service, request, report, deadline, clock, sleep)
    except Failure as failure:
        waiting = failure.report.get('error') == 'IMAGE_JOB_STILL_RUNNING'
        raise
    finally:
        # The source can be a photo of someone: it does not stay on the service once its job is over. A job still
        # queued needs it; a later call clears it (sweep).
        if uploaded and not waiting:
            forget(service, uploaded)


def sweep(service, now=None):
    """Sources this client uploaded that outlived their job (one left for a queued job, or a run cut short)."""
    try:
        listing = service.json('GET', '/project/inputs')
    except Failure:
        return
    moment = time.time() if now is None else now
    for item in listing.get('files') or ():
        name = item.get('name') if isinstance(item, dict) else None
        stamp = item.get('modified_time') if isinstance(item, dict) else None
        if (isinstance(name, str) and name.startswith(SOURCE_PREFIX) and isinstance(stamp, (int, float))
                and moment - stamp > SOURCE_KEPT_SECONDS):
            forget(service, name)


def collect(service, request, report, deadline, clock, sleep):
    """Wait for the job and fetch its picture into /data/artifact.bin."""
    from urllib.parse import quote
    while True:
        job = service.json('GET', '/project/jobs/' + quote(report['prompt_id'], safe=''))
        state = job.get('state')
        report.update({'state': state, 'queued_ms': job.get('queued_ms'), 'elapsed_ms': job.get('elapsed_ms')})
        if state == 'succeeded':
            break
        if state == 'failed':
            raise Failure('IMAGE_JOB_FAILED', **report, phase=job.get('phase'),
                          service_error=job.get('error') or job.get('status'))
        if clock() + POLL_SECONDS > deadline:
            raise Failure('IMAGE_JOB_STILL_RUNNING', **report,
                          note='服务还在排队或生成；用 job=prompt_id 再调用一次就能取回这张，不用重画。')
        sleep(POLL_SECONDS)
    view = first_view(job)
    if not view:
        raise Failure('IMAGE_JOB_HAS_NO_IMAGE', **report)
    status, headers, body = service.request('GET', view, limit=request['limit'])
    if status != 200:
        raise Failure('IMAGE_DOWNLOAD_REFUSED', **report, http_status=status)
    if len(body) > request['limit']:
        raise Failure('IMAGE_TOO_LARGE', **report, max_bytes=request['limit'])
    Path(BODY_PATH).write_bytes(body)
    report.update({'view_path': view, 'content_type': headers.get('content-type'), 'bytes': len(body),
                   'sha256': hashlib.sha256(body).hexdigest()})
    return report


def main(argv):
    try:
        request = json.loads(argv[1]) if len(argv) > 1 else {}
        endpoint = request.get('endpoint')
        if not isinstance(endpoint, str) or type(request.get('limit')) is not int \
                or not 0 < float(request.get('timeout', 0)) <= 600:
            raise Failure('INVALID_GENERATE_REQUEST')
        configured = json.loads(Path(CONFIG_PATH).read_text(encoding='utf-8')).get('endpoints') or {}
        entry = configured.get(endpoint)
        if not isinstance(entry, dict) or type(entry.get('port')) is not int:
            raise Failure('ENDPOINT_NOT_CONFIGURED', endpoint=str(endpoint)[:80])
        service = Service(entry.get('host') or '127.0.0.1', entry['port'], 30)
        value = run(request, service)
        print(json.dumps({('listed' if 'workflows' in value else 'generated'): True, **value}, ensure_ascii=False))
    except Failure as failure:
        print(json.dumps({'generated': False, **failure.report}, ensure_ascii=False))
    except Exception as exc:                       # 任何意外都如实报成失败，不冒充成功
        print(json.dumps({'generated': False, 'error': 'IMAGE_GENERATION_CRASHED',
                          'detail': (type(exc).__name__ + ': ' + str(exc))[:200]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
