"""Pictures from the configured local image service, for any task (owner 2026-10-06).

A task from any conversation may draw with the endpoint aliased `image`; the integration group stays
owner-only. The action brain gives a prompt and a few choices, never a request: the host runs
integration_image.py in the managed namespace, where only that relay is reachable, writes the picture into
the task workspace and registers it as her own (source `integration:image:...`), so a later turn can attach
it. Public services remain allowed; the brief names this one first because only its pictures go out with a
message. Stdlib only apart from the injected runner and registration hook, so it tests offline.
"""
from __future__ import annotations
import hashlib
import re
import secrets

from . import clock
from .integration_image import SOURCE_PREFIX
from .integration_import import resolve_target, validate_target_path

IMAGE_ENDPOINT = 'image'
GENERATE_IMAGE_TOOL_NAME = 'generate_image'
MAX_IMAGE_BYTES = 8 * 1024 * 1024        # the namespace's file-size cap and the outbound picture cap
DEFAULT_TIMEOUT, MIN_TIMEOUT, MAX_TIMEOUT = 180, 30, 300
PROMPT_CHARS = 8000
SOURCE_REF_CHARS = 512
POSE_ANGLES = ('front', 'diag', 'side', 'high', 'low')
POSE_QUERY_CHARS, POSE_REF_CHARS, LORA_MAX = 80, 512, 12
OPTION_RULES = {'steps': ('int', 1, 100), 'cfg': ('number', 0, 30),
                'sampler_name': ('name', None, None), 'scheduler': ('name', None, None)}

GENERATE_IMAGE_TOOL = {
    'name': GENERATE_IMAGE_TOOL_NAME,
    'description': ('Draw one picture with the local image service and put it in this task workspace. '
                    'list_routes=yes lists the ready workflows (what each is for, not for, and how '
                    'it wants to be prompted) without drawing; pick one and write the prompt in its style and '
                    'language (most want English). Then give the prompt and optionally that workflow id (otherwise '
                    'the service picks a generic anime one, optionally for a style), negative_prompt, width/height '
                    '(64-2048, multiples of 8), seed, and options (steps, cfg, sampler_name, scheduler) that the '
                    'workflow declares. Waits up to timeout seconds (default 180, max 300); a job still running '
                    'is reported with its prompt_id: call again with job=<prompt_id> to collect it instead of '
                    'drawing again. Nobody has seen the picture until you look: read_image with '
                    'artifact.artifact_id, compare it with what was asked, and draw again (better prompt or another '
                    'workflow) when it is wrong. To edit a picture, give source_image (its ref or artifact_id, as '
                    'read_image takes it) and say the change in the prompt; list_routes marks the routes that take '
                    'one. Before drawing: list_routes=yes also shows each route\'s loras ({id: default strength}) and '
                    'whether it takes pose; then poses=<words> searches the pose library without drawing '
                    '(poses_people, poses_angle, poses_limit optional) and returns view ids for pose. '
                    'loras={id: strength} (-2..2, 0 turns it off; unlisted ids are refused), pose=<view id>, '
                    'pose_strength 0..1 only where the route lists it; the reply carries pose (null if none). '
                    'The picture is registered as your own image, so a later turn can '
                    'send it with a message; show it in a report as a relative Markdown image. Returns the '
                    'workflow and its prompting guidance, seed, size, bytes and SHA-256 actually written, or the '
                    'service\'s real refusal.'),
    'parameters': {'prompt': {'type': 'string'},
                   'negative_prompt': {'type': 'string'},
                   'workflow': {'type': 'string'},
                   'style': {'type': 'string'},
                   'width': {'type': 'integer'},
                   'height': {'type': 'integer'},
                   'seed': {'type': 'integer'},
                   'options': {'type': 'object', 'additionalProperties': False,
                               'properties': {'steps': {'type': 'integer'}, 'cfg': {'type': 'number'},
                                              'sampler_name': {'type': 'string'},
                                              'scheduler': {'type': 'string'}}},
                   'loras': {'type': 'object', 'additionalProperties': True,
                             'description': 'LoRA strengths {id: -2..2}; ids and defaults per route in list_routes=yes'},
                   'pose': {'type': 'string', 'description': 'a view id (or pose id) from poses=<words>'},
                   'pose_strength': {'type': 'number'},
                   'poses': {'type': 'string', 'description': 'search the pose library, draws nothing'},
                   'poses_people': {'type': 'integer'},
                   'poses_angle': {'type': 'string'},
                   'poses_limit': {'type': 'integer'},
                   'job': {'type': 'string'},
                   'source_image': {'type': 'string'},
                   'workflows': {'type': 'boolean'},
                   'target_relative_path': {'type': 'string'},
                   'timeout': {'type': 'integer'}}}

