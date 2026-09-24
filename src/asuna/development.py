"""One owner-only candidate connected to the effective project.

The candidate is persistent across host restarts. Boot probing runs without
channel, scheduler or action consumers; normal task results remain raw facts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid

from .config import ROOT
from .sandbox import Sandbox
from .state import COLLECTIONS, Conflict, Denied, now


DEVELOPMENT_TOOLS = [
    {'name':'development_files','description':'Inspect the persistent candidate connected to this Asuna project.', 'parameters':{}},
    {'name':'development_read','description':'Read a UTF-8 project file from the candidate.',
     'parameters':{'path':{'type':'string','required':True}}},
    {'name':'development_write','description':'Write a UTF-8 project file in the candidate; changes are not active until publish.',
     'parameters':{'path':{'type':'string','required':True},'text':{'type':'string','required':True},'overwrite':{'type':'boolean'}}},
    {'name':'development_run','description':'Run a command in the candidate and return raw stdout, stderr and exit status, including failures.',
     'parameters':{'argv':{'type':'array','items':{'type':'string'},'required':True}}},
    {'name':'development_database_read','description':'Read unredacted records from the existing real Asuna database, bound to this local owner development task. No public database endpoint.',
     'parameters':{'collection':{'type':'string','required':True},
                   'filter':{'type':'object','additionalProperties':True},
                   'projection':{'type':'object','additionalProperties':True},
                   'skip':{'type':'integer'},'limit':{'type':'integer'}}},
    {'name':'development_publish','description':'Freeze this candidate, perform minimum non-consuming boot probe, and activate a bootable snapshot. Returns the actual probe result.',
     'parameters':{'reason':{'type':'string'}}},
]
DEVELOPMENT_NAMES = {tool['name'] for tool in DEVELOPMENT_TOOLS}
ROOT_FILES = ('pyproject.toml','uv.lock','package.json','package-lock.json',
              'start-asuna-ui.cmd','README.md','RUN_ASUNA.md','RUNTIME_API.md')
SOURCE_DIRS = ('src','config','dsh-plugin','tests','tools','migrations','docs','examples')
# The restart entry and this minimal publisher remain outside the editable
# candidate. It can improve the product, including host implementation.
PROTECTED = {'start-asuna.cmd','src/asuna/development.py','config/local.json',
             'config/asuna-channel.local.json','config/integration.local.json'}


def protected(name):
    return name in PROTECTED or name.startswith('config/') and name.endswith('.models.local.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DevelopmentWorkspace:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.base = ROOT / '.runtime' / 'adr007'
        self.candidate = ROOT / '.runtime' / 'work' / 'self-development' / 'project'
        self.baseline_path = self.base / 'baseline.json'
        self.lock = threading.RLock()

    def _project_files(self):
        rows = []
        for directory in SOURCE_DIRS:
            top = ROOT / directory
            if top.exists():
                rows.extend(p for p in top.rglob('*') if p.is_file() and not p.is_symlink()
                            and not any(part in ('.runtime','__pycache__','node_modules','.venv') for part in p.parts)
                            and not p.name.endswith('.pyc'))
        rows.extend(ROOT / name for name in ROOT_FILES if (ROOT / name).is_file())
        return sorted({p.relative_to(ROOT).as_posix():p for p in rows}.items())

    def ensure(self):
        with self.lock:
            if self.baseline_path.exists():
                if not self.candidate.is_dir():raise RuntimeError('DEVELOPMENT_CANDIDATE_MISSING')
                baseline=json.loads(self.baseline_path.read_text(encoding='utf-8'))
                # External host edits become part of the effective project.
                # Preserve any unpublished candidate edit; publication will
                # report a real conflict if both sides changed the same file.
                current=dict(self._project_files())
                refreshed=False
                for relative,source in current.items():
                    target=self.candidate/relative
                    previous=baseline.get(relative)
                    if (previous is not None and (not target.is_file() or digest(target)!=previous)) or (
                            previous is None and target.exists()):
                        continue
                    latest=digest(source)
                    if latest!=previous or not target.is_file():
                        target.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(source,target)
                        baseline[relative]=latest
                        refreshed=True
                for relative in list(baseline):
                    if relative not in current:
                        target=self.candidate/relative
                        if target.is_file() and digest(target)==baseline[relative]:
                            target.unlink()
                            del baseline[relative]
                            refreshed=True
                if refreshed:
                    temporary=self.baseline_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(baseline,ensure_ascii=False,sort_keys=True),encoding='utf-8')
                    os.replace(temporary,self.baseline_path)
                return baseline
            self.base.mkdir(parents=True, exist_ok=True)
            self.candidate.mkdir(parents=True, exist_ok=True)
            baseline = {}
            for relative, source in self._project_files():
                target = self.candidate / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                baseline[relative] = digest(source)
            temporary = self.baseline_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(baseline,ensure_ascii=False,sort_keys=True),encoding='utf-8')
            os.replace(temporary,self.baseline_path)
            return baseline

    def _path(self, relative):
        if not isinstance(relative,str) or not relative or Path(relative).is_absolute() or '\\' in relative:
            raise Denied('DEVELOPMENT_PATH_DENIED')
        p = (self.candidate / relative).resolve()
        if not p.is_relative_to(self.candidate.resolve()) or protected(p.relative_to(self.candidate).as_posix()):
            raise Denied('DEVELOPMENT_PATH_DENIED')
        return p

    def _candidate_files(self):
        return {p.relative_to(self.candidate).as_posix():p for p in self.candidate.rglob('*')
                if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(self.candidate.resolve())
                and not any(part in ('.runtime','__pycache__','node_modules','.venv')
                                           for part in p.relative_to(self.candidate).parts)}

    def call(self, task, tool, args):
        if not task.get('development_grant') or (task['scene_id'],task['requester_id']) != (
                self.config['chat']['scene_id'],self.config['chat']['person_id']):
            raise Denied('DEVELOPMENT_GRANT_REQUIRED')
        with self.lock:
            baseline = self.ensure()
            if tool == 'development_files':
                files = self._candidate_files()
                lineage=list(self.store.db.sink_receipts.find({'kind':'self_development_publish'},
                    {'candidate':1,'state':1,'changed_files':1,'deleted_files':1,'published_at':1,
                     'activated_at':1,'reason':1}).sort('published_at',-1).limit(8))
                return {'candidate':str(self.candidate),
                        'files':[{'path':name,'sha256':digest(path),'changed':digest(path)!=baseline.get(name)}
                                 for name,path in sorted(files.items())],
                        'deleted':[name for name in baseline if name not in files],
                        'publish_lineage':lineage}
            if tool == 'development_read':
                path=self._path(args.get('path'))
                if path.stat().st_size>262144:raise ValueError('DEVELOPMENT_READ_LIMIT')
                return {'path':args['path'],'text':path.read_text(encoding='utf-8'),'sha256':digest(path)}
            if tool == 'development_write':
                path=self._path(args.get('path'))
                if not isinstance(args.get('text'),str) or len(args['text'].encode())>1048576:
                    raise ValueError('DEVELOPMENT_WRITE_LIMIT')
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('w' if args.get('overwrite') else 'x',encoding='utf-8') as out:out.write(args['text'])
                return {'path':args['path'],'sha256':digest(path),'written':True}
            if tool == 'development_run':
                argv=args.get('argv')
                if not isinstance(argv,list) or not argv or not all(isinstance(a,str) for a in argv):
                    raise ValueError('DEVELOPMENT_ARGV_INVALID')
                if len(argv)>50 or sum(map(len,argv))>16000:raise ValueError('DEVELOPMENT_ARGV_LIMIT')
                try:
                    return Sandbox(self.candidate,allowed_root=self.candidate).run(argv)
                except TimeoutError as exc:
                    return {'argv':argv,'exit_code':None,'stdout':'','stderr':str(exc),'timed_out':True}
            if tool == 'development_database_read':
                collection=args.get('collection')
                if collection not in COLLECTIONS:raise Denied('DEVELOPMENT_COLLECTION_DENIED')
                query=args.get('filter',{})
                projection=args.get('projection')
                skip=args.get('skip',0);limit=args.get('limit',20)
                if not isinstance(query,dict) or projection is not None and not isinstance(projection,dict):
                    raise ValueError('DEVELOPMENT_QUERY_INVALID')
                if type(skip) is not int or skip<0 or type(limit) is not int or not 1<=limit<=50:
                    raise ValueError('DEVELOPMENT_PAGE_INVALID')
                rows=list(self.store.db[collection].find(query,projection).skip(skip).limit(limit))
                serialized=json.dumps(rows,ensure_ascii=False,default=str)
                if len(serialized.encode())>262144:raise ValueError('DEVELOPMENT_PAGE_TOO_LARGE')
                return {'database':self.store.name,'collection':collection,'skip':skip,'limit':limit,'rows':rows}
            if tool == 'development_publish':
                return self.publish(task,args.get('reason',''))
            raise Denied('UNKNOWN_DEVELOPMENT_TOOL')

    def publish(self, task, reason=''):
        if self.store.db.sink_receipts.find_one({'kind':'self_development_publish','state':'APPLIED'}):
            raise Conflict('PREVIOUS_PUBLISH_AWAITING_HOST_RESTART')
        baseline=self.ensure()
        files=self._candidate_files()
        changed=sorted(name for name,path in files.items() if digest(path)!=baseline.get(name))
        deleted=sorted(name for name in baseline if name not in files)
        if not changed and not deleted:return {'state':'NO_CHANGES'}
        if any(protected(name) for name in [*changed,*deleted]):raise Denied('DEVELOPMENT_FLOOR_PROTECTED')
        for name in [*changed,*deleted]:
            current=ROOT/name
            current_hash=digest(current) if current.exists() else None
            if current_hash!=baseline.get(name):
                raise Conflict('EFFECTIVE_PROJECT_CHANGED: '+name)
        identity=hashlib.sha256(json.dumps({name:digest(path) for name,path in sorted(files.items())},
                                           sort_keys=True).encode()).hexdigest()
        receipt_id='self-publish-'+identity[:32]
        previous=self.store.db.sink_receipts.find_one({'_id':receipt_id})
        if previous:return {'state':previous['state'],'candidate':identity,'receipt_id':receipt_id,
                            'boot_probe':previous.get('boot_probe')}
        frozen=self.base/'frozen'/identity
        if not frozen.exists():
            frozen.mkdir(parents=True)
            for name,path in files.items():
                target=frozen/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        probe=self._boot_probe(frozen)
        if probe['exit_code']!=0:
            return {'state':'BOOT_FAILED','candidate':identity,'changed_files':changed,
                    'boot_probe':probe,'activated':False}
        for name in deleted:(ROOT/name).unlink()
        for name in changed:
            target=ROOT/name;target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.adr007-'+uuid.uuid4().hex+'.tmp')
            shutil.copy2(frozen/name,temporary);os.replace(temporary,target)
        receipt=self.store.put('sink_receipts',{'_id':receipt_id,'scope_key':task['scope_key'],
            'task_id':task['_id'],'intent_revision':task['intent_revision'],'kind':'self_development_publish',
            'state':'APPLIED','candidate':identity,'changed_files':changed,'deleted_files':deleted,
            'reason':reason if isinstance(reason,str) else '', 'boot_probe':probe,
            'published_at':now()},stream=task['_id'])
        # The next candidate starts from the activated effective source. A new
        # copy is made only after this exact snapshot has been applied.
        updated={name:digest(path) for name,path in files.items()}
        temporary=self.baseline_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(updated,sort_keys=True),encoding='utf-8')
        os.replace(temporary,self.baseline_path)
        return {'state':'APPLIED_AWAITING_RESTART','candidate':identity,'receipt_id':receipt['_id'],
                'changed_files':changed,'boot_probe':probe,'activated':False}

    def _boot_probe(self, frozen):
        script='''import json,sys
sys.path.insert(0,sys.argv[1]+'/src')
from asuna.state import Store
from asuna.context import ContextBuilder
from asuna.coordinator import Coordinator
from asuna.tasks import TaskService,ToolBroker
from asuna.chat import Chat
from asuna.host import RuntimeHost
from asuna.development import DevelopmentWorkspace
config=json.load(sys.stdin)
config['task_mode']='workspace'
store=Store(config)
try:
 store.db.command('ping')
 store.authorize(config['chat']['scene_id'],config['chat']['person_id'])
 ContextBuilder(store)
 Coordinator(store,None)
 service=TaskService(store);broker=ToolBroker(service);broker.close()
 DevelopmentWorkspace(config,store)
 print(json.dumps({'core':'started','database':'reachable','role_action':'constructible','publish_path':'reachable','live_consumers':'none'}))
finally:store.client.close()
'''
        command=[str(ROOT/'.venv/Scripts/python.exe'),'-c',script,str(frozen)]
        try:
            done=subprocess.run(command,cwd=frozen,capture_output=True,timeout=45,
                                input=json.dumps(self.config,ensure_ascii=False),
                                encoding='utf-8',errors='replace')
            return {'exit_code':done.returncode,'stdout':done.stdout[-8192:],
                    'stderr':done.stderr[-8192:],'timed_out':False}
        except subprocess.TimeoutExpired as exc:
            return {'exit_code':None,'stdout':str(exc.stdout or '')[-8192:],
                    'stderr':str(exc.stderr or '')[-8192:],'timed_out':True}
