"""F02: measured native requests; unavailable counters stay null."""
import json,statistics,time,uuid
from datetime import datetime
from .config import ROOT,BUNDLE
from .evidence import Evidence,write_json,canonical,sha
from .state import Store
from .dsh_lane import DshLane

SYSTEM=((BUNDLE/'prompts/common.md').read_text(encoding='utf-8')+'\n'+
        (BUNDLE/'prompts/persona_p1_xiaoman.md').read_text(encoding='utf-8')+'\n'+
        '这是本地性能测量。只按当前问题给一个简短答案，不调用工具，不创造真实执行声明。保持此前记录的简单事实；该事实用于测试上下文保留，不涉及人类隐私。所有结果仅作传输、缓存和阶段延迟观测，没有预设体验合格阈值。')
COMPACTION_HISTORY=('这批合成测量日志的标签是 KC72。以下是日志内容，不需要逐行分析、计算或概括；本次只简短确认日志标签。\n'+
                    ''.join(f'record {i:03d} | code={sha(str(i).encode())[:12]} | measured={i*17+3} | source=local synthetic fixture\n' for i in range(64))+
                    '日志结束。这批日志的标签是 KC72，只简短确认该标签。')


def metrics(call,evidence):
    event=json.loads((evidence.root/call['response_ref']).read_text(encoding='utf-8'))['payload'];usage=None;timings=None
    for line in call['raw'].splitlines():
        if line.startswith('data: ') and line[6:]!='[DONE]':
            value=json.loads(line[6:]);usage=value.get('usage') or usage;timings=value.get('timings') or timings
    usage=usage or {};details=usage.get('prompt_tokens_details') or {}
    cached=details.get('cached_tokens')
    if cached is None and timings:cached=timings.get('cache_n')
    prompt=usage.get('prompt_tokens')
    reasoning=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens');completion=usage.get('completion_tokens')
    value={'input_tokens':prompt,'cached_tokens':cached,'uncached_tokens':prompt-cached if prompt is not None and cached is not None else None,
           'output_tokens':completion,'reasoning_tokens':reasoning,
           'content_tokens':completion-reasoning if completion is not None and reasoning is not None else None,
           'transport_first_byte_seconds':event.get('transport_first_byte_seconds'),'first_model_content_seconds':event.get('first_model_content_seconds'),
           'queue_seconds':event.get('queue_seconds'),'total_seconds':event.get('total_seconds'),
           'prefill_seconds':timings.get('prompt_ms')/1000 if timings and timings.get('prompt_ms') is not None else None,
           'decode_seconds':timings.get('predicted_ms')/1000 if timings and timings.get('predicted_ms') is not None else None,
           'model_load_seconds':None,'model_switch_seconds':None,'time_to_first_public_character_text':None,
           'raw_usage':usage,'raw_timings':timings,'request_messages_sha256':sha(canonical(call['body']['messages']))}
    value['missing_reasons']={k:('Private measured call has no publication; public receiver latencies are a separate source.' if k=='time_to_first_public_character_text' else 'Shared persistent endpoint exposes no attributable model load/switch event.' if k in ('model_load_seconds','model_switch_seconds') else 'Provider did not expose the required counter or timing; not inferred from total duration/tokens.') for k,v in value.items() if v is None}
    value['content_tokens_method']='reported completion total minus explicitly reported reasoning count; otherwise unknown'
    return value


