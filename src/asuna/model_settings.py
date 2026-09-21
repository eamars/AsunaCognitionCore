"""Two independent model routes; DSH compatibility options belong to models."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import uuid

from .config import validate_endpoint

LANES = ('character', 'executor')


def normalize(model):
    value = deepcopy(model)
    value.setdefault('api', 'openai-completions')
    value.setdefault('context_window', 262144)
    value.setdefault('token_counter', 'conservative_bytes')
    value.setdefault('reasoning_effort', 'off')
    value.setdefault('reasoning_efforts', {'off': None, 'high': 'high'})
    value.setdefault('compat', {'supportsDeveloperRole': False, 'maxTokensField': 'max_tokens'})
    # Legacy toggle is a deployment option, never inferred from a lane/model name.
    if 'native_thinking' in value and 'compat' not in model:
        value['compat'].update(thinkingFormat='chat-template', chatTemplateKwargs={'enable_thinking': value['native_thinking']})
    value.pop('native_thinking', None)
    return value


def validate(model):
    value = normalize(model)
    if value['api'] != 'openai-completions':
        raise ValueError('当前 Asuna 审计桥支持 OpenAI Chat Completions；不支持的协议不会假装生效。')
    validate_endpoint(value['base_url'])
    value['base_url'] = value['base_url'].rstrip('/')
    if not isinstance(value.get('model'), str) or not value['model'].strip():
        raise ValueError('模型 ID 不能为空')
    if any(not isinstance(value.get(k), int) or isinstance(value[k], bool) or value[k] < 1 for k in ('max_tokens', 'context_window')):
        raise ValueError('上下文窗口和输出上限必须为正整数')
    if value['context_window'] <= value['max_tokens'] + 4096:
        raise ValueError('上下文窗口必须大于输出上限加 4096 token 安全余量')
    if value['token_counter'] not in ('conservative_bytes', 'llama_cpp', 'anthropic_count'):
        raise ValueError('未知 token 计数方式')
    if value['reasoning_effort'] not in ('off', 'minimal', 'low', 'medium', 'high', 'xhigh'):
        raise ValueError('未知推理强度')
    if not isinstance(value['compat'], dict) or not isinstance(value['reasoning_efforts'], dict):
        raise ValueError('DSH 兼容参数与推理映射必须为 JSON 对象')
    if value['compat'].get('maxTokensField', 'max_tokens') not in ('max_tokens', 'max_completion_tokens'):
        raise ValueError('不支持的输出预算字段')
    sampling = value.get('sampling', {})
    if not isinstance(sampling, dict) or set(sampling) - {'temperature', 'top_p', 'top_k', 'min_p', 'seed', 'frequency_penalty', 'presence_penalty', 'repetition_penalty'}:
        raise ValueError('sampling 只能包含采样参数，不能覆盖模型、消息或工具')
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in sampling.values()):
        raise ValueError('采样参数必须为数值')
    value['sampling'] = sampling
    if not isinstance(value.get('api_key', ''), str):
        raise ValueError('API key 必须为文本')
    return value


def settings_path(config_path):
    path = Path(config_path).resolve()
    return path.with_name(path.stem + '.models.local.json')


def revision(config):
    return hashlib.sha256(json.dumps({k: config[k] for k in LANES}, sort_keys=True).encode()).hexdigest()


def public_models(config):
    result = {}
    for lane in LANES:
        model = normalize(config[lane])
        model['api_key_set'] = bool(model.pop('api_key', ''))
        result[lane] = model
    return result


def edited_models(config, body):
    if body.get('revision') != revision(config):
        raise ValueError('模型配置已变化，请重新打开设置后保存')
    if set(body.get('models', {})) != set(LANES):
        raise ValueError('必须提交两条独立模型路由')
    result = deepcopy(config)
    allowed = {'base_url', 'model', 'api', 'max_tokens', 'context_window', 'token_counter',
               'reasoning_effort', 'reasoning_efforts', 'compat', 'sampling', 'api_key', 'clear_api_key'}
    for lane in LANES:
        draft = body['models'][lane]
        if not isinstance(draft, dict) or set(draft) - allowed:
            raise ValueError('不支持的模型设置字段')
        value = normalize(config[lane])
        value.update({k: v for k, v in draft.items() if k not in ('api_key', 'clear_api_key')})
        if draft.get('clear_api_key'):
            value.pop('api_key', None)
        elif draft.get('api_key'):
            value['api_key'] = draft['api_key']
        # Never forward one server's saved credential to a newly entered endpoint.
        elif value['base_url'].rstrip('/') != config[lane]['base_url'].rstrip('/'):
            value.pop('api_key', None)
        result[lane] = validate(value)
    return result


def persist(config, path):
    target = Path(path)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump({lane: config[lane] for lane in LANES}, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
