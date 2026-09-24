#!/usr/bin/env python3
'''P2 闭环最小片的可重放补丁：只改 memory.py 的写入腿与 context.py 的读取腿。

用法：python3 tools/p2_apply_patch.py [--check]
先全部校验（每处原文必须唯一命中），任何一处对不上就一处都不落盘。
'''
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRY = '--check' in sys.argv
EDITS = []


def edit(path, old, new, note):
    EDITS.append((ROOT / path, old, new, note))


AUTO_ATTR = '''    # 后台低优先级摘要由程序写入，没有 episode_id，所以不能按"谁写的"放行，只能按
    # "本轮是否真的展示给过角色 + 现在仍是当前 scope/纪元的 active 条目"重读复核。
    UNDERSTANDING_AUTO_SOURCES=('dialogue_summary',)

'''

OLD_BODY = '''            else:
                sources=episode['monologue_refs']
                for key in sources:
                    if not self.store.db.memory_units.find_one({'_id':key,'episode_id':episode['_id'],
                            'scope_key':scope,'policy_epoch':episode['policy_epoch'],'status':'active'}):
                        raise Denied('UNDERSTANDING_SOURCE_NOT_CURRENT')
                content={k:v for k,v in base['content'].items() if k in {'body','familiarity','trust','closeness','tension'}}
                content['body']=body
                revision=self.store.mutate(entity,scope,base_id,content,sources,scope,operation,
                    reason='角色基于本轮真实输入与独白形成的理解；来源由程序关联。',change_class='interpretation')
                result={'state':'COMMITTED','entity':entity,'base_revision':base_id,
                    'accepted_revision':revision['_id'],'body':body,'source_ids':sources}
'''

NEW_BODY = '''            else:
                sources,auto=self._understanding_sources(episode,scope)
                content={k:v for k,v in base['content'].items() if k in {'body','familiarity','trust','closeness','tension'}}
                content['body']=body
                try:
                    revision=self.store.mutate(entity,scope,base_id,content,sources,scope,operation,
                        reason='角色基于本轮真实输入、独白与本轮展示给角色的程序摘要形成的理解；来源由程序关联。',
                        change_class='interpretation')
                except Conflict as exc:
                    # 头版本被同一轮更早的提交推前，或这条摘要覆盖的原文早已进入
                    # processed_source_ids：那是"没有可提交的新证据"，不是协议错误。
                    # 记审计后让本轮继续说话，不把整轮打成 FAILED_RUNTIME。
                    result={'state':'NOT_COMMITTED','entity':entity,'base_revision':base_id,
                        'reason':str(exc),'body':body,'source_ids':sources,'auto_source_ids':auto}
                else:
                    result={'state':'COMMITTED','entity':entity,'base_revision':base_id,
                        'accepted_revision':revision['_id'],'body':body,'source_ids':sources,
                        'auto_source_ids':auto}
'''

OLD_TAIL = '''        self.store.audit(episode['_id'],'understanding.result',result,scope)
        return result
'''

NEW_TAIL = '''        self.store.audit(episode['_id'],'understanding.result',result,scope)
        return result

    def _understanding_sources(self,episode,scope):
        """本回合独白 + 本回合程序实际展示过的当前场景摘要；两者都按当前库重读。

        独白仍必须是本 episode 写的那条（沿用原检查，防复用旧 episode 的独白）；摘要没有
        episode_id，只能凭 manifest.selected（本轮真给角色看过）加当前 active/同 scope/同
        纪元重读，且 kind 必须在白名单里——角色自己能写的条目不在这个口子内。
        """
        monologue=list(episode['monologue_refs'])
        for key in monologue:
            if not self.store.db.memory_units.find_one({'_id':key,'episode_id':episode['_id'],
                    'scope_key':scope,'policy_epoch':episode['policy_epoch'],'status':'active'}):
                raise Denied('UNDERSTANDING_SOURCE_NOT_CURRENT')
        auto=[]
        for key in episode.get('manifest',{}).get('selected',[]):
            if key in monologue:continue
            if self.store.db.memory_units.find_one({'_id':key,'scope_key':scope,
                    'policy_epoch':episode['policy_epoch'],'status':'active',
                    'kind':{'$in':list(self.UNDERSTANDING_AUTO_SOURCES)}}):
                auto.append(key)
        return monologue+auto,auto
'''

