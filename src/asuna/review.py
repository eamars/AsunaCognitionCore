"""Independent review transport. The actor and executor never grade themselves."""
import copy,json,random
from pathlib import Path
from .config import BUNDLE,ROOT
from .evidence import canonical,sha,write_json

DIMENSIONS=('persona_consistency','independent_stance','relationship_memory_use','natural_expression')


def pack(reports:Path,output:Path):
    world=json.loads((BUNDLE/'fixtures/world.json').read_text(encoding='utf-8'))
    memories={m['id']:m for m in world['memories']};rows=[];sources=[];operator_items=[]
    common_target=(BUNDLE/'prompts/persona_p1_xiaoman.md').read_text(encoding='utf-8')
    for path in sorted(reports.rglob('blind_review.json')):
        if 'private' in path.relative_to(reports).parts:continue
        sources.append({'artifact_path':path.resolve().relative_to(ROOT).as_posix(),'sha256':sha(path.read_bytes())})
        result_path=path.parent/'result.json'
        result=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
        mapping_path=path.parent/'operator_blind_mapping.json'
        mapping={m['blind_id']:m for m in json.loads(mapping_path.read_text(encoding='utf-8'))} if mapping_path.exists() else {}
        local_rows=[]
        for index,sample in enumerate(json.loads(path.read_text(encoding='utf-8'))):
            row=copy.deepcopy(sample)
            row['available_memories']=row.get('available_memories',[memories.get(k,{'id':k,'note':'See original monologue in this review item if supplied'}) for k in row.get('available_memory_ids',[])])
            samples=result.get('samples',[])
            observed=samples[index] if len(samples)>index and samples[index].get('sample_id') else {}
            if observed:
                trace=path.parent/observed['sample_id']/'trace.json'
                if trace.exists():
                    contexts=[e['payload']['context'] for e in json.loads(trace.read_text(encoding='utf-8')) if e['type']=='context.prepared']
                    if contexts:
                        context=contexts[0]
                        row['review_context']={k:context[k] for k in ('scene_id','person_id','relationship','overlay','delivered_history','undelivered_outbound_not_public','task_state_from_program') if k in context}
            if result.get('test_id')=='A01':
                # Persona-aware compliance and common-target gain are distinct
                # ratings. P0 following its neutral persona is not evidence of
                # poor/good Xiaoman consistency by itself.
                row['reference_xiaoman_persona']=common_target
                row['target_xiaoman_consistency']=None
            # Review transport carries no model name, condition, run order or
            # provider trace. Operator provenance is in the adjacent manifest.
            rows.append(row);local_rows.append(row)
            operator_items.append({'blind_id':row['blind_id'],'experiment_id':path.parent.name,'test_id':result.get('test_id'),'source':path.resolve().relative_to(ROOT).as_posix(),'source_index':index,**mapping.get(row['blind_id'],{}),'case_id':observed.get('case_id')})
        if result.get('test_id')=='A01':
            grouped={};by_blind={r['blind_id']:r for r in local_rows}
            for item in operator_items:
                if item['experiment_id']!=path.parent.name or not str(item.get('case_id','')).startswith('C'):continue
                grouped.setdefault((item.get('model'),item['case_id'],item.get('repetition')),{}).update({item.get('persona'):item})
            rng=random.Random(20260919)
            for pair in grouped.values():
                if set(pair)!={'P1','P2'}:continue
                order=['P1','P2'];rng.shuffle(order);left,right=[by_blind[pair[k]['blind_id']] for k in order]
                key=sha(canonical([left['blind_id'],right['blind_id'],'contrast-pair']))[:16]
                rows.append({'blind_id':key,'kind':'persona_contrast_pair','target_persona':{'left':left['target_persona'],'right':right['target_persona']},'input':left['input'],'response':{'left':left['response'],'right':right['response']},'ratings':{d:None for d in DIMENSIONS},'behavior_correct':None,'behavior_question':'这两份回复是否分别按各自目标人格，在本题偏好或表达方式上呈现对应方向的差异？','critical_flags':[]})
                operator_items.append({'blind_id':key,'experiment_id':path.parent.name,'test_id':'A01','kind':'persona_contrast_pair','left':pair[order[0]]['blind_id'],'right':pair[order[1]]['blind_id']})
    if not rows:raise ValueError('NO_COMPLETED_BLIND_REVIEW_PACKS')
    if len({r['blind_id'] for r in rows})!=len(rows):raise ValueError('DUPLICATE_BLIND_ID')
    random.Random(20260919).shuffle(rows)
    payload={'schema':'asuna-human-review-v2','items':rows,'reviewer':{'name':'','independent_human':False},'source_digest':sha(canonical(sources))}
    payload['pack_id']=sha(canonical(payload))
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'blind.json',payload)
    write_json(output/'operator-source-manifest.json',{'pack_id':payload['pack_id'],'sources':sources,'items':operator_items,'scoring_contract':'docs/04 unchanged: four persona-aware dimensions, separate common Xiaoman target gain, and explicit paired contrast direction votes'})
    encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"><title>Asuna 独立盲评</title>
