"""Exercise export I/O with real reviewed browser bytes and synthetic secrets."""
import base64,io,json,re,sys,uuid,zipfile
from datetime import datetime,timezone
from asuna.config import ROOT,BUNDLE,load
from asuna.evidence import Evidence,write_json,sha
from asuna.experiments import freeze
import asuna.reporting as reporting

ev=Evidence(ROOT/'reports'/('export-probe-'+uuid.uuid4().hex[:10]))
manifest=freeze(load(),BUNDLE/'fixtures/acceptance_cases.json',ev,'PROBE-EXPORT')
probe_root=ev.root/'isolated-files';reports=probe_root/'reports';reports.mkdir(parents=True)
image_bytes=(ROOT/'reports/ui-qa-20260920-01/review-mobile.jpg').read_bytes()
(reports/'screen.jpg').write_bytes(image_bytes)
secret='SYNTHETIC_EXPORT_SECRET_f892ed'
(reports/'text.json').write_text(json.dumps({'credential':secret}),encoding='utf-8')
(reports/'old-ui.html').write_text('<a href="data:application/json;base64,'+base64.b64encode(json.dumps({'credential':secret}).encode()).decode()+'">old download</a>',encoding='utf-8')
with zipfile.ZipFile(reports/'frozen-inputs.zip','w') as archive:
    archive.writestr('frozen.txt',secret)
reporting.ROOT=probe_root;reporting.BUNDLE=probe_root/'empty-bundle'
checks=[]
def denied(name):
    try:reporting.export({'api_key':secret},reports,probe_root/name)
    except ValueError as exc:
        assert str(exc)=='NON_TEXT_EXPORT_REQUIRES_EXPLICIT_REVIEW'
        checks.append({'case':name,'expected':'reject unreviewed binary','observed':str(exc),'status':'PASS'})
    else:raise AssertionError('UNREVIEWED_BINARY_ACCEPTED')
denied('unreviewed.zip')
review={'schema':'asuna-binary-review-v1','reviewer':'probe reuses visually reviewed Browser bytes',
        'files':[{'artifact_path':'reports/screen.jpg','sha256':sha(image_bytes),'mime_type':'image/jpeg'}]}
write_json(reports/'binary-review.json',review)
result=reporting.export({'api_key':secret},reports,probe_root/'reviewed.zip')
assert result['status']=='PASS'
with zipfile.ZipFile(probe_root/'reviewed.zip') as archive:
    assert archive.read('reports/screen.jpg')==image_bytes
    assert secret.encode() not in archive.read('reports/text.json')
    embedded=re.search(rb'data:application/json;base64,([A-Za-z0-9+/=]+)',archive.read('reports/old-ui.html'))[1]
    assert secret.encode() not in base64.b64decode(embedded) and b'[REDACTED]' in base64.b64decode(embedded)
    with zipfile.ZipFile(io.BytesIO(archive.read('reports/frozen-inputs.zip'))) as nested:
        assert nested.read('frozen.txt')==b'[REDACTED]'
    exported_manifest=json.loads(archive.read('evidence-manifest.json'))
    assert all(sha(archive.read(row['artifact_path']))==row['export_sha256'] for row in exported_manifest['files'])
checks.append({'case':'reviewed.zip','status':'PASS','observed':'Browser image bytes unchanged; ordinary and nested frozen text redacted; archive hashes verified.'})
(reports/'screen.jpg').write_bytes(image_bytes+b'changed-after-review')
denied('stale-review.zip')
write_json(ev.root/'binary-review.json',{
    'schema':'asuna-binary-review-v1',
    'reviewer':'implementation-agent: preserved previously reviewed Browser bytes plus exact synthetic trailing marker',
    'independent_cognition_review':False,
    'files':[{'artifact_path':(reports/'screen.jpg').relative_to(ROOT).as_posix(),
              'sha256':sha((reports/'screen.jpg').read_bytes()),'mime_type':'image/jpeg'}]})
write_json(ev.root/'result.json',{'test_id':'PROBE-EXPORT','status':'PASS',
    'experiment_id':manifest['experiment_id'],'executed_at':datetime.now(timezone.utc).isoformat(),
    'manifest_sha256':sha((ev.root/'manifest.json').read_bytes()),'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':0}],
    'assertions':checks,'limitations':['Isolated export candidate tree with actual Browser screenshot; not yet a complete repository export.']})
print(json.dumps({'run':ev.root.name,'status':'PASS','cases':len(checks)}))
