"""Record observed in-app Browser actions; validate its exported DOM value."""
import json, sys
from datetime import datetime, timezone
from asuna.config import ROOT
from asuna.evidence import sha, write_json
from asuna.review import ingest

qa=ROOT/'reports/ui-qa-20260920-01'
def ref(path):
    return {'artifact_path':path.relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes())}

def jpeg_size(raw):
    assert raw[:2]==b'\xff\xd8'
    pos=2
    while pos<len(raw):
        assert raw[pos]==255
        while raw[pos]==255:pos+=1
        marker=raw[pos];pos+=1
        length=int.from_bytes(raw[pos:pos+2],'big')
        if marker in (0xc0,0xc1,0xc2):
            return {'height':int.from_bytes(raw[pos+3:pos+5],'big'),
                    'width':int.from_bytes(raw[pos+5:pos+7],'big')}
        if marker==0xda:break
        pos+=length
    raise ValueError('JPEG_DIMENSIONS_UNAVAILABLE')

base=json.loads((qa/'blind.json').read_text(encoding='utf-8'))
submitted=json.loads((qa/'synthetic-ui-export.json').read_text(encoding='utf-8'))
assert base['pack_id']==submitted['pack_id'] and len(base['items'])==len(submitted['items'])==206
mutable={'ratings','behavior_correct','critical_flags','review_note','target_xiaoman_consistency'}
for before,after in zip(base['items'],submitted['items']):
    assert {k:v for k,v in before.items() if k not in mutable}=={k:v for k,v in after.items() if k not in mutable}
assert submitted['items'][0]['ratings']['natural_expression']==2
assert all(v is None for v in submitted['items'][1]['ratings'].values())
assert submitted['reviewer']['independent_human'] is False
try:ingest(qa/'blind.json',qa/'synthetic-ui-export.json',qa/'must-not-be-accepted')
except ValueError as exc:assert str(exc)=='INDEPENDENT_HUMAN_ATTESTATION_REQUIRED'
else:raise AssertionError('SYNTHETIC_REVIEW_ACCEPTED')
images=[]
for path in sorted(qa.glob('*.jpg')):
    images.append({**ref(path),'mime_type':'image/jpeg',**jpeg_size(path.read_bytes())})
write_json(qa/'binary-review.json',{
    'schema':'asuna-binary-review-v1','reviewer':'implementation-agent visual inspection',
    'independent_cognition_review':False,
    'scope':'Browser screenshots of synthetic acceptance materials and the operator audit UI; inspected for visible credentials.',
    'limitation':'Visual inspection is not an automated or exhaustive credential detector.',
    'files':images})
attempts=[
    {'id':'UI01','status':'FAIL','action':'Copy existing trace.html','observed':'File absent. Regenerated from preserved trace.json through production audit renderer.'},
    {'id':'UI02','status':'INCONCLUSIVE','action':'Original download button; waitForEvent(download), 10 seconds','observed':'No download event. No console error.'},
    {'id':'UI03','status':'INCONCLUSIVE','action':'Persistent save link; waitForEvent(download), 5 seconds','observed':'No download event. Readonly full JSON text fallback available.'},
    {'id':'UI04','status':'FAIL','action':'Locator evaluate for form field reads','observed':'Repeated 3000 ms timeouts; DOM-backed page evaluate read the same visible controls successfully.'},
    {'id':'UI05','status':'FAIL','action':'Read full 415159-character export textarea in one tool response','observed':'Tool text was truncated; JSON parsing failed. Retried in 60000-character DOM reads.'},
    {'id':'UI06','status':'PASS','action':'Join complete DOM reads and validate transport via production ingest','observed':'206 immutable items unchanged, first synthetic score retained, next row blank, independent_human=false rejected.'},
    {'id':'UI07','status':'FAIL','action':'Screenshot metadata PNG assertion, then optional PIL import','observed':'Screenshot API returned JPEG, not PNG; Pillow unavailable. Bytes unchanged, renamed .jpg and parsed JPEG SOF with stdlib.'}]
write_json(qa/'attempts.json',attempts)
result={
    'test_id':'PROBE-UI','status':'INCONCLUSIVE','executed_at':datetime.now(timezone.utc).isoformat(),
    'mode':'actual_in_app_browser_plus_production_importer','attempts':len(attempts),
    'commands':[{'argv':[sys.executable,*sys.argv],'exit_code':0}],
    'browser_actions':['reviewTab.goto / reload; domSnapshot; DOM-backed evaluate',
                       'locator fill/selectOption/click; next/previous; save link',
                       'waitForEvent(download); full readonly textarea exported in chunks',
                       'auditTab details opened for episode, phase, hash-verified actual provider request, native compaction range and summary',
                       'viewport set/reset; screenshot; dev.logs(error,warn)'],
    'checks':{'identity':'PASS','nonblank':'PASS','no_error_overlay':'PASS',
              'console_warnings_errors':0,'paging_and_score_retention':'PASS',
              'missing_reply_label':'PASS','complete_json_copy_export':'PASS',
              'synthetic_human_vote_rejected':'PASS','download_file_receipt':'INCONCLUSIVE',
              'actual_provider_request_visible':'PASS','compaction_range_and_summary_visible':'PASS',
              'desktop_and_narrow_no_horizontal_overflow':'PASS','review_reset_to_blank':'PASS'},
    'evidence':images+[ref(qa/'synthetic-ui-export.json'),ref(qa/'attempts.json'),ref(qa/'binary-review.json')],
    'sources':[ref(ROOT/'src/asuna/review.py'),ref(ROOT/'src/asuna/audit.py'),ref(qa/'blind.json'),
               ref(ROOT/'reports/formal-L08-20260919-02/1-dm-a/trace.json')],
    'limitations':['No browser download event/file receipt observed; full JSON copy path verified.',
                   'Narrow viewport actually measured 486 CSS pixels, not requested 390; desktop measured 1265.',
                   'Synthetic UI transport actions are not independent human cognition ratings.',
                   'Audit displays actual request, replacement range and summary; personality revision diff and interactive filtering remain incomplete.']}
write_json(qa/'result.json',result)
(qa/'report.md').write_text('''# In-app Browser verification

The review and audit pages rendered and responded through the in-app Browser at
http://127.0.0.1:8767/review.html and /trace.html. Browser download completion
remains INCONCLUSIVE; the full JSON copy path was verified and the production
importer rejected the synthetic, non-human submission.

The review keeps blank ratings, labels missing delivered replies, retains edits
across next/previous navigation, and exposes the entire export for copying. The
audit groups episodes/tasks and opens hash-verified actual provider requests,
native replacement ranges and actual summaries. Both observed viewport sizes
(1265 and 486 CSS pixels) showed no horizontal overflow or console errors.

Screenshots, exact hashes, browser APIs, failed attempts and limitations are in
result.json and attempts.json. Screenshot bytes were visually reviewed by the
implementation agent only; this does not supply a human cognition vote. Browser
tabs were restored to blank review controls after the synthetic transport test.
''',encoding='utf-8')
print(json.dumps({'status':result['status'],'checks_exit_code':0,'images':len(images),'items':len(base['items'])}))
