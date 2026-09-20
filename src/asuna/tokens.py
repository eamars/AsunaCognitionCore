from __future__ import annotations
import json
from .evidence import LocalHttp,sha,canonical


class TokenMeter:
    def __init__(self,cfg,evidence,lane):self.cfg,self.evidence,self.lane=cfg,evidence,lane

    def measure(self,body):
        http=LocalHttp(self.evidence)
        base=self.cfg['base_url'].removesuffix('/v1')
        try:
            if self.lane=='character':
                rendered=http.request('POST',base+'/apply-template','tokenizer.render',body)['prompt']
                tokens=http.request('POST',base+'/tokenize','tokenizer.count',{'content':rendered,'add_special':True})['tokens']
                return {'input_tokens':len(tokens),'method':'server_apply_template_and_tokenize','rendered_prompt_sha256':sha(rendered.encode()),'rendered_tokens_sha256':sha(canonical(tokens)),'exact_render_visible':True}
            messages=[];systems=[]
            for m in body['messages']:
                if m['role']=='system':systems.append(m['content']);continue
                if m['role']=='tool':
                    messages.append({'role':'user','content':[{'type':'tool_result','tool_use_id':m['tool_call_id'],'content':m['content']}]});continue
                content=[]
                if m.get('reasoning_content'):content.append({'type':'thinking','thinking':m['reasoning_content']})
                if isinstance(m.get('content'),str) and m['content']:content.append({'type':'text','text':m['content']})
                elif isinstance(m.get('content'),list):content+=m['content']
                for tool in m.get('tool_calls',[]):
                    content.append({'type':'tool_use','id':tool['id'],'name':tool['function']['name'],'input':json.loads(tool['function']['arguments'])})
                messages.append({'role':m['role'],'content':content})
            request={'model':body['model'],'messages':messages,'system':'\n\n'.join(systems),'thinking':{'type':'enabled'}}
            if body.get('tools'):request['tools']=[{'name':t['function']['name'],'description':t['function'].get('description',''),'input_schema':t['function']['parameters']} for t in body['tools']]
            count=http.request('POST',self.cfg['base_url']+'/messages/count_tokens','tokenizer.count',request)['input_tokens']
            return {'input_tokens':count,'method':'server_anthropic_count_tokens_equivalent_conversion','exact_render_visible':False,'limitation':'count conversion checked against returned usage; final server-rendered OpenAI token IDs are not exposed'}
        finally:http.client.close()

    def check(self,body,capacity_override=False):
        measured=self.measure(body)
        effective=self.cfg.get('context_window',262144)
        limit=effective-body['max_tokens']-4096
        result={**measured,'effective_capacity':effective,'output_budget':body['max_tokens'],'safety_margin':4096,'input_limit':limit,'capacity_probe_override':capacity_override}
        self.evidence.record('budget.checked',result)
        if result['input_tokens']>limit:raise ValueError('INPUT_BUDGET_EXCEEDED')
        return result
