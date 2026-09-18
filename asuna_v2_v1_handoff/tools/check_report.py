#!/usr/bin/env python3
"""Validate report integrity, not model quality. Standard library only.

Evidence paths are resolved relative to the report directory, never to arbitrary
host paths. PASS requires evidence and real execution metadata. A valid FAIL
report is a valid report; this script is not an automatic cognitive judge.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

STATUS = {'PASS', 'FAIL', 'BLOCKED', 'NOT_RUN', 'INCONCLUSIVE'}
GATES = {'ENGINEERING', 'LOCAL_DEPLOYMENT', 'COGNITION', 'PERFORMANCE'}

def validate(path: Path, allow_incomplete: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return [f'Cannot read report: {exc}']
    if not isinstance(data, dict): return ['report must be an object']
    root = Path(__file__).resolve().parents[1]
    contract = json.loads((root/'fixtures/acceptance_cases.json').read_text(encoding='utf-8'))
    expected = {r['test_id']: r for r in contract['cases']}
    for key in ('schema_version','run_id','overall_status','gates','environment','results',
                'human_review','what_works','what_fails','not_tested','design_deviations'):
        if key not in data: errors.append(f'Missing {key}')
    if errors: return errors
    if data['schema_version'] != 1: errors.append('Unsupported schema_version')
    if data['overall_status'] not in STATUS: errors.append('Invalid overall_status')
    if not isinstance(data['gates'], dict) or not GATES.issubset(data['gates']):
        return errors + ['Missing result gates']
    for gate in GATES:
        value=data['gates'][gate]
        if not isinstance(value,dict) or value.get('status') not in STATUS:
            return errors + [f'Invalid gate {gate}']
    if not isinstance(data['human_review'],dict) or not isinstance(data['environment'],dict):
        return errors + ['human_review and environment must be objects']
    if not isinstance(data['results'], list): return errors + ['results must be a list']
    seen: set[str] = set()
    report_dir = path.resolve().parent
    for r in data['results']:
        if not isinstance(r,dict):
            errors.append('result must be an object'); continue
        tid = r.get('test_id')
        if not isinstance(tid,str):
            errors.append('test_id must be a string'); continue
        if tid not in expected: errors.append(f'Unknown test_id {tid}')
        if tid in seen: errors.append(f'Duplicate test_id {tid}')
        seen.add(tid)
        state = r.get('status')
        if not isinstance(r.get('attempts'),int) or r.get('attempts',-1)<0:
            errors.append(f'{tid}: attempts must be a nonnegative integer'); continue
        if not isinstance(r.get('evidence',[]),list):
            errors.append(f'{tid}: evidence must be a list'); continue
        if state not in STATUS: errors.append(f'{tid}: invalid status')
        if not allow_incomplete and state in {'NOT_RUN','BLOCKED','INCONCLUSIVE'}:
            errors.append(f'{tid}: incomplete ({state})')
        if state == 'PASS':
            if not r.get('executed_at') or r.get('attempts',0) < 1:
                errors.append(f'{tid}: PASS without execution')
            if not r.get('commands') or not r.get('assertions'):
                errors.append(f'{tid}: PASS without commands/assertions')
            if not r.get('evidence'): errors.append(f'{tid}: PASS without evidence')
            if expected.get(tid,{}).get('suite') != 'engineering' and r.get('mode') not in {'live','live+manual'}:
                errors.append(f'{tid}: live test marked PASS without live mode')
        if state == 'FAIL' and not r.get('minimal_repro'):
            errors.append(f'{tid}: FAIL needs minimal_repro')
        for ev in r.get('evidence', []):
            if not isinstance(ev,dict):
                errors.append(f'{tid}: evidence must be an object'); continue
            rel = ev.get('path','')
            if not isinstance(rel,str):
                errors.append(f'{tid}: evidence path must be a string'); continue
            p = (report_dir/rel).resolve()
            if not rel or not p.is_relative_to(report_dir):
                errors.append(f'{tid}: unsafe evidence path'); continue
            if not p.is_file():
                errors.append(f'{tid}: missing evidence {rel}'); continue
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            if digest != ev.get('sha256'): errors.append(f'{tid}: evidence hash mismatch {rel}')
    if seen != set(expected): errors.append(f'Missing test IDs: {sorted(set(expected)-seen)}')
    if data['gates'].get('COGNITION',{}).get('status') == 'PASS':
        hr = data.get('human_review',{})
        if not hr.get('completed') or not isinstance(hr.get('reviewer_count'),int) or hr.get('reviewer_count',0) < 1:
            errors.append('COGNITION PASS needs independent human review')
    if data['overall_status'] == 'PASS':
        if any(not isinstance(r,dict) or r.get('status') != 'PASS' for r in data['results']):
            errors.append('overall PASS with non-PASS mandatory tests')
        if any(data['gates'].get(g,{}).get('status') != 'PASS' for g in GATES):
            errors.append('overall PASS with non-PASS gate')
        if not data.get('environment',{}).get('local_only_verified'):
            errors.append('overall PASS without local-only verification')
    return errors

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args()
    errs=validate(args.report,args.allow_incomplete)
    print(json.dumps({'report_format_valid':not errs,'errors':errs,
                      'scope':'report integrity only; no model/DSH/Mongo execution'},ensure_ascii=False,indent=2))
    return 1 if errs else 0
if __name__=='__main__': sys.exit(main())
