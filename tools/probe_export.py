"""Exercise actual archive generation, nested redaction and manifest verification."""
import io,json,uuid,zipfile
from pathlib import Path
from unittest.mock import patch
from asuna.config import ROOT
from asuna.evidence import write_json,sha
from asuna.reporting import export

name='export-probe-'+uuid.uuid4().hex[:12];root=ROOT/'.runtime'/name
(root/'reports').mkdir(parents=True);(root/'docs').mkdir();(root/'bundle').mkdir()
secret='synthetic-export-credential-'+uuid.uuid4().hex
raw=json.dumps({'api_key':secret,'float':0.931105987,'hash':'ab931105cd'}).encode()
(root/'reports/response.json').write_bytes(raw)
(root/'reports/private').mkdir();(root/'reports/private/hidden.txt').write_text('MUST_NOT_EXPORT')
with zipfile.ZipFile(root/'reports/frozen-inputs.zip','x') as z:z.writestr('config.txt',secret)
output=root/'evidence.zip';result_dir=ROOT/'reports'/name;result_dir.mkdir()
try:
    with patch('asuna.reporting.ROOT',root),patch('asuna.reporting.BUNDLE',root/'bundle'):
        result=export({'api_key':secret},root/'reports',output)
    with zipfile.ZipFile(output) as z:
        assert 'reports/private/hidden.txt' not in z.namelist()
        safe=json.loads(z.read('reports/response.json'))
        assert safe['api_key']=='[REDACTED]' and safe['float']==0.931105987 and safe['hash']=='ab931105cd'
        with zipfile.ZipFile(io.BytesIO(z.read('reports/frozen-inputs.zip'))) as nested:assert nested.read('config.txt')==b'[REDACTED]'
        manifest=json.loads(z.read('evidence-manifest.json'))
        assert all(sha(z.read(row['artifact_path']))==row['export_sha256'] for row in manifest['files'])
    assert (root/'reports/response.json').read_bytes()==raw
    write_json(result_dir/'result.json',{'test_id':'PROBE-export','status':'PASS','commands':[{'argv':['.venv/Scripts/python.exe','tools/probe_export.py'],'exit_code':0}],'assertions':['actual zip verified','source bytes unchanged','private excluded','nested secrets removed','unrelated float and hash retained'],'files':result['files']})
except Exception as exc:
    write_json(result_dir/'result.json',{'test_id':'PROBE-export','status':'FAIL','error_type':type(exc).__name__,'commands':[{'argv':['.venv/Scripts/python.exe','tools/probe_export.py'],'exit_code':1}]});raise
print(json.dumps({'run':name,'status':'PASS'}))
