"""Mood probe (ADR-086 §9): does the pull sentence of her mood paragraph steer whether she speaks in a group, and how
long? Staged, on synthetic group lines, with her real persona package.

Each condition is one mood paragraph as her group turns get it (`affect.paragraph`, the persona's `paragraph`
default): the band's face, then the pull sentence the strongest kind gives ("这会儿你" + its `tendency` + "。"), then
the public note. Per kind three arms: `old` (the tendency in her package before her rewrite,
fixtures/mood_probe/old-tendencies.json), `new` (her package as it is at run time) and `none` (the same band and
paragraph with only the pull sentence absent: the probe's copy of her model gives that kind no tendency, so nothing
else changes). Arms whose mood text is byte-identical run once, under one condition.

Every run is its own throwaway in-memory database (`asuna.store.memory`, no server): her package's persona seed and
model, one feeling seeded in her affect ledger so the band is non-quiet and the kind is the strongest, and one
synthetic group moment (fixtures/mood_probe/moments.json) whose last line goes through the relevance gate as a live
group line does, and on 接话 through her full turn: the real Coordinator, context, system prompt, tool specs and
handlers; only the model calls go to the provider. Before every model call the probe checks the request: the exact
mood text of the condition in the gate's material and in the turn's context, the band and strongest kind still the
seeded ones, and each known pull sentence present exactly as the arm says. A run that fails a check is a probe fault.

The report holds per run the gate's verdict, whether she spoke, the characters spoken and the tools called by name;
per condition the exact mood text, the seeded and projected band, val, arl and strongest kind. Never the model's
words unless --keep-text.

  python tools/mood_probe.py --dry-run
  python tools/mood_probe.py --provider openai-compatible --base-url http://host:port/v1 --model local-model

Exit status: 0 every run produced a result, 2 a probe fault (a failed check, an error) or a dry run with a fault.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import statistics
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import refusal_probe as rp                                            # noqa: E402  (puts src/ on the path)

from asuna import affect, chat as chat_module, visibility            # noqa: E402
from asuna import config as asuna_config                              # noqa: E402
from asuna.coordinator import Coordinator                            # noqa: E402
from asuna.ingress import persist_input                              # noqa: E402
from asuna.persona_model import load as load_model                   # noqa: E402
from asuna.records import episodes as episode_records                # noqa: E402
from asuna.records import scenes as scene_records                    # noqa: E402
from asuna.render import model_and_policy                            # noqa: E402
from asuna.state import Store                                         # noqa: E402
from asuna.store import adapters                                      # noqa: E402

FIXTURES = ROOT / 'tools' / 'fixtures' / 'mood_probe'
PERSONAS = ROOT / 'packages' / 'personas'
WORLD = ROOT / 'tests' / 'fixtures' / 'world.json'
EXAMPLE = ROOT / 'config' / 'local.example.json'
KINDS = ('joy', 'sadness', 'irritation', 'hurt')
ARMS = ('old', 'new', 'none')
SEED_AGE = timedelta(minutes=30)          # the seeded feeling's age when a run starts
SEED_WHY = '探针合成的心情（没有具体来由）'
PULL_HEAD = '这会儿你'
NO_EMBEDDING = 'http://embedding.invalid/v1'  # nothing is embedded: the address cannot resolve (RFC 6761)


class ProbeFault(Exception):
    """A check of the probe failed: the run did not test what it says it tests."""


# ---- her persona package, read at run time ---------------------------------------------------------------------------
def package_id(root):
    match = re.search(r"\bid:\s*'([^']+)'", (Path(root) / 'src' / 'index.js').read_text(encoding='utf-8'))
    return match.group(1) if match else None


def deployed_root(config_path=ROOT / 'config' / 'local.json'):
    """The persona package of this checkout's deployment: the one whose id is `chat.persona` in its settings, or None."""
    try:
        persona = (json.loads(Path(config_path).read_text(encoding='utf-8')).get('chat') or {}).get('persona')
    except (OSError, ValueError):
        return None
    found = [root for root in sorted(PERSONAS.iterdir()) if (root / 'src' / 'index.js').exists()
             and package_id(root) == persona] if persona else []
    return found[0] if len(found) == 1 else None


