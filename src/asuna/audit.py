"""The owner of the audit trail (`audit_events`), and its checks and replays: `verify` walks each stream's hash chain,
`verify_documents` compares stored documents with their last audited commit, and `replay` rebuilds the state in an
empty test database.

Every read of `audit_events` outside the shared layer (`Store.audit` appends, `Store.recover_commits`) goes through
this module's operations; verify, trace and replay read the other collections through the store's maintenance
surface. `render_html` writes a readable trace page. `asuna inspect` and `asuna replay` (cli.py) and the tests use
this module.
"""
from __future__ import annotations
import copy
import difflib
import html
import json
from pathlib import Path
from . import clock
from .evidence import canonical,sha
from .records.view import ANY, View, fenced, is_text
from .state import Store,Denied,content_digest,without_derived
from .store.words import AnyOf, Exists, Max, NoneOf, Not, Or, Range


# ── the owner of `audit_events` ──
# A record as stored (`fields` names what to return; `_id` always comes back). None follows the store's rule (ADR-104
# section 4): a stream, a scope, a persona or a reference given None, or a value not of its kind, finds nothing
# without a read, and so does a time bound given None. Not given is `ANY`. Views are `View`s, ordered as the replaced
# read was: by `occurred_at` (the default), by `seq`, by stream then `seq`, or none.
COLLECTION = 'audit_events'
ORDERS = {'occurred_at': (('occurred_at', 1),), 'seq': (('seq', 1),), 'stream': (('stream_id', 1), ('seq', 1)),
          None: ()}


def _bound(where, path, word, value):
    """`where` with one more bound on `path` (`word`: gt, gte or lt); None when the bound is None."""
    if value is ANY or where is None:
        return where
    if value is None:
        return None
    test = where.get(path)
    where[path] = Range(**{**(test.bounds() if isinstance(test, Range) else {}), word: value})
    return where


def events(store, kind=ANY, *, kinds=ANY, stream=ANY, streams=ANY, scope=ANY, since=ANY, after=ANY, before=ANY,
           persona=ANY, refused=ANY, outcome=ANY, reaches=ANY, besides_occurrence=ANY, ref=ANY, by='occurred_at'):
    """View: the audit records of a kind (or of any of `kinds`), in a stream (or any of `streams`), of a scope, at or
    after `since`, after `after`, before `before` (ISO text); and by what their payload says: the persona a review
    was shown to, whether a tool call was refused, a roll's outcome and whether it reached her, a roll of another
    occurrence than `besides_occurrence`, the record a mark is about (`ref`)."""
    where = fenced({}, {'type': (kind, is_text), 'stream_id': (stream, is_text), 'scope_key': (scope, is_text),
                        'payload.persona': (persona, is_text), 'payload.outcome': (outcome, is_text),
                        'payload.id': (ref, is_text)})
    if where is not None and kinds is not ANY:
        where['type'] = AnyOf(list(kinds))
    if where is not None and streams is not ANY:
        where['stream_id'] = AnyOf([value for value in streams if is_text(value)])
    if where is not None and refused is not ANY:
        where['payload.refused'] = Exists(bool(refused))
    if where is not None and reaches is not ANY:
        where['payload.reaches'] = bool(reaches)
    if where is not None and besides_occurrence is not ANY:
        where = {**where, 'payload.occurrence': Not(besides_occurrence)} if is_text(besides_occurrence) else None
    where = _bound(_bound(_bound(where, 'occurred_at', 'gte', since), 'occurred_at', 'gt', after),
                   'occurred_at', 'lt', before)
    return View(store, COLLECTION, where, ORDERS[by])


def count(store, kind, *, since=ANY, before=ANY):
    """How many audit records of a kind there are (at or after `since`, before `before`)."""
    return events(store, kind, since=since, before=before, by=None).count()


def commit_of(store, collection, document_id, fields=None):
    """The audited commit that wrote this document into this collection inline, or None."""
    where = fenced({'type': 'state.commit'}, {'payload.collection': (collection, is_text),
                                              'payload.document._id': (document_id, is_text)})
    return View(store, COLLECTION, where).first(fields=fields)


