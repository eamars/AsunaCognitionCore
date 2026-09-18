#!/usr/bin/env python3
"""Validate the handoff assets only. Does not contact DSH, MongoDB or models."""
from __future__ import annotations
import ast
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def j(path: str):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))

def jl(path: str):
    return [json.loads(line) for line in (ROOT/path).read_text(encoding='utf-8').splitlines() if line.strip()]

def main() -> int:
    errors=[]
    try:
        # Parse every JSON/JSONL and every Python source without executing fixtures.
        for p in ROOT.rglob('*.json'):
            json.loads(p.read_text(encoding='utf-8'))
        for p in ROOT.rglob('*.jsonl'):
            for line in p.read_text(encoding='utf-8').splitlines():
                if line.strip(): json.loads(line)
        for p in ROOT.rglob('*.py'):
            ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
        world=j('fixtures/world.json'); ids={m['id'] for m in world['memories']}
        scenes={s['scene_id']:s for s in world['scenes']}
        people={p['person_id'] for p in world['identities']}
        assert len(ids)==len(world['memories'])==12
        assert len(scenes)==4
        for name in world['personas'].values(): assert (ROOT/name).is_file(), name
        qs=jl('fixtures/retrieval_queries.jsonl'); ss=jl('fixtures/scenarios.jsonl')
        assert len(qs)==len(ss)==12
        assert len({q['id'] for q in qs})==12
        assert len({s['case_id'] for s in ss})==12
        for q in qs:
            assert set(q['gold']).issubset(ids),q
            scope=scenes[q['scene_id']]['scope_key']
            for mid in q['gold']:
                m=next(m for m in world['memories'] if m['id']==mid)
                assert m['scope_key'] in {scope,'global-safe'},(q,mid)
        for s in ss:
            assert s['scene_id'] in scenes and s['person_id'] in people
            assert set(s['memory_ids']).issubset(ids)
            scope=scenes[s['scene_id']]['scope_key']
            for mid in s['memory_ids']:
                m=next(m for m in world['memories'] if m['id']==mid)
                assert m['scope_key'] in {scope,'global-safe'}, (s['case_id'],mid)
        assert len(jl('fixtures/relationship_cases.jsonl'))==12
        assert len(jl('fixtures/continuity_cases.jsonl'))==10
        assert len(jl('fixtures/contrast_cases.jsonl'))==4
        assert len(jl('fixtures/evolution_cases.jsonl'))==3
        contract=j('fixtures/acceptance_cases.json'); cases=contract['cases']; tids={c['test_id'] for c in cases}
        assert len(tids)==len(cases)==contract['total_cases']==41
        for refs in j('fixtures/requirements_map.json').values(): assert set(refs).issubset(tids)
        report=j('reports/report.template.json')
        assert {r['test_id'] for r in report['results']}==tids
        assert all(r['status']=='NOT_RUN' for r in report['results'])
        exp=j('config/experiments.json')
        assert exp==j('config/experiments.yaml')
        matrix=exp['attribution']
        n=len(matrix['models'])*len(matrix['personas'])*len(matrix['cases'])*matrix['repetitions']
        assert n==matrix['expected_scenario_runs']==216
        assert n+matrix['contrast_scenario_runs']==matrix['total_scenario_runs_with_contrasts']==264
        # Recompute multi-file truth independently from the generated oracle.
        found={}
        for p in sorted((ROOT/'fixtures/reconcile_task').glob('shard_*.csv')):
            with p.open(encoding='utf-8',newline='') as f:
                for row in csv.DictReader(f):
                    if row['status']=='posted': found[row['record_id']]=int(row['amount_cents'])
        oracle=j('fixtures/oracles/reconcile_expected.json')
        assert len(found)==oracle['unique_posted_count']
        assert sum(found.values())==oracle['total_amount_cents']
        # Verify frozen package hashes when present.
        manifest=ROOT/'MANIFEST.sha256.json'
        if manifest.is_file():
            for rel,digest in json.loads(manifest.read_text(encoding='utf-8')).items():
                p=(ROOT/rel).resolve()
                assert p.is_relative_to(ROOT) and p.is_file(),rel
                assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,rel
    except (AssertionError,ValueError,KeyError,OSError,SyntaxError) as exc:
        errors.append(f'{type(exc).__name__}: {exc}')
    result={'bundle_integrity_pass':not errors,'acceptance_contracts':41,'behavior_scenarios':12,
            'retrieval_queries':12,'errors':errors,
            'NOT_TESTED':['local DSH','local MongoDB','local vector index','Gemma4','Qwen3.8','behavior quality','actual performance']}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if errors else 0
if __name__=='__main__': sys.exit(main())
