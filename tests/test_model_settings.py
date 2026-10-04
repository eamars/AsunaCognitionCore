"""Noninteractive configuration diagnostics; live acceptance is through Web UI."""
from copy import deepcopy
import json


from asuna.model_settings import edited_models, normalize, public_models, revision


def routes():
    model = {'base_url': 'http://127.0.0.1:9001/v1', 'model': 'model-a', 'max_tokens': 2048,
             'context_window': 32768, 'sampling': {'temperature': .2}, 'api_key': 'private-test-key'}
    return {'character': deepcopy(model), 'executor': deepcopy(model)}


def draft(config):
    return {lane: {k: v for k, v in normalize(config[lane]).items() if k != 'api_key'}
            for lane in ('character', 'executor')}


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


