"""Noninteractive configuration diagnostics; live acceptance is through Web UI."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from asuna.model_settings import edited_models, normalize, persist, public_models, revision, validate
from asuna.tokens import TokenMeter


def routes():
    model = {'base_url': 'http://127.0.0.1:9001/v1', 'model': 'model-a', 'max_tokens': 2048,
             'context_window': 32768, 'sampling': {'temperature': .2}, 'api_key': 'private-test-key'}
    return {'character': deepcopy(model), 'executor': deepcopy(model)}


def draft(config):
    return {lane: {k: v for k, v in normalize(config[lane]).items() if k != 'api_key'}
            for lane in ('character', 'executor')}


def test_independent_routes_allow_same_model_and_persist(tmp_path):
    config = routes()
    models = draft(config)
    models['executor']['max_tokens'] = 4096
    result = edited_models(config, {'revision': revision(config), 'models': models})
    assert result['character']['model'] == result['executor']['model']
    assert result['character']['max_tokens'] == 2048
    assert result['executor']['max_tokens'] == 4096
    path = tmp_path / 'models.json'
    persist(result, path)
    assert json.loads(path.read_text()) == result
    assert config['executor']['max_tokens'] == 2048
    with pytest.raises(ValueError, match='已变化'):
        edited_models(result, {'revision': revision(config), 'models': models})


def test_credentials_are_write_only_and_not_reused_on_new_endpoint():
    config = routes()
    assert 'private-test-key' not in json.dumps(public_models(config))
    models = draft(config)
    models['character']['base_url'] = 'http://127.0.0.1:9002/v1'
    result = edited_models(config, {'revision': revision(config), 'models': models})
    assert not result['character'].get('api_key')
    assert result['executor']['api_key'] == 'private-test-key'
    models['executor']['clear_api_key'] = True
    result = edited_models(config, {'revision': revision(config), 'models': models})
    assert not result['executor'].get('api_key')


def test_budget_is_model_owned_and_sampling_cannot_override_payload():
    model = validate(routes()['character'])
    body = {'messages': [{'role': 'user', 'content': '同一服务，两条职责。'}], 'max_completion_tokens': 1024}
    evidence = SimpleNamespace(record=lambda *args: None)
    character = TokenMeter(model, evidence, 'character').check(body)
    executor = TokenMeter(model, evidence, 'executor').check(body)
    assert character == executor
    assert character['output_budget'] == 1024
    assert character['method'] == 'UTF8_bytes_conservative_bound'
    with pytest.raises(ValueError, match='采样参数'):
        validate({**model, 'sampling': {'model': 'different-model'}})
    with pytest.raises(ValueError, match='计数'):
        validate({**model, 'token_counter': 'unknown'})
