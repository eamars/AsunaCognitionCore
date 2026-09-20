"""Recover human-review material from saved evidence, without model calls."""
import json
from pathlib import Path
from .config import ROOT,BUNDLE
from .evidence import canonical,sha


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def source_paths(reports):
    paths=[p for p in reports.rglob('blind_review.json') if 'private' not in p.relative_to(reports).parts]
    for p in reports.glob('*/result.json'):
        if not (p.parent/'blind_review.json').exists() and read(p).get('test_id')=='L06':paths.append(p)
    return sorted(paths)


def source_rows(path):
    if path.name!='result.json':return read(path)
    rows=[]
    persona=(BUNDLE/'prompts/persona_p1_xiaoman.md').read_text(encoding='utf-8')
    for sample in read(path).get('samples',[]):
        trace=path.parent/sample['id']/'trace.json'
        records=read(trace) if trace.exists() else []
        output=next((e['payload'] for e in records if e['type']=='reflection.output'),None)
        material=None
        if output:
            for ref in output.get('request_refs',[]):
                request=(ROOT/ref['artifact_path']).resolve()
                if not request.is_relative_to(ROOT.resolve()) or sha(request.read_bytes())!=ref['sha256']:
                    raise ValueError('REFLECTION_REQUEST_HASH_MISMATCH')
                body=json.loads(read(request)['payload']['body_utf8'])
                content=body['messages'][-1]['content']
                try:actual,_=json.JSONDecoder().raw_decode(content)
                except ValueError:continue
                material={k:actual[k] for k in ('scope_key','entity_key','current','sources') if k in actual}
        rows.append({'blind_id':sha(canonical([sample['database'],sample['id'],'reflection-review']))[:16],
                     'kind':'reflection','target_persona':persona,'input':'审阅实际反思窗口中的来源、当前状态和模型原始决定。',
                     'review_context':material,'response':output['content'] if output else None,
                     'subsequent_public_messages':[m['text'] for m in sample.get('public_messages',[])],
                     'ratings':{d:None for d in ('persona_consistency','independent_stance','relationship_memory_use','natural_expression')},
                     'behavior_correct':None,'behavior_question':'更新或 no_change 是否有符合来源的理由，并遵守作用范围？','critical_flags':[]})
    return rows


def observed_item(result,index,blind_id):
    samples=result.get('samples',[]);test=result.get('test_id')
    if test=='L08':
        for group in samples:
            for answer in group.get('answers',[]):
                if sha(canonical([group['database'],answer['id']]))[:16]==blind_id:
                    return {**answer,'case_id':answer['id'],'scene_id':group['scene'],'repetition':group['repetition'],
                            'sample_id':f"{group['repetition']}-{group['scene']}",
                            'mechanical_status':group['status'],'protocol_valid':answer['state']=='COMMITTED'}
        raise ValueError('CONTINUITY_REVIEW_SOURCE_MISSING')
    if len(samples)<=index:return {}
    observed=samples[index]
    if test=='A02':return {**observed['scenario'],'condition':observed['condition'],'repetition':observed['repetition']}
    if test=='L06':return {**observed,'case_id':observed['id'],'sample_id':observed['id'],'episode':observed.get('resumed_episode')}
    if test=='L11':return {**observed,'episode':observed.get('review_episode')}
    return observed


def context_for(path,observed):
    if not observed.get('sample_id'):return None
    trace=path.parent/observed['sample_id']/'trace.json'
    if not trace.exists():return None
    contexts=[e['payload']['context'] for e in read(trace) if e['type']=='context.prepared' and (not observed.get('episode') or e['stream_id']==observed['episode'])]
    if not contexts:return None
    context=contexts[0]
    return {k:context[k] for k in ('scene_id','person_id','relationship','overlay','delivered_history','undelivered_outbound_not_public','task_state_from_program') if k in context}
