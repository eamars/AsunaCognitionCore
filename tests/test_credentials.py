"""Her credential vault (owner 2026-10-07): filed at home, used blind by one sandboxed command of a home task."""
import pytest

from asuna import credentials, role_tools
from asuna.state import Denied

SECRET = 'Pa55!word-for-test'


@pytest.fixture
def vault():
    """DSH's credential store as the Host serves it (credentialRecords): records by name, payload {note, env}."""
    records = {}

    def host(args):
        op = args['op']
        if op == 'list':
            return [{'name': name, 'note': p['note'], 'env': list(p['env'])} for name, p in records.items()]
        if op == 'read':
            return records.get(args['name'])
        if op == 'write':
            records[args['name']] = {'note': args['note'], 'env': args['env']}
            return {'written': args['name']}
        if op == 'delete':
            records.pop(args['name'], None)
            return {'deleted': args['name']}
    credentials.attach(host)
    yield records
    credentials.attach(None)


def test_a_credential_is_filed_by_name_and_no_listing_carries_its_value(vault):
    kept = credentials.keep('solar', '主人的光伏账号，只读', {'SOLAR_EMAIL': 'a@example.org', 'SOLAR_PASSWORD': SECRET})
    assert kept['kept'] == 'solar' and kept['env'] == ['SOLAR_EMAIL', 'SOLAR_PASSWORD'] and SECRET not in str(kept)
    assert credentials.listing() == [{'name': 'solar', 'note': '主人的光伏账号，只读', 'env': ['SOLAR_EMAIL', 'SOLAR_PASSWORD']}]
    for bad in ({'PATH': 'x'}, {'lower': 'x'}, {}, {'OK_NAME': ''}):
        with pytest.raises(Denied, match='CREDENTIAL_ENV_INVALID'):
            credentials.keep('solar', 'x', bad)
    with pytest.raises(Denied, match='CREDENTIAL_NAME_INVALID'):
        credentials.keep('Solar Pass', 'x', {'A_B': 'v'})
    # Every form of a stored value is hidden: as written, url-encoded (a login form), inside lists and dicts.
    scrubbed = credentials.scrub({'out': 'pw=%s form=%s' % (SECRET, 'Pa55%21word-for-test'), 'rows': [SECRET]})
    assert SECRET not in str(scrubbed) and 'Pa55%21' not in str(scrubbed) and scrubbed['rows'] == ['[凭据已隐藏]']
    assert credentials.environment(['solar']) == {'SOLAR_EMAIL': 'a@example.org', 'SOLAR_PASSWORD': SECRET}
    with pytest.raises(Denied, match='CREDENTIAL_NOT_FOUND'):
        credentials.environment(['nope'])
    assert credentials.drop('solar') == {'dropped': 'solar'} and credentials.listing() == []


def test_every_tool_schema_stays_inside_what_dsh_registers():
    """DSH's defineTool takes a JSON-schema subset (dsh-tools): additionalProperties is a boolean, nothing else. One
    tool outside it fails the whole preset, and every session of hers goes unavailable (2026-10-07)."""
    from asuna.development import DEVELOPMENT_TOOLS, PERSONA_JOB_TOOLS
    from asuna.tasks import SANDBOX_TOOL
    allowed = {'type', 'oneOf', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'const',
               'description', 'title', 'default', 'examples'}

    def check(node, path):
        assert isinstance(node, dict), path
        extra = set(node) - allowed
        assert not extra, '%s: %s' % (path, extra)
        if 'additionalProperties' in node:
            assert isinstance(node['additionalProperties'], bool), path + '.additionalProperties'
        for key, child in (node.get('properties') or {}).items():
            check(child, path + '.' + key)
        for i, child in enumerate(node.get('oneOf') or ()):
            check(child, '%s.oneOf[%d]' % (path, i))
        if isinstance(node.get('items'), dict):
            check(node['items'], path + '.items')

    specs = role_tools.all_specs() + DEVELOPMENT_TOOLS + PERSONA_JOB_TOOLS + [SANDBOX_TOOL]
    for spec in specs:
        for name, param in spec['parameters'].items():
            check({k: v for k, v in param.items() if k != 'required'}, spec['name'] + '.' + name)