edit('src/asuna/memory.py', '    def commit_understanding(self,episode,body):\n',
     AUTO_ATTR + '    def commit_understanding(self,episode,body):\n',
     '类属性：可被程序自动登记为来源的 kind 白名单')
edit('src/asuna/memory.py', OLD_BODY, NEW_BODY,
     '来源解析改走 _understanding_sources；预期冲突降级为审计过的 NOT_COMMITTED')
edit('src/asuna/memory.py', OLD_TAIL, NEW_TAIL,
     '新增 _understanding_sources：本轮独白 + 本轮展示过的摘要')

OLD_FACTS = """        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','source_event_ids','status','historical_sources','speaker','scene_seq','occurred_at','segment_index','segment_count') if k in m} for m in memories]
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
"""

NEW_FACTS = """        facts=[{k:m[k] for k in ('_id','body_markdown','epistemic_type','kind','source_event_ids','source_window','generated_at','status','historical_sources','speaker','scene_seq','occurred_at','segment_index','segment_count') if k in m} for m in memories]
        # derived_summary 显式与 public_statement 同层：它是程序按原文整理的转述，既不是
        # 角色的看法也不是人物亲口陈述。摘要没有 scene_seq/segment_index，同层内不抢位。
        facts.sort(key=lambda m:({'character_interpretation':0,'public_statement':1,'derived_summary':1,'reported_speech':2}.get(m.get('epistemic_type'),1),m.get('scene_seq',0),m.get('segment_index',0)))
"""

edit('src/asuna/context.py', OLD_FACTS, NEW_FACTS,
     '摘要进下一轮时带上 kind/覆盖区间/生成时间，排序层显式化')
edit('src/asuna/context.py',
     "角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。',\n",
     "角色后来重复旧说法，不会推翻人物已给出的更正。保留旧记录作为历史，不将再次召回当作新经历。derived_summary 是程序后台从一段原文整理出来的有界摘要：source_window 是它覆盖的 scene_seq 区间，source_event_ids 可回读原文；它只证明那段交流里说过什么，不是新的经历，也不等于任何人确认过的事实，与同一人物较新的明确陈述冲突时以陈述为准，需要细节就回读来源。',\n",
     'memory_source_rules 补 derived_summary 的读法')
edit('src/asuna/context.py',
     "                    'route':'有值得留下的理解变化时，在 DECIDE 中选择 reflect_understanding=true；程序随后让你独立反思一次并提交。无需每轮更新。'}\n",
     "                    'route':'有值得留下的理解变化时，在 DECIDE 中选择 reflect_understanding=true；程序随后让你独立反思一次并提交。无需每轮更新。本轮上下文里的 derived_summary 也会被程序一并登记成这次理解的来源（按本轮实际展示与当前场景/纪元复核，不用你填 ID）；同一批原文已经进过这条关系时，程序记为未提交并给出原因，那不算你改过自己。'}\n",
     '理解提交的能力说明补来源口径')


def main():
    # 同一文件的多处改动必须在演进的文本上依次校验：先全部试算，任一处对不上就不落盘。
    working, failed, notes = {}, [], []
    for path, old, new, note in EDITS:
        text = working.get(path) if path in working else path.read_text(encoding='utf-8')
        hits = text.count(old)
        if hits != 1:
            failed.append('%s：%s（原文命中 %d 次）' % (path.name, note, hits))
            continue
        working[path] = text.replace(old, new, 1)
        notes.append((path, note))
    if failed:
        print('\n'.join('FAIL ' + line for line in failed))
        return 1
    for path, note in notes:
        print('%s %s：%s' % ('DRY   ' if DRY else 'PATCH', path.name, note))
    if not DRY:
        for path, text in working.items():
            path.write_text(text, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
