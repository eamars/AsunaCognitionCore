"""Role system prompt rendering (ADR-009 §8.1).

Rendered text = neutral core header (common.md) + the persona document's
``inject=always`` sections readable in this session class (public first, then
owner-private) + the voice document's. It is the complete system prompt of a
role session. Episodes keep only ``system_ref`` (revisions, class and hashes)
and every stage re-renders from it; results are cached by ``render_sha256``.
The render is never truncated: an over-budget render is still complete, and is
reported (audit + red status) instead.
"""
from __future__ import annotations

from collections import OrderedDict
import threading

from .config import prompt_path
from .documents import DocumentStore, render_markdown
from .evidence import sha
from . import visibility

_CACHE: OrderedDict = OrderedDict()
_LOCK = threading.Lock()
_CACHE_LIMIT = 32
_REPORTED = set()


def common_text(config) -> str:
    return prompt_path(config, 'common.md').read_text(encoding='utf-8')


def readable_sections(content, cls, *, inject=('always',)):
    """Sections of a document visible to a session class, public before owner-private."""
    if not content:
        return []
    chosen = [s for s in content['sections'] if s['inject'] in inject and visibility.readable(s['visibility'], cls)]
    return [s for s in chosen if s['visibility'] == 'public'] + [s for s in chosen if s['visibility'] != 'public']


def _document_text(content, cls):
    if content is None:
        return ''
    if 'sections' not in content:              # a pre-conversion legacy persona head revision
        return content.get('body', '')
    return render_markdown(readable_sections(content, cls))


def compose(common, persona_content, voice_content, cls) -> str:
    text = common + '\n' + _document_text(persona_content, cls)
    voice = _document_text(voice_content, cls)
    return text + ('\n' + voice if voice else '')


def _remember(text: str) -> str:
    digest = sha(text.encode())
    with _LOCK:
        _CACHE[digest] = text
        _CACHE.move_to_end(digest)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return digest


def model_and_policy(store, persona):
    from .persona_model import neutral
    from .policy import PolicyStore
    model = store.config.get('persona_model') or neutral(persona, (store.config.get('chat') or {}).get('display_name') or persona)
    return model, PolicyStore(store, persona, model).params()


def estimate_tokens(text: str) -> int:
    """Conservative upper bound used for chunk budgets too: UTF-8 bytes ≥ tokens."""
    return len(text.encode('utf-8'))


def budget_limit(store, persona):
    """min(render.budget_tokens, character context window × render.max_window_share), or None."""
    from .persona_model import effective
    model, policy = model_and_policy(store, persona)
    budget = effective(model, 'render.budget_tokens', policy)
    share = effective(model, 'render.max_window_share', policy)
    window = (store.config.get('character') or {}).get('context_window')
    limits = [value for value in (budget, int(window * share) if window and share else None) if value]
    return min(limits) if limits else None


def render_system(store, persona: str, cls: str = visibility.OWNER_PRIVATE):
    """Render the current role system prompt for a session class; returns (text, system_ref)."""
    docs = DocumentStore(store, persona)
    persona_rev, persona_doc = docs.read('persona')
    if persona_doc is None:
        raise ValueError('REQUIRED_PERSONA_MISSING')
    voice_rev, voice_doc = docs.read('voice')
    common = common_text(store.config)
    text = compose(common, persona_doc, voice_doc, cls)
    ref = {'persona_doc_revision': persona_rev, 'voice_doc_revision': voice_rev, 'session_class': cls,
           'common_sha256': sha(common.encode()), 'render_sha256': _remember(text)}
    report_budget(store, persona, persona_doc, voice_doc, common)
    return text, ref


def render_status(store, persona) -> dict:
    """Owner-private render (the largest) against the budget, for the settings card and memory tab."""
    docs = DocumentStore(store, persona)
    _, persona_doc = docs.read('persona')
    _, voice_doc = docs.read('voice')
    estimate = estimate_tokens(compose(common_text(store.config), persona_doc, voice_doc, visibility.OWNER_PRIVATE))
    limit = budget_limit(store, persona)
    return {'estimate_tokens': estimate, 'limit_tokens': limit, 'over_budget': bool(limit and estimate > limit)}


