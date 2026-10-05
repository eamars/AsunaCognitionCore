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
BODY_PATH = '/data/artifact.bin'
CHUNK = 65536
POLL_SECONDS = 2.0
TEXT_TO_IMAGE = 'text-to-image'


class Failure(Exception):
    def __init__(self, error, **detail):
        super().__init__(error)
        self.report = {'error': error, **detail}


class Service:
    def __init__(self, host, port, timeout, connect=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.connect = connect

    def request(self, method, path, body=None, *, limit=4 * 1024 * 1024):
        """One request; returns (status, headers, bytes). Never follows a redirect."""
        import http.client
        connection = None
        try:
            connection = (self.connect or http.client.HTTPConnection)(self.host, self.port, timeout=self.timeout)
            headers = {'Host': '%s:%d' % (self.host, self.port), 'Accept': '*/*', 'Connection': 'close',
                       'User-Agent': 'asuna-generate-image/1'}
            data = None
            if body is not None:
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


def text_to_image(workflow):
    modes = (workflow.get('capabilities') or {}).get('input_modes') or ()
    return TEXT_TO_IMAGE in modes


def choose_workflow(service, request):
    """The named workflow when it is ready and draws from text; otherwise the service's own choice."""
    name = request.get('workflow')
    if not name:
        query = {'domain': 'general', 'content_mode': 'sfw', 'input_type': 'text', 'input_mode': 'text_to_image',
                 'prompt_granularity': 'detailed'}
        if request.get('style'):
            query['style'] = request['style']
        resolved = service.json('POST', '/project/resolve', query)
        ready = [m.get('workflow_id') for m in resolved.get('matches') or () if isinstance(m, dict) and m.get('ready')]
        name = resolved.get('selected_workflow') if resolved.get('selected_workflow') in ready else (ready or [None])[0]
        if not name:
            raise Failure('IMAGE_NO_READY_WORKFLOW', note='服务没有给出可用（ready）的文生图路线。')
    from urllib.parse import quote
    detail = service.json('GET', '/project/workflows/' + quote(name, safe=''))
    # The detail is {"workflow": <description>, "prompt": <graph>}; the description is what is checked.
    workflow = detail['workflow'] if isinstance(detail.get('workflow'), dict) else detail
    if not workflow.get('ready'):
        raise Failure('IMAGE_WORKFLOW_NOT_READY', workflow=name)
    if not text_to_image(workflow):
        raise Failure('IMAGE_WORKFLOW_NOT_TEXT_TO_IMAGE', workflow=name,
                      input_modes=(workflow.get('capabilities') or {}).get('input_modes'))
    return name, workflow


def parameters(request, workflow):
    """Only the fields the workflow declares; anything else is refused here, as the service would."""
    wanted = {'prompt': request['prompt'], 'batch_size': 1}
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


def first_view(job):
    for item in job.get('outputs') or ():
        url = item.get('url') if isinstance(item, dict) else None
        if isinstance(url, str) and url.startswith('/view?') and item.get('kind', 'images') == 'images':
            return url
    return None


def run(request, service, *, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + request['timeout']
    report = {}
    if request.get('job'):
        report['prompt_id'] = request['job']
    else:
        name, workflow = choose_workflow(service, request)
        queued = service.json('POST', '/project/generate',
                              {'workflow': name, 'parameters': parameters(request, workflow), 'client_id': 'asuna'})
        effective = queued.get('effective_parameters') or queued.get('applied_parameters') or {}
        report.update({'workflow': name, 'prompt_id': queued.get('prompt_id'),
                       'seed': effective.get('seed'), 'width': effective.get('width'),
                       'height': effective.get('height'),
                       'warnings': [w.get('message', w) if isinstance(w, dict) else w
                                    for w in queued.get('warnings') or ()][:5]})
        if not report['prompt_id']:
            raise Failure('IMAGE_SERVICE_BAD_RESPONSE', step='POST /project/generate')
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
        print(json.dumps({'generated': True, **run(request, service)}, ensure_ascii=False))
    except Failure as failure:
        print(json.dumps({'generated': False, **failure.report}, ensure_ascii=False))
    except Exception as exc:                       # 任何意外都如实报成失败，不冒充成功
        print(json.dumps({'generated': False, 'error': 'IMAGE_GENERATION_CRASHED',
                          'detail': (type(exc).__name__ + ': ' + str(exc))[:200]}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
