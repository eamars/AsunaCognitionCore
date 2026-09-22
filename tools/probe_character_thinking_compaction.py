"""Isolated Gemma native-thinking and near-capacity compaction probe.

This intentionally starts a fresh pinned DSH lane per reasoning level.  It does
not touch the live Asuna host, Mongo state, QQ adapter, or checked-in model
configuration.  The upstream model is still the configured local character
endpoint; only the temporary provider compat flag is changed to enable native
thinking.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

import httpx
import yaml
from deepseek_harness import DeepSeekHarness

from asuna.config import BUNDLE, ROOT, load
from asuna.evidence import Evidence, sha, write_json
from asuna.provider_proxy import ProviderProxy


def parse_sse(raw: str) -> dict:
    finish = None
    usage = None
    content_parts = []
    reasoning_parts = []
    for line in raw.splitlines():
        if not line.startswith('data: ') or line[6:].strip() == '[DONE]':
            continue
        try:
            item = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if item.get('usage') is not None:
            usage = item['usage']
        for choice in item.get('choices', []):
            if choice.get('finish_reason') is not None:
                finish = choice['finish_reason']
            delta = choice.get('delta', {}) or {}
            if isinstance(delta.get('content'), str):
                content_parts.append(delta['content'])
            if isinstance(delta.get('reasoning_content'), str):
                reasoning_parts.append(delta['reasoning_content'])
    return {
        'finish_reason': finish,
        'usage': usage,
        'content_chars': len(''.join(content_parts)),
        'reasoning_chars': len(''.join(reasoning_parts)),
    }


def summarize_call(call: dict) -> dict:
    parsed = parse_sse(call['raw'])
    usage = parsed['usage'] or {}
    last_content = call['body'].get('messages', [{}])[-1].get('content', '')
    if not isinstance(last_content, str):
        last_content = json.dumps(last_content, ensure_ascii=False)
    return {
        'purpose': 'compaction' if 'ASUNA_COMPACTION_V1' in last_content else 'generation',
        'finish_reason': parsed['finish_reason'],
        'prompt_tokens': usage.get('prompt_tokens', usage.get('input_tokens')),
        'completion_tokens': usage.get('completion_tokens', usage.get('output_tokens')),
        'reasoning_tokens': usage.get('reasoning_tokens'),
        'content_chars': parsed['content_chars'],
        'reasoning_chars': parsed['reasoning_chars'],
        'request_ref': call.get('request_ref'),
        'response_ref': call.get('response_ref'),
    }


def build_patch(work: Path, home: Path, receipts: Path, proxy: ProviderProxy, model: dict, level: str, endpoint_file: Path) -> Path:
    disabled = [
        'llm-deepseek', 'deepseek-llm-api-extensions', 'session-log-deepseek',
        'plugin-package-inventory-deepseek', 'persistent-bash', 'persistent-pwsh',
        'terminal-bash', 'terminal-pwsh', 'pty', 'subprocess', 'session-title-llm',
        'compaction-basic',
    ]
    compat = {
        'supportsDeveloperRole': False,
        'supportsReasoningEffort': False,
        'thinkingFormat': 'chat-template',
        'chatTemplateKwargs': {'enable_thinking': True},
        'maxTokensField': 'max_tokens',
    }
    provider = {
        'api': 'openai-completions',
        'baseURL': proxy.url,
        'apiKeyEnv': 'ASUNA_LOCAL_DUMMY_KEY',
        'compat': compat,
        'models': [{
            'id': model['model'],
            'contextWindow': model['context_window'],
            'maxTokens': model['max_tokens'],
            'reasoningEfforts': {'low': 'low', 'medium': 'medium', 'high': 'high', 'off': None},
        }],
        'streamIdleTimeoutMs': 1800 * 1000,
        'timeoutMs': 1800 * 1000,
    }
    rows = [{'id': name, 'disabled': True} for name in disabled]
    rows += [{
        'id': 'system-prompt',
        'config': {'includeHarnessIdentity': False, 'includeRuntimeContext': False, 'personaPrefix': ''},
    }, {
        'insert': [
            {'id': 'asuna-token-meter', 'name': '@deepseek-ai/dsh-token-meter'},
            {'id': 'asuna-skills', 'name': '@deepseek-ai/dsh-skill'},
            {'id': 'asuna-compaction', 'name': (ROOT / 'dsh-plugin/compaction.ts').as_posix(), 'config': {'maxTokens': model['max_tokens']}},
            {'id': 'asuna-runtime', 'name': (ROOT / 'dsh-plugin/runtime-v2.ts').as_posix(), 'config': {
                'model': model['model'], 'reasoningEffort': level, 'maxTokens': model['max_tokens'],
                'workdir': work.as_posix(), 'skillsEnabled': False,
                'receipts': receipts.as_posix(), 'endpointFile': endpoint_file.as_posix(),
            }},
            {'id': 'asuna-local-provider', 'name': '@deepseek-ai/dsh-llm-pi-ai', 'config': {'providers': {'asuna-local': provider}}},
        ],
    }]
    path = work / 'lane.patch.yml'
    path.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return path


def run_level(model: dict, level: str, target_ratio: float, max_turns: int, filler_chars: int) -> dict:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_id = f'THINK-COMPACT-{stamp}-{level}-{uuid.uuid4().hex[:6]}'
    evidence = Evidence(ROOT / 'reports' / run_id)
    home = Path(model['_dsh_home']) / run_id
    work = Path(model['_workdir']) / run_id
    receipts = home / 'operations'
    endpoint_file = home / 'bridge-endpoint.json'
    home.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    receipts.mkdir(parents=True, exist_ok=True)

    cfg = dict(model)
    cfg['reasoning_effort'] = level
    cfg['compat'] = {
        'supportsDeveloperRole': False,
        'supportsReasoningEffort': False,
        'thinkingFormat': 'chat-template',
        'chatTemplateKwargs': {'enable_thinking': True},
        'maxTokensField': 'max_tokens',
    }
    proxy = ProviderProxy(cfg, evidence, 'character')
    system = (
        (BUNDLE / 'prompts/common.md').read_text(encoding='utf-8') + '\n' +
        (ROOT / 'config/prompts/persona_local.md').read_text(encoding='utf-8') +
        '\n这是一个隔离的原生 thinking 与 compaction 压力探针。保持回答简短，不编造现实执行。'
    )
    child_env = {key: '' for key in os.environ}
    for key in ('SystemRoot', 'SYSTEMROOT', 'WINDIR', 'PATH', 'PATHEXT', 'TEMP', 'TMP', 'COMSPEC'):
        if key in os.environ:
            child_env[key] = os.environ[key]
    token = uuid.uuid4().hex
    child_env.update({
        'DSH_HOME': str(home),
        'DSH_TELEMETRY_DISABLED': '1',
        'ASUNA_LOCAL_DUMMY_KEY': 'local-only-not-a-secret',
        'ASUNA_BRIDGE_TOKEN': token,
        'PYTHONIOENCODING': 'utf-8',
    })
    patch = build_patch(work, home, receipts, proxy, model, level, endpoint_file)
    manifest = {
        'experiment_id': run_id, 'level': level, 'native_thinking': True,
        'model': model['model'], 'context_window': model['context_window'],
        'max_tokens': model['max_tokens'], 'target_ratio': target_ratio,
        'filler_chars': filler_chars, 'patch': str(patch),
        'dsh_version': '0.1.5-rc.2',
    }
    write_json(evidence.root / 'manifest.json', manifest)
    http = None
    rows = []
    try:
        with DeepSeekHarness(
            dsh_bin=str(ROOT / 'node_modules/.bin/dsh.cmd'), dsh_home=str(home),
            profile='sdk-minimal', patches=(str(patch),), cwd=str(work), env=child_env,
            provider='asuna-local', model=model['model'], reasoning_effort=level,
            max_tokens=model['max_tokens'], request_timeout_seconds=1800, initialize_timeout_seconds=45,
        ):
            deadline = time.monotonic() + 30
            while not endpoint_file.exists():
                if time.monotonic() > deadline:
                    raise TimeoutError('BRIDGE_ENDPOINT_NOT_READY')
                time.sleep(0.1)
            port = json.loads(endpoint_file.read_text(encoding='utf-8'))['port']
            http = httpx.Client(timeout=httpx.Timeout(1800, connect=10), trust_env=False)

            def run(operation: str, text: str, compact_before: bool = False) -> dict:
                payload = {
                    'session': f'probe-{level}', 'operation': operation, 'phase': 'SPEAK',
                    'text': text, 'system': system,
                }
                if compact_before:
                    payload['compact_before'] = True
                before = len(proxy.calls)
                response = http.post(
                    f'http://127.0.0.1:{port}/run',
                    headers={'Authorization': 'Bearer ' + token}, json=payload,
                )
                result = {'status_code': response.status_code, 'operation': operation}
                try:
                    result['body'] = response.json()
                except ValueError:
                    result['body'] = {'raw': response.text[:1000]}
                if response.is_error:
                    return result
                result['provider_calls'] = [summarize_call(call) for call in proxy.calls[before:]]
                return result

            first = run('probe-first', '请只回复“收到”，不要解释。')
            first_calls = first.get('provider_calls') or []
            rows.append({'kind': 'short', 'status_code': first.get('status_code'), 'provider_call': first_calls[-1] if first_calls else None, 'native_finish': first.get('body', {}).get('finish_reason')})
            if first.get('status_code') != 200:
                raise RuntimeError('SHORT_PROBE_FAILED:' + json.dumps(first, ensure_ascii=False)[:1000])

            target_tokens = int(model['context_window'] * target_ratio)
            reached = None
            for index in range(1, max_turns + 1):
                marker = f'FILLER_{level}_{index:02d}_'
                repeated = (marker + ' 保留这条测试记录但不要复述。')
                filler = (repeated * max(1, filler_chars // len(repeated) + 1))[:filler_chars]
                text = filler + f'\n\n记录结束。只回复“收到{index}”，不要解释，也不要重复记录。'
                item = run(f'probe-fill-{index:02d}', text)
                calls = item.get('provider_calls') or []
                call = calls[-1] if calls else {}
                rows.append({'kind': 'fill', 'index': index, 'status_code': item.get('status_code'), 'provider_call': call, 'native_finish': item.get('body', {}).get('finish_reason')})
                prompt_tokens = call.get('prompt_tokens')
                if item.get('status_code') != 200:
                    raise RuntimeError('FILL_PROBE_FAILED:' + json.dumps(item, ensure_ascii=False)[:1200])
                if isinstance(prompt_tokens, int) and prompt_tokens >= target_tokens:
                    reached = {'index': index, 'prompt_tokens': prompt_tokens, 'ratio': prompt_tokens / model['context_window']}
                    break
            if reached is None:
                last = rows[-1].get('provider_call') or {}
                reached = {'index': max_turns, 'prompt_tokens': last.get('prompt_tokens'), 'ratio': ((last.get('prompt_tokens') or 0) / model['context_window'])}

            compact = run('probe-compaction', '压缩完成后只回复“压缩后收到”。', compact_before=True)
            compact_body = compact.get('body') or {}
            compactions = compact_body.get('compactions') or ([] if not compact_body.get('compaction') else [compact_body['compaction']])
            compact_calls = compact.get('provider_calls') or []
            compact_call = next((call for call in compact_calls if call.get('purpose') == 'compaction'), None)
            after_compact_generation = next((call for call in reversed(compact_calls) if call.get('purpose') != 'compaction'), None)
            compact_ok = (
                compact.get('status_code') == 200 and bool(compactions) and
                compact_call is not None and compact_call.get('finish_reason') in (None, 'stop')
            )
            rows.append({
                'kind': 'compaction', 'status_code': compact.get('status_code'),
                'provider_call': compact_call, 'post_compaction_generation': after_compact_generation,
                'native_finish': compact_body.get('finish_reason'),
                'compactions': len(compactions), 'compaction_events': len(compact_body.get('compaction_events') or []),
                'ok': compact_ok,
            })
            after = run('probe-after-compaction', '压缩后继续。只回复“继续正常”。')
            after_calls = after.get('provider_calls') or []
            rows.append({'kind': 'after_compaction', 'status_code': after.get('status_code'), 'provider_call': after_calls[-1] if after_calls else None, 'native_finish': after.get('body', {}).get('finish_reason')})
            summary = {
                'run_id': run_id, 'level': level, 'native_thinking': True,
                'status': 'PASS' if compact_ok and after.get('status_code') == 200 else 'FAIL',
                'near_compaction': reached, 'rows': rows,
                'provider_calls': len(proxy.calls), 'evidence_dir': str(evidence.root.relative_to(ROOT)),
            }
            write_json(evidence.root / 'result.json', summary)
            return summary
    except Exception as exc:
        summary = {
            'run_id': run_id, 'level': level, 'native_thinking': True, 'status': 'FAIL',
            'error': {'type': type(exc).__name__, 'message': str(exc)},
            'near_compaction': locals().get('reached'), 'rows': rows,
            'provider_calls': len(proxy.calls), 'evidence_dir': str(evidence.root.relative_to(ROOT)),
        }
        write_json(evidence.root / 'result.json', summary)
        return summary
    finally:
        if http is not None:
            http.close()
        proxy.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--levels', default='low,medium,high')
    parser.add_argument('--target-ratio', type=float, default=0.68)
    parser.add_argument('--max-turns', type=int, default=18)
    parser.add_argument('--filler-chars', type=int, default=12000)
    args = parser.parse_args()
    config = load()
    model = dict(config['character'])
    model['_dsh_home'] = config['dsh_home']
    model['_workdir'] = config['workdir']
    results = []
    for level in [x.strip() for x in args.levels.split(',') if x.strip()]:
        if level not in ('low', 'medium', 'high'):
            raise SystemExit('unsupported level: ' + level)
        print(json.dumps({'event': 'start', 'level': level}, ensure_ascii=False), flush=True)
        result = run_level(model, level, args.target_ratio, args.max_turns, args.filler_chars)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    out = ROOT / 'reports' / ('THINK-COMPACT-SUMMARY-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.json')
    write_json(out, {'levels': results, 'config': {'native_thinking': True, 'target_ratio': args.target_ratio, 'max_turns': args.max_turns, 'filler_chars': args.filler_chars}})
    print(json.dumps({'summary': str(out.relative_to(ROOT)), 'statuses': [r['status'] for r in results]}, ensure_ascii=False))
    return 0 if all(r['status'] == 'PASS' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
