from __future__ import annotations
import argparse,json,sys,uuid
from datetime import datetime,timezone
from pathlib import Path
import os
ROOT=Path(os.environ.get('ASUNA_DATA_ROOT', Path(__file__).resolve().parents[2])).resolve()


def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='strict')
    parser=argparse.ArgumentParser(prog='asuna',description='正式交互使用 Web：asuna ui。其他命令仅用于显式 debug/维护。');parser.add_argument('--config',default='config/local.json')
    parser.add_argument('--debug',action='store_true',help='显式启用 CLI 调试/维护；不用于正式交互或 Web 验收')
    sub=parser.add_subparsers(dest='command',required=True)
    for cmd in ('ui','db-init','seed','inspect','rollback','index','delete','cancel','replay'):
        p=sub.add_parser(cmd,help='启动正式 Web 界面' if cmd=='ui' else '仅 debug/维护，需要 --debug');p.add_argument('--config',default=argparse.SUPPRESS);p.add_argument('--database');p.add_argument('--out')
        if cmd!='ui':p.add_argument('--debug',action='store_true',default=argparse.SUPPRESS,help='显式启用 CLI 调试/维护')
        if cmd=='ui':
            p.add_argument('--port',type=int,default=8780);p.add_argument('--profile',help='DSH profile (default asuna-native; asuna-demo for the demo environment)')
        if cmd=='seed':p.add_argument('--fixture',required=True,help='synthetic test world (tests/fixtures/world.json)')
        if cmd=='inspect':
            p.add_argument('kind',choices=['episode','task','request','trace']);p.add_argument('id',nargs='?');p.add_argument('--format',choices=['json','html'],default='json');p.add_argument('--view',choices=['provider'],default='provider')
        if cmd=='rollback':
            p.add_argument('--scope',required=True);p.add_argument('--entity',required=True);p.add_argument('--target-revision',required=True);p.add_argument('--base-revision',required=True);p.add_argument('--operation',required=True);p.add_argument('--operator',action='store_true',required=True)
        if cmd=='delete':p.add_argument('memory_id');p.add_argument('--operator',action='store_true',required=True)
        if cmd=='cancel':p.add_argument('task_id')
        if cmd=='replay':p.add_argument('trace');p.add_argument('--mode',choices=['state-only'],required=True);p.add_argument('--deny-model-and-tools',action='store_true',required=True)
    args=parser.parse_args();ev=None;store=None
    if args.command!='ui' and not args.debug:
        parser.error('CLI_DEBUG_ONLY: 正式交互请运行 start-asuna.cmd 或 asuna ui；CLI 调试/维护必须显式添加 --debug。')
    try:
        if args.command=='ui':
            if args.database or args.out:
                raise ValueError('Native Web uses the installed profile')
            from .native_ui import ui
            return ui(args.config,port=args.port,profile=args.profile)
        from .config import load
        from .state import Store
        from .evidence import Evidence,write_json
        from .audit import render_html,replay
        config=load(args.config)
        if args.command=='index':
            run=args.command+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:6]
            ev=Evidence(Path(args.out) if args.out else ROOT/'reports'/run)
        store=Store(config,args.database)
        if args.command=='db-init':value=store.migrate()
        elif args.command=='seed':store.migrate();store.seed(Path(args.fixture));value={'database':store.name,'seeded':True}
        elif args.command=='index':
            from .retrieval import Retrieval
            r=Retrieval(store,ev)
            try:value={'indexed':r.index_pending(),'ready':r.ensure_index()}
            finally:r.close()
        elif args.command=='rollback':
            from .memory import MemoryService
            value=MemoryService(store).rollback(args.entity,args.scope,args.target_revision,args.base_revision,args.operation,operator=True)
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
