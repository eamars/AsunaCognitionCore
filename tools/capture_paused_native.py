"""Copy only proven-owned paused native sessions, without resuming any process."""
import argparse,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze,artifact

parser=argparse.ArgumentParser();parser.add_argument('capture',type=Path);args=parser.parse_args()
capture=args.capture.resolve()
assert capture.is_relative_to((ROOT/'reports').resolve())
cfg=load();ev=Evidence(ROOT/'reports'/('paused-native-capture-'+uuid.uuid4().hex[:12]))
freeze(cfg,BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-PAUSED-NATIVE-CAPTURE')
rows=[]
for sample in json.loads(capture.read_text(encoding='utf-8'))['samples']:
    ref=sample['ownership'];ownership=(ROOT/ref['artifact_path']).resolve()
    assert ownership.is_relative_to((ROOT/'reports').resolve()) and sha(ownership.read_bytes())==ref['sha256']
    owned=json.loads(ownership.read_text(encoding='utf-8'))
    for session in owned['sessions']:
        row={'database':owned['database'],'session_id':session['_id'],'scope_key':session['scope_key'],'source_ownership':ref,'status':'INCONCLUSIVE'}
        try:
            home=Path(session['dsh_home']).resolve();allowed=(Path(cfg['dsh_home'])/owned['database']).resolve()
            assert owned['database'].startswith('asuna_v2_test_') and allowed.is_relative_to((ROOT/'.runtime').resolve())
            assert home.parent==allowed and home.name in ('character','executor')
            assert str((ROOT/sample['source_directory']).resolve()) in session['evidence_roots']
            candidates=[p for p in (home/'sessions').rglob('session.v3.jsonl') if p.parent.name==session['_id']]
            assert len(candidates)==1
            source=candidates[0].resolve();assert source.is_relative_to((home/'sessions').resolve())
            raw=source.read_bytes();events=[];invalid=[]
            for number,line in enumerate(raw.splitlines(),1):
                try:events.append(json.loads(line))
                except ValueError:invalid.append(number)
            assert events and events[0].get('type')=='session' and events[0].get('id')==session['_id']
            assert source.read_bytes()==raw
            destination=ev.root/owned['database']/home.name/session['_id']/'session.v3.jsonl'
            destination.parent.mkdir(parents=True);destination.write_bytes(raw)
            row.update(status='PASS' if not invalid else 'INCONCLUSIVE',native_session=artifact(destination),source_path=source.relative_to(ROOT).as_posix(),source_sha256=sha(raw),
                       parsed_records=len(events),invalid_lines=invalid,inflight_operation=session.get('inflight_operation'),
                       native_summary_completions=sum(e['type']=='compaction/end' and not e.get('data',{}).get('error') for e in events),
                       native_summary_errors=[e['data']['error'] for e in events if e['type']=='compaction/end' and e.get('data',{}).get('error')],
                       last_event={'type':events[-1]['type'],'seq':events[-1].get('seq')})
        except Exception as exc:row.update(status='FAIL',error_type=type(exc).__name__)
        rows.append(row)
status='FAIL' if any(r['status']=='FAIL' for r in rows) else 'INCONCLUSIVE' if any(r['status']=='INCONCLUSIVE' for r in rows) else 'PASS'
code=int(status=='FAIL')
write_json(ev.root/'result.json',{'test_id':'PROBE-PAUSED-NATIVE-CAPTURE','status':status,'mode':'read_only_exact_owned_native_session_snapshots','executed_at':datetime.now(timezone.utc).isoformat(),'source_capture':artifact(capture),'samples':rows,'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':code}],
                                'limitations':['Snapshot of persisted native events after earlier process stop, not a resumed/completed trial.','Cannot recover an unpersisted model response or infer completion from an in-flight task. Invalid partial lines, if any, are retained exactly.','No configuration, operation bearer token, environment file or unrelated session is copied.']})
print(json.dumps({'run':ev.root.name,'status':status,'sessions':len(rows),'summaries':sum(r.get('native_summary_completions',0) for r in rows)}));raise SystemExit(code)