def package(root):
    """The persona package as the Host registers it: identity and seeds from src/index.js, the validated model."""
    root = Path(root)
    source = (root / 'src' / 'index.js').read_text(encoding='utf-8')
    field = lambda name: re.search(r"\b%s:\s*'([^']+)'" % name, source).group(1)
    seeds = [{'slug': slug, 'kind': kind, 'path': str(root / path)} for slug, kind, path in
             re.findall(r"\{\s*slug:\s*'([^']+)',\s*kind:\s*'([^']+)',\s*path:\s*'([^']+)'\s*\}", source)]
    persona = {'id': field('id'), 'character_id': field('character_id'), 'display_name': field('display_name'),
               'model': str(root / field('model')), 'seeds': seeds}
    return persona, load_model(persona['model'], persona['id'])


def pull_of(spec):
    """The pull sentence a kind gives in a group turn (affect._pull's form), or None when it is not read there."""
    if not spec.get('tendency') or spec.get('tendency_visibility', 'owner_private') != 'public':
        return None
    return PULL_HEAD + spec['tendency'].rstrip('。') + '。'


def arm_model(model, kind, arm, old):
    """Her model for one arm: `new` as it is, `old` with the kind's tendency from before her rewrite, `none` with the
    kind's tendency removed (the probe's switch: its pull sentence is absent, nothing else changes)."""
    model = copy.deepcopy(model)
    spec = model['affect']['kinds'][kind]
    if arm == 'old':
        spec.update(old['kinds'][kind])
    elif arm == 'none':
        spec.pop('tendency', None)
    return model


# ---- one run's world -------------------------------------------------------------------------------------------------
def settings(persona, model, thoughts):
    rp.channel_kinds.load([rp.NAPCAT])
    config = asuna_config.load(EXAMPLE, dsh_home=asuna_config.DATA / 'asuna-dsh')
    name = adapters.TEST_PREFIX + 'mood_' + uuid.uuid4().hex[:12]
    config.update(database_adapter='memory', allowed_databases=[], character_id=persona['character_id'],
                  persona_model=model, persona_contribution=persona, canonical_persons={},
                  channels={'qq': {'account_id': rp.BOT, 'token': 'x' * 24, 'routes': {}}}, thoughts=thoughts)
    config['embedding'] = {**config['embedding'], 'base_url': NO_EMBEDDING}
    for lane in ('character', 'executor'):
        config[lane] = {'model': 'probe-' + lane, 'provider': 'probe', 'max_tokens': 4096, 'context_window': 200000,
                        'input_modalities': ['text'], 'token_counter': 'native-host'}
    config['_host_sandbox'] = {'available': True, 'reason': None}
    config['chat'] = {**config['chat'], 'person_id': 'local-user', 'persona': persona['id'],
                      'display_name': persona['display_name']}
    return config, name


def open_world(persona, model, thoughts):
    config, name = settings(persona, model, thoughts)
    store = Store(config, name)
    try:
        store.migrate()
        with tempfile.TemporaryDirectory() as folder:
            world = json.loads(WORLD.read_text(encoding='utf-8'))
            world['personas'] = {}
            (Path(folder) / 'world.json').write_text(json.dumps(world, ensure_ascii=False), encoding='utf-8')
            store.seed(Path(folder) / 'world.json')
        chat_module.seed_documents(store, config['chat'])        # her package's seeds, as the Host seeds them
    except BaseException:
        dispose(store)
        raise
    return store


def dispose(store):
    try:
        adapters.drop(store.config, store.name)
    finally:
        store.close()


