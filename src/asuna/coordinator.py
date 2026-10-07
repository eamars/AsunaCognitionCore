"""One character turn per episode (ADR-011 §3).

An episode is one thing that happened to her: a message, an action result, an internal opportunity, a
question from the action brain. Its turn is one native DSH turn in her role session:

    ATTENDING ─(join)→ PREPARED → TURN → SPEAK_ACCEPTED → COMMITTED / WAITING_TASK
                                     ↘ COMMITTED (stay_silent) / WAITING_TASK (delegated, silent)
                                     ↘ FAILED_PROTOCOL / SUPPRESSED / INTERRUPTED

The worker prepares the turn's context (context.py); the plugin composes it into the turn's first
message. She calls `think` first, then the tools exposed for this turn (role_tools.py); each call is
run here, on this thread, while the native turn waits for its result. Every text she writes in the
turn — beside a tool call too — is what she says, in order (on a platform, each its own message); it
passes one check (answers.speech_problem) before the existing publication path sends it. A platform line
belongs to the first turn that had it in view: when that turn ends, the line gets no turn of its own
(_absorb). Everything the old DECIDE/WRITE/SELF/REFLECT stages did is now a tool call.
"""
from __future__ import annotations

from dataclasses import replace
import json
import threading

from .config import prompt_path, character_id
from .context import ContextBuilder
from .evidence import canonical, sha
from .lanes import Lane
from .publish import PublishService
from .render import episode_system
from . import answers, visibility, outbound_media, role_tools
from .state import Store, Denied, now
from .tasks import FeedbackStale, require_current_feedback
from .queue import database_effects_lock


class ProtocolFailure(RuntimeError):
    pass


# Every state a turn can be resumed from after a restart (chat.py, tasks.py, recover()).
RESUMABLE = ('ATTENDING', 'PREPARED', 'TURN', 'SPEAK_ACCEPTED', 'INTERRUPTED')
# What started a turn, for the conversation's trigger title (the client words it in the viewer's language).
TRIGGERS = {'task_feedback': 'task_result', 'consult': 'question', 'self_development': 'internal',
            'presence': 'internal', 'settlement': 'internal', 'scheduled': 'schedule', 'visit': 'visit', 'note': 'note'}


