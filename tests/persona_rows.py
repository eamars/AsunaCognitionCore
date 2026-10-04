"""Persona document rows for the fake stores in the offline case runners.

The persona is a document (``doc:<persona>:persona``); legacy ``persona:<id>`` heads are gone.
"""


def persona_rows(body, persona='P1', revision_id='rev-persona-0'):
    from asuna.documents import PREAMBLE, SCOPE, _section
    key = f'doc:{persona}:persona|{SCOPE}'
    head = {'_id': key, 'scope_key': SCOPE, 'revision_id': revision_id, 'revision': 1}
    revision = {'_id': revision_id, 'entity_key': key, 'scope_key': SCOPE, 'mutation_id': 'seed:' + revision_id,
                'revision': 1, 'source_ids': [], 'parent_revision_id': None,
                'content': {'kind': 'persona', 'title': 'persona',
                            'sections': [_section(PREAMBLE, '', body, visibility='public', inject='always')]}}
    return head, revision