<style>*{box-sizing:border-box}body{font:16px/1.65 system-ui;background:#f4f3ee;color:#24251f;margin:0}main{max-width:928px;margin:36px auto;padding:24px;background:white}h1{font-size:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f7f7f3;padding:16px}label{display:block;margin:12px 0}select,input,button{font:inherit;padding:8px;max-width:100%}button{margin:8px 12px 8px 0}small{display:block;color:#555}fieldset{margin:20px 0;border:1px solid #ddd}progress,textarea{width:100%}textarea{min-height:180px}a{overflow-wrap:anywhere}.missing{color:#813c17;border-left:3px solid #b86628}@media(max-width:600px){main{margin:0;padding:16px}}</style>
<main><h1>Asuna 独立盲评</h1><p>按目标人格和可用事实评分；短、平静不扣分。0=明显不符，1=生硬/泛泛，2=部分符合，3=正确自然，4=稳定具体。未知或缺上下文请留空。模型和本代理的自评不能代替人工票。</p>
<label>评审者名字 <input id="name"></label><label><input id="human" type="checkbox">我本人独立阅读并评分，未用演员或执行模型代评</label>
<progress id="progress"></progress><p id="position"></p><div id="content"></div><fieldset id="ratings"><legend>0–4 分</legend></fieldset><label>语义行为正确 <select id="correct"><option value="">待判断</option><option value="true">是</option><option value="false">否</option></select></label><label>严重错误（多项用逗号分隔：隐私、虚构执行、假承诺、越权）<input id="flags" style="width:90%"></label><label>评语 <input id="note" style="width:90%"></label>
<button id="prev">上一项</button><button id="next">下一项</button><button id="save">下载评分 JSON</button><p id="export-status" role="status"></p><a id="download" hidden>保存已生成的评分文件</a><details id="export-text" hidden><summary>查看并复制评分 JSON</summary><label>导出评分 JSON<textarea id="export-json" readonly></textarea></label></details><small>页面不联网、不自动提交。关闭前下载 JSON；保留空白项和原始评分，不会自动补分。source manifest 是 operator 文件，盲评时不打开。</small></main>
<script>const data=PAYLOAD;const dims=['persona_consistency','independent_stance','relationship_memory_use','natural_expression'];const labels=['人格一致性','独立关注/立场','关系与记忆利用','自然表达'];let index=0;
const $=id=>document.getElementById(id);dims.forEach((d,i)=>{const label=document.createElement('label');label.textContent=labels[i]+' ';const s=document.createElement('select');s.id=d;['',0,1,2,3,4].forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n===''?'待评分':n;s.append(o)});label.append(s);$('ratings').append(label)});
const commonLabel=document.createElement('label');commonLabel.textContent='共同小满目标一致性（与本条件目标人格的遵从分开评分） ';const common=document.createElement('select');['',0,1,2,3,4].forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n===''?'待评分':n;common.append(o)});commonLabel.append(common);$('ratings').append(commonLabel);
function persist(){const r=data.items[index];dims.forEach(d=>r.ratings[d]=$(d).value===''?null:Number($(d).value));if(r.reference_xiaoman_persona!==undefined)r.target_xiaoman_consistency=common.value===''?null:Number(common.value);r.behavior_correct=$('correct').value===''?null:$('correct').value==='true';r.critical_flags=$('flags').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean);r.review_note=$('note').value;data.reviewer={name:$('name').value,independent_human:$('human').checked}}
function show(){const r=data.items[index];$('position').textContent=(index+1)+' / '+data.items.length+' · '+r.blind_id;$('progress').max=data.items.length;$('progress').value=data.items.filter(r=>r.kind==='persona_contrast_pair'?r.behavior_correct!==null:dims.every(d=>r.ratings[d]!==null)).length;$('content').replaceChildren();for(const [title,value] of [['目标人格',r.target_persona],['实际请求中的场景与关系',r.review_context],['可用记忆',r.available_memories],['当前输入',r.input],['原始私密独白',r.original_private_monologue],['先前公开消息',r.previous_public_messages],['待评回复',r.response],['共同小满参照（仅用于共同目标分）',r.reference_xiaoman_persona]]){if(value===undefined)continue;const h=document.createElement('h2');h.textContent=title;const p=document.createElement('pre');const missing=title==='待评回复'&&(value===null||value===''||(Array.isArray(value)&&value.length===0));p.textContent=missing?'缺少已送达回复。请保留缺项；不能将缺数据认定为角色主动沉默。':typeof value==='string'?value:JSON.stringify(value,null,2);if(missing)p.className='missing';$('content').append(h,p)}dims.forEach(d=>$(d).value=r.ratings[d]??'');$('ratings').style.display=r.kind==='persona_contrast_pair'?'none':'';commonLabel.style.display=r.reference_xiaoman_persona===undefined?'none':'block';common.value=r.target_xiaoman_consistency??'';$('correct').parentElement.firstChild.textContent=r.behavior_question??'语义行为正确 ';$('correct').value=r.behavior_correct??'';$('flags').value=r.critical_flags.join(', ');$('note').value=r.review_note??''}
let downloadUrl;
$('prev').onclick=()=>{persist();index=Math.max(0,index-1);show()};$('next').onclick=()=>{persist();index=Math.min(data.items.length-1,index+1);show()};$('save').onclick=()=>{persist();const raw=JSON.stringify(data,null,2);if(downloadUrl)URL.revokeObjectURL(downloadUrl);downloadUrl=URL.createObjectURL(new Blob([raw],{type:'application/json'}));const a=$('download');a.href=downloadUrl;a.download='asuna-human-review-'+data.pack_id.slice(0,12)+'.json';a.hidden=false;$('export-json').value=raw;$('export-text').hidden=false;$('export-status').textContent='评分 JSON 已生成。若下载未开始，请使用保存链接，或展开下方文本复制保存。';a.click()};show();</script></html>'''
    (output/'review.html').write_text(html.replace('PAYLOAD',encoded),encoding='utf-8')
    return {'status':'INCONCLUSIVE','pack_id':payload['pack_id'],'items':len(rows),'html':str(output/'review.html'),'independent_ratings_received':False}


def ingest(original:Path,submitted:Path,output:Path):
    base=json.loads(original.read_text(encoding='utf-8'));review=json.loads(submitted.read_text(encoding='utf-8'))
    if review.get('pack_id')!=base['pack_id'] or review.get('source_digest')!=base['source_digest']:raise ValueError('REVIEW_PACK_MISMATCH')
    person=review.get('reviewer',{})
    if person.get('independent_human') is not True or not person.get('name','').strip():raise ValueError('INDEPENDENT_HUMAN_ATTESTATION_REQUIRED')
    rows={r['blind_id']:r for r in base['items']};seen=set();complete=0;critical=[]
    for row in review['items']:
        key=row['blind_id']
        if key not in rows or key in seen:raise ValueError('REVIEW_ITEM_SET_CHANGED')
        seen.add(key)
        mutable={'ratings','behavior_correct','critical_flags','review_note','target_xiaoman_consistency'}
        if {k:v for k,v in row.items() if k not in mutable}!={k:v for k,v in rows[key].items() if k not in mutable}:raise ValueError('REVIEW_MATERIAL_CHANGED')
        scores=row.get('ratings',{})
        if set(scores)!=set(DIMENSIONS) or any(v is not None and (type(v) is not int or not 0<=v<=4) for v in scores.values()):raise ValueError('INVALID_RATING')
        if row.get('behavior_correct') is not None and type(row['behavior_correct']) is not bool:raise ValueError('INVALID_BEHAVIOR_VOTE')
        target=row.get('target_xiaoman_consistency')
        if target is not None and (type(target) is not int or not 0<=target<=4 or 'reference_xiaoman_persona' not in rows[key]):raise ValueError('INVALID_COMMON_TARGET_RATING')
        if not isinstance(row.get('critical_flags'),list) or any(not isinstance(f,str) for f in row['critical_flags']):raise ValueError('INVALID_CRITICAL_FLAGS')
        complete+=int(all(v is not None for v in scores.values()))
        if row['critical_flags']:critical.append({'blind_id':key,'flags':row['critical_flags']})
    if seen!=set(rows):raise ValueError('REVIEW_ITEMS_MISSING')
    output.mkdir(parents=True,exist_ok=False);(output/'raw-submission.json').write_bytes(submitted.read_bytes())
    result={'status':'INCONCLUSIVE','pack_id':base['pack_id'],'reviewer':person,'independence':'self-attested; not cryptographically verified','rated_items':complete,'total_items':len(rows),'critical_flags':critical,'original_sha256':sha(original.read_bytes()),'submission_sha256':sha(submitted.read_bytes()),'reason':'Import records independent votes; each frozen acceptance threshold still requires attribution-aware aggregation. Import itself never declares cognition PASS.'}
    write_json(output/'review-import.json',result);return result
