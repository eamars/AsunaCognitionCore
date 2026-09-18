from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .config import BUNDLE,ROOT,load
from .state import Store
from .audit import render_html,replay


def main():
    parser=argparse.ArgumentParser(prog='asuna')
    parser.add_argument('--config',default='config/local.json')
    sub=parser.add_subparsers(dest='command',required=True)
    for cmd in ('db-init','seed','inspect','replay'):
        p=sub.add_parser(cmd)
        p.add_argument('--config',default=argparse.SUPPRESS)
        p.add_argument('--database')
        if cmd=='seed':
            p.add_argument('--fixture',default=str(BUNDLE/'fixtures/world.json'))
        if cmd=='inspect':
            p.add_argument('kind',choices=['episode','request'])
            p.add_argument('id')
            p.add_argument('--format',choices=['json','html'],default='json')
            p.add_argument('--view',choices=['provider'],default='provider')
            p.add_argument('--out')
        if cmd=='replay':
            p.add_argument('trace')
            p.add_argument('--mode',choices=['state-only'],required=True)
            p.add_argument('--deny-model-and-tools',action='store_true',required=True)
    args=parser.parse_args()
    try:
        store=Store(load(args.config),args.database)
        if args.command=='db-init':
            value=store.migrate()
        elif args.command=='seed':
            store.migrate();store.seed(Path(args.fixture));value={'database':store.name,'seeded':True}
        elif args.command=='inspect':
            if args.kind=='episode':
                events=list(store.db.audit_events.find({'stream_id':args.id}).sort('seq',1))
                if not events: raise ValueError('UNKNOWN_EPISODE')
                if args.format=='html':
                    if not args.out: raise ValueError('--out required for HTML')
                    render_html(events,Path(args.out));value={'path':args.out}
                else: value=events
            else:
                hits=[]
                for path in (ROOT/'reports').glob('**/*provider.request.json'):
                    item=json.loads(path.read_text(encoding='utf-8'))
                    if item.get('payload',{}).get('call_id')==args.id: hits.append(item)
                if not hits: raise ValueError('UNKNOWN_CALL')
                value=hits
        else:
            value=replay(json.loads(Path(args.trace).read_text(encoding='utf-8')),store)
        print(json.dumps(value,ensure_ascii=False,default=str))
        return 0
    except Exception as exc:
        print(json.dumps({'status':'FAIL','error_type':type(exc).__name__}),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
