"""Read-only recovery of interrupted trial state, matched to persisted ownership."""
import json,sys
from pathlib import Path
from asuna.config import ROOT,load
from asuna.evidence import Evidence,write_json
from asuna.experiments import artifact
from asuna.state import Store
from asuna.live_trials import capture_trial_state

summary=Path(sys.argv[1]).resolve()
if not summary.is_relative_to((ROOT/'reports').resolve()):raise ValueError('PAUSE_SUMMARY_SCOPE')
cfg=load();home=Path(cfg['dsh_home']);records=[]
homes=[p for p in home.glob('*/*') if p.is_dir() and p.name in ('character','executor') and p.parent.name.startswith(cfg['test_database_prefix'])]
for paused in json.loads(summary.read_text(encoding='utf-8')):
    root=ROOT/'reports'/paused['experiment_id']
    directories={p.parent for p in root.rglob('*runtime.fingerprint.json') if not (p.parent/'trace.json').exists()}
    for directory in sorted(directories):
        fingerprints=[json.loads(p.read_text(encoding='utf-8')) for p in directory.glob('*runtime.fingerprint.json')]
        candidates=set()
        for event in fingerprints:
            stamp=event['time_ns']/1e9;lane=event['payload'].get('lane')
            # Timestamp only narrows a read-only query; it never proves identity.
            candidates.update(p.parent.name for p in homes if abs(p.stat().st_ctime-stamp)<10 and (lane is None or p.name==lane))
        matches=[]
        for name in candidates:
            observer=Store(cfg,name)
            try:
                owned=list(observer.db.sessions.find({'evidence_roots':str(directory.resolve())},{'_id':1,'evidence_roots':1,'inflight_operation':1,'scope_key':1,'dsh_home':1}))
                if owned:matches.append((name,owned))
            finally:observer.client.close()
        entry={'source_directory':directory.relative_to(ROOT).as_posix(),'candidates_queried':len(candidates),'matches':len(matches),'status':'INCONCLUSIVE'}
        if len(matches)==1:
            name,owned=matches[0];ev=Evidence(summary.parent/'recovered'/directory.relative_to(ROOT/'reports'))
            write_json(ev.root/'session-ownership.json',{'database':name,'sessions':owned,'matching_rule':'Exact persisted evidence_roots entry; timestamp is only candidate narrowing.'})
            captured=capture_trial_state(cfg,name,ev)
            entry.update(database=name,status='PASS' if captured else 'FAIL',ownership=artifact(ev.root/'session-ownership.json'),terminal_state=artifact(ev.root/'terminal-state.json') if captured else None)
        records.append(entry)
value={'test_id':'PROBE-PAUSED-STATE-CAPTURE','status':'PASS' if all(r['status']=='PASS' for r in records) else 'INCONCLUSIVE','samples':records,'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':0}],'limitations':['Read-only snapshot after process stop, not a resumed or completed model experiment. A killed in-flight provider may lack a terminal response record.']}
write_json(summary.parent/'state-capture-result.json',value);print(json.dumps({'status':value['status'],'samples':len(records),'recovered':sum(r['status']=='PASS' for r in records)}))