SIGNATURES = ((b'\x89PNG\r\n\x1a\n', 'png'), (b'\xff\xd8\xff', 'jpg'), (b'GIF87a', 'gif'), (b'GIF89a', 'gif'))


def available(config):
    """The tool exists for a task only when the integration runs and has an `image` endpoint."""
    from . import sandbox_backend
    profile = (config or {}).get('integration') or {}
    endpoints = profile.get('endpoints') or ()
    return (profile.get('enabled') is True and sandbox_backend.available(config)
            and any(isinstance(e, dict) and e.get('name') == IMAGE_ENDPOINT for e in endpoints))


def _error(reason, **detail):
    return {'generated': False, 'error': reason, **detail}


def _given(value):
    """What she gave, for a refusal (bounded)."""
    if value is None:
        return '没给'
    if isinstance(value, str):
        return '给的是 %r' % value[:60] if len(value) <= 60 else '给的是 %d 字' % len(value)
    return '给的是 %s %s' % (type(value).__name__, str(value)[:40])


OPTION_WORDS = {'steps': 'steps 要是 1..100 的整数', 'cfg': 'cfg 要是 0..30 的数',
                'sampler_name': 'sampler_name 要是小写字母、数字或 _（80 字以内）',
                'scheduler': 'scheduler 要是小写字母、数字或 _（80 字以内）'}