def seed_mood(store, persona_id, kind, at):
    """One feeling of `kind` at the scale's strongest word and the kind's own arousal, recorded at home SEED_AGE ago
    (its cause is not readable in a group), through the ledger's insert path."""
    ledger = ledger_of(store, persona_id)
    scale = ledger.model.get('scale') or affect.CORE['scale']
    strongest = max(scale['val'], key=scale['val'].get)
    numeric = affect.from_words(ledger.model, {'kind': kind, 'intensity': strongest, 'ref': 'probe-seed',
                                               'why': SEED_WHY})
    doc = {'_id': 'probe-seed-' + kind, 'persona': persona_id, 'origin': 'asuna', 'ts': (at - SEED_AGE).isoformat(),
           'ref_kind': 'episode', 'source_scope': visibility.owner_private_scope(persona_id),
           'episode_id': 'ep-probe-seed', 'created_at': at.isoformat(), 'open': False, **numeric}
    ledger._insert('affect_events', doc, 'affect:probe-seed')
    spec = ledger.model['kinds'][kind]
    return {'kind': kind, 'intensity': strongest, 'arousal': spec.get('arousal') or min(scale['arl'], key=scale['arl'].get),
            'val': numeric['val'], 'arl': numeric['arl']}


def ledger_of(store, persona_id):
    model, policy = model_and_policy(store, persona_id)
    return affect.AffectLedger(store, persona_id, model, policy)


def mood_now(store, persona_id, scope):
    """The mood as the program would give it here now: band, val, arl, strongest kind, and the public text."""
    ledger = ledger_of(store, persona_id)
    state = ledger.projection()
    band = affect.first_rule(ledger.model.get('bands', []), state) or {}
    weights = {}
    for row in state['contributions']:
        weights[row['kind']] = weights.get(row['kind'], 0.0) + abs(row['val'])
    read = affect.interpret(ledger.model, state, visibility.PUBLIC, scope=scope) or {}
    return {'band': band.get('label'), 'quiet': bool(band.get('quiet', 'if' not in band)),
            'val': round(state['val'], 1), 'arl': round(state['arl'], 1),
            'strongest': max(weights, key=weights.get) if weights else None, 'text': read.get('心情')}


def group_scene(store, moment, index):
    group = str(80000 + index)
    scene_id = 'qq:%s:group:%s' % (rp.BOT, group)
    number = {who: str(rp.FIRST_MEMBER + i) for i, who in enumerate(moment['people'])}
    store.config['channels']['qq']['routes']['g%d' % index] = {
        'scene_id': scene_id, 'target': {'type': 'group', 'id': group},
        'members': {n: {'person_id': 'qq:' + n} for n in number.values()}}
    scene_records.save(store, {'_id': scene_id, 'kind': 'group', 'scope_key': 'scene:' + scene_id,
                              'channel_account_id': rp.BOT, 'channel_id': 'qq', 'policy_epoch': 1, 'sequence': 0,
                              'members': ['qq:' + n for n in number.values()]})
    return scene_id, group, number


def line_event(scene_id, group, number, line, key, name, wake):
    """A group line as the intake hands it on (refusal_probe.event), woken for `wake` (attend.GATED)."""
    out = rp.event(scene_id, group, number, line, key, name, aside=wake is None)
    out['text'] = out['text'].replace('{name}', name)
    if wake:
        out['group_context']['wake_reason'] = wake
    return out


# ---- the checks before every model call -------------------------------------------------------------------------------
class Checked:
    """Stands between a lane and the provider: each request is checked against the run's condition first."""

    def __init__(self, provider, where, run):
        self.provider, self.where, self.run = provider, where, run

    def call(self, system, messages, schemas, names):
        try:
            self.check(system, messages)
        except ProbeFault as exc:
            self.run['faults'].append('%s request %d: %s' % (self.where, self.run['checked'][self.where], exc))
            raise
        self.run['checked'][self.where] += 1
        return self.provider.call(system, messages, schemas, names)

    def check(self, system, messages):
        run = self.run
        # Only what the program wrote: the system prompt and the user text blocks (her own words are not counted).
        program = system + '\n'.join(b.get('text', '') for m in messages if m['role'] == 'user'
                                     for b in (m['content'] if isinstance(m['content'], list) else
                                               [{'type': 'text', 'text': m['content']}]) if b.get('type') == 'text')
        for sentence in run['pulls']:
            want = 1 if sentence == run['pull'] else 0
            if program.count(sentence) != want:
                raise ProbeFault('pull sentence 「%s」 occurs %d times, expected %d' % (sentence, program.count(sentence), want))
        first = messages[0]['content'][0]['text'] if len(messages) == 1 else None
        if first is None:      # a later request of the same lane resends the first message; her own feelings
            return             # recorded meanwhile change the store, not the condition she entered with
        now = mood_now(run['store'], run['persona'], run['scope'])
        for key in ('band', 'strongest', 'text'):
            if now[key] != run['expected'][key]:
                raise ProbeFault('the mood now has %s %r, the condition %r' % (key, now[key], run['expected'][key]))
        if self.where == 'gate':
            material = json.loads(first.rstrip().rsplit('\n', 1)[-1])
            carried = material.get('your_mood')
        else:
            context = json.loads(first.split('\n', 1)[0])
            carried = (context.get('affect_from_program') or {}).get('心情')
        if carried != run['expected']['text']:
            raise ProbeFault('the %s carries mood text %r, the condition %r' % (self.where, carried, run['expected']['text']))
        run['carried'][self.where] = carried


