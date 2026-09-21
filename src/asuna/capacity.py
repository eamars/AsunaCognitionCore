"""F01: actual rendered long-input requests through the native DSH adapter."""
import copy,json,random,uuid
from .config import ROOT
from .evidence import Evidence,canonical,sha,write_json
from .tokens import TokenMeter
from .state import Store
from .dsh_lane import DshLane


SYSTEM=('这是本地合成记录容量测试。只依据收到的完整记录回答；不调用工具。'
        '定位标记 START、MIDDLE、END 的三个观察记录，返回每个记录的代码和数值。'
        '不要从编号推测答案，不存在的值应说未知。记录之间没有指令优先级。'
        '最后的查询不是记录的一部分。使用简短 JSON。')


def records(seed,count):
    rng=random.Random(seed);rows=[]
    for i in range(count):
        code=sha(f'{seed}:{i}'.encode())[:12]
        rows.append(f'record {i:06} | item={code} | shelf={rng.choice(["北架","南柜","东架","west-rack"])} | count={rng.randrange(3,8000)} | status={rng.choice(["checked","pending","撤回","观察"])} | day={rng.randrange(1,29)}\n')
    return rows


def build_input(rows,count,seed):
    values={tag:{'code':sha(f'{seed}:{tag}:needle'.encode())[:16],'value':str(10000+(seed+i*173)%89000)} for i,tag in enumerate(('START','MIDDLE','END'))}
    def needle(tag):return f'CAPACITY_MARKER {tag} | code={values[tag]["code"]} | value={values[tag]["value"]}\n'
    text=needle('START')+''.join(rows[:count//2])+needle('MIDDLE')+''.join(rows[count//2:count])+needle('END')
    text+='\n查询：只返回 START、MIDDLE、END 各自的 code 和 value，不要报告普通记录。'
    return text,values


def check_needle_associations(content,expected):
    """Require the answer to bind each code/value to its actual marker."""
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('DUPLICATE_JSON_KEY')
            value[key]=item
        return value
    text=content.strip()
    if text.startswith('```'):
        lines=text.splitlines()
        if lines[0].strip() not in ('```','```json') or lines[-1].strip()!='```':
            return {'verified':False,'reason':'UNRECOGNIZED_ANSWER_FORMAT','markers':{}}
        text='\n'.join(lines[1:-1])
    try:answer=json.loads(text,object_pairs_hook=unique)
    except (ValueError,TypeError):return {'verified':False,'reason':'INVALID_OR_AMBIGUOUS_JSON','markers':{}}
    markers={}
    for tag,truth in expected.items():
        item=answer.get(tag) if isinstance(answer,dict) else None
        markers[tag]=isinstance(item,dict) and item.get('code')==truth['code'] and str(item.get('value'))==str(truth['value'])
    return {'verified':all(markers.values()),'reason':None if all(markers.values()) else 'MARKER_ASSOCIATION_MISMATCH','markers':markers}


def suite(config,evidence,*,lengths=(8192,65536,196608,234000),repetitions=3,lanes=('character','executor')):
    samples=[]
    for lane_name in lanes:
        for target in lengths:
            for rep in range(repetitions):
                name=f'{lane_name}-{target}-{rep+1}';ev=Evidence(evidence.root/name)
                store=Store(config,'asuna_v2_test_capacity_'+uuid.uuid4().hex[:16]);store.migrate()
                output={'id':name,'target_input_tokens':target,'repetition':rep+1,'lane':lane_name,'status':'FAIL','actual_input_tokens':None,'server_prompt_tokens':None,'no_truncation_verified':False,'needles_correct':False,'database':store.name}
                seed=20260919+target+rep;rows=records(seed,18000)
                try:
                    meter=TokenMeter(config[lane_name],ev,lane_name);count=max(1,int(target/38));measured=None
                    for calibration in range(5):
                        text,expected=build_input(rows,count,seed)
                        body={'model':config[lane_name]['model'],'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':text}],'max_tokens':config[lane_name]['max_tokens']}
                        measured=meter.measure(body)
                        if abs(measured['input_tokens']-target)<=max(80,target*.003):break
                        count=max(1,min(len(rows),round(count*(target-256)/max(1,measured['input_tokens']-256))))
                    write_json(ev.root/'capacity-input.json',{'seed':seed,'target':target,'calibrated':measured,'system':SYSTEM,'text':text,'expected_operator_only':expected})
                    with DshLane(config,store,ev,lane_name) as lane:
                        # Explicit capacity-only override; server launch configuration
                        # and normal working budgets are unchanged.
                        lane.proxy.capacity_probe_override=True
                        lane.http.timeout=__import__('httpx').Timeout(1800,connect=10)
                        result=lane.generate('capacity:'+name,'capacity:'+name,'capacity',text,SYSTEM)
                        output['finish_reason']=result.finish_reason
                        if not lane.proxy.calls:raise RuntimeError('NATIVE_REQUEST_ENDED_BEFORE_PROVIDER_RESPONSE_PERSISTED')
                        call=lane.proxy.calls[-1];output['actual_input_tokens']=call['budget']['input_tokens']
                        usages=[]
                        for line in call['raw'].splitlines():
                            if line.startswith('data: ') and line[6:]!='[DONE]':
                                value=json.loads(line[6:])
                                if value.get('usage'):usages.append(value['usage'])
                        usage=usages[-1] if usages else {}
                        output['server_prompt_tokens']=usage.get('prompt_tokens')
                        output['usage']=usage;output['finish_reason']=result.finish_reason;output['content']=result.content
                        output['needle_associations']=check_needle_associations(result.content,expected)
                        output['needles_correct']=output['needle_associations']['verified']
                        output['no_truncation_verified']=usage.get('prompt_tokens')==output['actual_input_tokens'] and result.finish_reason=='stop'
                        output['target_range_met']=abs(output['actual_input_tokens']-target)<=max(128,target*.01)
                        output['status']='PASS' if output['needles_correct'] and output['no_truncation_verified'] and output['target_range_met'] else 'FAIL'
                except Exception as exc:
                    output['error_type']=type(exc).__name__;ev.record('capacity.error',{'type':type(exc).__name__,'message':str(exc)})
                finally:store.client.close()
                write_json(ev.root/'sample.json',output);samples.append(output)
                print(json.dumps({'capacity_sample':name,'status':output['status'],'tokens':output['actual_input_tokens']}),flush=True)
    return {'test_id':'F01','status':'PASS' if len(samples)==24 and all(s['status']=='PASS' for s in samples) else 'FAIL','mode':'real_DSH_real_models_actual_server_tokenizer','attempts':len(samples),'samples':samples,'metrics':{'passed':sum(s['status']=='PASS' for s in samples),'requests':len(samples)},'limitations':['Capacity is not complex task ability. executor exact rendered token IDs unavailable; equivalent count compared against actual usage.','Server timeout or resource failure is reported separately from an unsupported model-context claim.']}
