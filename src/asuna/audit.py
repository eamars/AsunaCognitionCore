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
    from .config import ROOT
    groups={}
    def pretty(value):return '<pre>'+html.escape(json.dumps(value,ensure_ascii=False,indent=2,default=str))+'</pre>'
    def requests(event):
        refs=event['payload'].get('request_refs',[])
        views=[]
        for ref in refs:
            label=html.escape(ref.get('artifact_path','未记录路径'))
            try:
                path=(ROOT/ref['artifact_path']).resolve()
                if not path.is_relative_to((ROOT/'reports').resolve()) or not path.name.endswith('provider.request.json'):
                    raise ValueError('请求路径不在报告目录')
                raw=path.read_bytes()
                if sha(raw)!=ref['sha256']:raise ValueError('请求文件 hash 不符')
                payload=json.loads(raw)['payload']
                title='摘要实际请求（压缩前材料）' if payload.get('purpose')=='compaction' else '实际 provider 请求'
                # Display the recorded wire body, not a reconstructed prompt.
                body='<pre>'+html.escape(payload['body_utf8'])+'</pre>'
                views.append('<details class="request"><summary>'+title+' · '+label+'</summary>'+pretty({k:v for k,v in payload.items() if k!='body_utf8'})+body+'</details>')
            except (OSError,KeyError,ValueError) as exc:
                views.append('<p class="missing">请求证据不可展开：'+label+' · '+html.escape(str(exc))+'</p>')
        return ''.join(views)
    for event in events:
        phase=event['payload'].get('phase')
        label={'MONOLOGUE':'角色持久独白','DECIDE':'角色意图','SPEAK':'公开回复候选（以送达回执为准）'}.get(phase,'')
        title=html.escape(f"{event['stream_id']} / {event['seq']} / {event['type']} {label}")
        extra=''
        if event['type']=='compaction.native':
            result=event['payload'].get('result',{})
            extra='<div class="compare"><section><h3>被替换的原始范围</h3>'+pretty({k:result.get(k) for k in ('shadowedRange','shadowedSeqs','shadowedTokenCount')})+'</section><section><h3>实际压缩摘要</h3>'+pretty(result.get('summary'))+'</section></div>'
        row=f'<details class="event"><summary>{title}</summary>'+extra+requests(event)+pretty(event)+'</details>'
        key=event['stream_id'].split(':',1)[0] if event['stream_id'].startswith(('ep-','task-')) else event['stream_id']
        groups.setdefault(key,[]).append(row)
    sections=[]
    for key,rows in sorted(groups.items(),key=lambda pair:pair[0]=='seed'):
        label='初始化记录' if key=='seed' else '角色回合' if key.startswith('ep-') else '执行任务' if key.startswith('task-') else '系统事件'
        sections.append('<details class="stream"><summary>'+html.escape(f'{label} · {key} · {len(rows)} 条记录')+'</summary>'+''.join(rows)+'</details>')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Asuna operator audit</title><style>*{box-sizing:border-box}body{max-width:1100px;margin:2em auto;padding:0 16px;font:16px/1.6 system-ui;background:#f5f5f2;color:#202020}summary{cursor:pointer;padding:.6em;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1em;background:white}.stream{border:1px solid #ccc;margin:12px 0}.stream>summary{font-weight:600}.event{margin-left:12px;border-top:1px solid #ddd}.request{margin:12px;border-left:3px solid #47766c}.compare{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:12px;min-width:0}.compare section{min-width:0}.missing{color:#8b3516}@media(max-width:650px){.compare{grid-template-columns:1fr}.event{margin-left:4px}}</style><h1>Asuna 操作者审计</h1><p>独白是角色持久叙事；reasoning 是模型返回字段。生成不等于送达。先展开回合或任务，再查看阶段及 hash 校验后的实际请求。页面无脚本、无外网资源。</p>'+''.join(sections)+'</html>',encoding='utf-8')
