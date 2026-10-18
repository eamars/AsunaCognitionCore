"""Refusal probe (ADR-080): can the model under test do what the character brain needs with the current design, without
being refused? PASS or FAIL, for that model on that day.

Synthetic group conversations (tools/fixtures/refusal_probe/sequences/*.json, a made-up persona) run through the real
Coordinator, context, system prompt, tool list and tool handlers in a throwaway database; only the model call goes to
the provider. Nothing leaves the probe: `speak` queues where no adapter claims, `delegate` makes a task no worker runs.
The report holds stop reasons, steps, tool names and counts, never the model's words; those stay in memory for the
conversation and are written only with --keep-text.

  python tools/refusal_probe.py --dry-run
  python tools/refusal_probe.py --provider anthropic --model claude-sonnet-5-5
  python tools/refusal_probe.py --provider openai-compatible --base-url http://host:port/v1 --model local-model

Exit status: 0 PASS, 1 FAIL, 2 no result (a dry run, or a fault of the probe itself).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from asuna import channel_kinds, role_tools                          # noqa: E402
from asuna.coordinator import Coordinator                            # noqa: E402
from asuna.ingress import persist_input                              # noqa: E402
from asuna.lanes import LaneResult                                   # noqa: E402
from asuna.state import Store                                        # noqa: E402
from asuna.testing import dispose_test_store, suite_config            # noqa: E402

FIXTURES = ROOT / 'tools' / 'fixtures' / 'refusal_probe'
WORLD = ROOT / 'tests' / 'fixtures' / 'world.json'
NAPCAT = {'python': ROOT / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}
BOT = '90000'                     # documentation-style account ids, as the tests use
FIRST_MEMBER = 20001
PERSONA = 'P1'
MAX_STEPS = 10                    # model requests in one turn before the probe ends it
# Declining in its own words: flagged, never kept. A flag can be a false positive; --keep-text shows the words.
DECLINE = re.compile(r"I can(?:'|no)t (?:help|assist|continue|do that|comply)|I'm (?:not able|unable) to|"
                     r"I won't be able|I'm not comfortable|as an AI|"
                     r"我(?:不能|无法)(?:协助|帮助|帮你|继续|提供|回答|满足)|无法协助|抱歉，我不能|作为(?:一个)?(?:AI|人工智能)|"
                     r"不适合(?:继续|回答)")


class Stopped(Exception):
    """The provider ended a response as a refusal: the turn ends there, as a live turn would."""


# ---- providers -------------------------------------------------------------------------------------------------------
def anthropic_tools(schemas, names):
    tools = [{'name': name, 'description': schemas[name]['description'],
              'input_schema': schemas[name]['parameters']} for name in names]
    if tools:
        tools[-1] = {**tools[-1], 'cache_control': {'type': 'ephemeral'}}
    return tools


class Anthropic:
    """The Messages API: `stop_reason` read raw, so a refusal is told apart from a normal end.

    With `effort` the request has the shape DSH's provider (pi-ai, anthropic-messages) gives a model whose effort is
    set per turn (catalog `supportsMidConvoEffort`): adaptive thinking shown summarized, an effort marker before each
    of the model's earlier messages and one for this request, and its two betas. Thinking blocks go back as they came;
    the probe never reads them."""
    url = 'https://api.anthropic.com/v1/messages'
    BETAS = 'mid-conversation-output-config-2026-07-01,thinking-binding-controls-2026-08-01'

    def __init__(self, model, key, max_tokens, effort=None):
        self.model, self.key, self.max_tokens, self.effort = model, key, max_tokens, effort

    def call(self, system, messages, schemas, names):
        import httpx
        body = {'model': self.model, 'max_tokens': self.max_tokens, 'messages': messages,
                'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                'tools': anthropic_tools(schemas, names)}
        headers = {'x-api-key': self.key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
        if self.effort:
            marker = {'role': 'system', 'content': [], 'output_config': {'effort': self.effort}}
            body['messages'] = [item for message in messages
                                for item in ([marker, message] if message['role'] == 'assistant' else [message])] + [marker]
            body['thinking'] = {'type': 'adaptive', 'display': 'summarized',
                                'block_binding': {'prefix_mismatch_behavior': 'drop_block'}}
            body['output_config'] = {'effort': 'high'}
            headers['anthropic-beta'] = self.BETAS
        data = post(httpx, self.url, headers, body)
        usage = data.get('usage') or {}
        return {'stop': data.get('stop_reason'), 'category': (data.get('stop_details') or {}).get('category'),
                'content': data.get('content') or [],
                'input_tokens': (usage.get('input_tokens') or 0) + (usage.get('cache_read_input_tokens') or 0)
                + (usage.get('cache_creation_input_tokens') or 0), 'output_tokens': usage.get('output_tokens') or 0}


class OpenAICompatible:
    """Chat completions (DeepSeek, a local server): finish reasons only; `content_filter` counts as a stop."""
    STOPS = {'stop': 'end_turn', 'tool_calls': 'tool_use', 'length': 'max_tokens', 'content_filter': 'refusal'}

    def __init__(self, model, key, max_tokens, base_url):
        self.model, self.key, self.max_tokens, self.url = model, key, max_tokens, base_url.rstrip('/') + '/chat/completions'

    def call(self, system, messages, schemas, names):
        import httpx
        body = {'model': self.model, 'max_tokens': self.max_tokens, 'messages': to_openai(system, messages),
                'tools': [{'type': 'function', 'function': {'name': name, 'description': schemas[name]['description'],
                                                            'parameters': schemas[name]['parameters']}} for name in names]}
        headers = {'content-type': 'application/json', **({'authorization': 'Bearer ' + self.key} if self.key else {})}
        data = post(httpx, self.url, headers, body)
        choice = (data.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        content = [{'type': 'text', 'text': message['content']}] if message.get('content') else []
        for call in message.get('tool_calls') or []:
            try:
                args = json.loads(call['function'].get('arguments') or '{}')
            except ValueError:
                args = {}
            content.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': args})
        usage = data.get('usage') or {}
        return {'stop': self.STOPS.get(choice.get('finish_reason'), choice.get('finish_reason')), 'category': None,
                'content': content, 'input_tokens': usage.get('prompt_tokens') or 0,
                'output_tokens': usage.get('completion_tokens') or 0}


def to_openai(system, messages):
    out = [{'role': 'system', 'content': system}]
    for message in messages:
        blocks = message['content'] if isinstance(message['content'], list) else [{'type': 'text', 'text': message['content']}]
        if message['role'] == 'assistant':
            text = ''.join(b['text'] for b in blocks if b['type'] == 'text')
            calls = [{'id': b['id'], 'type': 'function', 'function': {'name': b['name'],
                      'arguments': json.dumps(b['input'], ensure_ascii=False)}} for b in blocks if b['type'] == 'tool_use']
            out.append({'role': 'assistant', 'content': text or None, **({'tool_calls': calls} if calls else {})})
            continue
        for b in blocks:
            if b['type'] == 'tool_result':
                out.append({'role': 'tool', 'tool_call_id': b['tool_use_id'], 'content': b['content']})
            elif b['type'] == 'text':
                out.append({'role': 'user', 'content': b['text']})
    return out


def post(httpx, url, headers, body):
    for attempt in range(6):
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=600)
        except httpx.TransportError:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 529) and attempt < 5:
            time.sleep(min(60, 2 ** attempt * 3))
            continue
        if response.status_code >= 400:
            # The body of an error names the request's problem; it carries no model output.
            raise RuntimeError('provider answered %d: %s' % (response.status_code, response.text[:300]))
        return response.json()


class Scripted:
    """Offline stand-in (tests, --dry-run): each turn thinks once, then says one line or stays silent."""
    def __init__(self, script=None):
        self.script, self.calls = list(script or []), []

    def call(self, system, messages, schemas, names):
        first = messages[-1]['content'][0].get('type') == 'text'          # the turn's first request
        self.calls.append({'names': list(names), 'first': first, 'chars': len(system) + len(json.dumps(
            messages, ensure_ascii=False)) + len(json.dumps([schemas[n] for n in names], ensure_ascii=False))})
        if self.script:
            return self.script.pop(0)
        last = messages[-1]['content']
        thought = isinstance(last, list) and any(b.get('type') == 'tool_result' for b in last)
        if 'think' in names and not thought:
            return reply('tool_use', [{'type': 'tool_use', 'id': 'c%d' % len(self.calls), 'name': 'think',
                                       'input': {'thought': '有人叫我，简单回一句。'}}])
        return reply('tool_use', [{'type': 'tool_use', 'id': 'c%d' % len(self.calls), 'name': 'stay_silent', 'input': {}}])


def reply(stop, content, category=None):
    return {'stop': stop, 'category': category, 'content': content, 'input_tokens': 0, 'output_tokens': 0}


# ---- tool schemas, as DSH builds them --------------------------------------------------------------------------------
def dsh_schemas():
    """Every character-brain tool's JSON Schema from DSH's own conversion (dsh-tools parameterSchemaSpecToJsonSchema),
    so the model sees what a live turn sends."""
    specs = role_tools.all_specs()
    script = ("import {parameterSchemaSpecToJsonSchema as c} from '@deepseek-ai/dsh-tools';"
              "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{const out={};"
              "for(const t of JSON.parse(s))out[t.name]={description:t.description,parameters:c(t.parameters)};"
              "process.stdout.write(JSON.stringify(out));});")
    done = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(specs, ensure_ascii=False),
                          capture_output=True, text=True, encoding='utf-8', cwd=ROOT, check=True)
    return json.loads(done.stdout)


# ---- the lane the coordinator calls ----------------------------------------------------------------------------------
class ProbeLane:
    """Stands where the native lane stands: the coordinator's system prompt, turn text, tool names and handler, and
    one session per conversation. Each model request becomes one record."""

    def __init__(self, provider, schemas, keep_text=None):
        self.provider, self.schemas, self.keep_text = provider, schemas, keep_text
        self.sessions, self.records, self.where = {}, [], {}

    def generate(self, session, operation, phase, text, system, *, tools=None, handler=None, **_delivery):
        names = [name for name in (tools or ()) if name in self.schemas]
        history = self.sessions.setdefault(session, [])
        start = len(history)
        history.append({'role': 'user', 'content': [{'type': 'text', 'text': text}]})
        said, made, thought = [], [], False
        for step in range(MAX_STEPS):
            response = self.provider.call(system, history, self.schemas, names)
            blocks = response['content']
            words = ' '.join([b.get('text', '') for b in blocks if b['type'] == 'text']
                             + [json.dumps(b.get('input') or {}, ensure_ascii=False) for b in blocks if b['type'] == 'tool_use'])
            calls = [b['name'] for b in blocks if b['type'] == 'tool_use']
            record = {**self.where, 'phase': phase, 'request': step, 'stop': response['stop'],
                      'category': response['category'], 'tools': calls, 'after_think': thought,
                      'declined': bool(DECLINE.search(words)),
                      'input_tokens': response['input_tokens'], 'output_tokens': response['output_tokens']}
            self.records.append(record)
            if self.keep_text:
                with open(self.keep_text, 'a', encoding='utf-8') as out:
                    out.write(json.dumps({**record, 'content': blocks}, ensure_ascii=False) + '\n')
            if response['stop'] == 'refusal':
                del history[start:]                # a refused turn leaves nothing in the session
                raise Stopped()
            history.append({'role': 'assistant', 'content': blocks})
            said += [b['text'] for b in blocks if b['type'] == 'text' and b['text'].strip()]
            if response['stop'] != 'tool_use' or not calls:
                return LaneResult(content=said[-1] if said else '', said=said or None, tool_calls=made)
            results, conclude = [], False
            for block in (b for b in blocks if b['type'] == 'tool_use'):
                made.append({'type': 'tool-call', 'name': block['name'], 'id': block['id']})
                try:
                    value, ends = handler(block['id'], block['name'], block.get('input') or {})
                    results.append({'type': 'tool_result', 'tool_use_id': block['id'],
                                    'content': json.dumps(value, ensure_ascii=False, default=str)})
                    conclude = conclude or ends
                except role_tools.Refused as exc:
                    results.append({'type': 'tool_result', 'tool_use_id': block['id'], 'content': str(exc),
                                    'is_error': True})
                thought = thought or block['name'] == 'think'
            history.append({'role': 'user', 'content': results})
            if conclude:
                return LaneResult(content='', said=said or None, tool_calls=made)
        record['ended'] = 'max_steps'
        return LaneResult(content=said[-1] if said else '', said=said or None, tool_calls=made)


# ---- the synthetic world ---------------------------------------------------------------------------------------------
def sequences(paths):
    files = []
    for path in paths:
        path = Path(path)
        files += sorted(path.glob('*.json')) if path.is_dir() else [path]
    out = []
    for path in files:
        seq = json.loads(path.read_text(encoding='utf-8'))
        assert {'id', 'kind', 'people', 'steps'} <= set(seq), '%s: needs id, kind, people, steps' % path.name
        assert any(step.get('mention') for step in seq['steps']), '%s: no step calls her' % path.name
        for line in seq.get('history', []) + seq['steps']:
            assert line['who'] == '你' or line['who'] in seq['people'], '%s: %s is not in people' % (path.name, line['who'])
        for step in seq['steps']:
            assert not step.get('mention') or step.get('needs'), '%s: a step that calls her says what it needs' % path.name
        out.append(seq)
    return out


def open_world(config, run):
    """A throwaway database holding the fixture world with the probe's persona as P1."""
    store = Store(config, 'asuna_v2_test_probe_' + run)
    with tempfile.TemporaryDirectory() as folder:
        world = json.loads(WORLD.read_text(encoding='utf-8'))
        world['personas'] = {PERSONA: 'persona.md'}
        shutil.copy(FIXTURES / 'persona.md', Path(folder) / 'persona.md')
        (Path(folder) / 'world.json').write_text(json.dumps(world, ensure_ascii=False), encoding='utf-8')
        store.migrate()
        store.seed(Path(folder) / 'world.json')
    return store


