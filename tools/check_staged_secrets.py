"""Report paths only; never print configured secret values or matching bytes."""
import json,re,subprocess
from asuna.config import ROOT,load
from asuna.evidence import write_json

secrets=set()
def collect(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if re.search(r'password|token|api.?key|secret',key,re.I) and isinstance(item,str) and len(item)>=6:secrets.add(item)
            else:collect(item)
    elif isinstance(value,list):
        for item in value:collect(item)
collect(load())
for name in ('operator-ssh.json','embedding-ssh.json'):
    path=ROOT/'.runtime'/name
    if path.exists():collect(json.loads(path.read_text(encoding='utf-8')))
patterns=[re.compile(r'(?<![A-Za-z0-9_.:/\\-])'+re.escape(s)+r'(?![A-Za-z0-9_.:/\\-])') for s in secrets]
paths=subprocess.check_output(['git','diff','--cached','--name-only','--diff-filter=ACM','-z'],cwd=ROOT).decode().split('\0')
matches=[];checked=0
for name in filter(None,paths):
    raw=subprocess.check_output(['git','show',':'+name],cwd=ROOT)
    values=[]
    if name.endswith('.zip'):
        import io,zipfile
        with zipfile.ZipFile(io.BytesIO(raw)) as z:values=[z.read(n).decode('utf-8',errors='ignore') for n in z.namelist()]
    else:values=[raw.decode('utf-8',errors='ignore')]
    if any(p.search(value) for value in values for p in patterns):matches.append(name)
    checked+=1
print(json.dumps({'checked':checked,'matching_paths':matches,'status':'FAIL' if matches else 'PASS'}))
raise SystemExit(bool(matches))
