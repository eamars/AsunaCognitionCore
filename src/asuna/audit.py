from __future__ import annotations
import copy
import difflib
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
    groups={};responses={}
    revisions={e['payload']['document']['_id']:e['payload']['document'] for e in events if e['type']=='state.commit' and e['payload'].get('collection')=='state_revisions'}
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
                if path.parent not in responses:
                    responses[path.parent]={}
                    for response_path in path.parent.glob('*provider.response.json'):
                        response=json.loads(response_path.read_text(encoding='utf-8'))['payload']
                        responses[path.parent][response.get('call_id')]=(response_path,response)
                matched=responses[path.parent].get(payload.get('call_id'))
                timing='<p class="missing">缺少 provider 返回或耗时；不按零计算。</p>'
                if matched:
                    response_path,response=matched;usage=None
                    for line in response.get('body_utf8','').splitlines():
                        if line.startswith('data: ') and line[6:].strip()!='[DONE]':
                            value=json.loads(line[6:])
                            if value.get('usage'):usage=value['usage']
                    timing='<h4>实际返回的耗时与 tokens</h4>'+pretty({'response_artifact':response_path.relative_to(ROOT).as_posix(),'response_sha256':sha(response_path.read_bytes()),'usage':usage,**{k:response.get(k) for k in ('status_code','queue_seconds','total_seconds','first_model_content_seconds','public_text_ttft_seconds')}})
                views.append('<details class="request"><summary>'+title+' · '+label+'</summary>'+pretty({k:v for k,v in payload.items() if k!='body_utf8'})+timing+body+'</details>')
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
            before=requests(event) if event['payload'].get('request_refs') else '<p class="missing">旧记录未逐次关联摘要请求；请在对应阶段请求中核查，不能仅凭范围断言内容完整。</p>'
            extra='<div class="compare"><section><h3>被替换的原始范围与摘要输入</h3>'+pretty({k:result.get(k) for k in ('shadowedRange','shadowedSeqs','shadowedTokenCount')})+before+'</section><section><h3>实际压缩摘要</h3>'+pretty(result.get('summary'))+'</section></div>'
        if event['type'] in ('state.proposed','state.intent','state.conflict'):
            extra='<h3>'+{'state.proposed':'待处理提议','state.intent':'PENDING · 写入意图','state.conflict':'CONFLICT · 未提交'}[event['type']]+'</h3>'+pretty(event['payload'])
        if event['type']=='state.commit':
            collection=event['payload'].get('collection');doc=event['payload'].get('document',{})
            if collection=='state_revisions':
                prior=revisions.get(doc.get('parent_revision_id'))
                extra='<h3>人格 / 关系版本变更</h3>'+pretty({'entity':doc.get('entity_key'),'revision_id':doc.get('_id'),'parent_revision_id':doc.get('parent_revision_id'),'scope':doc.get('scope_key'),'write_state':'PENDING' if event['type']=='state.intent' else '版本已保存；是否生效以 state_heads 提交为准','source_ids':doc.get('source_ids'),'reason':doc.get('reason'),'change_class':doc.get('change_class'),'rollback_target':doc.get('rollback_target')})
                if prior:
                    diff=''.join(difflib.unified_diff(json.dumps(prior.get('content'),ensure_ascii=False,indent=2).splitlines(True),json.dumps(doc.get('content'),ensure_ascii=False,indent=2).splitlines(True),fromfile='parent '+prior['_id'],tofile='revision '+doc['_id']))
                    extra+='<pre>'+html.escape(diff or '正文没有变化。')+'</pre>'
                else:extra+='<p class="missing">本 trace 没有父版本；初始化版本或证据缺项，不虚构旧内容。</p>'
            elif collection=='state_heads':extra='<h3>状态头 '+('COMMITTED' if event['type']=='state.commit' else 'PENDING')+'</h3>'+pretty(doc)
            elif collection=='messages':extra='<h3>消息状态 · '+html.escape(doc.get('delivery_state',doc.get('state','RECEIVED' if doc.get('direction')=='inbound' else '未记录')))+'</h3>'
        row=f'<details class="event"><summary>{title}</summary>'+extra+('' if event['type']=='compaction.native' else requests(event))+pretty(event)+'</details>'
        key=event['stream_id'].split(':',1)[0] if event['stream_id'].startswith(('ep-','task-')) else event['stream_id']
        groups.setdefault(key,[]).append(row)
    sections=[]
    for key,rows in sorted(groups.items(),key=lambda pair:pair[0]=='seed'):
        label='初始化记录' if key=='seed' else '角色回合' if key.startswith('ep-') else '执行任务' if key.startswith('task-') else '系统事件'
        sections.append('<details class="stream"><summary>'+html.escape(f'{label} · {key} · {len(rows)} 条记录')+'</summary>'+''.join(rows)+'</details>')
    output.parent.mkdir(parents=True,exist_ok=True)
    machine=output.with_suffix('.json')
    if machine.exists():
        if json.loads(machine.read_text(encoding='utf-8'))!=json.loads(canonical(events)):
            raise ValueError('AUDIT_JSON_COMPANION_MISMATCH')
    else:
        from .evidence import write_json
        write_json(machine,events)
    download='<p><a download href="'+html.escape(machine.name,quote=True)+'">导出机器 JSON</a></p>'
    output.write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Asuna operator audit</title><style>*{box-sizing:border-box}body{max-width:1100px;margin:2em auto;padding:0 16px;font:16px/1.6 system-ui;background:#f5f5f2;color:#202020}summary{cursor:pointer;padding:.6em;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1em;background:white}.stream{border:1px solid #ccc;margin:12px 0}.stream>summary{font-weight:600}.event{margin-left:12px;border-top:1px solid #ddd}.request{margin:12px;border-left:3px solid #47766c}.compare{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:12px;min-width:0}.compare section{min-width:0}.missing{color:#8b3516}@media(max-width:650px){.compare{grid-template-columns:1fr}.event{margin-left:4px}}</style><h1>Asuna 操作者审计</h1><p>独白是角色持久叙事；reasoning 是模型返回字段。生成不等于送达。先展开回合或任务，再查看阶段及 hash 校验后的实际请求。页面无脚本、无外网资源。</p>'+download+''.join(sections)+'</html>',encoding='utf-8')
