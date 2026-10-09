"""Role system prompt rendering (ADR-009 §8.1).

Rendered text = neutral core header (common.md) + the persona document's
``inject=always`` sections readable in this session class (public first, then
owner-private) + the voice document's. It is the complete system prompt of a
role session. Episodes keep only ``system_ref`` (revisions, class and hashes)
and every stage re-renders from it; results are cached by ``render_sha256``.
The render is never truncated: an over-budget render is still complete, and is
reported (audit + red status) instead. The limit follows the package's own seeds: a persona that ships more seed
text gets room for it (budget_limit).
"""
from __future__ import annotations

from collections import OrderedDict
import math
from pathlib import Path
import re
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


def readable_sections(content, cls, *, inject=('always',), place=None):
    """Sections of a document visible to a session class, public before owner-private. With a place, a section pinned
    to other places (ADR-032) is left out."""
    if not content:
        return []
    chosen = [s for s in content['sections'] if s['inject'] in inject and visibility.readable(s['visibility'], cls)
              and (place is None or not visibility.section_places(s) or place in visibility.section_places(s))]
    return [s for s in chosen if s['visibility'] == 'public'] + [s for s in chosen if s['visibility'] != 'public']


def _document_text(content, cls, place=None):
    if content is None:
        return ''
    if 'sections' not in content:              # a pre-conversion legacy persona head revision
        return content.get('body', '')
    return render_markdown(readable_sections(content, cls, place=place))


def compose(common, persona_content, voice_content, cls, place=None) -> str:
    text = common + '\n' + _document_text(persona_content, cls, place)
    voice = _document_text(voice_content, cls, place)
    return text + ('\n' + voice if voice else '')


def largest(common, persona_content, voice_content):
    """(estimated tokens, text) of the largest render over the places: the one the budget bounds."""
    renders = [compose(common, persona_content, voice_content, cls, place) for place, cls in visibility.PLACE_CLASS.items()]
    text = max(renders, key=estimate_tokens)
    return estimate_tokens(text), text


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


# Chinese, Japanese and Korean characters, and their full-width punctuation: about one token each or less.
WIDE = re.compile('[\u1100-\u11ff\u2e80-\u9fff\ua960-\ua97f\uac00-\ud7ff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef'
                  '\U00020000-\U0003ffff]')   # personal-scan: ok (CJK extension planes)
SEED_ROOM = 1.25            # what the package's own seeds render to, plus a quarter to grow


def estimate_tokens(text: str) -> int:
    """Tokenizer-free upper estimate: one token per CJK character, DSH's characters/4 for everything else."""
    wide = len(WIDE.findall(text))
    return wide + math.ceil((len(text) - wide) / 4)


def seed_estimate(store, persona):
    """Estimated tokens of the owner-private render the installed package's own persona and voice seeds make, or
    None when the package declares neither."""
    from .documents import parse_markdown
    seeds = {seed['slug']: seed for seed in (store.config.get('persona_contribution') or {}).get('seeds') or []
             if seed.get('slug') in ('persona', 'voice')}
    if not seeds:
        return None
    content = {}
    for slug, seed in seeds.items():
        try:
            content[slug] = {'sections': parse_markdown(Path(seed['path']).read_text(encoding='utf-8'), seed['kind'])[1]}
        except OSError:
            return None
    return largest(common_text(store.config), content.get('persona'), content.get('voice'))[0]


def budget_limit(store, persona):
    """The larger of render.budget_tokens and the package's seeds with room to grow, never above the character
    context window × render.max_window_share; None when nothing bounds it."""
    from .persona_model import effective
    model, policy = model_and_policy(store, persona)
    budget = effective(model, 'render.budget_tokens', policy)
    share = effective(model, 'render.max_window_share', policy)
    window = (store.config.get('character') or {}).get('context_window')
    seeded = seed_estimate(store, persona)
    wanted = [value for value in (budget, math.ceil(seeded * SEED_ROOM) if seeded else None) if value]
    cap = int(window * share) if window and share else None
    limit = max(wanted) if wanted else None
    return min(limit, cap) if limit and cap else limit or cap


def render_system(store, persona: str, cls: str = visibility.OWNER_PRIVATE, place=None):
    """Render the current role system prompt for a session class and place; returns (text, system_ref)."""
    docs = DocumentStore(store, persona)
    persona_rev, persona_doc = docs.read('persona')
    if persona_doc is None:
        raise ValueError('REQUIRED_PERSONA_MISSING')
    voice_rev, voice_doc = docs.read('voice')
    common = common_text(store.config)
    text = compose(common, persona_doc, voice_doc, cls, place)
    ref = {'persona_doc_revision': persona_rev, 'voice_doc_revision': voice_rev, 'session_class': cls, 'place': place,
           'common_sha256': sha(common.encode()), 'render_sha256': _remember(text)}
    report_budget(store, persona, persona_doc, voice_doc, common)
    return text, ref