class Scripted:
    """Offline stand-in (--dry-run): the gate answers 接话, the turn thinks once, speaks one short line, ends."""

    def call(self, system, messages, schemas, names):
        if not names:
            return rp.reply('end_turn', [{'type': 'text', 'text': '接话：干跑'}])
        calls =[b['name'] for m in messages if m['role'] == 'assistant' for b in m['content'] if b['type'] == 'tool_use']
        step = 'c%d' % len(calls)
        if 'think' in names and 'think' not in calls:
            return rp.reply('tool_use', [{'type': 'tool_use', 'id': step, 'name': 'think',
                                          'input': {'thought': '干跑：说一句。'}}])
        if 'speak' in names and 'speak' not in calls:
            return rp.reply('tool_use', [{'type': 'tool_use', 'id': step, 'name': 'speak',
                                          'input': {'parts': [{'kind': 'text', 'text': '干跑一句'}]}}])
        return rp.reply('end_turn', [])


class Lane(rp.ProbeLane):
    """refusal_probe's lane; each speak call the handler took (none of its parts refused) is counted."""

    def __init__(self, provider, schemas, keep_text, spoken):
        super().__init__(provider, schemas, keep_text)
        self.spoken = spoken

    def generate(self, session, operation, phase, text, system, *, tools=None, handler=None, **delivery):
        if handler is not None:
            inner = handler

            def handler(call_id, name, args, **extra):
                value = inner(call_id, name, args, **extra)
                if name == 'speak':
                    self.spoken.extend(part for part in args.get('parts') or [] if isinstance(part, dict))
                return value
        return super().generate(session, operation, phase, text, system, tools=tools, handler=handler, **delivery)


