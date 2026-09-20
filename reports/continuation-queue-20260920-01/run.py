"""Dispatch only existing dedicated V1 drivers; no scoring or automatic retries."""
import json,os,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from asuna.evidence import write_json,sha

root=Path(__file__).resolve().parents[2];directory=Path(__file__).resolve().parent
plans=[('tasks','formal-L02-20260920-resume-01',['L03','L12','L11','L09']),('cognition','formal-A01-20260920-resume-01',['A02'])]
write_json(directory/'start.json',{'pid':os.getpid(),'parent_pid':os.getppid(),'started_at':datetime.now(timezone.utc).isoformat(),'argv':sys.orig_argv,'dispatcher_sha256':sha(Path(__file__).read_bytes()),'plans':plans,'rules':['At most two own model workflows including the already-running prerequisites.','Wait for each prior result and use new experiment directories.','No automatic retry, threshold edit or model launch change.','If a driver exits without result.json, stop that queue.']})
def lane(label,prerequisite,tests):
    deadline=time.monotonic()+21600
    prior=root/'reports'/prerequisite/'result.json'
    while not prior.exists():
        if time.monotonic()>deadline:raise TimeoutError('PREREQUISITE_NOT_COMPLETED_'+label)
        time.sleep(5)
    for test in tests:
        output=root/'reports'/('formal-'+test+'-20260920-resume-01')
        if output.exists():raise FileExistsError(str(output))
        command=[str(root/'.venv/Scripts/python.exe'),'-X','utf8',str(root/'tools/run_acceptance.py'),test,'--out',str(output)] if test in ('L03','L12') else [str(root/'.venv/Scripts/asuna.exe'),'evaluate','--test',test,'--out',str(output)]
        log=directory/test;log.mkdir()
        write_json(log/'start.json',{'argv':command,'started_at':datetime.now(timezone.utc).isoformat(),'prerequisite_result':str(prior.relative_to(root)),'prerequisite_sha256':sha(prior.read_bytes())})
        with (log/'stdout.txt').open('xb') as out,(log/'stderr.txt').open('xb') as err:
            process=subprocess.Popen(command,cwd=root,stdout=out,stderr=err)
            write_json(log/'process.json',{'pid':process.pid,'parent_pid':os.getpid(),'argv':command})
            print(json.dumps({'started':test,'pid':process.pid}),flush=True)
            code=process.wait()
        record={'argv':command,'exit_code':code,'ended_at':datetime.now(timezone.utc).isoformat()}
        write_json(log/'completion.json',record)
        if output.exists():write_json(output/'invocation.json',record)
        print(json.dumps({'finished':test,'exit_code':code}),flush=True)
        prior=output/'result.json'
        if not prior.exists():raise RuntimeError('DRIVER_HAS_NO_FINAL_RESULT_'+test)
    return {'lane':label,'completed':tests}
results=[]
with ThreadPoolExecutor(max_workers=2) as pool:
    futures=[pool.submit(lane,*plan) for plan in plans]
    for future in futures:
        try:results.append(future.result())
        except Exception as exc:results.append({'status':'FAIL','type':type(exc).__name__,'message':str(exc)})
code=int(any(r.get('status')=='FAIL' for r in results))
write_json(directory/'completion.json',{'status':'FAIL' if code else 'PASS','results':results,'exit_code':code,'meaning':'Dispatch completion only, not acceptance success. All driver results retain their own status.'})
raise SystemExit(code)