def render_status(store, persona) -> dict:
    """The largest render over the places against the budget, for the settings card and memory tab."""
    docs = DocumentStore(store, persona)
    _, persona_doc = docs.read('persona')
    _, voice_doc = docs.read('voice')
    estimate = largest(common_text(store.config), persona_doc, voice_doc)[0]
    limit = budget_limit(store, persona)
    return {'estimate_tokens': estimate, 'limit_tokens': limit, 'over_budget': bool(limit and estimate > limit)}


def report_budget(store, persona, persona_doc, voice_doc, common):
    estimate, text = largest(common, persona_doc, voice_doc)
    limit = budget_limit(store, persona)
    digest = sha(text.encode())
    if limit and estimate > limit and digest not in _REPORTED:
        _REPORTED.add(digest)
        store.audit('render:' + persona, 'render.over_budget', {'estimate_tokens': estimate, 'limit_tokens': limit,
                    'render_sha256': digest}, 'global-safe')


def budget_gate(store, persona):
    """For DocumentStore.apply: refuse a persona/voice change that grows an over-budget render, and growth of a
    note already far over its limit (context_budget.note_gate)."""
    from .documents import DocumentError
    from .context_budget import note_gate
    docs = DocumentStore(store, persona)

    def check(slug, new_content):
        if slug not in ('persona', 'voice'):
            note_gate(slug, docs.read(slug)[1], new_content)
            return
        limit = budget_limit(store, persona)
        if not limit:
            return
        common = common_text(store.config)
        current = {'persona': docs.read('persona')[1], 'voice': docs.read('voice')[1]}
        proposed = {**current, slug: new_content}
        before = largest(common, current['persona'], current['voice'])[0]
        after = largest(common, proposed['persona'], proposed['voice'])[0]
        if after > before and after > limit:
            raise DocumentError('PERSONA_RENDER_OVER_BUDGET', over_budget_words(proposed, before, after, limit))
    return check


def over_budget_words(proposed, before, after, limit):
    """By how much a write overshoots, and the largest always-injected sections she could tuck away or trim."""
    sizes = sorted(((estimate_tokens(s['heading'] + s['body']), slug, s['sid'])
                    for slug in ('persona', 'voice')
                    for s in readable_sections((proposed[slug] or {}).get('sections') and proposed[slug],
                                               visibility.OWNER_PRIVATE)), reverse=True)[:3]
    largest = '、'.join('%s#%s（约 %d）' % (slug, sid, tokens) for tokens, slug, sid in sizes)
    return ('写完约 %d token，上限 %d，超出 %d（写之前是 %d）；%s先把不常用的 always 节用 set_tags 改成 inject=on_demand '
            '收起来（recall 还读得到），或把这次写的改短' % (after, limit, after - limit, before,
                                                       '最大的 always 节：%s。' % largest if largest else ''))


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
    text = compose(common, revisions[0], revisions[1], ref.get('session_class', visibility.OWNER_PRIVATE), ref.get('place'))
    digest = _remember(text)
    if digest != ref['render_sha256'] and stream:
        store.audit(stream, 'system.render_drift', {'expected': ref['render_sha256'], 'actual': digest,
                    'common_sha256': sha(common.encode()), 'expected_common_sha256': ref['common_sha256']}, scope)
    return text


def episode_system(store, ep: dict) -> str:
    """Stage system prompt, re-rendered from the episode's system_ref (drift is audited)."""
    return system_for(store, ep['system_ref'], stream=ep.get('_id'), scope=ep.get('scope_key', 'operator'))


def action_values(store, persona=None, cls=visibility.PUBLIC) -> str:
    """Action-brain system suffix (ADR-009 §8.3, revised by the owner 2026-10-04).

    ``render.action_persona``:
    - ``values`` (core default): public persona sections tagged ``render.values_tag``, else the name alone;
    - ``persona``: who she is — the persona document's every-turn sections readable in the class of the
      conversation the task came from. Never memory, relationships, emotion or other state.
    """
    name = (store.config.get('chat') or {}).get('display_name') or 'character'
    persona = persona or (store.config.get('chat') or {}).get('persona')
    if not persona:
        return '\n你服务的角色：' + name + '。共享其公开价值，但不代写角色台词、独白或感受。'
    from .persona_model import effective
    model, policy = model_and_policy(store, persona)
    _, content = DocumentStore(store, persona).read('persona')
    if effective(model, 'render.action_persona', policy) == 'persona':
        sections = readable_sections(content, cls)
        text = ('\n你是' + name + '的行动侧：以下是她是谁，照她的为人做事、写汇报。上面的行动规则优先；'
                '人格不扩大授权，也不让你替她对外说话、写独白或决定感受。')
        return text + ('\n' + render_markdown(sections) if sections else '')
    tag = effective(model, 'render.values_tag', policy) or 'values'
    values = [s for s in (content or {}).get('sections', [])
              if s['visibility'] == 'public' and tag in s.get('tags', [])]
    text = '\n你服务的角色：' + name + '。共享其公开价值，但不代写角色台词、独白或感受。'
    if values:
        text += '\n' + render_markdown(values)
    return text