AGAIN = '可以再试一次；还不行就不画这张，写进报告'


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def validate(args):
    """(request, None) or (None, error): what the namespace script may do is decided here."""
    if not isinstance(args, dict):
        return None, _error('INVALID_GENERATE_ARGUMENTS', note='参数要是一个对象：prompt、workflow 等字段。')
    request = {'endpoint': IMAGE_ENDPOINT, 'limit': MAX_IMAGE_BYTES}
    timeout = args.get('timeout', DEFAULT_TIMEOUT)
    if not _int(timeout, MIN_TIMEOUT, MAX_TIMEOUT):
        return None, _error('INVALID_TIMEOUT', allowed=[MIN_TIMEOUT, MAX_TIMEOUT],
                            note='timeout 只能是 %d..%d 的整数（秒），%s；不写就是 %d。'
                                 % (MIN_TIMEOUT, MAX_TIMEOUT, _given(timeout), DEFAULT_TIMEOUT))
    request['timeout'] = timeout
    if args.get('workflows') is not None:
        if args['workflows'] is not True:
            return None, _error('INVALID_WORKFLOWS', note='list_routes 只能写 yes（列出能用的路线，不画图），%s；'
                                                          '要画图就不写 list_routes。' % _given(args['workflows']))
        request['list'] = True
        return request, None
    pose_keys = [k for k in ('poses_people', 'poses_angle', 'poses_limit') if args.get(k) is not None]
    if args.get('poses') is not None:
        query = args['poses']
        if not isinstance(query, str) or not query.strip() or len(query) > POSE_QUERY_CHARS:
            return None, _error('INVALID_POSES', note='poses 要写一个 1..%d 字的搜索词（先试英文，如 sit；中文常常查不到），%s。'
                                                      % (POSE_QUERY_CHARS, _given(query)))
        search = {'q': query.strip()}
        if args.get('poses_people') is not None:
            if not _int(args['poses_people'], 1, 2):
                return None, _error('INVALID_POSES_PEOPLE', note='poses_people 只能是 1 或 2，%s。' % _given(args['poses_people']))
            search['people'] = args['poses_people']
        if args.get('poses_angle') is not None:
            if args['poses_angle'] not in POSE_ANGLES:
                return None, _error('INVALID_POSES_ANGLE', allowed=list(POSE_ANGLES),
                                    note='poses_angle 只能是 %s 之一，%s。' % ('、'.join(POSE_ANGLES), _given(args['poses_angle'])))
            search['angle'] = args['poses_angle']
        if args.get('poses_limit') is not None:
            if not _int(args['poses_limit'], 1, 20):
                return None, _error('INVALID_POSES_LIMIT', note='poses_limit 要是 1..20 的整数，%s；不写服务给 8 条。' % _given(args['poses_limit']))
            search['limit'] = args['poses_limit']
        request['pose_search'] = search
        return request, None
    if pose_keys:
        return None, _error('POSES_FILTER_WITHOUT_QUERY', keys=pose_keys,
                            note='%s 是 poses=<搜索词> 的过滤项，单独写没有用；要搜姿势就把 poses 写上，要画图就去掉它们。' % '、'.join(pose_keys))
    job = args.get('job')
    if job is not None:
        if not isinstance(job, str) or not re.fullmatch(r'[0-9A-Za-z-]{8,64}', job):
            return None, _error('INVALID_JOB', note='job 是上一次回执里的 prompt_id（8..64 位字母、数字或连字符），%s；'
                                                    '照抄回执里的 prompt_id。' % _given(job))
        request['job'] = job
        return request, None
    prompt = args.get('prompt')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > PROMPT_CHARS:
        return None, _error('PROMPT_REQUIRED', max_chars=PROMPT_CHARS,
                            note='prompt 要写一段 1..%d 字的画面描述，%s；只想看路线就写 list_routes=yes，'
                                 '取上次没画完的就写 job。' % (PROMPT_CHARS, _given(prompt)))
    request['prompt'] = prompt
    negative = args.get('negative_prompt')
    if negative is not None:
        if not isinstance(negative, str) or len(negative) > PROMPT_CHARS:
            return None, _error('INVALID_NEGATIVE_PROMPT', max_chars=PROMPT_CHARS,
                                note='negative_prompt 要是 %d 字以内的字符串，%s。' % (PROMPT_CHARS, _given(negative)))
        request['negative_prompt'] = negative
    for key, pattern in (('workflow', r'[A-Za-z0-9][A-Za-z0-9._-]{0,119}'), ('style', r'[a-z0-9][a-z0-9_-]{0,39}')):
        value = args.get(key)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                return None, _error('INVALID_' + key.upper(), value=str(value)[:120],
                                    note=('workflow 照抄 list_routes=yes 列出的 id' if key == 'workflow' else
                                          'style 是小写字母、数字、_ 或 -，40 字以内') + '；不写就用通用路线。')
            request[key] = value
    for key in ('width', 'height'):
        value = args.get(key)
        if value is not None:
            if not _int(value, 64, 2048) or value % 8:
                return None, _error('INVALID_' + key.upper(),
                                    note='%s 要是 64..2048 之间 8 的倍数，%s。' % (key, _given(value)))
            request[key] = value
    if args.get('seed') is not None:
        if not _int(args['seed'], 0, 2**63 - 1):
            return None, _error('INVALID_SEED', note='seed 要是 0 以上的整数，%s；不写就随机。' % _given(args['seed']))
        request['seed'] = args['seed']
    options = args.get('options')
    if options is not None:
        if not isinstance(options, dict):
            return None, _error('INVALID_OPTIONS', note='options 要是对象，例如 {"steps": 30, "cfg": 7}，%s。' % _given(options))
        for key, value in options.items():
            rule = OPTION_RULES.get(key)
            if rule is None:
                return None, _error('OPTION_NOT_OFFERED', option=str(key)[:40], offered=sorted(OPTION_RULES),
                                    note='options 只收 %s；去掉 %s。' % ('、'.join(sorted(OPTION_RULES)), str(key)[:40]))
            kind, low, high = rule
            ok = (_int(value, low, high) if kind == 'int'
                  else isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high
                  if kind == 'number' else isinstance(value, str) and re.fullmatch(r'[a-z0-9_]{1,80}', value))
            if not ok:
                return None, _error('INVALID_OPTION', option=key, note='%s，%s；照 list_routes=yes 里这条路线声明的取值写。'
                                                                     % (OPTION_WORDS[key], _given(value)))
        request['options'] = dict(options)
    loras = args.get('loras')
    if loras is not None:
        if (not isinstance(loras, dict) or len(loras) > LORA_MAX
                or not all(isinstance(k, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', k) for k in loras)):
            return None, _error('INVALID_LORAS', note='loras 要是对象 {LoRA id: 强度}，例如 {"character": 0.4}；id 照 list_routes=yes '
                                                      '里这条路线的 loras 抄，%s。' % _given(loras))
        for key, value in loras.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not -2 <= value <= 2:
                return None, _error('INVALID_LORA_STRENGTH', lora=key, note='loras 里每个强度要是 -2..2 的数（0 是关掉），%s 的值%s。'
                                                                              % (key, _given(value)))
        request['loras'] = dict(loras)
    pose = args.get('pose')
    if pose is not None:
        if not isinstance(pose, str) or not pose.strip() or len(pose) > POSE_REF_CHARS:
            return None, _error('INVALID_POSE', note='pose 要写 poses=<搜索词> 返回的 view id（或 pose id），%s。' % _given(pose))
        request['pose'] = pose.strip()
    strength = args.get('pose_strength')
    if strength is not None:
        if isinstance(strength, bool) or not isinstance(strength, (int, float)) or not 0 <= strength <= 1:
            return None, _error('INVALID_POSE_STRENGTH', note='pose_strength 要是 0..1 的数，%s；只有 list_routes=yes 里写着 pose_strength 的路线收它。' % _given(strength))
        request['pose_strength'] = strength
    source = args.get('source_image')
    if source is not None and (not isinstance(source, str) or not 4 <= len(source) <= SOURCE_REF_CHARS):
        return None, _error('INVALID_SOURCE_IMAGE', note='source_image 是一张图的 ref（图旁标的 att-…）或 artifact_id'
                                                         '（blob-…），和 read_image 收的一样，%s。' % _given(source))
    return request, None


def extension(data):
    for signature, name in SIGNATURES:
        if data.startswith(signature):
            return name
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None


def generate(args, *, runner, workspace, protected=(), register=None, now=None, source=None):
    """One picture into the workspace; failures are the service's or the transport's own words.

    `source(ref)` reads the picture to edit with read_image's own fence and returns {data, register}: `register`
    files the result where an edit of that picture may go (outbound_media.edit_register)."""
    request, failure = validate(args)
    if failure:
        return failure
    relative = args.get('target_relative_path')
    if relative is not None:
        relative, failure = validate_target_path(relative)
        if failure:
            return {'generated': False, **failure}
        target, failure = resolve_target(workspace, relative, protected)
        if failure:
            return {'generated': False, **failure}
        if target.exists():
            return _error('TARGET_EXISTS', target_relative_path=relative, note='换一个文件名；生成的图不覆盖已有文件。')
    picture = None
    if args.get('source_image') is not None and not request.get('list') and not request.get('job'):
        if source is None:
            return _error('SOURCE_IMAGE_UNAVAILABLE', note='这里读不到原图，改图做不了；只从文字画就去掉 source_image。')
        try:
            picture = source(args['source_image'])
        except (ValueError, PermissionError) as exc:
            return _error('SOURCE_IMAGE_NOT_READABLE', detail=str(exc)[:400])
        kind = extension(picture['data'])
        if kind is None:
            return _error('SOURCE_IMAGE_NOT_A_PICTURE', note='source_image 读到的不是 png/jpeg/gif/webp 图片；换一张。')
        token = hashlib.sha256(picture['data']).hexdigest()[:12] + '-' + secrets.token_hex(3)
        request['source'] = {'file': 'source.' + kind, 'name': '%s%s.%s' % (SOURCE_PREFIX, token, kind)}
        register = picture.get('register') or register
    result = runner.generate_image(request, **({'source': picture['data']} if picture else {}))
    report = result.get('report') or {}
    if result.get('transport_error'):
        return _error('IMAGE_TRANSPORT_FAILED', detail=str(result['transport_error'])[:400],
                      note='没连上生图服务，不是参数的问题；' + AGAIN + '。')
    if request.get('list'):
        if not report.get('listed'):
            return {k: v for k, v in report.items() if v is not None} or _error(
            'IMAGE_LIST_FAILED', note='生图服务没列出路线，也没给原因；' + AGAIN + '。')
        return {'workflows': report.get('workflows') or [],
                'note': '按 best_for/not_for 挑路线，用它要的 style 和语言写提示词（多数要英文）；画时把 workflow 填上；标着 source_image 的路线是改一张图的，写上 source_image；路线带 loras 就按它列的 id 写 loras={id: 强度}（不写按默认强度自动用上），pose 为 true 的路线才收 pose（先 poses=<搜索词> 取 view id）。'}
    if request.get('pose_search'):
        if not report.get('listed'):
            return {k: v for k, v in report.items() if v is not None} or _error(
                'IMAGE_POSES_FAILED', note='生图服务没给出姿势清单，也没给原因；' + AGAIN + '。')
        return {k: v for k, v in report.items() if k != 'listed' and v is not None}
    if not report.get('generated'):
        return {k: v for k, v in report.items() if v is not None} or _error(
            'IMAGE_GENERATION_FAILED', note='生图服务没画出来，也没给原因；' + AGAIN + '。')
    body = result.get('body') or b''
    kind = extension(body)
    if kind is None:
        return _error('IMAGE_NOT_A_PICTURE', content_type=report.get('content_type'), bytes=len(body),
                      note='服务返回的不是 png/jpeg/gif/webp 图片，没有存；换个 workflow 再画，还不行写进报告。')
    if relative is None:
        stamp = (now or clock.now()).strftime('%Y%m%d-%H%M%S')
        relative = 'images/%s-%s.%s' % (stamp, hashlib.sha256(body).hexdigest()[:8], kind)
        target, failure = resolve_target(workspace, relative, protected)
        if failure:
            return {'generated': False, **failure}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as handle:
            handle.write(body)
    except FileExistsError:
        return _error('TARGET_EXISTS', target_relative_path=relative, note='换一个文件名；生成的图不覆盖已有文件。')
    except OSError as exc:
        return _error('TARGET_WRITE_FAILED', detail=(type(exc).__name__ + ': ' + (exc.strerror or str(exc)))[:300],
                      note='图没写进工作区，不是参数的问题；换个 target_relative_path ' + AGAIN + '。')
    value = {'generated': True, 'workflow': report.get('workflow'), 'prompt_id': report.get('prompt_id'),
             'seed': report.get('seed'), 'width': report.get('width'), 'height': report.get('height'),
             'elapsed_ms': report.get('elapsed_ms'), 'target_relative_path': relative, 'bytes': len(body),
             'sha256': hashlib.sha256(body).hexdigest(), 'media_type': 'image/' + ('jpeg' if kind == 'jpg' else kind)}
    if report.get('loras') is not None:
        value['loras'] = report['loras']
    if report.get('pose_strength') is not None:
        value['pose_strength'] = report['pose_strength']
    if report.get('warnings'):
        value['warnings'] = report['warnings']
    if report.get('guidance'):
        value['guidance'] = report['guidance']
    if register is not None:
        try:
            outcome = register(body, {'endpoint': IMAGE_ENDPOINT, 'artifact_path': report.get('view_path'),
                                      'target_relative_path': relative})
        except Exception as exc:
            outcome = {'registered': False, 'reason': (type(exc).__name__ + ': ' + str(exc))[:120]}
        if isinstance(outcome, dict) and outcome:
            value['artifact'] = outcome
    value = {k: v for k, v in value.items() if v is not None}
    if not request.get('job'):                    # 续取只取图，回执里没有提交时的 pose：那一发不报 null，免得误读成「没用姿势」
        value['pose'] = report.get('pose')      # 没用姿势就如实是 null：画完拿它核对姿势真用上没有
    value['note'] = ('画面还没人看过：先用 read_image 传 artifact.artifact_id 亲眼看一遍，对照要求；不对就按 guidance '
                     '改提示词或换 workflow 再画。报告里用相对路径的 Markdown 图片展示；artifact_id 是可以随消息发出去的那张。')
    return value