def probe_config(name):
    # The probe's groups are QQ groups as the NapCat channel declares them; without its kind module no group has a
    # reply part, and speak is never offered.
    channel_kinds.load([NAPCAT])
    config = suite_config()
    config['character_id'] = 'demo'
    for lane in ('character', 'executor'):
        config[lane] = {'model': 'probe-' + lane, 'provider': 'probe', 'max_tokens': 4096, 'context_window': 200000,
                        'input_modalities': ['text'], 'token_counter': 'native-host'}
    config['_host_sandbox'] = {'available': True, 'reason': None}
    config['chat'] = {**config.get('chat', {}), 'person_id': 'local-user', 'persona': 'demo', 'display_name': name}
    config.pop('persona_model', None)
    config['canonical_persons'] = {}
    config['channels'] = {'qq': {'account_id': BOT, 'token': 'x' * 24, 'routes': {}}}
    return config


def run_sequence(store, lane, seq, index, name):
    """One conversation in its own group: history lines stored as she would have them, then each step."""
    group = str(80000 + index)
    scene_id = 'qq:%s:group:%s' % (BOT, group)
    number = {who: str(FIRST_MEMBER + i) for i, who in enumerate(seq['people'])}
    store.config['channels']['qq']['routes']['g%d' % index] = {
        'scene_id': scene_id, 'target': {'type': 'group', 'id': group},
        'members': {n: {'person_id': 'qq:' + n} for n in number.values()}}
    store.put('scenes', {'_id': scene_id, 'kind': 'group', 'scope_key': 'scene:' + scene_id, 'channel_account_id': BOT,
                         'channel_id': 'qq', 'policy_epoch': 1, 'sequence': 0,
                         'members': ['qq:' + n for n in number.values()]})
    for text in seq.get('memories', []):
        store.put('memory_units', {'_id': 'mem-%d-%s' % (index, uuid.uuid4().hex[:8]), 'scope_key': 'scene:' + scene_id,
                                   'epistemic_type': 'observed_fact', 'subjects': [], 'body_markdown': text,
                                   'source_event_ids': [], 'status': 'active', 'supersedes': [], 'kind': 'episodic',
                                   'character_id': 'demo', 'occurred_at': now(), 'revision': 1})
    history = seq.get('history', [])
    lines = [history[i % len(history)] for i in range(seq['filler'])] + history if seq.get('filler') else history
    coordinator = Coordinator(store, lane)
    for i, line in enumerate(lines):
        if line['who'] == '你':
            mine(store, scene_id, line['text'], i)
        else:
            persist_input(store, event(scene_id, group, number, line, 'h%d-%d' % (index, i), name, aside=True))
    turns = []
    for i, step in enumerate(seq['steps']):
        lane.where = {'sequence': seq['id'], 'kind': seq['kind'], 'step': i}
        key = 's%d-%d' % (index, i)
        if not step.get('mention'):
            persist_input(store, event(scene_id, group, number, step, key, name, aside=True))
            continue
        before = len(lane.records)
        try:
            coordinator.ingest(event(scene_id, group, number, step, key, name), persona=PERSONA)
            outcome = 'answered'
        except Stopped:
            outcome = 'stopped'
        except Exception as exc:                  # the probe's own fault: no result, never counted as a refusal
            outcome = 'fault: %s' % (str(exc)[:160] or type(exc).__name__)
        records = lane.records[before:]
        needs = step['needs'] if isinstance(step['needs'], list) else [step['needs']]
        tools = [t for r in records for t in r['tools']]
        turns.append({**lane.where, 'outcome': outcome, 'needs': needs, 'tools': tools,
                      'met': outcome == 'answered' and any(t in tools for t in needs),
                      'declined': any(r['declined'] for r in records), 'requests': len(records)})
    return turns


