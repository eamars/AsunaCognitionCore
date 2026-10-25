"""Role system prompt rendering (ADR-009 §8.1).

Rendered text = neutral core header (common.md) + the carried sections of the persona document readable in this
session class and place (public first, then owner-private) + the voice document's: what is carried is carried.py's
(each section where its tier puts it, its `place:` tags honoured). It is the complete system prompt of a role
session. Episodes keep only ``system_ref`` (revisions, class, place, the carried section ids and hashes) and every
stage re-renders exactly those sections from it; results are cached by ``render_sha256``. The render is never
truncated: a pair whose identity layer is over its limit is reported (audit + red status) instead, and a write that
grows it is refused (budget_gate). The limit follows the package's own seeds: a persona that ships more seed text
gets room for it (budget_limit).
"""
from __future__ import annotations

from collections import OrderedDict
import math
from pathlib import Path
import re
import threading

from .config import prompt_path
from .documents import DocumentStore, render_markdown
from .evidence import canonical, sha
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


def role_text(config, rendered, speaks=False):
    """Her role system prompt: the persona render, then how a turn goes and what its blocks are (block_guide.py,
    ADR-056). The persona budget bounds the render alone: the guide is the core's, the same for every persona.
    `speaks`: the conversation speaks only through speak (the guide says how her words leave, once)."""
    from .block_guide import guide
    return rendered + '\n\n' + guide(config, speaks)


def largest(common, persona_content, voice_content):
    """(estimated tokens, text) of the largest render over the places of raw documents, as written: what seed_estimate
    measures of a package's own seeds. What is carried is carried.py's."""
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
    """Each (place, class) pair's identity ceiling (carried.limit): render.identity_tokens, plus room for a package's
    own seeds, never above the character context window × render.max_window_share; None when nothing bounds it."""
    from .carried import limit
    return limit(store, persona)


def render_system(store, persona: str, cls: str = visibility.OWNER_PRIVATE, place=None, speaks=False):
    """Render the current role system prompt for a session class and place, and whether its conversation speaks only
    through speak; returns (text, system_ref). The ref records which sections were carried, so a re-render is the
    same prompt (system_for)."""
    from .carried import placed, sections, system_text
    docs = DocumentStore(store, persona)
    persona_rev, persona_doc = docs.read('persona')
    if persona_doc is None:
        raise ValueError('REQUIRED_PERSONA_MISSING')
    voice_rev, voice_doc = docs.read('voice')
    common = common_text(store.config)
    contents = {'persona': persona_doc, 'voice': voice_doc}
    found = {slug: sections(placed(store, persona, slug, content), cls, place) for slug, content in contents.items()}
    text = role_text(store.config, system_text(common, found, contents), speaks)
    ref = {'persona_doc_revision': persona_rev, 'voice_doc_revision': voice_rev, 'session_class': cls, 'place': place,
           'speaks': bool(speaks), 'common_sha256': sha(common.encode()), 'render_sha256': _remember(text),
           'carried': {slug: [s['sid'] for s in found[slug]] for slug in found}}
    report_budget(store, persona, persona_doc, voice_doc, common)
    return text, ref


def render_status(store, persona) -> dict:
    """Each pair's identity layer against its limit, for the settings card and memory tab: the largest one's estimate,
    whether any pair is over, and every pair's size."""
    from .carried import identity
    sizes = identity(store, persona)
    limit = budget_limit(store, persona)
    return {'estimate_tokens': max(sizes.values()), 'limit_tokens': limit,
            'over_budget': bool(limit and any(size > limit for size in sizes.values())),
            'pairs': [{'place': place, 'class': cls, 'tokens': size} for (place, cls), size in sizes.items()]}


def report_budget(store, persona, persona_doc=None, voice_doc=None, common=None):
    """Audit, once for each state of it, a pair whose identity layer is over its limit."""
    from .carried import contents, identity
    limit = budget_limit(store, persona)
    if not limit:
        return
    docs = contents(store, persona)
    docs.update({slug: doc for slug, doc in (('persona', persona_doc), ('voice', voice_doc)) if doc is not None})
    sizes = identity(store, persona, docs=docs, common=common)
    over = {'%s/%s' % pair: size for pair, size in sizes.items() if size > limit}
    digest = sha(canonical([over, limit]))
    if over and digest not in _REPORTED:
        _REPORTED.add(digest)
        store.audit('render:' + persona, 'render.over_budget', {'pairs': over, 'limit_tokens': limit}, 'global-safe')


def budget_gate(store, persona):
    """For DocumentStore.apply, adopt_seed and promote_memory: refuse a write that grows her identity layer in a pair
    over its limit, and growth of a note already far over its own (carried.gate)."""
    from .carried import gate
    return gate(store, persona)