def report_budget(store, persona, persona_doc, voice_doc, common):
    largest = compose(common, persona_doc, voice_doc, visibility.OWNER_PRIVATE)
    limit = budget_limit(store, persona)
    estimate = estimate_tokens(largest)
    digest = sha(largest.encode())
    if limit and estimate > limit and digest not in _REPORTED:
        _REPORTED.add(digest)
        store.audit('render:' + persona, 'render.over_budget', {'estimate_tokens': estimate, 'limit_tokens': limit,
                    'render_sha256': digest}, 'global-safe')


def budget_gate(store, persona):
    """For DocumentStore.apply: refuse a persona/voice change that grows an over-budget render."""
    from .documents import DocumentError
    docs = DocumentStore(store, persona)

    def check(slug, new_content):
        if slug not in ('persona', 'voice'):
            return
        limit = budget_limit(store, persona)
        if not limit:
            return
        common = common_text(store.config)
        current = {'persona': docs.read('persona')[1], 'voice': docs.read('voice')[1]}
        proposed = {**current, slug: new_content}
        before = estimate_tokens(compose(common, current['persona'], current['voice'], visibility.OWNER_PRIVATE))
        after = estimate_tokens(compose(common, proposed['persona'], proposed['voice'], visibility.OWNER_PRIVATE))
        if after > before and after > limit:
            raise DocumentError('PERSONA_RENDER_OVER_BUDGET', f'estimate {after} > limit {limit}')
    return check


def system_for(store, ref: dict, *, stream: str | None = None, scope: str = 'operator') -> str:
    """Re-render the system prompt an episode fixed at preparation time.

    A published core prompt change between stages yields a fresh render; the
    drift is audited rather than failing the turn.
    """
    with _LOCK:
        cached = _CACHE.get(ref['render_sha256'])
    if cached is not None:
        return cached
    revisions = []
    for field in ('persona_doc_revision', 'voice_doc_revision'):
        revision = store.db.state_revisions.find_one({'_id': ref[field]}) if ref.get(field) else None
        if ref.get(field) and not revision:
            raise ValueError('SYSTEM_REF_REVISION_MISSING')
        revisions.append(revision['content'] if revision else None)
    common = common_text(store.config)
    text = compose(common, revisions[0], revisions[1], ref.get('session_class', visibility.OWNER_PRIVATE))
    digest = _remember(text)
    if digest != ref['render_sha256'] and stream:
        store.audit(stream, 'system.render_drift', {'expected': ref['render_sha256'], 'actual': digest,
                    'common_sha256': sha(common.encode()), 'expected_common_sha256': ref['common_sha256']}, scope)
    return text


def episode_system(store, ep: dict) -> str:
    """Stage system prompt, re-rendered from the episode's system_ref (drift is audited)."""
    return system_for(store, ep['system_ref'], stream=ep.get('_id'), scope=ep.get('scope_key', 'operator'))


def action_values(store, persona=None) -> str:
    """Action-brain system suffix: always a public render (ADR-009 §8.3).

    Only persona sections that are public and tagged with ``render.values_tag``;
    the display name alone when there are none. Never owner-private text.
    """
    name = (store.config.get('chat') or {}).get('display_name') or 'character'
    persona = persona or (store.config.get('chat') or {}).get('persona')
    values = []
    if persona:
        from .persona_model import effective
        model, policy = model_and_policy(store, persona)
        tag = effective(model, 'render.values_tag', policy) or 'values'
        _, content = DocumentStore(store, persona).read('persona')
        values = [s for s in (content or {}).get('sections', [])
                  if s['visibility'] == 'public' and tag in s.get('tags', [])]
    text = '\n你服务的角色：' + name + '。共享其公开价值，但不代写角色台词、独白或感受。'
    if values:
        text += '\n' + render_markdown(values)
    return text
