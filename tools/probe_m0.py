"""Narrow capability probe. This is not a formal acceptance suite or a substitute runtime."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from pymongo import MongoClient, WriteConcern
from pymongo.operations import SearchIndexModel
from asuna.config import ROOT, BUNDLE, load, redacted, validate_database
from asuna.evidence import Evidence, LocalHttp, write_json, sha, canonical

run_id = datetime.now(timezone.utc).strftime('M0-%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:6]
out = ROOT / 'reports' / run_id
evidence = Evidence(out)
config = load()
http = LocalHttp(evidence)
manifest = {str(p.relative_to(BUNDLE)): sha(p.read_bytes()) for p in sorted(BUNDLE.rglob('*')) if p.is_file()}
write_json(out / 'experiment_manifest.json', {'experiment_id': run_id, 'kind': 'capability-probe-not-formal-evaluation', 'fixture_hashes': manifest, 'config': redacted(config)})
results = []
environment = {'run_id': run_id, 'platform': sys.platform, 'python': sys.version, 'database': config['database'], 'isolation': redacted(config), 'models': {}, 'capabilities': results, 'unknowns': ['DSH provider integration pending', 'tool subprocess sandbox unverified', 'server-rendered token IDs unavailable', '196k and 234k capacity NOT_RUN', 'human cognition ratings NOT_RUN']}

def probe(name, fn):
    try:
        value = fn()
        results.append({'probe_id': name, 'status': 'PASS', 'value': value})
        print(json.dumps({'probe': name, 'status': 'PASS'}), flush=True)
        return value
    except Exception as exc:
        # Driver exception strings may contain connection details; type/code only.
        item = {'probe_id': name, 'status': 'FAIL', 'exception_type': type(exc).__name__, 'code': getattr(exc, 'code', None)}
        results.append(item)
        evidence.record('probe.failure', item)
        print(json.dumps(item), flush=True)
        return None

for lane in ('character', 'executor', 'embedding'):
    cfg = config[lane]
    models = probe(lane + '.models', lambda: http.request('GET', cfg['base_url'] + '/models', 'discovery', api_key=cfg.get('api_key', '')))
    environment['models'][lane] = {'models_response': models, 'configuration': redacted(config)[lane], 'deployment_variant': True}
    if lane != 'embedding':
        props = probe(lane + '.props', lambda: http.request('GET', cfg['base_url'].removesuffix('/v1') + '/props', 'discovery'))
        if props:
            template = props.get('chat_template', '')
            environment['models'][lane]['template_sha256'] = sha(template.encode())
            environment['models'][lane]['server_reported_capacity'] = props.get('default_generation_settings', {}).get('n_ctx')
            environment['models'][lane]['server_properties'] = {k:v for k,v in props.items() if k not in ('chat_template','ui','ui_settings')}
        messages = [{'role': 'system', 'content': '本地连接探针。只输出用户要求的短文本，不调用工具。'}, {'role': 'user', 'content': '请只回复：连接正常'}]
        body = {'model': cfg['model'], 'messages': messages, 'stream': False, 'max_tokens': 256, **cfg['sampling']}
        response = probe(lane + '.completion', lambda: http.request('POST', cfg['base_url'] + '/chat/completions', 'connectivity', body))
        environment['models'][lane]['completion_probe'] = response

emb_cfg = config['embedding']
embedding = probe('embedding.batch', lambda: http.request('POST', emb_cfg['base_url'] + '/embeddings', 'embedding.probe', {'model': emb_cfg['model'], 'input': ['search_document: alpha private record', 'search_document: beta public record', 'search_query: alpha record']}, emb_cfg.get('api_key','')))
vectors = None
if embedding:
    data = sorted(embedding['data'], key=lambda x:x['index'])
    assert [r['index'] for r in data] == [0,1,2]
    vectors = [r['embedding'] for r in data]
    environment['models']['embedding']['dimension'] = len(vectors[0])
    environment['models']['embedding']['returned_model'] = embedding.get('model')

client = MongoClient(config['mongo_uri'], serverSelectionTimeoutMS=6000, connectTimeoutMS=6000, timeoutMS=20000)
probe('mongo.ping', lambda: client.admin.command('ping'))
hello = probe('mongo.hello', lambda: client.admin.command('hello'))
environment['mongo'] = {'topology': 'replica-set' if hello and hello.get('setName') else 'standalone-or-unknown', 'transactions_verified': False}
db = client[validate_database(config, config['database'])]
collection = db.get_collection('integration_probes', write_concern=WriteConcern(w='majority', j=True))
def cas():
    collection.insert_one({'_id': run_id, 'schema_version': 1, 'kind': 'probe', 'revision': 0})
    first = collection.update_one({'_id': run_id, 'revision': 0}, {'$set': {'revision': 1}})
    second = collection.update_one({'_id': run_id, 'revision': 0}, {'$set': {'revision': 2}})
    assert first.modified_count == 1 and second.modified_count == 0
    return {'journal_majority_acknowledged': True, 'cas_winner_count': 1}
probe('mongo.write_cas', cas)
if vectors:
    vc = db['integration_probe_vectors']
    for i,scope in enumerate(('scene:dm-a','scene:g1')):
        vc.insert_one({'_id':run_id+str(i),'scope_key':scope,'embedding':vectors[i], 'run_id':run_id})
    index = SearchIndexModel(name='asuna_probe_vector_v1', type='vectorSearch', definition={'fields':[{'type':'vector','path':'embedding','numDimensions':len(vectors[0]),'similarity':'cosine'}, {'type':'filter','path':'scope_key'}, {'type':'filter','path':'run_id'}]})
    probe('mongo.vector_index_create', lambda: vc.create_search_index(index))
    indices = probe('mongo.vector_index_status', lambda: list(vc.list_search_indexes()))
    environment['mongo']['vector_indices'] = indices
    query = [{'$vectorSearch':{'index':'asuna_probe_vector_v1','path':'embedding','queryVector':vectors[2],'numCandidates':10,'limit':2,'filter':{'scope_key':'scene:dm-a', 'run_id':run_id}}}, {'$project':{'embedding':0}}]
    evidence.record('vector.query', {'query':query})
    def query_vector():
        rows = list(vc.aggregate(query))
        assert len(rows) == 1 and rows[0]['scope_key'] == 'scene:dm-a', 'index not ready or filtering failed'
        return rows
    probe('mongo.scope_vector_query', query_vector)

source = Path('C:/workspace/deepseek-harness')
environment['dsh'] = {'source_path':str(source),'source_commit':subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),'npm_requested_version':'0.1.1-rc.2','runtime_probe':'NOT_RUN','sdk_gap':'PyPI distributions unavailable in current index; explicit npm executable and source SDK pending compatibility probe'}
environment['scripts'] = {}
for name in ('start-gemma4-26b-a4b-it-qat-ud-q4_k_xl-4090-vision-mtp.ps1','start-qwen38-flash-next-uncensored-freetoken-vision.ps1'):
    p = Path('C:/workspace/qwen38_27b/scripts') / name
    environment['scripts'][str(p)] = sha(p.read_bytes())
write_json(out / 'environment.json', environment)
write_json(out / 'resolved.redacted.json', redacted(config))
lines = ['# M0 integration probe', '', 'Exploratory evidence only; not formal E/L/A/F acceptance.', '', '| Probe | Status |', '|---|---|']
lines += [f"| {r['probe_id']} | {r['status']} |" for r in results]
lines += ['', '## Unverified boundaries', *['- '+s for s in environment['unknowns']], '', 'All failures and serialized provider requests remain in this attempt directory. No real QQ/device sends; no legacy application was imported.']
(out/'integration_probe.md').write_text('\n'.join(lines),encoding='utf-8')
write_json(out / 'command.json', {'command': '.venv/Scripts/python.exe tools/probe_m0.py', 'exit_code': 2, 'reason':'DSH and sandbox stage-0 boundaries not yet verified', 'run_id':run_id})
print(json.dumps({'run_id':run_id,'report':str(out/'environment.json'),'status':'PARTIAL'},ensure_ascii=False))
raise SystemExit(2)