def prepared_for(store, scope, person, epoch, *, stream=ANY, limit=24, page=200):
    """The newest `context.prepared` records (stream and time only) of turns in this scope with this person at this
    policy epoch, at most `limit`, newest first (ties by id). Who a turn was with is in each record's payload, which
    some kinds of records write as text: it is read with the record and compared here, page by page in that order."""
    if not (is_text(person) and isinstance(epoch, (int, float)) and not isinstance(epoch, bool)):
        return []
    view = View(store, COLLECTION, fenced({'type': 'context.prepared'}, {'scope_key': (scope, is_text),
                                                                        'stream_id': (stream, is_text)}),
                (('occurred_at', 1), ('_id', 1)))
    found, skip = [], 0
    while len(found) < limit:
        rows = view.rows(newest_first=True, limit=page, skip=skip,
                         fields=['stream_id', 'occurred_at', 'payload.context.person_id',
                                 'payload.context.policy_epoch'])
        for row in rows:
            context = (row.get('payload') or {}).get('context')
            if isinstance(context, dict) and context.get('person_id') == person and context.get('policy_epoch') == epoch:
                found.append({key: row[key] for key in ('_id', 'stream_id', 'occurred_at') if key in row})
        if len(rows) < page:
            break
        skip += page
    return found[:limit]


def streams(store):
    """Every stream of the audit trail, ascending."""
    return store.collection(COLLECTION).group({}, ['stream_id'], None)


def redact_streams(store, scope, deletion, streams_of, session_ids):
    """An erasure's declared rebase of the audit chain (ADR-105): in every stream, each record of the scope, of a
    stream of one of `streams_of` (a turn's or a task's id, or one of their sub-streams), or whose payload names one
    of `session_ids` has its payload replaced by the deletion's mark and its payload's hash; every record is
    re-chained. (previous roots, new roots), by stream."""
    previous_roots, new_roots = {}, {}
    rows = store.collection(COLLECTION)
    for stream in streams(store):
        previous = '0' * 64
        chain = events(store, stream=stream, by='seq').rows()
        previous_roots[stream] = chain[-1]['event_hash']
        for event in chain:
            of_turn = any(stream == key or stream.startswith(key + ':') for key in streams_of)
            if event['scope_key'] == scope or of_turn or any(sid in str(event.get('payload', {})) for sid in session_ids):
                event['payload'] = {'redacted_by': deletion, 'previous_payload_sha256': sha(canonical(event['payload']))}
            event['prev_hash'] = previous
            event.pop('event_hash')
            event['event_hash'] = sha(canonical(event))
            previous = event['event_hash']
            rows.replace(event)
        new_roots[stream] = previous
    return previous_roots, new_roots


def reconcile_calls(observed_body_hashes,events):
    from collections import Counter
    requests=[e['payload'] for e in events if e['type']=='provider.request']
    responses=[e['payload'] for e in events if e['type'] in ('provider.response','provider.error')]
    if Counter(observed_body_hashes)!=Counter(r['body_sha256'] for r in requests):raise ValueError('PROVIDER_AUDIT_COUNT_MISMATCH')
    response_ids={r['call_id'] for r in responses}
    if any(not r.get('purpose') or r['call_id'] not in response_ids for r in requests):raise ValueError('PROVIDER_AUDIT_JOIN_INCOMPLETE')
    return {'requests':len(requests),'responses_or_errors':len(response_ids),'matched':True}


# Retention (ADR-067, ADR-074): the audit is bounded by time and by size. Past RETENTION_DAYS a record goes, except her
# own tool calls, kept KEPT_DAYS so an old thought still says what she did next (reasons.then), and the latest showing
# of each review, kept whatever its age so the next one counts from it. Above CAP_BYTES of data the oldest go first,
# whatever their kind, until it is under the cap again.
RETENTION_DAYS=30
KEPT_DAYS={'role_tool':365}
LATEST_KEPT=('review.tools_week','review.tools_week.started','review.exchanges','review.map','sticker.review_offered',
           'audit.pruned')      # the latest run explains the chain's gaps (verify), whatever its age
CAP_BYTES=6*10**9


LATEST_PAGE=500


