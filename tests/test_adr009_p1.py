"""ADR-009 P1 MongoDB tests: T1.3 policy store, T1.5 per-persona isolation (policy)."""
import json


from asuna.persona_model import validate
from conftest import FIXTURES

MODEL = validate(json.loads((FIXTURES / 'personas/demo/persona-model.json').read_text(encoding='utf-8')), 'demo')


def item(key, value, what='测试参数', cls='param'):
    return {'key': key, 'value': value, 'what': what, 'class': cls}