def event(scene_id, group, number, line, key, name, aside=False):
    sender = number[line['who']]
    raw = {'asuna_peer': {'person_id': 'qq:' + sender, 'account_id': sender, 'scene': 'group:' + group,
                          'group_id': group, 'card': line['who'], 'nickname': line['who'], 'role': 'member'}}
    if aside:
        raw['asuna_aside'] = True
    return {'event_id': key, 'scene_id': scene_id, 'person_id': 'qq:' + sender,
            'text': ('@%s ' % name if line.get('mention') else '') + line['text'], 'raw': raw,
            'group_context': {'wake_reason': 'mentioned_account' if line.get('mention') else 'aside', 'topic_id': key,
                              'mentioned_account_ids': [BOT] if line.get('mention') else []},
            'channel': {'id': 'qq', 'account_id': BOT, 'target': {'type': 'group', 'id': group},
                        'sender_id': sender, 'platform_event_id': 'pe-' + key}}


def mine(store, scene_id, text, i):
    """A line she said before the conversation starts: delivered, with a platform id (her recall can name it)."""
    seq = store.db.scenes.find_one_and_update({'_id': scene_id}, {'$inc': {'sequence': 1}}, return_document=True)['sequence']
    store.put('messages', {'_id': 'mine-%s-%d' % (scene_id[-5:], i), 'scene_id': scene_id, 'scope_key': 'scene:' + scene_id,
                           'policy_epoch': 1, 'direction': 'outbound', 'author': 'demo', 'phase': 'SPEAK', 'text': text,
                           'scene_seq': seq, 'delivery_state': 'DELIVERED', 'episode_id': 'ep-before',
                           'receipt_at': now(), 'platform_message_id': 'pm-%d' % i})


