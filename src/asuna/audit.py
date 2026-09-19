from __future__ import annotations
import copy
import html
import json
from pathlib import Path
from .evidence import canonical,sha
from .state import Store,Denied


def reconcile_calls(observed_body_hashes,events):
    from collections import Counter
    requests=[e['payload'] for e in events if e['type']=='provider.request']
    responses=[e['payload'] for e in events if e['type'] in ('provider.response','provider.error')]
    if Counter(observed_body_hashes)!=Counter(r['body_sha256'] for r in requests):raise ValueError('PROVIDER_AUDIT_COUNT_MISMATCH')
    response_ids={r['call_id'] for r in responses}
    if any(not r.get('purpose') or r['call_id'] not in response_ids for r in requests):raise ValueError('PROVIDER_AUDIT_JOIN_INCOMPLETE')
    return {'requests':len(requests),'responses_or_errors':len(response_ids),'matched':True}


def verify(events: list[dict]):
    heads={}
    for event in sorted(events,key=lambda e:(e['stream_id'],e['seq'])):
        previous_seq,previous_hash=heads.get(event['stream_id'],(0,'0'*64))
        body={k:v for k,v in event.items() if k!='event_hash'}
        if event['seq']!=previous_seq+1 or event['prev_hash']!=previous_hash or sha(canonical(body))!=event['event_hash']:
            raise ValueError('AUDIT_HASH_CHAIN_INVALID')
        heads[event['stream_id']]=(event['seq'],event['event_hash'])
    return heads


def replay(events: list[dict], target: Store):
    if not target.name.startswith('asuna_v2_test_'):
        raise Denied('REPLAY_REQUIRES_NEW_TEST_DATABASE')
    verify(events)
    if any(target.db[c].count_documents({}) for c in ('state_heads','tasks','messages')):
        raise Denied('REPLAY_TARGET_NOT_EMPTY')
    target.migrate()
    # Only state projections; this function has no lane/tool/publication dependency.
    for event in sorted(events,key=lambda e:(e['occurred_at'],e['stream_id'],e['seq'])):
        if event['type']=='state.commit':
            payload=event['payload'];doc=payload['document']; collection=payload['collection']
            current=target.db[collection].find_one({'_id':doc['_id']})
            if not current or current.get('revision',0)<doc.get('revision',0):
                target.db[collection].replace_one({'_id':doc['_id']},copy.deepcopy(doc),upsert=True)
    return projection(target)


def projection(store):
    data={name:list(store.db[name].find({}).sort('_id',1)) for name in ('state_heads','tasks','messages','sink_receipts')}
    return {'sha256':sha(canonical(data)),'data':data}


def render_html(events, output: Path):
    verify(events)
    rows=[]
    for event in events:
        title=html.escape(f"{event['stream_id']} / {event['seq']} / {event['type']}")
        body=html.escape(json.dumps(event,ensure_ascii=False,indent=2,default=str))
        rows.append(f'<details><summary>{title}</summary><pre>{body}</pre></details>')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Asuna operator audit</title><style>body{max-width:1100px;margin:2em auto;font:16px system-ui;background:#f5f5f2;color:#202020}summary{cursor:pointer;padding:.6em}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1em;background:white}details{border-bottom:1px solid #ccc}</style><h1>Asuna 操作者审计</h1><p>独白是角色持久叙事；reasoning 是模型返回字段。生成不等于送达。</p>'+''.join(rows),encoding='utf-8')