class Coordinator:
    def __init__(self, store: Store, character: Lane, *, context=None, publisher=None, crash=lambda point:None,
                 task_service=None, **_ignored):
        self.store,self.character = store,character
        self.context=context or ContextBuilder(store)
        self.publisher=publisher or PublishService(store,crash=crash)
        self.crash=crash
        self.lock=threading.RLock()
        self.scheduler=None
        self.native_session_resolver=None
        self.appraiser=None           # optional affect appraiser route; runs after commit, never inside a turn
        self.attend=None              # the relevance gate's lane (attend.py); without it every wake runs the full turn
        self.appraisals={}
        # The plugin's view of the two brains talking (native_worker.py): a collaboration entry for her
        # conversation, and a message for a running action session. Both are optional observers.
        self.on_collab=None
        self.on_action_message=None
        from .tasks import TaskService
        self.tasks=task_service or TaskService(store)
        self.tools=role_tools.RoleTools(self)

    def ingest(self, event: dict, *, persona='P1'):
        with self.lock:
            scene=self.store.authorize(event['scene_id'],event['person_id'])
            ep_id='ep-'+sha(canonical([event['scene_id'],event['event_id'],event.get('episode_kind','external')]))[:32]
            existing=self.store.db.episodes.find_one({'_id':ep_id})
            if existing:
                self.store.audit(ep_id,'ingress.deduped',{'event_id':event['event_id']},scene['scope_key'])
                return existing
            from .ingress import persist_input
            persist_input(self.store,event)
            from . import attend
            if self.attend and attend.gated(scene,event):
                # The gate first: nothing is recalled until she chooses to join (attend.py).
                ep=self.store.put('episodes',{'_id':ep_id,'scene_id':scene['_id'],'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],'source_event_id':event['event_id'],'episode_kind':event.get('episode_kind','external'),'state':'ATTENDING','persona':persona,'person_id':event['person_id'],'attend_event':event,'context':{},'manifest':{},'monologue_refs':[]},stream=ep_id)
                if scene.get('character_context'):
                    ep=self._update(ep,character_context=scene['character_context'])
                if self.native_session_resolver:
                    ep=self._update(ep,native_session_id=self._role_session(event,ep_id,scene,persona))
                return self.advance(ep_id)
            _,context,manifest=self.context.prepare(event,persona)
            self.store.audit(ep_id,'context.prepared',{'manifest':manifest,'context':context},scene['scope_key'])
            ep=self.store.put('episodes',{'_id':ep_id,'scene_id':scene['_id'],'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],'source_event_id':event['event_id'],'episode_kind':event.get('episode_kind','external'),'state':'PREPARED','persona':persona,'manifest':manifest,'context':context,'system_ref':manifest['system_ref'],'person_id':event['person_id'],'monologue_refs':[],**{k:event[k] for k in ('task_id','intent_revision','delegation_depth') if k in event}},stream=ep_id)
            if scene.get('character_context'):
                ep=self._update(ep,character_context=scene['character_context'])
            if event.get('native_session_id') or self.native_session_resolver:
                ep=self._update(ep,native_session_id=self._role_session(event,ep_id,scene,persona))
            return self.advance(ep_id)

    def _binding(self, ep):
        binding=f"{character_id(self.store.config)}:{ep['scene_id']}:{ep['policy_epoch']}:{ep['persona']}"
        return binding+':'+ep['character_context'] if ep.get('character_context') else binding

    def _role_session(self, event, ep_id, scene, persona):
        """The native role session this turn runs in; same rule as native binding."""
        if event.get('native_session_id'):
            return event['native_session_id']
        proto={'_id':ep_id,'scene_id':scene['_id'],'scope_key':scene['scope_key'],'person_id':event['person_id'],'persona':persona,
               'policy_epoch':scene['policy_epoch'],**({'character_context':scene['character_context']} if scene.get('character_context') else {}),
               **{k:event[k] for k in ('task_id',) if k in event}}
        return self.native_session_resolver(proto)

    def _update(self, ep, **changes):
        return self.store.put('episodes',{**ep,**changes},expected=ep['revision'],stream=ep['_id'])

    # ── the action brain asks her (ask_character) ────────────────────
    def consult(self, task, call_key, args):
        """One internal turn in her role session: she answers the action brain with answer_action.

        No publication, no task claim, no new authority. Serialized with her other turns; the action
        brain's tool waits for the answer, never holding the task/effects lock (tasks.py).
        """
        if set(args)-{'question','context'} or not isinstance(args.get('question'),str) or not args['question'].strip():
            raise ValueError('CONSULT_QUESTION_REQUIRED')
        if not isinstance(args.get('context',''),str):raise ValueError('CONSULT_CONTEXT_MUST_BE_TEXT')
        with self.lock:
            self.tasks.valid(task)
            scene=self.store.authorize(task['scene_id'],task['requester_id'])
            original=self.store.db.episodes.find_one({'_id':task['episode_id'],
                'scene_id':task['scene_id'],'person_id':task['requester_id'],
                'scope_key':task['scope_key'],'policy_epoch':task['policy_epoch']})
            if not original or scene['scope_key']!=task['scope_key']:raise Denied('CONSULT_CONTEXT_UNAVAILABLE')
            source=self.store.db.messages.find_one({'_id':task['raw_input_refs'][0],
                'scene_id':task['scene_id'],'scope_key':task['scope_key'],'policy_epoch':task['policy_epoch']})
            if not source:raise ValueError('CONSULT_SOURCE_MISSING')
            question=args['question'].strip()
            self.collab(task,'question',{'from':'action','text':question},entry_id='q:'+call_key)
            ep_id='ep-'+sha(canonical([task['scene_id'],call_key,'consult']))[:32]
            ep=self.store.db.episodes.find_one({'_id':ep_id})
            if not ep:
                event={'event_id':call_key,'scene_id':task['scene_id'],'person_id':task['requester_id'],
                    'text':question,'episode_kind':'consult','task_id':task['_id'],
                    'trusted_context_events':[{'kind':'action_question','task':task['_id'],'title':task.get('title') or task['goal'],
                        'brief':task.get('brief') or task['goal'],'original_input':source['text'],'question':question,
                        'action_context':args.get('context','')}]}
                if source.get('event',{}).get('group_context'):event['group_context']=source['event']['group_context']
                _,context,manifest=self.context.prepare(event,original['persona'])
                ep=self.store.put('episodes',{'_id':ep_id,'scene_id':scene['_id'],'scope_key':scene['scope_key'],
                    'policy_epoch':scene['policy_epoch'],'source_event_id':call_key,'episode_kind':'consult',
                    'state':'PREPARED','persona':original['persona'],'person_id':task['requester_id'],
                    'manifest':manifest,'context':context,'system_ref':manifest['system_ref'],'monologue_refs':[],
                    'task_id':task['_id'],'native_session_id':original.get('native_session_id'),
                    **({'character_context':original['character_context']} if original.get('character_context') else {})},
                    stream=ep_id)
            if ep['state']!='COMMITTED':
                ep=self._turn(ep)
            if ep['state']!='COMMITTED' or not ep.get('answer'):
                raise ProtocolFailure('CONSULT_NOT_ANSWERED: '+str(ep.get('failure') or ep['state']))
            self.collab(task,'answer',{'from':'character','text':ep['answer']},entry_id='a:'+call_key)
            return {'answer':ep['answer'],'kind':'character_interpretation','internal':True,
                'context_diagnostics':{k:ep['context'][k] for k in ('retrieval_diagnostic_from_host',) if k in ep['context']}}

    # ── one turn ────────────────────────────────────────────────────
    def _notice(self, ep):
        """The turn's first message: the prepared context and this turn's instruction."""
        kind=role_tools.turn_kind(ep)
        instruction=prompt_path(self.store.config,'turn.md').read_text(encoding='utf-8')
        extra=prompt_path(self.store.config,'turn_consult.md').read_text(encoding='utf-8') if kind=='consult' else ''
        if ep.get('resume_diagnostic'):
            extra+='\n宿主上次中断了这一回合（不是新的用户指令；继续原来的事）：'+ep['resume_diagnostic'][:1200]
            done=[call['tool'] for call in sorted((ep.get('tool_calls') or {}).values(),key=lambda c:c['seq']) if 'result' in call]
            if done:
                extra+='\n这一回合中断前已经生效的工具调用（不用再做一遍）：'+'、'.join(done)
            tasks=[row for row in self.store.db.tasks.find({'_id':{'$in':ep.get('task_ids') or []}},{'title':1,'goal':1})]
            if tasks:
                extra+='\n这一回合中断前已经交给行动脑的事（不要再交一遍）：'+'、'.join(
                    '「%s」（%s）'%(row.get('title') or row.get('goal'),row['_id']) for row in tasks)
        return instruction+('\n'+extra if extra else '')

    @staticmethod
    def _operation(ep_id, generation):
        return ep_id+':TURN'+(':resume:'+str(generation) if generation else '')

    def _turn(self, ep):
        """Run (or resume) the episode's native turn until she speaks, stays silent or answers."""
        try:
            return self._run_turn(ep)
        finally:
            # The native turn waits after each stage for another one (a repair note); tell it there is none.
            done=getattr(self.character,'turn_done',None)
            if done:
                done(self.store.db.episodes.find_one({'_id':ep['_id']}) or ep)

    def _run_turn(self, ep):
        kind=role_tools.turn_kind(ep)
        names=role_tools.exposed(self.store,ep)
        generation=int(ep.get('turn_generation') or 0)
        fresh=ep['state']=='PREPARED'
        changes={}
        if not fresh:
            # A native turn whose result was saved (its lane receipt) is replayed from it, never generated
            # again; one that never finished, or failed its checks, runs again as a new native turn.
            if ep['state']=='FAILED_PROTOCOL' or not self.store.db.lane_receipts.find_one({'_id':self._operation(ep['_id'],generation)}):
                generation+=1
            # delegate saves its task before the call is recorded: a task this episode made is its own.
            made=[row['_id'] for row in self.store.db.tasks.find({'episode_id':ep['_id']},{'_id':1})]
            changes['task_ids']=[*dict.fromkeys([*(ep.get('task_ids') or []),*made])]
        ep=self._update(ep,state='TURN',turn_tools=names,turn_generation=generation,
                        turn_thought=False if fresh else bool(ep.get('turn_thought')),**changes)
        operation=self._operation(ep['_id'],generation)
        instruction=self._notice(ep)
        handler=lambda call_id,name,args:self.tools.call(ep['_id'],call_id,name,args)
        note=''
        seen=[]
        for attempt in range(answers.REPAIRS+1):
            value=self._deliver(ep,operation if not attempt else operation+':fix-'+str(attempt),
                                instruction if not attempt else note,names,handler,first=not attempt)
            seen+=list(value.seen_inputs or ())
            ep=self.store.db.episodes.find_one({'_id':ep['_id']})
            if value.finish_reason not in answers.MODEL_FINISHES:
                # Not her mistake (a transport error after DSH's retries, an interrupted turn).
                raise ProtocolFailure('TURN_NOT_FINISHED: '+json.dumps({'finish_reason':value.finish_reason,
                    'diagnostic':value.diagnostic,'request_refs':value.request_refs},ensure_ascii=False))
            if kind=='consult' and ep.get('answer'):
                return self._update(ep,state='COMMITTED')
            speech=self._speech(ep,value)
            # stay_silent ends the turn with nothing more to say: words she already wrote in it still leave.
            if ep.get('silent') and kind!='consult' and not speech:
                if not ep.get('await_answer') or attempt:
                    self._absorb(ep,seen)
                    return self._update(ep,state='WAITING_TASK' if self._waits(ep) else 'COMMITTED',
                                        silent_reason=ep['silent']['reason'])
                # await_answer is about words she said, yet none were written (a reply left in her thinking):
                # asked once whether she meant to say something.
                ep=self._update(ep,silent=None)
                issue=answers.NOTHING_WRITTEN
            else:
                issue=answers.speech_problem(replace(value,content=speech),thought=bool(ep.get('turn_thought')),
                                             consult=kind=='consult')
                if issue is None and kind!='consult':
                    from . import stickers
                    issue=stickers.speech_problem(self.store,ep,speech)    # ADR-016: her stickers and faces
            if issue is None:
                self._absorb(ep,seen)
                return self._publish(self._update(ep,state='SPEAK_ACCEPTED',speech=speech))
            self.store.audit(ep['_id'],'turn.rejected',{'operation':operation,'attempt':attempt,'problem':issue,
                'request_refs':value.request_refs},ep['scope_key'])
            note=answers.turn_note(issue)
        raise ProtocolFailure('INVALID_TURN_OUTPUT: '+json.dumps({'problem':issue,'finish_reason':value.finish_reason,
            'request_refs':value.request_refs},ensure_ascii=False))

    def _speech(self, ep, value):
        """Every text she wrote this turn, in order; with more than one, each leaves as its own message where the
        persona allows several (speak.max_messages), else they join as paragraphs of one. A text she wrote again
        word for word (a model often restates its reply after a tool result) leaves once."""
        pieces=list(dict.fromkeys(text.strip() for text in (value.said if value.said is not None else [value.content or ''])
                                  if isinstance(text,str) and text.strip()))
        if len(pieces)<=1:
            return pieces[0] if pieces else ''
        from .persona_model import effective
        from .render import model_and_policy
        from .rhythm import SPLIT_MARKER
        model,policy=model_and_policy(self.store,ep['persona'])
        if int(effective(model,'speak.max_messages',policy) or 1)>1:
            return ('\n'+(effective(model,'speak.split_marker',policy) or SPLIT_MARKER)+'\n').join(pieces)
        return '\n\n'.join(pieces)

    def _absorb(self, ep, seen):
        """Platform lines that came into her view for the first time during this turn are hers now: she answered
        them here, or chose not to. Each still waiting for its own turn is marked, and the queue completes it
        without one (chat.py) — the same line is never answered twice."""
        own='in-'+ep['_id']
        for input_id in dict.fromkeys(seen):
            row=self.store.db.messages.find_one({'_id':input_id,'scene_id':ep['scene_id'],'direction':'inbound'})
            if not row or input_id==own or row.get('absorbed_by') or row.get('ingress_state')!='ACCEPTED':
                continue
            self.store.put('messages',{**row,'absorbed_by':ep['_id']},expected=row['revision'],stream=ep['_id'])
            self.store.audit(ep['_id'],'input.absorbed',{'input_id':input_id},ep['scope_key'])

    def _deliver(self, ep, operation, text, names, handler, *, first):
        """One delivery to her role session: the turn's notice, or the program's note in the same turn."""
        require_current_feedback(self.store, ep)
        self.store.audit(ep['_id'],'turn.started',{'operation':operation,'tools':names},ep['scope_key'])
        # A native role session composes the notice itself: what it still shows verbatim is not repeated.
        delivery=({'context':ep['context'],'tail':text,'episode_id':ep['_id']}
                  if first and getattr(self.character,'composes_context',False) else {})
        body=(json.dumps(ep['context'],ensure_ascii=False,default=str)+'\n'+text) if first and not delivery else text
        value=self.character.generate(self._binding(ep),operation,'TURN' if first else 'REPAIR',body,
                                      episode_system(self.store,ep),tools=names,handler=handler,
                                      trigger='note' if ep['context'].get('note_from_program')
                                      else TRIGGERS.get(role_tools.turn_kind(ep),'message'),**delivery)
        self.crash('after_lane_delivery')
        from .state import content_ref
        self.store.audit(ep['_id'],'turn.output',{'operation':operation,**content_ref(value.content),
            'reasoning':content_ref(value.reasoning),'finish_reason':value.finish_reason,'diagnostic':value.diagnostic,
            'request_refs':value.request_refs,'receipt':value.receipt,'delivery':value.delivery,
            **({'corrected':True} if value.corrected else {})},ep['scope_key'])
        require_current_feedback(self.store, ep)
        return value

    def _waits(self, ep):
        return any((self.store.db.tasks.find_one({'_id':task_id},{'state':1}) or {}).get('state') in ('READY','RUNNING')
                   for task_id in ep.get('task_ids') or ())

    def _publish(self, ep):
        """ADR-009 §11.1: up to speak.max_messages segments, published in order (default 1)."""
        from .persona_model import effective
        from .render import model_and_policy
        from .rhythm import split_speech, pacing, SPLIT_MARKER
        from datetime import datetime as _dt, timezone as _tz
        ep_id=ep['_id']
        model,policy=model_and_policy(self.store,ep['persona'])
        segments=split_speech(ep['speech'],effective(model,'speak.split_marker',policy) or SPLIT_MARKER,
                              effective(model,'speak.max_messages',policy) or 1)
        from . import stickers
        segments=stickers.split(segments)       # ADR-016: a sticker leaves as a message of its own
        scene=self.store.db.scenes.find_one({'_id':ep['scene_id']})
        times=pacing(segments,_dt.now(_tz.utc),effective(model,'speak.chars_per_second',policy) or 12,
                     effective(model,'speak.min_gap_s',policy) or 1,effective(model,'speak.max_gap_s',policy) or 5)
        keys=[]
        # 这一回合被程序接受的那张图（没有就 None）：只挂在第一段上，字节仍在 BlobStore，行上只写元数据。
        attach_meta=outbound_media.attachment_for_speak(ep)
        for index,segment in enumerate(segments):
            key=ep_id+':speak:'+str(index)
            keys.append(key)
            if not self.store.db.messages.find_one({'_id':key}):
                sequence=self.store.db.scenes.find_one_and_update({'_id':ep['scene_id']},{'$inc':{'sequence':1}},return_document=True)['sequence']
                row={'_id':key,'publication_key':key,'episode_id':ep_id,'scene_id':ep['scene_id'],'scene_seq':sequence,'scope_key':ep['scope_key'],'policy_epoch':ep['policy_epoch'],'text':segment,'direction':'outbound','author':character_id(self.store.config),'phase':'SPEAK','reply_to':'in-'+ep_id,'monologue_refs':ep['monologue_refs'],'delivery_state':'READY'}
                sticker=stickers.outbound(self.store,ep['persona'],segment)
                if sticker:
                    row.update(sticker)
                    stickers.sent(self.store,ep['persona'],sticker['sticker']['name'],ep['scene_id'])
                elif attach_meta and not self.store.db.messages.find_one({'episode_id':ep_id,'phase':'SPEAK',
                        'attachment':{'$exists':True},'sticker':{'$exists':False}},{'_id':1}):
                    row['attachment']=dict(attach_meta)     # her attach_image picture: on her first words
                if len(segments)>1:
                    row.update(segment_index=index,segment_count=len(segments))
                    if scene.get('channel_id'):
                        row['not_before']=times[index].isoformat()
                self.store.put('messages',row,stream=ep_id)
        for key in keys:
            published=self.publisher.publish(key)
            if published.get('delivery_state') in ('FAILED','UNKNOWN'):
                self.publisher.cancel_after(published)
                break
            if len(keys)>1:
                self.crash('after_segment_publish')
        self.crash('before_episode_commit')
        return self._update(self.store.db.episodes.find_one({'_id':ep_id}),
                            state='WAITING_TASK' if self._waits(ep) else 'COMMITTED')

    def _attend(self, ep):
        """Ask the gate (attend.py) in her per-group session; 不理 ends the episode before any recall."""
        from . import attend
        from .state import content_ref
        event=ep['attend_event']
        scene=self.store.authorize(ep['scene_id'],ep['person_id'])
        row=self.store.db.messages.find_one({'_id':'in-'+ep['_id']})
        operation=ep['_id']+':ATTEND:0'
        self.store.audit(ep['_id'],'phase.started',{'operation':operation,'phase':'ATTEND'},ep['scope_key'])
        try:
            material=attend.material(self.store,scene,event,row,ep['persona'])
            question=attend.instruction(self.store.config)+'\n'+json.dumps(material,ensure_ascii=False)
            system=attend.system(self.store,ep['persona'])
            def generate(attempt, note):
                current=operation if not attempt else operation+':fix-'+str(attempt)
                value=self.attend.generate(self._binding(ep),current,'ATTEND',note or question,system)
                self.store.audit(ep['_id'],'phase.output',{'operation':current,'phase':'ATTEND',**content_ref(value.content),
                    'finish_reason':value.finish_reason,'request_refs':value.request_refs},ep['scope_key'])
                return value
            def rejected(attempt, issue, value):
                self.store.audit(ep['_id'],'phase.rejected',{'operation':operation,'phase':'ATTEND','attempt':attempt,
                    'problem':issue,'request_refs':value.request_refs},ep['scope_key'])
            value,verdict=answers.ask(generate,attend.NEED,attend.check,rejected=rejected)
            if verdict is None:          # not the model's mistake: the gate could not answer
                verdict={'choice':'quiet','reason':'没能判断：'+value.finish_reason}
        except (Denied,ProtocolFailure):
            raise
        except answers.Rejected as exc:
            verdict={'choice':'quiet','reason':'没能判断：没有按 接话／不理 回答'}
            self.store.audit(ep['_id'],'attend.failed',{'problem':exc.problem},ep['scope_key'])
        except Exception as exc:
            # A gate that cannot answer lets the message pass quietly; it never fails the turn.
            verdict={'choice':'quiet','reason':'没能判断：'+type(exc).__name__}
            self.store.audit(ep['_id'],'attend.failed',{'error':str(exc)[:300]},ep['scope_key'])
        self.store.audit(ep['_id'],'attend.verdict',verdict,ep['scope_key'])
        if row:
            self.store.put('messages',{**row,'processing_outcome':'ATTEND_JOIN' if verdict['choice']=='join' else 'ATTEND_QUIET',
                                       'attend':verdict},expected=row['revision'],stream=ep['_id'])
        if verdict['choice']!='join':
            return self._update(ep,state='COMMITTED',attend=verdict,silent_reason='不理：'+verdict['reason'])
        _,context,manifest=self.context.prepare(event,ep['persona'])
        context['attend_from_program']='你刚才决定接这次话：'+(verdict['reason'] or '想说点什么')
        self.store.audit(ep['_id'],'context.prepared',{'manifest':manifest,'context':context},ep['scope_key'])
        return self._update(ep,state='PREPARED',attend=verdict,context=context,manifest=manifest,
                            system_ref=manifest['system_ref'])

    def advance(self, ep_id: str):
        ep=self._advance(ep_id)
        if (self.appraiser and ep.get('state') in ('COMMITTED','WAITING_TASK') and ep['_id'] not in self.appraisals
                and ep.get('episode_kind')!='consult' and (ep.get('attend') or {}).get('choice')!='quiet'):
            import threading as _threading
            worker=_threading.Thread(target=self.appraiser.run,args=(ep['_id'],),name='asuna-appraise',daemon=True)
            self.appraisals[ep['_id']]=worker
            worker.start()
        return ep

    def _advance(self, ep_id: str):
        with self.lock:
            ep=self.store.db.episodes.find_one({'_id':ep_id})
            if not ep:
                raise ValueError('EPISODE_NOT_FOUND')
            if ep['state'] in ('SUPPRESSED', 'COMMITTED'):
                return ep
            try:
                require_current_feedback(self.store, ep)
            except FeedbackStale as exc:
                return self._suppress_feedback(ep, exc)
            if self.native_session_resolver and not ep.get('native_session_id'):
                ep=self._update(ep,native_session_id=self.native_session_resolver(ep))
            if ep['state']=='FAILED_PROTOCOL' and ep.get('episode_kind')=='task_feedback':
                scene=self.store.authorize(ep['scene_id'],ep['person_id'])
                if scene['policy_epoch']!=ep['policy_epoch']:
                    raise Denied('FEEDBACK_POLICY_STALE')
                ep=self._update(ep,resume_diagnostic=ep.get('failure',''))
                self.store.audit(ep_id,'feedback.continued',{'generation':int(ep.get('turn_generation') or 0)+1},ep['scope_key'])
            if ep['state']=='INTERRUPTED':
                # Explicitly resumed role generation keeps its scene/session. Completed tools and
                # publications are not replayed: tool calls keep their recorded results.
                ep=self._update(ep,state='SPEAK_ACCEPTED' if ep.get('speech') else 'TURN',
                                resume_diagnostic=ep.get('failure','宿主中断'))
            elif ep['state']=='TURN' and not ep.get('resume_diagnostic'):
                ep=self._update(ep,resume_diagnostic='宿主重启时这一回合还没结束')
            try:
                if ep['state']=='ATTENDING':
                    ep=self._attend(ep)
                    if ep['state']=='COMMITTED':
                        return ep
                if ep['state'] in ('PREPARED','TURN','FAILED_PROTOCOL'):
                    ep=self._turn(ep)
                if ep['state']=='SPEAK_ACCEPTED':
                    ep=self._publish(ep)
                return ep
            except FeedbackStale as exc:
                return self._suppress_feedback(self.store.db.episodes.find_one({'_id':ep_id}), exc)
            except ProtocolFailure as exc:
                self.store.audit(ep_id,'phase.failed',{'reason':str(exc)},ep['scope_key'])
                return self._update(self.store.db.episodes.find_one({'_id':ep_id}),state='FAILED_PROTOCOL',failure=str(exc))

    def _suppress_feedback(self, ep, error):
        self.store.audit(ep['_id'], 'feedback.suppressed', {'reason': str(error)}, ep['scope_key'])
        return self._update(ep, state='SUPPRESSED', feedback_suppression=str(error))

    def recover(self):
        self.store.recover_commits()
        return [self.advance(ep['_id']) for ep in self.store.db.episodes.find(
            {'state':{'$in':['PREPARED','TURN','SPEAK_ACCEPTED']},'episode_kind':{'$ne':'consult'}})]

    # ── working with the action brain (ADR-011 §4) ──────────────────
    def _grants(self, ep):
        """(development, integration, capabilities) for a task delegated from this episode."""
        from .tasks import WORKSPACE_TOOLS, ACTION_DSH_CAPABILITIES
        from .vision import route_filtered_tool_names
        from .integration import event_granted, INTEGRATION_TOOLS
        from .grants import development_granted
        source=self.store.db.messages.find_one({'_id':'in-'+ep['_id']}) or {}
        event=source.get('event',{})
        scene=self.store.db.scenes.find_one({'_id':ep['scene_id']}) or {'_id':ep['scene_id']}
        development=ep.get('episode_kind')!='consult' and development_granted(self.store,scene,
            {**event,'episode_kind':ep.get('episode_kind'),'task_id':ep.get('task_id'),'person_id':ep['person_id']},
            (ep.get('manifest') or {}).get('session_class'))
        capabilities=list(WORKSPACE_TOOLS)
        if development:
            from .development import DEVELOPMENT_TOOLS, PERSONA_JOB_TOOLS
            capabilities+=[*DEVELOPMENT_TOOLS,*PERSONA_JOB_TOOLS]
        integration=event_granted(self.store.config,event)
        if integration:capabilities+=INTEGRATION_TOOLS
        from .image_generation import available as image_available, GENERATE_IMAGE_TOOL
        if image_available(self.store.config):capabilities.append(GENERATE_IMAGE_TOOL)
        from . import sandbox_backend, visibility
        # Running commands is for the owner's own scenes (owner 2026-10-06): the Host sandbox confines writes only,
        # so in anyone else's scene the boundary is that the tool is not given.
        if (not sandbox_backend.available(self.store.config)
                or (ep.get('manifest') or {}).get('session_class')!=visibility.OWNER_PRIVATE):
            capabilities=[tool for tool in capabilities if (tool['name'] if isinstance(tool,dict) else tool)!='sandbox_run']
        names=[*dict.fromkeys([*route_filtered_tool_names(capabilities,self.store.config),*ACTION_DSH_CAPABILITIES])]
        return development,integration,names

    def delegate(self, ep, call_id, title, brief):
        """A new task: the action brain's first message is her brief (§4)."""
        from .grants import workspace_grant
        workspace_grant(self.store.config,ep['scene_id'],ep['person_id'])
        task_id='task-'+sha(canonical([ep['_id'],call_id]))[:32]
        task=self.store.db.tasks.find_one({'_id':task_id})
        if not task:
            development,integration,names=self._grants(ep)
            source_ref=('in-'+ep['_id']) if ep.get('episode_kind')!='consult' else None
            original=self.store.db.tasks.find_one({'_id':ep.get('task_id')}) if ep.get('task_id') else None
            raw=[source_ref] if source_ref and self.store.db.messages.find_one({'_id':source_ref},{'_id':1}) else (original or {}).get('raw_input_refs',[])
            with database_effects_lock(self.store.name):
                require_current_feedback(self.store, ep)
                task=self.store.put('tasks',{'_id':task_id,'request_key':task_id,'thread':task_id,'episode_id':ep['_id'],
                    'scene_id':ep['scene_id'],'scope_key':ep['scope_key'],'requester_id':ep['person_id'],
                    'policy_epoch':ep['policy_epoch'],'persona_revision':ep['manifest']['persona_revision'],
                    'intent_revision':1,'goal':title,'title':title,'brief':brief,'constraints':[],
                    'raw_input_refs':raw,'state':'READY','fencing_token':0,'tool_steps':0,
                    'integration_profile':'owner' if integration else None,'development_grant':development,
                    'allowed_capabilities':names,'native_session_id':ep.get('native_session_id'),
                    'created_at':now()},stream=ep['_id'])
            self.crash('after_task_persist')
        fresh=self.store.db.episodes.find_one({'_id':ep['_id']})
        self._update(fresh,task_ids=[*dict.fromkeys([*(fresh.get('task_ids') or []),task_id])])
        self.collab(task,'message',{'from':'character','text':brief,'title':title},entry_id='brief:'+task_id)
        return task

    def message_action(self, ep, call_id, task, message):
        """Her words to the action brain about one task: steered into a running one, or continuing a finished one."""
        development,integration,names=self._grants(ep)
        if (bool(task.get('integration_profile'))!=bool(integration)
                or bool(task.get('development_grant')) and not development):
            # Work under the owner's grants takes words only from a turn with the same grants (ADR-011 §6.2).
            raise role_tools.Refused('这一回合的授权和原来那件事不一样，不能给它补话或接着做；要做就用 delegate 交一件新的。')
        if task['state'] in ('READY','RUNNING'):
            message_id='msg-'+sha(canonical([ep['_id'],call_id]))[:32]
            if not self.store.db.task_messages.find_one({'_id':message_id}):
                self.store.put('task_messages',{'_id':message_id,'task_id':task['_id'],'thread':task.get('thread') or task['_id'],
                    'from':'character','text':message,'episode_id':ep['_id'],'delivered':False,
                    'scope_key':task['scope_key'],'created_at':now()},stream=task['_id'])
                self.collab(task,'message',{'from':'character','text':message},entry_id=message_id)
                if self.on_action_message:
                    self.on_action_message(task,{'id':message_id,'text':message})
            return {'task':task['_id'],'state':'行动脑下一步就会看到这句话'}
        local=(ep['scene_id'],ep['person_id'])==(self.store.config['chat']['scene_id'],self.store.config['chat']['person_id'])
        source=(self.store.db.messages.find_one({'_id':'in-'+ep['_id']}) or {}).get('event',{})
        if task['state']=='STALE':
            raise role_tools.Refused('这件事正在被改，等它的新版本。')
        if task['state']=='CANCELLED' and task.get('cancel_reason')!='host_stop':
            raise role_tools.Refused('这件事已经叫停了，不能接着做；要再做就用 delegate 交一件新的。')
        if task['state']=='PAUSED' and not (ep.get('episode_kind')=='external' and local and not source.get('channel')):
            raise role_tools.Refused('这件事在重启时暂停了：只有本机主人明确要继续时才能接着做。')
        task_id='task-'+sha(canonical([ep['_id'],call_id]))[:32]
        continued=self.store.db.tasks.find_one({'_id':task_id})
        if not continued:
            binding=task.get('execution_binding') or f"task:{task['_id']}:{task['scope_key']}:{task['policy_epoch']}:{task['intent_revision']}"
            source_ref='in-'+ep['_id']
            raw=[source_ref] if self.store.db.messages.find_one({'_id':source_ref},{'_id':1}) else task['raw_input_refs']
            with database_effects_lock(self.store.name):
                require_current_feedback(self.store, ep)
                continued=self.store.put('tasks',{'_id':task_id,'request_key':task_id,'thread':task.get('thread') or task['_id'],
                    'episode_id':ep['_id'],'scene_id':ep['scene_id'],'scope_key':ep['scope_key'],'requester_id':ep['person_id'],
                    'policy_epoch':ep['policy_epoch'],'persona_revision':ep['manifest']['persona_revision'],'intent_revision':1,
                    'goal':task.get('title') or task['goal'],'title':task.get('title') or task['goal'],'brief':message,
                    'constraints':[],'raw_input_refs':raw,'state':'READY','fencing_token':0,'tool_steps':0,
                    'integration_profile':'owner' if integration else None,'development_grant':development,
                    'allowed_capabilities':names,'continues_task_id':task['_id'],'execution_binding':binding,
                    'native_session_id':task.get('native_session_id') or ep.get('native_session_id'),
                    'created_at':now()},stream=ep['_id'])
        fresh=self.store.db.episodes.find_one({'_id':ep['_id']})
        self._update(fresh,task_ids=[*dict.fromkeys([*(fresh.get('task_ids') or []),task_id])])
        self.collab(continued,'message',{'from':'character','text':message},entry_id='brief:'+task_id)
        return {'task':task_id,'continues':task['_id'],'state':'已交给行动脑，接着原来的过程做',
                'note':'结果回来会再叫你。'}

    def collab(self, task, kind, data, entry_id=None):
        """One entry of the collaboration thread in her conversation (§7.1); the plugin draws it."""
        if not self.on_collab:
            return
        try:
            self.on_collab(task,{'id':entry_id or kind+':'+sha(canonical([task['_id'],kind,data]))[:16],
                                 'kind':kind,'at':now(),**data})
        except Exception as exc:          # the thread is a view; its failure never changes the turn
            self.store.audit(task['_id'],'collab.failed',{'error':str(exc)[:300]},task['scope_key'])