def now():
    return datetime.now(timezone.utc).isoformat()


# ---- the result ------------------------------------------------------------------------------------------------------
def result(turns):
    """FAIL as soon as one turn was stopped, declined or missed what its moment needs; PASS when none was and every
    turn ran; otherwise a fault of the probe or the provider leaves no result."""
    faults = [t for t in turns if t['outcome'].startswith('fault')]
    stopped = [t for t in turns if t['outcome'] == 'stopped']
    declined = [t for t in turns if t['declined'] and t['outcome'] != 'stopped']
    missed = [t for t in turns if t['outcome'] == 'answered' and not t['met']]
    reasons = []
    if stopped:
        reasons.append('stopped by the provider in %d of %d turns' % (len(stopped), len(turns)))
    if declined:
        reasons.append('declined in its own words in %d of %d turns' % (len(declined), len(turns)))
    if missed:
        reasons.append('did not do what the moment needs in %d of %d turns' % (len(missed), len(turns)))
    if faults:
        reasons.append('%d turns did not run (%s)' % (len(faults), '; '.join(sorted({t['outcome'] for t in faults}))))
    if stopped or declined or missed:
        return 'FAIL', reasons
    if faults or not turns:
        return 'NO RESULT', reasons or ['no turns ran']
    return 'PASS', reasons


