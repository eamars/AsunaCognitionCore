"""Role system prompt rendering (ADR-009 §8.1).

The rendered text is the complete system prompt of a role session. Episodes keep
only ``system_ref`` — the revisions and hashes the render used — and every stage
re-renders from it; results are cached by ``render_sha256``. The render is never
truncated.
"""
from __future__ import annotations

from collections import OrderedDict
import threading

from .config import prompt_path
from .evidence import sha

_CACHE: OrderedDict = OrderedDict()
_LOCK = threading.Lock()
_CACHE_LIMIT = 32


def common_text(config) -> str:
    return prompt_path(config, 'common.md').read_text(encoding='utf-8')


def _compose(common: str, persona_body: str) -> str:
    return common + '\n' + persona_body


def _remember(text: str) -> str:
    digest = sha(text.encode())
    with _LOCK:
        _CACHE[digest] = text
        _CACHE.move_to_end(digest)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return digest


def render_system(store, persona: str):
    """Render the current role system prompt; returns (text, system_ref)."""
    pair = store.head('persona:' + persona, 'global-safe')
    if not pair:
        raise ValueError('REQUIRED_PERSONA_MISSING')
    head, revision = pair
    common = common_text(store.config)
    text = _compose(common, revision['content']['body'])
    return text, {'persona_doc_revision': head['revision_id'], 'voice_doc_revision': None,
                  'common_sha256': sha(common.encode()), 'render_sha256': _remember(text)}


def system_for(store, ref: dict, *, stream: str | None = None, scope: str = 'operator') -> str:
    """Re-render the system prompt an episode fixed at preparation time.

    A published core prompt change between stages yields a fresh render; the
    drift is audited rather than failing the turn.
    """
    with _LOCK:
        cached = _CACHE.get(ref['render_sha256'])
    if cached is not None:
        return cached
    revision = store.db.state_revisions.find_one({'_id': ref['persona_doc_revision']})
    if not revision:
        raise ValueError('SYSTEM_REF_REVISION_MISSING')
    common = common_text(store.config)
    text = _compose(common, revision['content']['body'])
    digest = _remember(text)
    if digest != ref['render_sha256'] and stream:
        store.audit(stream, 'system.render_drift', {'expected': ref['render_sha256'], 'actual': digest,
                    'common_sha256': sha(common.encode()), 'expected_common_sha256': ref['common_sha256']}, scope)
    return text


def episode_system(store, ep: dict) -> str:
    """Stage system prompt: legacy in-flight episodes still carry the full text."""
    if ep.get('system') is not None:
        return ep['system']
    return system_for(store, ep['system_ref'], stream=ep.get('_id'), scope=ep.get('scope_key', 'operator'))


def action_values(store) -> str:
    """Action-brain system suffix: always a public render (ADR-009 §8.3).

    Only the persona's display name until persona documents with public
    ``values`` sections exist; never the persona body.
    """
    name = (store.config.get('chat') or {}).get('display_name') or 'character'
    return '\n你服务的角色：' + name + '。共享其公开价值，但不代写角色台词、独白或感受。'