# Each pair has its own identity layer, bounded on its own: a section pinned to one place never fills another's.
PLACE_WORDS = {'home': '家里', 'peer': '另一个自己那条线', 'group': '群里', 'dm': '私聊'}


def over_budget_words(store, persona, pair, before, after, limit, docs=None):
    """How far a pair is over (or a write would take it), the way out, and the largest sections it carries now
    (carried.over_words)."""
    from .carried import over_words
    return over_words(store, persona, pair, before, after, limit, docs)


def system_for(store, ref: dict, *, stream: str | None = None, scope: str = 'operator') -> str:
    """Re-render the system prompt an episode fixed at preparation time: the sections its ref recorded as carried, from
    the revisions it names.

    A published core prompt change between stages yields a fresh render; the
    drift is audited rather than failing the turn.
    """
    from .carried import placed, sections, system_text
    with _LOCK:
        cached = _CACHE.get(ref['render_sha256'])
    if cached is not None:
        return cached
    revisions = {}
    for slug, field in (('persona', 'persona_doc_revision'), ('voice', 'voice_doc_revision')):
        revision = store.db.state_revisions.find_one({'_id': ref[field]}) if ref.get(field) else None
        if ref.get(field) and not revision:
            raise ValueError('SYSTEM_REF_REVISION_MISSING')
        revisions[slug] = revision['content'] if revision else None
    cls, place = ref.get('session_class', visibility.OWNER_PRIVATE), ref.get('place')
    if ref.get('carried') is not None:
        found = {}
        for slug, content in revisions.items():
            by_sid = {s['sid']: s for s in (content or {}).get('sections') or []}
            found[slug] = [by_sid[sid] for sid in ref['carried'].get(slug) or [] if sid in by_sid]
    else:                                   # a ref from before it recorded what it carried: as carried now
        persona = (store.config.get('chat') or {}).get('persona')
        found = {slug: sections(placed(store, persona, slug, content) if persona else content, cls, place)
                 for slug, content in revisions.items()}
    common = common_text(store.config)
    text = role_text(store.config, system_text(common, found, revisions), ref.get('speaks', False))
    digest = _remember(text)
    if digest != ref['render_sha256'] and stream:
        store.audit(stream, 'system.render_drift', {'expected': ref['render_sha256'], 'actual': digest,
                    'common_sha256': sha(common.encode()), 'expected_common_sha256': ref['common_sha256']}, scope)
    return text


def episode_system(store, ep: dict) -> str:
    """Stage system prompt, re-rendered from the episode's system_ref (drift is audited)."""
    return system_for(store, ep['system_ref'], stream=ep.get('_id'), scope=ep.get('scope_key', 'operator'))


def action_values(store, persona=None, cls=visibility.PUBLIC, place=None) -> str:
    """Action-brain system suffix (ADR-009 §8.3, revised by the owner 2026-10-04).

    ``render.action_persona``:
    - ``core`` (default): who she is in her own core sentences, readable in the class of the conversation the task
      came from: a person doing the work, not a software engineer, and none of her rules for talking (owner
      2026-10-14);
    - ``values``: public persona sections tagged ``render.values_tag``, else the name alone;
    - ``persona``: who she is — the persona document's every-turn sections readable in the class of the
      conversation the task came from. Never memory, relationships, emotion or other state.

    What is carried is carried.py's, for the class and place of the conversation the task came from.
    """
    name = (store.config.get('chat') or {}).get('display_name') or 'character'
    persona = persona or (store.config.get('chat') or {}).get('persona')
    if not persona:
        return '\n你是' + name + '。'
    from .persona_model import effective
    model, policy = model_and_policy(store, persona)
    mode = effective(model, 'render.action_persona', policy)
    from .carried import placed, sections as carried_sections
    if mode == 'core':
        _, core = DocumentStore(store, persona).read('core')
        sections = carried_sections(placed(store, persona, 'core', core), cls, place)
        text = '\n你是' + name + '。下面是你自己写的「我是谁」，里面的「我」就是你：照它做事、写汇报；上面的规则优先，它不扩大授权。'
        return text + ('\n' + '\n'.join(' '.join(str(s.get('body') or '').split()) for s in sections) if sections else '')
    _, content = DocumentStore(store, persona).read('persona')
    if mode == 'persona':
        sections = carried_sections(placed(store, persona, 'persona', content), cls, place)
        text = '\n你是' + name + '。下面是你人设里每回合带上的几节（你自己写的）：照它做事、写汇报；上面的规则优先，人设不扩大授权。'
        return text + ('\n' + render_markdown(sections) if sections else '')
    tag = effective(model, 'render.values_tag', policy) or 'values'
    values = [s for s in (content or {}).get('sections', [])
              if s['visibility'] == 'public' and tag in s.get('tags', [])]
    text = '\n你是' + name + '。你自己的公开价值：'
    if values:
        text += '\n' + render_markdown(values)
    return text
