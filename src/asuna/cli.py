from __future__ import annotations
import argparse,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
from .config import BUNDLE,ROOT,load
from .state import Store
from .evidence import Evidence,write_json
from .audit import render_html,replay


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='strict')
    parser=argparse.ArgumentParser(prog='asuna');parser.add_argument('--config',default='config/local.json')
    sub=parser.add_subparsers(dest='command',required=True)
    for cmd in ('chat','doctor','db-init','seed','run','inspect','compact','reflect','rollback','index','delete','cancel','replay','evaluate','report','export','review-pack','review-import','review-aggregate'):
        p=sub.add_parser(cmd);p.add_argument('--config',default=argparse.SUPPRESS);p.add_argument('--database');p.add_argument('--out')
        if cmd=='seed':p.add_argument('--fixture',default=str(BUNDLE/'fixtures/world.json'))
        if cmd=='run':
            p.add_argument('--scene',default='dm-a');p.add_argument('--person',default='A');p.add_argument('--text');p.add_argument('--events',type=Path);p.add_argument('--persona',default='P1',choices=['P0','P1','P2']);p.add_argument('--workspace',type=Path);p.add_argument('--mentioned',action='store_true');p.add_argument('--compact-before',action='store_true');p.add_argument('--supersedes-task')
        if cmd=='inspect':
            p.add_argument('kind',choices=['episode','task','request','trace']);p.add_argument('id',nargs='?');p.add_argument('--format',choices=['json','html'],default='json');p.add_argument('--view',choices=['provider'],default='provider')
        if cmd=='compact':p.add_argument('--scene',default='dm-a');p.add_argument('--persona',default='P1')
        if cmd=='reflect':p.add_argument('--scope',required=True);p.add_argument('--entity',required=True)
        if cmd=='rollback':
            p.add_argument('--scope',required=True);p.add_argument('--entity',required=True);p.add_argument('--target-revision',required=True);p.add_argument('--base-revision',required=True);p.add_argument('--operation',required=True);p.add_argument('--operator',action='store_true',required=True)
        if cmd=='delete':p.add_argument('memory_id');p.add_argument('--operator',action='store_true',required=True)
        if cmd=='cancel':p.add_argument('task_id')
        if cmd=='replay':p.add_argument('trace');p.add_argument('--mode',choices=['state-only'],required=True);p.add_argument('--deny-model-and-tools',action='store_true',required=True)
        if cmd=='evaluate':p.add_argument('--test',required=True);p.add_argument('--manifest',default=str(BUNDLE/'fixtures/acceptance_cases.json'))
        if cmd in ('report','export'):p.add_argument('--reports',default=str(ROOT/'reports'))
        if cmd=='review-pack':p.add_argument('--reports',default=str(ROOT/'reports'))
        if cmd=='review-import':p.add_argument('--original',required=True);p.add_argument('--submitted',required=True)
        if cmd=='review-aggregate':p.add_argument('--original',required=True);p.add_argument('--imports',nargs='*',default=[])
        if cmd=='report':p.add_argument('--human-assessment',type=Path)
    args=parser.parse_args();ev=None;store=None
    try:
        config=load(args.config)
        if args.command=='chat':
            from .chat import chat
            return chat(config,args.database,args.out)
        if args.command in ('run','doctor','reflect','index','evaluate'):
            run=args.command+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
            ev=Evidence(Path(args.out) if args.out else ROOT/'reports'/run)
        store=Store(config,args.database)
        if args.command=='doctor':
            from .doctor import doctor
            value=doctor(config,ev)
        elif args.command=='db-init':value=store.migrate()
        elif args.command=='seed':store.migrate();store.seed(Path(args.fixture));value={'database':store.name,'seeded':True}
        elif args.command=='index':
            from .retrieval import Retrieval
            r=Retrieval(store,ev)
            try:value={'indexed':r.index_pending(),'ready':r.ensure_index()}
            finally:r.close()
        elif args.command=='run':
            from .application import Application
            events=[json.loads(line) for line in args.events.read_text(encoding='utf-8').splitlines() if line.strip()] if args.events else [{'event_id':str(uuid.uuid4()),'scene_id':args.scene,'person_id':args.person,'text':args.text,'mentioned':args.mentioned,**({'supersedes_task_id':args.supersedes_task} if args.supersedes_task else {})}]
            if any(not e.get('text') for e in events):raise ValueError('TEXT_OR_EVENTS_REQUIRED')
            with Application(config,ev,args.database) as app:
                if args.compact_before:
                    scene=app.store.db.scenes.find_one({'_id':args.scene});binding=f'xiaoman:{args.scene}:{scene["policy_epoch"]}:{args.persona}'
                    if scene.get('character_context'):binding+=':'+scene['character_context']
                    app.character.compact(binding)
                episodes=app.router.batch(events,persona=args.persona,workspace=args.workspace)
                value={'episodes':[{'id':e.get('_id',e.get('message_id')),'state':e['state']} for e in episodes],'public':{e['scene_id']:app.store.public_messages(e['scene_id'],e['person_id']) for e in events},'evidence':str(ev.root)}
        elif args.command=='reflect':
            from .memory import MemoryService
            from .dsh_lane import DshLane
            with DshLane(config,store,ev) as lane:value=MemoryService(store).reflect(lane,args.scope,args.entity,'reflect-'+uuid.uuid4().hex)
        elif args.command=='rollback':
            from .memory import MemoryService
            value=MemoryService(store).rollback(args.entity,args.scope,args.target_revision,args.base_revision,args.operation,operator=True)
        elif args.command=='compact':
            scene=store.db.scenes.find_one({'_id':args.scene});binding=f'xiaoman:{args.scene}:{scene["policy_epoch"]}:{args.persona}'
            if scene.get('character_context'):binding+=':'+scene['character_context']
            session=store.db.sessions.find_one({'binding_key':binding})
            if not session:raise ValueError('SESSION_NOT_FOUND')
            store.put('sessions',{**session,'compact_requested':True,'compact_request_id':str(uuid.uuid4())},expected=session['revision'],stream=binding)
            value={'state':'QUEUED','binding':binding,'summary_generated':False}
        elif args.command=='delete':
            from .privacy import PrivacyService
            value=PrivacyService(store).delete_memory(args.memory_id,operator=True)
        elif args.command=='cancel':
            from .tasks import TaskService
            value=TaskService(store).cancel(args.task_id,operator=True)
        elif args.command=='inspect':
            if args.kind=='request':
                value=[]
                for path in (ROOT/'reports').glob('**/*provider.request.json'):
                    if 'private' in path.relative_to(ROOT/'reports').parts:continue
                    item=json.loads(path.read_text(encoding='utf-8'))
                    if item.get('payload',{}).get('call_id')==args.id:value.append(item)
            else:value=list(store.db.audit_events.find({} if args.kind=='trace' else {'stream_id':args.id}).sort([('stream_id',1),('seq',1)]))
            if not value:raise ValueError('UNKNOWN_AUDIT_OBJECT')
            if args.format=='html':
                if not args.out:raise ValueError('OUT_REQUIRED')
                render_html(value,Path(args.out));value={'path':args.out}
        elif args.command=='replay':value=replay(json.loads(Path(args.trace).read_text(encoding='utf-8')),store)
        elif args.command=='evaluate':
            from .experiments import evaluate
            value=evaluate(config,args.test,Path(args.manifest),ev)
        elif args.command=='review-aggregate':
            from .review_scores import aggregate
            if not args.out:raise ValueError('OUT_REQUIRED')
            value=aggregate(Path(args.original),[Path(p) for p in args.imports],Path(args.out))
        elif args.command in ('review-pack','review-import'):
            from .review import pack,ingest
            if not args.out:raise ValueError('OUT_REQUIRED')
            value=pack(Path(args.reports),Path(args.out)) if args.command=='review-pack' else ingest(Path(args.original),Path(args.submitted),Path(args.out))
        else:
            from .reporting import build_report,export
            value=build_report(Path(args.reports),Path(args.out) if args.out else ROOT/'report.json',human_assessment=args.human_assessment) if args.command=='report' else export(config,Path(args.reports),Path(args.out) if args.out else ROOT/'evidence.zip')
        if ev:write_json(ev.root/'command_result.json',value)
        print(json.dumps(value,ensure_ascii=False,default=str))
        return 1 if isinstance(value,dict) and value.get('status')=='FAIL' else 0
    except Exception as exc:
        failure={'status':'FAIL','error_type':type(exc).__name__,'message':str(exc) if isinstance(exc,(ValueError,PermissionError)) else 'See local diagnostic evidence'}
        if ev:ev.record('command.error',failure)
        print(json.dumps(failure,ensure_ascii=False),file=sys.stderr);return 1
    finally:
        if store:store.client.close()


if __name__=='__main__':raise SystemExit(main())