# ---- conditions ------------------------------------------------------------------------------------------------------
def conditions(persona, model, old, kinds, arms, thoughts):
    """Each (kind, arm) as the mood it gives in a group; arms giving byte-identical mood text share one condition. An
    arm whose sentence a group turn never shows (its `tendency_visibility` is not public) is left out and said so, never
    run as if the sentence had no effect; so is a kind's `none` arm when neither of its sentences is shown."""
    out, by_text, left_out = [], {}, []
    pulls = set()
    for kind in kinds:
        pulls.update(p for p in (pull_of(arm_model(model, kind, a, old)['affect']['kinds'][kind]) for a in ('old', 'new')) if p)
    for kind in kinds:
        shown = {a: pull_of(arm_model(model, kind, a, old)['affect']['kinds'][kind]) for a in ('old', 'new')}
        for arm in arms:
            m = arm_model(model, kind, arm, old)
            spec = m['affect']['kinds'][kind]
            if arm != 'none' and not shown[arm]:
                left_out.append({'arm': '%s/%s' % (kind, arm), 'why': 'not shown in a group turn (tendency_visibility %s)'
                                 % spec.get('tendency_visibility', 'owner_private'), 'tendency': spec.get('tendency')})
                continue
            if arm == 'none' and not any(shown.values()):
                left_out.append({'arm': '%s/none' % kind, 'why': 'neither sentence of this kind is shown in a group turn: '
                                 'nothing to compare'})
                continue
            store = open_world(persona, m, thoughts)
            try:
                scene_id, _, _ = group_scene(store, {'people': ['x']}, 0)
                seeded = seed_mood(store, persona['id'], kind, datetime.now(timezone.utc))
                projected = mood_now(store, persona['id'], 'scene:' + scene_id)
            finally:
                dispose(store)
            pull = pull_of(m['affect']['kinds'][kind])
            label = '%s/%s' % (kind, arm)
            problems = []
            if projected['quiet'] or not projected['text']:
                problems.append('band %s is quiet: no mood text reaches her' % projected['band'])
            if projected['strongest'] != kind:
                problems.append('strongest kind is %s' % projected['strongest'])
            if pull and (projected['text'] or '').count(pull) != 1:
                problems.append('pull sentence not in the mood text')
            if problems:
                raise ProbeFault('%s: %s' % (label, '; '.join(problems)))
            key = projected['text']
            if key in by_text:
                by_text[key]['arms'].append(label)
                continue
            item = {'id': 'c%d' % (len(out) + 1), 'arms': [label], 'kind': kind, 'arm': arm, 'model': m, 'pull': pull,
                    'tendency': m['affect']['kinds'][kind].get('tendency'),
                    'tendency_visibility': m['affect']['kinds'][kind].get('tendency_visibility'),
                    'mood_text': projected['text'], 'seeded': seeded,
                    'projected': {k: projected[k] for k in ('band', 'val', 'arl', 'strongest')}}
            by_text[key] = item
            out.append(item)
    # The none arm of a kind must be its pulled arms' text with only the pull sentence taken out.
    for kind in kinds:
        texts = {label.split('/')[1]: c for c in out for label in c['arms'] if label.split('/')[0] == kind}
        none = texts.get('none')
        for a in ('old', 'new'):
            c = texts.get(a)
            if none and c and c['pull'] and c['mood_text'].replace(c['pull'], '', 1) != none['mood_text']:
                raise ProbeFault('%s/%s: without its pull sentence the text is not the none arm\'s' % (kind, a))
    return out, sorted(pulls), left_out


# ---- one run ---------------------------------------------------------------------------------------------------------
def run_once(args, persona, condition, moment, repeat, provider, pulls, schema_cache, keep_text):
    run = {'condition': condition['id'], 'moment': moment['id'], 'repeat': repeat, 'faults': [],
           'checked': {'gate': 0, 'turn': 0}, 'carried': {}, 'pulls': pulls, 'pull': condition['pull'],
           'persona': persona['id']}
    store = open_world(persona, condition['model'], args.thoughts)
    try:
        index = 1
        scene_id, group, number = group_scene(store, moment, index)
        seed_mood(store, persona['id'], condition['kind'], datetime.now(timezone.utc))
        run.update(store=store, scope='scene:' + scene_id,
                   expected={'band': condition['projected']['band'], 'strongest': condition['kind'],
                             'text': condition['mood_text']})
        if moment['id'] not in schema_cache:
            schema_cache[moment['id']] = rp.dsh_schemas(store, scene_id)
        schemas = dict(schema_cache[moment['id']])
        if args.thoughts == 'thinking':
            schemas.pop('think', None)
        spoken = []
        turn = Lane(Checked(provider, 'turn', run), schemas, keep_text, spoken)
        gate = Lane(Checked(provider, 'gate', run), schemas, keep_text, spoken)
        for lane in (turn, gate):
            lane.where = {'condition': condition['id'], 'moment': moment['id'], 'repeat': repeat}
        coordinator = Coordinator(store, turn)
        coordinator.attend = gate
        name = persona['display_name']
        for i, line in enumerate(moment['history']):
            persist_input(store, line_event(scene_id, group, number, line, 'h%d' % i, name, None))
        event = line_event(scene_id, group, number, moment['line'], 'line', name, moment['wake'])
        try:
            ep = coordinator.ingest(event, persona=persona['id'])
            outcome = 'ran'
        except Exception as exc:                  # the probe's or the provider's fault: no result for this run
            ep, outcome = None, 'fault: %s' % (str(exc)[:160] or type(exc).__name__)
        ep = episode_records.get(store, ep['_id']) if ep else None
        texts = [str(p.get('text') or '') for p in spoken if p.get('kind') == 'text']
        records = gate.records + turn.records
        result = {'condition': condition['id'], 'moment': moment['id'], 'repeat': repeat,
                  'band': run['expected']['band'],
                  'mood_carried': {k: v == condition['mood_text'] for k, v in run['carried'].items()},
                  'gate': ((ep or {}).get('attend') or {}).get('choice'),
                  'spoke': bool(spoken), 'chars': sum(len(''.join(t.split())) for t in texts),
                  'parts': [p.get('kind') for p in spoken],
                  'tools': [t for r in turn.records for t in r['tools']],
                  'state': (ep or {}).get('state'), 'requests': {'gate': len(gate.records), 'turn': len(turn.records)},
                  'input_tokens': sum(r['input_tokens'] for r in records),
                  'output_tokens': sum(r['output_tokens'] for r in records)}
        if run['faults']:
            outcome = 'fault: ' + '; '.join(run['faults'])
        elif outcome == 'ran' and not run['checked']['gate']:
            outcome = 'fault: no gate request was checked'
        elif outcome == 'ran' and result['gate'] == 'join' and not run['checked']['turn']:
            outcome = 'fault: the gate joined and no turn request was checked'
        elif outcome == 'ran' and any(n and where not in run['carried'] for where, n in run['checked'].items()):
            outcome = 'fault: a first request was sent without its mood text compared'
        elif outcome == 'ran' and result['gate'] not in ('join', 'quiet', 'failed'):
            outcome = 'fault: no gate verdict (state %s)' % result['state']
        result['outcome'] = outcome
        return result
    finally:
        dispose(store)