def _latest(store):
    """The _ids of the newest record of each LATEST_KEPT kind in each stream (by its time): never pruned. Two records
    of one kind in one stream at the same moment are both kept."""
    rows=store.collection(COLLECTION)
    heads=rows.group({'type':AnyOf(list(LATEST_KEPT))},('type','stream_id'),Max('occurred_at'))
    out=[]
    for start in range(0,len(heads),LATEST_PAGE):
        page=heads[start:start+LATEST_PAGE]
        out+=[row['_id'] for row in rows.find(Or(*[{'type':head['type'],'stream_id':head['stream_id'],
                                                         'occurred_at':head['total']} for head in page]),
                                                fields=['_id'])]
    return out


def prune(store, moment=None, cap=None):
    """Delete the audit records past retention, then the oldest while the audit is over its cap. Every run writes one
    `audit.pruned` record, also when it deleted nothing (her ask, 2026-10-20: a run that found nothing and no run look
    alike otherwise): up to when, how many by which rule, the audit's records and bytes before and after, how long."""
    import time
    from datetime import timedelta
    started=time.monotonic()
    moment=moment or clock.now()
    cap=CAP_BYTES if cap is None else cap
    rows=store.collection(COLLECTION)
    first=rows.size()
    keep=_latest(store)
    cutoff=(moment-timedelta(days=RETENTION_DAYS)).isoformat()
    deleted=rows.delete({'occurred_at':Range(lt=cutoff),'_id':NoneOf(keep),'type':NoneOf(list(KEPT_DAYS))},many=True)
    for kind,days in KEPT_DAYS.items():
        deleted+=rows.delete({'type':kind,'occurred_at':Range(lt=(moment-timedelta(days=days)).isoformat())},many=True)
    before,by=cutoff,{'time':deleted} if deleted else {}
    stats=rows.size()
    if stats.bytes>cap and stats.records:
        # as many of the oldest as the excess holds at the average record size; the boundary is the next one's time
        over=-(-(stats.bytes-cap)*stats.records//stats.bytes)
        nxt=list(rows.find({'_id':NoneOf(keep)},[('occurred_at',1)],over,1,['occurred_at']))
        if nxt:
            before=max(before,nxt[0]['occurred_at'])
            by['size']=rows.delete({'occurred_at':Range(lt=before),'_id':NoneOf(keep)},many=True)
            deleted+=by['size']
    last=rows.size()
    store.audit('audit-retention','audit.pruned',{'before':before,'deleted':deleted,'by':by,
                                                 'records':[first.records,last.records],
                                                 'bytes':[first.bytes,last.bytes],
                                                 'seconds':round(time.monotonic()-started,1),'days':RETENTION_DAYS,
                                                 'kept_days':KEPT_DAYS,'latest_kept':list(LATEST_KEPT),'cap_bytes':cap})
    return deleted


def verify(events: list[dict]):
    """Each event's own hash, and each stream's chain. A gap in a chain is accepted only where retention removed
    events older than its cutoff (the `audit.pruned` records among the events)."""
    pruned=max((e['payload'].get('before') for e in events if e['type']=='audit.pruned'),default=None)
    heads={}
    for event in sorted(events,key=lambda e:(e['stream_id'],e['seq'])):
        previous_seq,previous_hash,previous_at=heads.get(event['stream_id'],(0,'0'*64,None))
        body={k:v for k,v in event.items() if k!='event_hash'}
        if sha(canonical(body))!=event['event_hash']:
            raise ValueError('AUDIT_HASH_CHAIN_INVALID')
        if event['seq']!=previous_seq+1 or event['prev_hash']!=previous_hash:
            if not (pruned and event['seq']>previous_seq+1 and (previous_at is None or previous_at<pruned)):
                raise ValueError('AUDIT_HASH_CHAIN_INVALID')
        heads[event['stream_id']]=(event['seq'],event['event_hash'],event['occurred_at'])
    return {stream:head[:2] for stream,head in heads.items()}


def _commit_key(payload):
    return payload['collection'], (payload['document']['_id'] if 'document' in payload else payload['id'])


def verify_documents(events: list[dict], store: Store):
    """Compare each document's latest audited commit with the collection (ADR-009 D-4).

    Inline commits are compared by value, reference commits by content_sha256. A document
    whose stored revision differs from the trace's latest is outside the trace and not judged.
    """
    latest={}
    for event in sorted(events,key=lambda e:(e['occurred_at'],e['stream_id'],e['seq'])):
        if event['type']=='state.commit':
            latest[_commit_key(event['payload'])]=event['payload']
    tampered=[]
    for (collection,key),payload in latest.items():
        doc=store.maintenance.record(collection,key)
        if doc is not None and payload.get('derived_left_out'):
            doc=without_derived(collection,doc,payload['derived_left_out'])[0]
        expected=payload.get('document')
        revision=expected.get('revision') if expected is not None else payload.get('revision')
        if doc is None or (doc.get('revision') or 0)!=(revision or 0):
            continue
        wanted=content_digest(collection,expected) if expected is not None else payload['content_sha256']
        if content_digest(collection,doc)!=wanted:
            tampered.append(collection+'/'+str(key))
    if tampered:
        raise ValueError('AUDIT_DOCUMENT_TAMPERED: '+', '.join(sorted(tampered)))
    return len(latest)


def trace_contents(events: list[dict], store: Store):
    """{content_sha256: document} for reference commits that still match the collection; exported with a trace."""
    out={}
    for event in events:
        payload=event['payload']
        if event['type']=='state.commit' and 'content_sha256' in payload:
            doc=store.maintenance.record(payload['collection'],payload['id'])
            if doc is not None and payload.get('derived_left_out'):
                doc=without_derived(payload['collection'],doc,payload['derived_left_out'])[0]
            if doc is not None and content_digest(payload['collection'],doc)==payload['content_sha256']:
                out[payload['content_sha256']]=doc
    return out


def replay(events: list[dict], target: Store, contents: dict | None=None):
    if not target.name.startswith('asuna_v2_test_'):
        raise Denied('REPLAY_REQUIRES_NEW_TEST_DATABASE')
    verify(events)
    contents=contents or {}
    last={}
    for event in sorted(events,key=lambda e:(e['occurred_at'],e['stream_id'],e['seq'])):
        if event['type']=='state.commit':
            last[_commit_key(event['payload'])]=event['_id']
    if any(next(iter(target.maintenance.records(c)),None) is not None for c in ('state_heads','tasks','messages')):
        raise Denied('REPLAY_TARGET_NOT_EMPTY')
    target.migrate()
    # Only state projections; this function has no lane/tool/publication dependency.
    for event in sorted(events,key=lambda e:(e['occurred_at'],e['stream_id'],e['seq'])):
        if event['type']=='state.commit':
            payload=event['payload'];collection=payload['collection']
            doc=payload.get('document')
            if doc is None:
                doc=contents.get(payload['content_sha256'])
                if doc is None:
                    # Only the final revision of a referenced document has to be supplied.
                    if last[_commit_key(payload)]==event['_id']:
                        raise ValueError('REPLAY_CONTENT_MISSING: '+collection+'/'+str(payload['id']))
                    continue
                if content_digest(collection,doc)!=payload['content_sha256']:
                    raise ValueError('REPLAY_CONTENT_MISMATCH: '+collection+'/'+str(payload['id']))
            current=target.maintenance.record(collection,doc['_id'])
            if not current or current.get('revision',0)<doc.get('revision',0):
                target.maintenance.restore(collection,copy.deepcopy(doc))
    return projection(target)


def projection(store):
    data={name:list(store.maintenance.records(name)) for name in ('state_heads','tasks','messages','sink_receipts')}
    return {'sha256':sha(canonical(data)),'data':data}


def render_html(events, output: Path):
    verify(events)
    from .config import ROOT
    groups={};responses={}
    revisions={e['payload']['document']['_id']:e['payload']['document'] for e in events if e['type']=='state.commit' and e['payload'].get('collection')=='state_revisions' and 'document' in e['payload']}
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
        label={'TURN':'角色回合','REPAIR':'程序检查后的同一回合','SPEAK':'公开回复候选（以送达回执为准）'}.get(phase,'')
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
