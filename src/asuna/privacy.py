"""Explicit operator erasure, with scope invalidation and auditable redaction roots."""
import copy
from pathlib import Path
import uuid
from .config import ROOT
from .evidence import canonical,sha,write_json
from .state import Denied,now


class PrivacyService:
    def __init__(self,store):self.store=store

    def delete_memory(self,key,*,operator=False,active_lanes=()):
        if not operator:raise Denied('OPERATOR_ERASURE_REQUIRED')
        db=self.store.db;memory=db.memory_units.find_one({'_id':key})
        if not memory:raise ValueError('MEMORY_NOT_FOUND')
        scope=memory['scope_key']
        if scope=='global-safe':raise Denied('GLOBAL_ERASURE_REQUIRES_ALL_SCENE_MIGRATION')
        deletion='erase-'+uuid.uuid4().hex
        self.store.audit(deletion,'privacy.intent',{'memory_id':key,'scope':scope},scope)
        scene=db.scenes.find_one({'scope_key':scope})
        self.store.put('scenes',{**scene,'policy_epoch':scene['policy_epoch']+1},expected=scene['revision'],stream=deletion)
        # Immediate fencing precedes potentially slow file cleanup.
        for lane in active_lanes:lane.close()
        sources=set(memory.get('source_event_ids',[]))|{key}
        affected={key}
        for _ in range(32):
            rows=list(db.memory_units.find({'scope_key':scope,'$or':[{'depends_on':{'$in':list(sources)}},{'source_event_ids':{'$in':list(sources)}}]}))
            new={m['_id'] for m in rows}-affected
            if not new:break
            affected|=new;sources|=new
        roots=set();session_ids=set()
        for session in db.sessions.find({'scope_key':scope}):
            roots.add(session.get('evidence_root',''));session_ids.add(session['_id'])
            home=Path(session['dsh_home']).resolve()
            if not home.is_relative_to((ROOT/'.runtime').resolve()):raise Denied('ERASURE_HOME_OUTSIDE_REPOSITORY')
            for directory in (home/'sessions').glob('**/'+session['_id']):
                directory=directory.resolve()
                if not directory.is_relative_to(home) or directory.name!=session['_id']:raise Denied('ERASURE_PATH_DENIED')
                for path in sorted(directory.rglob('*'),key=lambda p:len(p.parts),reverse=True):
                    if path.is_file():path.unlink()
                    elif path.is_dir():path.rmdir()
                directory.rmdir()
            for path in (home/'operations').glob('*.json'):
                import json
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('session')==session['_id'] or path.name=='boundary-'+session['_id']+'.json':path.unlink()
            db.sessions.update_one({'_id':session['_id']},{'$set':{'state':'INVALIDATED','deletion_id':deletion}})
        ep_ids={e['_id'] for e in db.episodes.find({'scope_key':scope},{'_id':1})}
        task_ids={t['_id'] for t in db.tasks.find({'scope_key':scope},{'_id':1})}
        for mem in db.memory_units.find({'scope_key':scope}):
            derived=mem.get('kind') in ('monologue','chat_chunk') and mem.get('episode_id') in ep_ids
            if mem['_id'] in affected or derived or mem.get('kind')=='chat_chunk':
                db.memory_units.replace_one({'_id':mem['_id']},{'_id':mem['_id'],'schema_version':1,'revision':mem['revision']+1,'scope_key':scope,'status':'tombstone','deletion_id':deletion,'body_markdown':'','source_event_ids':[],'policy_epoch':scene['policy_epoch']+1})
            else:db.memory_units.update_one({'_id':mem['_id']},{'$set':{'policy_epoch':scene['policy_epoch']+1}})
        for collection in ('episodes','tasks','messages','artifacts','sink_receipts'):
            for doc in db[collection].find({'scope_key':scope}):
                # Conservative scope erasure includes generated paraphrases and
                # unfinished work. Retain identity/state/hash, never old bodies.
                retained={k:doc[k] for k in ('_id','schema_version','revision','scope_key','scene_id','source_event_id','episode_kind','publication_key','request_key','binding_key','content_hash','scene_seq','direction','author','adapter_id','platform_event_id') if k in doc}
                retained.update(deletion_id=deletion,state='INVALIDATED',delivery_state='REDACTED',text='[deleted]',policy_epoch=scene['policy_epoch']+1)
                db[collection].replace_one({'_id':doc['_id']},retained)
        for receipt in db.lane_receipts.find({'session_id':{'$in':list(session_ids)}}):
            db.lane_receipts.replace_one({'_id':receipt['_id']},{'_id':receipt['_id'],'schema_version':1,'scope_key':'operator','state':'INVALIDATED','deletion_id':deletion})
        for head in db.state_heads.find({'scope_key':scope}):
            rev=db.state_revisions.find_one({'_id':head['revision_id']})
            while rev and rev.get('parent_revision_id'):rev=db.state_revisions.find_one({'_id':rev['parent_revision_id']})
            if rev and not(set(rev.get('source_ids',[]))&sources):
                db.state_heads.update_one({'_id':head['_id']},{'$set':{'revision_id':rev['_id'],'revision':head['revision']+1}})
            else:db.state_heads.delete_one({'_id':head['_id']})
        active_revisions={h['revision_id'] for h in db.state_heads.find({'scope_key':scope})}
        for rev in db.state_revisions.find({'scope_key':scope,'_id':{'$nin':list(active_revisions)}}):
            db.state_revisions.update_one({'_id':rev['_id']},{'$set':{'content':{},'source_ids':[],'status':'tombstone','deletion_id':deletion}})
        # Intentional erasure is a declared chain rebase, not a claim that the
        # original chain still verifies. Preserve old terminal hashes only.
        previous_roots={};new_roots={}
        for stream in db.audit_events.distinct('stream_id'):
            previous='0'*64
            events=list(db.audit_events.find({'stream_id':stream}).sort('seq',1))
            previous_roots[stream]=events[-1]['event_hash']
            for event in events:
                if event['scope_key']==scope or any(stream==key or stream.startswith(key+':') for key in ep_ids|task_ids) or any(sid in str(event.get('payload',{})) for sid in session_ids):
                    event['payload']={'redacted_by':deletion,'previous_payload_sha256':sha(canonical(event['payload']))}
                event['prev_hash']=previous;event.pop('event_hash');event['event_hash']=sha(canonical(event));previous=event['event_hash']
                db.audit_events.replace_one({'_id':event['_id']},event)
            new_roots[stream]=previous
        removed_files=0
        for root in roots:
            if not root:continue
            path=Path(root).resolve()
            if not path.is_relative_to((ROOT/'reports').resolve()) or path==ROOT/'reports':raise Denied('ERASURE_EVIDENCE_ROOT_DENIED')
            for item in path.rglob('*'):
                if item.is_file():item.unlink();removed_files+=1
            write_json(path/'erasure.json',{'deletion_id':deletion,'scope_key':scope,'reason':'conservative removal of the affected run evidence containing raw requests','previous_audit_roots':previous_roots})
        result={'deletion_id':deletion,'scope_key':scope,'memory_ids':sorted(affected),'policy_epoch':scene['policy_epoch']+1,'invalidated_sessions':sorted(session_ids),'evidence_files_removed':removed_files,'old_roots':previous_roots,'new_roots':new_roots,'limitations':['global-safe deletion currently rejected','scope-wide generated content and affected run evidence are conservatively erased','previously downloaded exports and external backups cannot be recalled; backup retention not configured']}
        self.store.audit(deletion,'privacy.completed',result,'operator')
        return result
