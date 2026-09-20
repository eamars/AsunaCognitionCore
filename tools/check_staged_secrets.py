"""Report paths only; never print configured secret values or matching bytes."""
import base64,json,re,subprocess
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
# Read exactly the staged blobs through one Git process. Thousands of preserved
# provider artifacts should not require thousands of Windows process launches.
with subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) as batch:
    for name in filter(None,paths):
        if '\n' in name or '\r' in name:raise ValueError('UNSUPPORTED_STAGED_PATH')
        batch.stdin.write((':'+name+'\n').encode());batch.stdin.flush()
        header=batch.stdout.readline().split()
        if len(header)!=3 or header[1]!=b'blob':raise ValueError('STAGED_BLOB_READ_FAILED')
        size=int(header[2]);raw=batch.stdout.read(size)
        if len(raw)!=size or batch.stdout.read(1)!=b'\n':raise ValueError('STAGED_BLOB_TRUNCATED')
        values=[]
        if name.endswith('.zip'):
            import io,zipfile
            with zipfile.ZipFile(io.BytesIO(raw)) as z:values=[z.read(n).decode('utf-8',errors='ignore') for n in z.namelist()]
        else:values=[raw.decode('utf-8',errors='ignore')]
        values += [base64.b64decode(m,validate=True).decode('utf-8') for value in list(values) for m in re.findall(r'data:application/json;base64,([A-Za-z0-9+/=]+)',value)]
        if any(p.search(value) for value in values for p in patterns):matches.append(name)
        checked+=1
    batch.stdin.close()
    if batch.wait()!=0:raise ValueError('STAGED_BLOB_PROCESS_FAILED')
print(json.dumps({'checked':checked,'matching_paths':matches,'status':'FAIL' if matches else 'PASS'}))
raise SystemExit(bool(matches))