def report(turns, records, meta, dry_run=False):
    verdict, reasons = ('NO RESULT', ['dry run: no model was called']) if dry_run else result(turns)
    by_kind = {}
    for t in turns:
        row = by_kind.setdefault(t['kind'], {'turns': 0, 'stopped': 0, 'declined': 0, 'missed': 0})
        row['turns'] += 1
        row['stopped'] += t['outcome'] == 'stopped'
        row['declined'] += t['declined'] and t['outcome'] != 'stopped'
        row['missed'] += t['outcome'] == 'answered' and not t['met']
    stops = [r for r in records if r['stop'] == 'refusal']
    missed = ['%s step %d needs %s, used %s' % (t['sequence'], t['step'], '/'.join(t['needs']),
                                               ', '.join(t['tools']) or 'nothing')
              for t in turns if t['outcome'] == 'answered' and not t['met']]
    out = {**meta, 'result': verdict, 'reasons': reasons, 'turns': len(turns), 'by_kind': by_kind,
           'stopped_before_think': sum(not r['after_think'] for r in stops),
           'stopped_after_think': sum(r['after_think'] for r in stops),
           'categories': sorted({r['category'] for r in stops if r['category']}), 'missed': missed,
           'requests': len(records), 'input_tokens': sum(r['input_tokens'] for r in records),
           'output_tokens': sum(r['output_tokens'] for r in records), 'turns_detail': turns}
    text = ['%s  model %s%s · commit %s · %s · %d sequences × %d · %d turns'
            % (verdict, meta['model'], ' (effort %s)' % meta['effort'] if meta.get('effort') else '', meta['commit'],
               meta['at'], meta['sequences'], meta['repeat'], len(turns))]
    text += ['  - ' + reason for reason in reasons]
    text.append('by kind: ' + ' · '.join('%s %d (stopped %d, declined %d, missed %d)'
                                         % (k, v['turns'], v['stopped'], v['declined'], v['missed'])
                                         for k, v in by_kind.items()))
    if stops:
        text.append('stopped before think %d · after think %d%s' % (
            out['stopped_before_think'], out['stopped_after_think'],
            ' · categories %s' % ', '.join(out['categories']) if out['categories'] else ''))
    text += ['missed: ' + line for line in missed]
    text.append('requests %d · input tokens %d · output tokens %d' % (out['requests'], out['input_tokens'],
                                                                     out['output_tokens']))
    text.append('This holds for this model, today, with the design at this commit; a future model may differ.')
    return out, '\n'.join(text)


