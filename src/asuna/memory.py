"""Her written memory: `commit_understanding` saves the understanding of a person she writes in a turn, `chunk`
cuts chat lines into memory units for recall, in each conversation up to its mark (`chunk_marks`, before which every
line is settled), and `rollback` is the operator's audited undo.

Every write goes through the store's revision check. role_tools.py, memory_indexer.py and `asuna rollback` call it.
"""
from __future__ import annotations
import copy
from datetime import datetime,timedelta,timezone
from . import clock
from .config import character_id
from .evidence import canonical,sha
from .state import Store,Denied,Conflict,now
from .queue import database_effects_lock
from .records import messages as message_records
from . import summary_attribution
from .records import scenes as scene_records
from .records import memories as memory_records
from .records import heads as head_records

try:                                  # 跨场景只读联动（A2）：关系记录落在哪一份由配置决定
    from . import scene_links
except Exception:
    scene_links = None



NOT_THIS_SCENE = 'UNDERSTANDING_SCOPE_PROMOTION_DENIED: 这份理解不属于这个对话（不是你的错）；重试也一样，下回合再更新'


class MemoryService:
    def __init__(self,store:Store):self.store=store

    # 后台低优先级摘要由程序写入，没有 episode_id，所以不能按"谁写的"放行，只能按
    # "本轮是否真的展示给过角色 + 现在仍是当前 scope/纪元的 active 条目"重读复核。
    UNDERSTANDING_AUTO_SOURCES=('dialogue_summary',)

    def commit_understanding(self,episode,body,layer='here',person_id=None,short=None,base=None):
        """Commit bounded role-authored prose using the existing revision/CAS path: the here layer (this
        conversation's record) or the person layer (one record for the person, understanding.py).

        `person_id`: whom it is about (default the turn's person); `short`: her one line for herself, saved in the
        same revision (ADR-082); `base`: the revisions this turn showed her of that person ({'here', 'person'}, from a
        recall), in place of the turn's own projection. A body of 「不更新」 with a short keeps the body as shown and
        changes only the short."""
        person_id=person_id or episode['person_id']
        own=person_id==episode['person_id']
        scope=episode['scope_key'];operation=episode['_id']+(':understanding' if layer=='here' else ':understanding:person')+('' if own else ':'+person_id)
        scene=scene_records.authorize(self.store, episode['scene_id'], episode['person_id'])
        if (scene['scope_key'],scene['policy_epoch'])!=(scope,episode['policy_epoch']):
            raise Denied('UNDERSTANDING_SCOPE_OR_EPOCH_CHANGED: 这个对话的授权刚变过（不是你的错），这次理解存不了；重试也一样，下回合再更新')
        if body.strip()=='不更新' and short is None:
            result={'state':'NO_CHANGE'}
        elif layer=='person':
            result=self._commit_person(episode,body,scope,operation,person_id,short,base)
        else:
            entity='relationship:'+person_id
            target_scope,linked=scope,[]
            if scene_links:
                target=scene_links.relationship_target(self.store.config,self.store,scene,person_id)
                entity,target_scope,linked=target['entity'],target['scope'],list(target['linked_scopes'])
            # 本轮上下文里给她看的那一份优先（manifest 记的是她实际读到的 head）；但它只能是本场景
            # 那一份，或配置认定同一个人时的那一份——别的都算越权，不给「看起来连着」的错写。
            key=(episode['manifest'].get('relationship_entity_key') if own and base is None else None) or (entity+'|'+target_scope)
            if key not in {entity+'|'+target_scope,'relationship:'+person_id+'|'+scope}:
                raise Denied(NOT_THIS_SCENE)
            entity,_,target_scope=key.rpartition('|')
            if target_scope!=scope and (not linked or scope not in linked
                                        or not entity.startswith('relationship:')):
                raise Denied(NOT_THIS_SCENE)
            base_id=(base or {}).get('here') if base is not None else episode['manifest']['relationship_revision']
            found=head_records.revision(self.store,base_id,entity=key) if base_id else None
            # No record yet (everyone starts with none): her first understanding creates it.
            if base_id and not found:raise Denied('UNDERSTANDING_BASE_NOT_IN_CONTEXT: 这回合看到的那份理解已经找不到了（不是你的错）；重试也一样，下回合再更新')
            content=self._content(found,body,short)
            if content is None:
                result={'state':'NO_CHANGE'}
            else:
                sources,auto,skipped,stale=self._understanding_sources(episode,scope,person_id)
                try:
                    revision=head_records.mutate(self.store,entity,target_scope,base_id,content,sources,scope,operation,
                        linked_scopes=linked,
                        reason='角色基于本轮真实输入、独白与本轮展示给角色的程序摘要形成的理解；来源由程序关联。',
                        change_class='interpretation')
                except Conflict as exc:
                    # 头版本被同一轮更早的提交推前，或这条摘要覆盖的原文早已进入
                    # processed_source_ids：那是"没有可提交的新证据"，不是协议错误。
                    # 记审计后让本轮继续说话，不把整轮打成 FAILED_RUNTIME。
                    result={'state':'NOT_COMMITTED','entity':entity,'target_scope':target_scope,'base_revision':base_id,
                        'reason':str(exc),'body':content['body'],'source_ids':sources,'auto_source_ids':auto,
                        'auto_source_skipped':skipped,'auto_stale_source_ids':stale}
                else:
                    result={'state':'COMMITTED','entity':entity,'target_scope':target_scope,'base_revision':base_id,
                        'accepted_revision':revision['_id'],'body':content['body'],'source_ids':sources,
                        'auto_source_ids':auto,'auto_source_skipped':skipped,
                        'auto_stale_source_ids':stale}
        self.store.audit(episode['_id'],'understanding.result',{**result,'layer':layer,'person_id':person_id},scope)
        return result

    @staticmethod
    def _content(base,body,short):
        """The new content of a layer, or None when nothing changes. 「不更新」 keeps the shown body and changes the
        short (there must be a body to keep)."""
        old=(base or {}).get('content') or {}
        if body.strip()=='不更新':
            if not base:
                raise Denied('UNDERSTANDING_NOTHING_TO_KEEP: 这一层还没写过，没有正文可以留着；content 写完整的正文')
            body=old.get('body') or ''
        elif not body.strip():
            raise Denied('EMPTY_UNDERSTANDING')
        content={'body':body,**({'short':short} if short is not None else {})}
        if base and body==old.get('body') and (short is None or short==old.get('short')):
            return None
        return content

    def _commit_person(self,episode,body,scope,operation,person_id=None,short=None,base=None):
        """The person layer: written from this conversation into the person's one record, with where and when."""
        from .understanding import PERSON_SCOPE,person_entity
        person_id=person_id or episode['person_id']
        entity=person_entity(self.store.config,self.store,person_id)
        key=entity+'|'+PERSON_SCOPE if base is not None else episode['manifest'].get('person_entity_key')
        if key!=entity+'|'+PERSON_SCOPE:
            raise Denied('UNDERSTANDING_PERSON_NOT_IN_CONTEXT: 这回合没给你看他的人那层（不是你的错）；重试也一样，下回合再写')
        base_id=(base or {}).get('person') if base is not None else episode['manifest'].get('person_revision')
        found=head_records.revision(self.store,base_id,entity=key) if base_id else None
        if base_id and not found:raise Denied('UNDERSTANDING_BASE_NOT_IN_CONTEXT: 这回合看到的那份理解已经找不到了（不是你的错）；重试也一样，下回合再更新')
        content=self._content(found,body,short)
        if content is None:
            return {'state':'NO_CHANGE'}
        sources,auto,skipped,stale=self._understanding_sources(episode,scope,person_id)
        common={'entity':entity,'target_scope':PERSON_SCOPE,'base_revision':base_id,'body':content['body'],'source_ids':sources,
                'auto_source_ids':auto,'auto_source_skipped':skipped,'auto_stale_source_ids':stale}
        try:
            revision=head_records.mutate(self.store,entity,PERSON_SCOPE,base_id,content,sources,scope,operation,
                linked_scopes=[scope],change_class='interpretation',
                reason='角色在一个对话里写下的、她认为这个人在哪儿都成立的理解；来源由程序关联。',
                origin={'scene_id':episode['scene_id'],'at':now()})
        except Conflict as exc:
            return {'state':'NOT_COMMITTED','reason':str(exc),**common}
        return {'state':'COMMITTED','accepted_revision':revision['_id'],**common}

    def _understanding_sources(self,episode,scope,person_id=None):
        """本回合独白 + 本回合程序实际展示过、且确实盖到当前说话人的当前场景摘要。

        独白仍必须是本 episode 写的那条（沿用原检查，防复用旧 episode 的独白）；摘要没有
        episode_id，只能凭 manifest.selected（本轮真给角色看过）加当前 active/同 scope/同
        纪元重读，且 kind 必须在白名单里——角色自己能写的条目不在这个口子内。

        群场景里展示过的摘要可能只盖了别人的话。那种条目照样给角色看，但不许登记成
        「我对当前这个人」的关系来源：盖没盖过这个人由 summary_attribution 从真实行算，
        没盖过就把原因一起返回（进审计，不静默丢）。corrected_by 非空的摘要仍然算来源，
        但会一并记成 stale——那段转述之后有人更正过，读法由上下文说明负责。
        """
        monologue=list(episode['monologue_refs'])
        for key in monologue:
            if not memory_records.get(self.store,key,episode=episode['_id'],scope=scope,
                    epoch=episode['policy_epoch'],status='active'):
                raise Denied('UNDERSTANDING_SOURCE_NOT_CURRENT: 这回合的心里话没对上这个对话（不是你的错）；重试也一样，下回合再更新')
        auto,skipped,stale=[],[],[]
        for key in episode.get('manifest',{}).get('selected',[]):
            if key in monologue:continue
            unit=memory_records.get(self.store,key,scope=scope,epoch=episode['policy_epoch'],status='active',
                    kinds=self.UNDERSTANDING_AUTO_SOURCES)
            if not unit:continue
            covers,why=summary_attribution.covers_person(self.store,unit,person_id or episode['person_id'])
            if not covers:
                skipped.append({'id':key,'reason':why});continue
            auto.append(key)
            if unit.get('corrected_by'):stale.append(key)
        if not monologue and not auto and message_records.get(self.store, 'in-'+episode['_id'], fields=['_id']):
            # ADR-099: a turn with no thought (the model did not think) takes the line she answers, made on demand.
            self.chunk(episode['scene_id'])
            key='chunk-'+sha(canonical(['in-'+episode['_id'],2,0]))
            if memory_records.get(self.store,key,['_id'],scope=scope,status='active'):
                auto.append(key)
        if not monologue and not auto:
            raise Denied('UNDERSTANDING_NO_SOURCE: 这回合没有能挂上的来源（没有想法的记录，也没有这里的人说的话）；下回合再更新')
        return monologue+auto,auto,skipped,stale

    def rollback(self,entity,scope,target_id,base_id,operation,*,operator=False):
        """Append an audited revision; do not erase history or reapply events."""
        if not operator:raise Denied('OPERATOR_ROLLBACK_REQUIRED')
        if not entity.startswith(('relationship:','scene_affect:')):raise Denied('POLICY_ENTITY_DENIED')
        with database_effects_lock(self.store.name):
            pair=head_records.current(self.store,entity,scope)
            if not pair:raise Denied('UNKNOWN_STATE_ENTITY')
            head,current=pair;ancestors={};node=current
            for _ in range(512):
                if not node:break
                if node['_id'] in ancestors:raise Denied('REVISION_CYCLE')
                ancestors[node['_id']]=node
                node=head_records.revision(self.store,node['parent_revision_id']) if node.get('parent_revision_id') else None
            prior=head_records.by_mutation(self.store,operation)
            if prior:
                if prior.get('rollback_target')==target_id and prior.get('parent_revision_id')==base_id and prior['_id'] in ancestors:return prior
                raise Conflict('ROLLBACK_OPERATION_REUSED_OR_UNCOMMITTED')
            if current['_id']!=base_id:raise Conflict('BASE_REVISION_STALE')
            target=ancestors.get(target_id)
            if not target or target.get('status')=='tombstone' or target.get('deletion_id') or target['scope_key']!=scope:
                raise Denied('ROLLBACK_TARGET_NOT_ACTIVE_ANCESTOR')
            for source in target.get('source_ids',[]):
                memory=memory_records.get(self.store,source)
                if not memory or memory.get('status')=='tombstone' or memory['scope_key'] not in ('global-safe',scope):raise Denied('ROLLBACK_SOURCE_INVALIDATED')
            value={'_id':sha(canonical([operation,entity,scope])),'mutation_id':operation,'entity_key':head['_id'],'scope_key':scope,
                'content':copy.deepcopy(target['content']),'source_ids':target.get('source_ids',[]),'processed_source_ids':current.get('processed_source_ids',[]),
                'parent_revision_id':base_id,'rollback_target':target_id,'change_class':'operator_rollback'}
            revision=head_records.save_revision(self.store,value,stream='rollback:'+operation)
            head_records.save_head(self.store,{**head,'revision_id':revision['_id']},expected=head['revision'],stream='rollback:'+operation)
            return revision

    def chunk(self,scene_id):
        """Cut a conversation's lines after its mark into memory units for recall. A round (ADR-117 B8) reads the
        lines after the mark (records.memories.chunk_mark) in every state, chunks each settled spoken line of this
        epoch (`settled`, `spoken`; a unit whose id exists is skipped, so a lost mark only starts again from 0), and
        moves the mark to just before the first line not settled yet: a reply still on its way holds it and is chunked
        once it is delivered. The lines themselves are never written. Returns the units made."""
        scene=scene_records.get(self.store, scene_id)
        mark=memory_records.chunk_mark(self.store,scene_id)
        moment=clock.now()
        reached,held,lines=mark,False,[]
        for row in message_records.lines(self.store,scene_id,after=mark).each(fields=LINE_FIELDS):
            if not settled(row,scene['policy_epoch'],moment):
                held=True;continue
            if not held:reached=row['scene_seq']
            if spoken(row) and row.get('policy_epoch',1)==scene['policy_epoch']:lines.append(row)
        cut=[]
        for row in lines:
            # Stable per-message segments: adding another turn cannot regroup
            # old events or drop the last single message. No text is discarded.
            parts=[];part='';size=0
            for char in row.get('text') or '':
                cost=len(char.encode('utf-8'))
                if size+cost>900:parts.append(part);part='';size=0
                part+=char;size+=cost
            if part:parts.append(part)
            cut+=[(row,index,body,len(parts),'chunk-'+sha(canonical([row['_id'],2,index]))) for index,body in enumerate(parts)]
        keys=[key for *_,key in cut]
        found=set()
        for start in range(0,len(keys),EXISTS_BATCH):
            found|={unit['_id'] for unit in memory_records.many(self.store,keys[start:start+EXISTS_BATCH]).each(fields=['_id'])}
        made=[]
        for row,index,body,count,key in cut:
            if key in found:continue
            made.append(memory_records.save(self.store,{'_id':key,'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],
                'character_id':character_id(self.store.config),'kind':'chat_chunk','body_markdown':body,
                'epistemic_type':'reported_speech' if row['direction']=='inbound' else 'public_statement',
                'speaker':row['author'],'scene_seq':row['scene_seq'],'occurred_at':row.get('occurred_at',row.get('received_at')),
                'segment_index':index,'segment_count':count,'source_event_ids':[row['_id']],
                'depends_on':[row['_id']],'status':'active','embedding_status':'PENDING',
                'chunk_budget_method':'UTF8_bytes_conservative_bound','overlap_tokens':0},stream='chunk:'+scene_id))
        if reached>mark:
            memory_records.mark_chunked(self.store,scene_id,reached,clock.stamp())
        return made