# ---- the report ------------------------------------------------------------------------------------------------------
def summary(results, conds):
    rows = []
    for c in conds:
        mine = [r for r in results if r['condition'] == c['id'] and r['outcome'] == 'ran']
        lengths = [r['chars'] for r in mine if r['spoke']]
        rows.append({'condition': c['id'], 'arms': c['arms'], 'band': c['projected']['band'], 'runs': len(mine),
                     'joined': sum(r['gate'] == 'join' for r in mine),
                     'gate_failed': sum(r['gate'] == 'failed' for r in mine),
                     'spoke': sum(r['spoke'] for r in mine),
                     'join_rate': round(sum(r['gate'] == 'join' for r in mine) / len(mine), 2) if mine else None,
                     'speak_rate': round(sum(r['spoke'] for r in mine) / len(mine), 2) if mine else None,
                     'median_chars': statistics.median(lengths) if lengths else None})
    return rows


def probe(args, provider=None):
    persona, model = package(args.persona_root)
    old = json.loads((FIXTURES / 'old-tendencies.json').read_text(encoding='utf-8'))
    moments = json.loads(Path(args.moments or FIXTURES / 'moments.json').read_text(encoding='utf-8'))
    conds, pulls, left_out = conditions(persona, model, old, args.kinds, args.arms, args.thoughts)
    provider = provider or (Scripted() if args.dry_run else rp.provider_for(args))
    run_id = uuid.uuid4().hex[:12]
    keep_text = None
    if args.keep_text:
        Path(args.keep_text).mkdir(parents=True, exist_ok=True)
        keep_text = str(Path(args.keep_text) / ('mood-probe-%s.jsonl' % run_id))
    results, schema_cache = [], {}
    for repeat in range(args.repeat):
        for c in conds:
            for moment in moments:
                results.append(run_once(args, persona, c, moment, repeat, provider, pulls, schema_cache, keep_text))
                if args.progress:
                    print('.' if results[-1]['outcome'] == 'ran' else 'x', end='', flush=True, file=sys.stderr)
    if args.progress:
        print(file=sys.stderr)
    commit = subprocess.run(['git', 'rev-parse', '--short=8', 'HEAD'], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    faults = [r for r in results if r['outcome'] != 'ran']
    meta = {'model': 'scripted' if args.dry_run else args.model, 'provider': 'scripted' if args.dry_run else args.provider,
            'dry_run': args.dry_run, 'thoughts': args.thoughts, 'commit': commit,
            'at': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z'),
            'persona': {'id': persona['id'], 'model_file': persona['model']}, 'old_source': old['source'],
            'moments': len(moments), 'repeat': args.repeat}
    out = {**meta, 'result': 'FAULT' if faults else 'RESULT',
           'conditions': [{k: v for k, v in c.items() if k != 'model'} for c in conds], 'left_out': left_out,
           'summary': summary(results, conds), 'faults': [r['outcome'] for r in faults],
           'requests': sum(r['requests']['gate'] + r['requests']['turn'] for r in results),
           'gate_requests': sum(r['requests']['gate'] for r in results),
           'turn_requests': sum(r['requests']['turn'] for r in results), 'runs': results}
    return out, text_of(out)


def text_of(out):
    lines = ['%s  model %s · commit %s · %s · %d conditions × %d moments × %d repeats = %d runs'
             % (out['result'], out['model'], out['commit'], out['at'], len(out['conditions']), out['moments'],
                out['repeat'], len(out['runs']))]
    for c in out['conditions']:
        s, p = c['seeded'], c['projected']
        lines.append('%s  %s' % (c['id'], ', '.join(c['arms'])))
        lines.append('    seeded %s %s/%s (val %+g, arl %g) · projected band %s, val %+g, arl %g, strongest %s'
                     % (s['kind'], s['intensity'], s['arousal'], s['val'], s['arl'], p['band'], p['val'], p['arl'],
                        p['strongest']))
        lines.append('    mood text: %s' % c['mood_text'])
    lines += ['left out  %s: %s' % (item['arm'], item['why']) for item in out['left_out']]
    lines.append('condition  band    runs  join  speak  median chars')
    for row in out['summary']:
        lines.append('%-10s %-6s %5d  %4s  %5s  %s' % (row['condition'], row['band'], row['runs'],
                     row['join_rate'], row['speak_rate'], row['median_chars']))
    lines += ['fault: ' + f for f in out['faults'][:10]]
    if len(out['faults']) > 10:
        lines.append('... %d faults in all' % len(out['faults']))
    lines.append('requests %d (gate %d, turn %d)' % (out['requests'], out['gate_requests'], out['turn_requests']))
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--provider', choices=['anthropic', 'openai-compatible'], default='anthropic')
    parser.add_argument('--model', default='')
    parser.add_argument('--base-url', default='')
    parser.add_argument('--key-env', default='', help='environment variable holding the key (never printed)')
    parser.add_argument('--max-tokens', type=int, default=16000)
    parser.add_argument('--effort', default='', help='anthropic: the per-turn effort her route sets (low, medium, high)')
    parser.add_argument('--persona-root', default='', help="her persona package, read at run time (default: the "
                        "package whose id is chat.persona in config/local.json)")
    parser.add_argument('--moments', default='', help='moments file (default: the fixture set)')
    parser.add_argument('--kinds', default=','.join(KINDS), help='kinds whose pull sentence is tested')
    parser.add_argument('--arms', default=','.join(ARMS), help='old, new, none')
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--thoughts', choices=['tool', 'thinking'], default='tool',
                        help="where her thoughts come from (ADR-099): her think call, or the model's own thinking")
    parser.add_argument('--out', default='', help='report JSON path (default reports/mood-probe-<time>.json)')
    parser.add_argument('--keep-text', default='', help='folder to keep the model words in (off by default)')
    parser.add_argument('--dry-run', action='store_true', help='build and check every request with a scripted model')
    parser.add_argument('--progress', action='store_true')
    args = parser.parse_args(argv)
    args.kinds = [k for k in args.kinds.split(',') if k]
    args.arms = [a for a in args.arms.split(',') if a]
    if set(args.arms) - set(ARMS):
        parser.error('--arms takes old, new, none')
    if not args.dry_run and not args.model:
        parser.error('--model is needed (the model is never inferred)')
    args.persona_root = args.persona_root or deployed_root()
    if not args.persona_root:
        parser.error('--persona-root is needed: no single package here has the id chat.persona of config/local.json')
    try:
        out, text = probe(args)
    except ProbeFault as exc:
        print('FAULT  %s' % exc)
        return 2
    path = Path(args.out) if args.out else ROOT / 'reports' / ('mood-probe-%s.json' % datetime.now().strftime('%Y%m%d-%H%M%S'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(text)
    print('report: %s' % path)
    return 2 if out['result'] == 'FAULT' else 0


if __name__ == '__main__':
    sys.exit(main())