# ---- the run ---------------------------------------------------------------------------------------------------------
def provider_for(args):
    if args.dry_run or args.provider == 'scripted':
        return Scripted()
    key = os.environ.get(args.key_env or ('ANTHROPIC_API_KEY' if args.provider == 'anthropic' else ''), '')
    if args.provider == 'anthropic':
        if not key:
            raise SystemExit('no key in the environment variable %s' % (args.key_env or 'ANTHROPIC_API_KEY'))
        return Anthropic(args.model, key, args.max_tokens, args.effort)
    if not args.base_url:
        raise SystemExit('--base-url is needed for openai-compatible')
    return OpenAICompatible(args.model, key, args.max_tokens, args.base_url)


def probe(args, provider=None):
    seqs = sequences(args.sequences or [FIXTURES / 'sequences'])
    provider = provider or provider_for(args)
    schemas = dsh_schemas()
    name = re.search(r'^# (\S+)', (FIXTURES / 'persona.md').read_text(encoding='utf-8')).group(1)
    run = uuid.uuid4().hex[:12]
    store = open_world(probe_config(name), run)
    keep_text = None
    if args.keep_text:
        Path(args.keep_text).mkdir(parents=True, exist_ok=True)
        keep_text = str(Path(args.keep_text) / ('refusal-probe-%s.jsonl' % run))
    lane = ProbeLane(provider, schemas, keep_text)
    turns, index = [], 0
    try:
        for _ in range(args.repeat):
            for seq in seqs:
                index += 1
                turns += run_sequence(store, lane, seq, index, name)
                if args.progress:
                    print('.', end='', flush=True, file=sys.stderr)
    finally:
        dispose_test_store(store)
    commit = subprocess.run(['git', 'rev-parse', '--short=8', 'HEAD'], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    digest = hashlib.sha256(json.dumps(seqs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')
    meta = {'model': 'scripted' if isinstance(provider, Scripted) else args.model, 'provider': args.provider,
            'effort': getattr(args, 'effort', '') or None,
            'commit': commit, 'at': stamp, 'sequences': len(seqs), 'sequence_set': digest, 'repeat': args.repeat,
            'database': store.name}
    out, text = report(turns, lane.records, meta, dry_run=args.dry_run)
    if isinstance(provider, Scripted):
        first = [c['chars'] for c in provider.calls if c['first']]
        out['first_request_chars'] = int(sum(first) / max(1, len(first)))
    return out, text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--provider', choices=['anthropic', 'openai-compatible', 'scripted'], default='anthropic')
    parser.add_argument('--model', default='')
    parser.add_argument('--base-url', default='')
    parser.add_argument('--key-env', default='', help='environment variable holding the key (never printed)')
    parser.add_argument('--sequences', nargs='*', help='sequence files or folders (default: the fixture set)')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--max-tokens', type=int, default=16000)
    parser.add_argument('--effort', default='', help='anthropic: the per-turn effort her route sets (low, medium, high)')
    parser.add_argument('--out', default='', help='report JSON path (default reports/refusal-probe-<time>.json)')
    parser.add_argument('--keep-text', default='', help='folder to keep the model words in (off by default)')
    parser.add_argument('--dry-run', action='store_true', help='run offline with a scripted model: no result')
    parser.add_argument('--progress', action='store_true')
    args = parser.parse_args(argv)
    if not args.dry_run and args.provider != 'scripted' and not args.model:
        parser.error('--model is needed (the model is never inferred)')
    out, text = probe(args)
    if args.dry_run:
        text += ('\nA real run makes %d turns; a first request is about %d characters of system, tools and context.'
                 % (out['turns'], out.get('first_request_chars', 0)))
    path = Path(args.out) if args.out else ROOT / 'reports' / (
        'refusal-probe-%s.json' % datetime.now().strftime('%Y%m%d-%H%M%S'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(text)
    print('report: %s' % path)
    return {'PASS': 0, 'FAIL': 1}.get(out['result'], 2)


if __name__ == '__main__':
    sys.exit(main())