def suite(config,evidence,*,repetitions=10,switch_cycles=10,lanes=('character','executor')):
    outputs=[]
    for name in lanes:
        ev=Evidence(evidence.root/name);store=Store(config,'asuna_v2_test_perf_'+uuid.uuid4().hex[:16]);store.migrate()
        try:
            with DshLane(config,store,ev,name) as lane:
                plan=[]
                for i in range(repetitions):plan.append(('fixed',f'fixed-{i}','记录：青桥柜标记为 CX81。只回复已记下。'))
                for i in range(repetitions):plan.append(('continuation','continuation',f'这是第 {i+1} 次确认：青桥柜标记 CX81，只简短确认。'))
                for temperature in ('cold','hot'):
                    for i in range(switch_cycles):
                        for leg,scope in enumerate(('A','B','A')):
                            session=f'switch-cold-{i}-{leg}-{scope}' if temperature=='cold' else f'switch-hot-{scope}'
                            plan.append(('switch-'+temperature,session,f'独立场景 {scope}，标记为 {scope}52。只简短确认当前标记。'))
                plan += [('before-compact','compact',COMPACTION_HISTORY),('after-compact','compact','这批日志的标签是什么？'),('after-compact-hot','compact','再确认一次日志标签。')]
                write_json(ev.root/'plan.json',{'plan':plan,'replay_repetitions':repetitions,'switch_cycles_per_temperature':switch_cycles,'cold_definition':'Fresh native session and distinct leading system prefix for each leg; no server flush/restart. Actual provider cache counters, when present, describe residual reuse.','hot_definition':'Reuse the two native A/B sessions across all A-B-A cycles.'})
                for i,(condition,session,text) in enumerate(plan):
                    binding='performance:'+session
                    if condition=='after-compact':lane.compact(binding)
                    before=len(lane.proxy.calls)
                    try:
                        system=('独立冷前缀 '+session+'。\n'+SYSTEM) if condition=='switch-cold' else SYSTEM
                        started=time.perf_counter();operation=f'perf:{name}:{i}'
                        result=lane.generate(binding,operation,'SPEAK' if name=='character' else 'execution',text,system)
                        elapsed=time.perf_counter()-started;compactions=[]
                        for event in store.db.audit_events.find({'stream_id':operation,'type':'compaction.native'}):
                            native=event['payload'];bracket=native['events']
                            start=next((e['time'] for e in bracket if e['type']=='compaction/start'),None)
                            end=next((e['time'] for e in bracket if e['type']=='compaction/end'),None)
                            compactions.append({'compaction_id':native['result']['compactionId'],'seconds':(end-start)/1000 if start is not None and end is not None else None,'clock':'native persisted bracket epoch milliseconds','request_refs':native['request_refs'],'response_refs':native['response_refs'],'provider_summary_join':native['provider_summary_join']})
                        calls=lane.proxy.calls[before:];row={'lane':name,'condition':condition,'ordinal':i,'status':'PASS' if result.finish_reason=='stop' and (condition!='after-compact' or len(compactions)==1 and compactions[0]['seconds'] is not None and compactions[0]['provider_summary_join']=='EXACT_CONTENT_AND_OPERATION') else 'FAIL','operation_seconds':elapsed,'native_compactions':compactions,'measurements':[metrics(c,ev) for c in calls]}
                        row['finish_reason']=result.finish_reason
                    except Exception as exc:
                        ev.record('performance.error',{'type':type(exc).__name__,'message':str(exc)})
                        row={'lane':name,'condition':condition,'ordinal':i,'status':'FAIL','error_type':type(exc).__name__,'measurements':[]}
                    outputs.append(row);write_json(ev.root/f'sample-{i:03}.json',row)
                    print(json.dumps({'performance_lane':name,'condition':condition,'ordinal':i,'status':row['status']}),flush=True)
        finally:store.client.close()
    fixed={}
    for name in lanes:
        hot=[r['measurements'][-1] for r in outputs if r['lane']==name and r['condition']=='fixed' and r['ordinal']>0 and r['measurements']]
        ratios=[r['cached_tokens']/r['input_tokens'] for r in hot if r['cached_tokens'] is not None and r['input_tokens']]
        fixed[name]={'hot_reuse_ratio':sum(ratios)/len(ratios) if ratios else None,'metric_available_samples':len(ratios),'prefix_stable':len({r['request_messages_sha256'] for r in hot})==1}
    public=public_latency_samples()
    write_json(evidence.root/'public-latency.json',public)
    failed=any(o['status']=='FAIL' for o in outputs) or any(not m['prefix_stable'] or m['metric_available_samples']==repetitions-1 and m['hot_reuse_ratio']<.9 for m in fixed.values())
    return {'test_id':'F02','status':'FAIL' if failed else 'INCONCLUSIVE','mode':'real_DSH_real_provider_timing_and_cache_counters','attempts':len(outputs),'samples':outputs,'metrics':{'fixed_prefix':fixed,'performance_slo':None,'public_text_latency_samples':public,'measured_private_turns':len(outputs),'expected_private_turns':len(lanes)*(2*repetitions+6*switch_cycles+3),'native_compactions':sum(len(r.get('native_compactions',[])) for r in outputs)},'limitations':['No absolute latency SLO approved.','Cold cases use fresh sessions and distinct leading prefixes, not an unverified server cache flush; report actual residual cache reuse or unknown.','Public-text latency uses actual audited receiver acceptance timestamps from formal L02 traces, under the configuration recorded by each source experiment. It includes queueing and may include concurrent evaluation load.','Private cache turns have no public text; model-content and transport-first-byte counters are not presented as public output.','Run after other endpoint workloads finish for controlled hot-cache interpretation; incidental shared-server traffic cannot be excluded.','Missing cache or prefill/decode/model-load fields are null with reasons, never inferred from total time.']}


def public_latency_samples():
    results=[]
    for path in sorted((ROOT/'reports').glob('formal-L02-*/task-*/trace.json')):
        trace=json.loads(path.read_text(encoding='utf-8'));docs={}
        for event in sorted(trace,key=lambda e:(e['occurred_at'],e['stream_id'],e['seq'])):
            if event['type']=='state.commit':
                payload=event['payload'];doc=payload['document'];key=(payload['collection'],doc['_id'])
                if key not in docs or docs[key]['revision']<doc['revision']:docs[key]=doc
        incoming=[v for (col,_),v in docs.items() if col=='messages' and v.get('direction')=='inbound' and v.get('platform_event_id')=='input']
        if not incoming:continue
        start=datetime.fromisoformat(incoming[0]['received_at']);messages={v['_id']:v for (col,_),v in docs.items() if col=='messages'}
        tasks={v['_id']:v for (col,_),v in docs.items() if col=='tasks'}
        episodes={v['_id']:v for (col,_),v in docs.items() if col=='episodes'}
        samples=[]
        for (col,_),receipt in docs.items():
            if col!='sink_receipts' or 'publication_key' not in receipt:continue
            message=messages.get(receipt['publication_key']);ep=episodes.get(message.get('episode_id')) if message else None
            if not ep:continue
            at=datetime.fromisoformat(receipt['received_at']);task=tasks.get(ep.get('task_id'))
            samples.append({'kind':'task_final' if ep.get('episode_kind')=='task_feedback' else 'initial_response','publication_key':receipt['publication_key'],'seconds_from_input':(at-start).total_seconds(),'seconds_from_task_completion':(at-datetime.fromisoformat(task['finished_at'])).total_seconds() if task and task.get('finished_at') and ep.get('episode_kind')=='task_feedback' else None})
        results.append({'source':{'artifact_path':path.relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes())},'first_public_character_text_seconds':min((s['seconds_from_input'] for s in samples),default=None),'publications':samples,'clock':'same coordinator wall-clock; receiver acceptance, not transport TTFT'})
    return results