# ADR-117 B8: which lines a chunk round may step past (`settled`).
TERMINAL_STATES=('DELIVERED','FAILED','CANCELLED_AFTER_FAILURE','CANCELLED_BY_HER','REDACTED')
LEFT_SETTLES=timedelta(hours=1)        # her line on its way this long counts as settled (and is not chunked)
LINE_FIELDS=['text','direction','delivery_state','author','policy_epoch','scene_seq','occurred_at','received_at',
             'receipt_at','claimed_at','queued_at']
EXISTS_BATCH=500                       # chunk ids looked up per read


def settled(row,epoch,moment):
    """Whether nothing can change any more whether this line is chunked, so a chunk round may step past it: a line
    that came in (a person's, or the program's own moment), a line of another epoch, her line delivered or in a
    terminal state (TERMINAL_STATES: failed, cancelled after a failure, cancelled by her, redacted), or her line left
    on its way (ready, queued, sending, unknown) for more than LEFT_SETTLES, from its receipt, else its claim, else
    when it was queued. Her line on its way within the hour is not, nor one that carries none of those times (a
    reply between its write and its publishing). `moment`: now, an aware datetime."""
    if row.get('policy_epoch',1)!=epoch or row.get('direction')!=message_records.OUTBOUND:
        return True
    if row.get('delivery_state') in TERMINAL_STATES:
        return True
    left=row.get('receipt_at') or row.get('claimed_at') or row.get('queued_at')
    try:
        since=datetime.fromisoformat(str(left).replace('Z','+00:00')) if left else None
    except ValueError:
        since=None
    if since is not None and since.tzinfo is None:
        since=since.replace(tzinfo=timezone.utc)
    return since is not None and moment-since>LEFT_SETTLES


def spoken(row):
    """Whether a line is chunked once settled: a person's line, or hers delivered (`message_records.said`, people
    only); never the program's own line, never a redacted one."""
    if row.get('author')==message_records.PROGRAM_AUTHOR or row.get('delivery_state')=='REDACTED':
        return False
    return row.get('direction')==message_records.INBOUND or (row.get('direction')==message_records.OUTBOUND
                                                             and row.get('delivery_state')==message_records.DELIVERED)
