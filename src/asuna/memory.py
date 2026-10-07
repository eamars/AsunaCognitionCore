from __future__ import annotations
import copy
import json
from .config import character_id
from .evidence import canonical,sha
from .state import Store,Denied,Conflict
from .queue import database_effects_lock
from .ingress import NOT_CORE_NOTICE
from . import summary_attribution

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

    def commit_understanding(self,episode,body):
        """Commit bounded role-authored prose using the existing revision/CAS path."""
        scope=episode['scope_key'];operation=episode['_id']+':understanding'
        scene=self.store.authorize(episode['scene_id'],episode['person_id'])
        if (scene['scope_key'],scene['policy_epoch'])!=(scope,episode['policy_epoch']):
            raise Denied('UNDERSTANDING_SCOPE_OR_EPOCH_CHANGED: 这个对话的授权刚变过（不是你的错），这次理解存不了；重试也一样，下回合再更新')
        if body.strip()=='不更新':
            result={'state':'NO_CHANGE'}
        else:
            entity='relationship:'+episode['person_id']
            target_scope,linked=scope,[]
            if scene_links:
                target=scene_links.relationship_target(self.store.config,self.store.db,scene,episode['person_id'])
                entity,target_scope,linked=target['entity'],target['scope'],list(target['linked_scopes'])
            # 本轮上下文里给她看的那一份优先（manifest 记的是她实际读到的 head）；但它只能是本场景
            # 那一份，或配置认定同一个人时的那一份——别的都算越权，不给「看起来连着」的错写。
            key=episode['manifest'].get('relationship_entity_key') or (entity+'|'+target_scope)
            if key not in {entity+'|'+target_scope,'relationship:'+episode['person_id']+'|'+scope}:
                raise Denied(NOT_THIS_SCENE)
            entity,_,target_scope=key.rpartition('|')
            if target_scope!=scope and (not linked or scope not in linked
                                        or not entity.startswith('relationship:')):
                raise Denied(NOT_THIS_SCENE)
            base_id=episode['manifest']['relationship_revision']
            base=self.store.db.state_revisions.find_one({'_id':base_id,'entity_key':key}) if base_id else None
            # No record yet (everyone starts with none): her first understanding creates it.
            if base_id and not base:raise Denied('UNDERSTANDING_BASE_NOT_IN_CONTEXT: 这回合看到的那份理解已经找不到了（不是你的错）；重试也一样，下回合再更新')
            if not body.strip():raise Denied('EMPTY_UNDERSTANDING')
            if base and body==base['content'].get('body'):
                result={'state':'NO_CHANGE'}
            else:
                sources,auto,skipped,stale=self._understanding_sources(episode,scope)
                content={'body':body}
                try:
                    revision=self.store.mutate(entity,target_scope,base_id,content,sources,scope,operation,
                        linked_scopes=linked,
                        reason='角色基于本轮真实输入、独白与本轮展示给角色的程序摘要形成的理解；来源由程序关联。',
                        change_class='interpretation')
                except Conflict as exc:
                    # 头版本被同一轮更早的提交推前，或这条摘要覆盖的原文早已进入
                    # processed_source_ids：那是"没有可提交的新证据"，不是协议错误。
                    # 记审计后让本轮继续说话，不把整轮打成 FAILED_RUNTIME。
                    result={'state':'NOT_COMMITTED','entity':entity,'target_scope':target_scope,'base_revision':base_id,
                        'reason':str(exc),'body':body,'source_ids':sources,'auto_source_ids':auto,
                        'auto_source_skipped':skipped,'auto_stale_source_ids':stale}
                else:
                    result={'state':'COMMITTED','entity':entity,'target_scope':target_scope,'base_revision':base_id,
                        'accepted_revision':revision['_id'],'body':body,'source_ids':sources,
                        'auto_source_ids':auto,'auto_source_skipped':skipped,
                        'auto_stale_source_ids':stale}
        self.store.audit(episode['_id'],'understanding.result',result,scope)
        return result

    def _understanding_sources(self,episode,scope):
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
            if not self.store.db.memory_units.find_one({'_id':key,'episode_id':episode['_id'],
                    'scope_key':scope,'policy_epoch':episode['policy_epoch'],'status':'active'}):
                raise Denied('UNDERSTANDING_SOURCE_NOT_CURRENT: 这回合的心里话没对上这个对话（不是你的错）；重试也一样，下回合再更新')
        auto,skipped,stale=[],[],[]
        for key in episode.get('manifest',{}).get('selected',[]):
            if key in monologue:continue
            unit=self.store.db.memory_units.find_one({'_id':key,'scope_key':scope,
                    'policy_epoch':episode['policy_epoch'],'status':'active',
                    'kind':{'$in':list(self.UNDERSTANDING_AUTO_SOURCES)}})
            if not unit:continue
            covers,why=summary_attribution.covers_person(self.store,unit,episode['person_id'])
            if not covers:
                skipped.append({'id':key,'reason':why});continue
            auto.append(key)
            if unit.get('corrected_by'):stale.append(key)
        return monologue+auto,auto,skipped,stale

    def rollback(self,entity,scope,target_id,base_id,operation,*,operator=False):
        """Append an audited revision; do not erase history or reapply events."""
        if not operator:raise Denied('OPERATOR_ROLLBACK_REQUIRED')
        if not entity.startswith(('relationship:','scene_affect:')):raise Denied('POLICY_ENTITY_DENIED')
        with database_effects_lock(self.store.name):
            pair=self.store.head(entity,scope)
            if not pair:raise Denied('UNKNOWN_STATE_ENTITY')
            head,current=pair;ancestors={};node=current
            for _ in range(512):
                if not node:break
                if node['_id'] in ancestors:raise Denied('REVISION_CYCLE')
                ancestors[node['_id']]=node
                node=self.store.db.state_revisions.find_one({'_id':node['parent_revision_id']}) if node.get('parent_revision_id') else None
            prior=self.store.db.state_revisions.find_one({'mutation_id':operation})
            if prior:
                if prior.get('rollback_target')==target_id and prior.get('parent_revision_id')==base_id and prior['_id'] in ancestors:return prior
                raise Conflict('ROLLBACK_OPERATION_REUSED_OR_UNCOMMITTED')
            if current['_id']!=base_id:raise Conflict('BASE_REVISION_STALE')
            target=ancestors.get(target_id)
            if not target or target.get('status')=='tombstone' or target.get('deletion_id') or target['scope_key']!=scope:
                raise Denied('ROLLBACK_TARGET_NOT_ACTIVE_ANCESTOR')
            for source in target.get('source_ids',[]):
                memory=self.store.db.memory_units.find_one({'_id':source})
                if not memory or memory.get('status')=='tombstone' or memory['scope_key'] not in ('global-safe',scope):raise Denied('ROLLBACK_SOURCE_INVALIDATED')
            value={'_id':sha(canonical([operation,entity,scope])),'mutation_id':operation,'entity_key':head['_id'],'scope_key':scope,
                'content':copy.deepcopy(target['content']),'source_ids':target.get('source_ids',[]),'processed_source_ids':current.get('processed_source_ids',[]),
                'parent_revision_id':base_id,'rollback_target':target_id,'change_class':'operator_rollback'}
            revision=self.store.put('state_revisions',value,stream='rollback:'+operation)
            self.store.put('state_heads',{**head,'revision_id':revision['_id']},expected=head['revision'],stream='rollback:'+operation)
            return revision

    def chunk(self,scene_id):
        scene=self.store.db.scenes.find_one({'_id':scene_id})
        rows=list(self.store.db.messages.find({'scene_id':scene_id,**NOT_CORE_NOTICE,'$or':[{'direction':'inbound'},{'delivery_state':'DELIVERED'}]}).sort('scene_seq',1))
        made=[]
        for row in rows:
            if row.get('policy_epoch',1)!=scene['policy_epoch']:continue
            if row.get('memory_chunk_version')==2:continue
            # Stable per-message segments: adding another turn cannot regroup
            # old events or drop the last single message. No text is discarded.
            parts=[];part='';size=0
            for char in row['text']:
                cost=len(char.encode('utf-8'))
                if size+cost>900:parts.append(part);part='';size=0
                part+=char;size+=cost
            if part:parts.append(part)
            for index,body in enumerate(parts):
                key='chunk-'+sha(canonical([row['_id'],2,index]))
                if self.store.db.memory_units.find_one({'_id':key}):continue
                made.append(self.store.put('memory_units',{'_id':key,'scope_key':scene['scope_key'],'policy_epoch':scene['policy_epoch'],
                    'character_id':character_id(self.store.config),'kind':'chat_chunk','body_markdown':body,
                    'epistemic_type':'reported_speech' if row['direction']=='inbound' else 'public_statement',
                    'speaker':row['author'],'scene_seq':row['scene_seq'],'occurred_at':row.get('occurred_at',row.get('received_at')),
                    'segment_index':index,'segment_count':len(parts),'source_event_ids':[row['_id']],
                    'depends_on':[row['_id']],'status':'active','embedding_status':'PENDING',
                    'chunk_budget_method':'UTF8_bytes_conservative_bound','overlap_tokens':0},stream='chunk:'+scene_id))
            self.store.put('messages',{**row,'memory_chunk_version':2},expected=row['revision'],stream='chunk:'+scene_id)
        return made
