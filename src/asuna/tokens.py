from __future__ import annotations
import json
from .evidence import LocalHttp,sha,canonical


def _without_inline_images(messages):
    """把 data: 内联图片从「按字节保守上界」里摘出去，并如实报出份数与原始字节。

    图片不是文本 token：视觉 token 由路由与 DSH 的 imageRequestPricing 定价。这里只保证
    Asuna 这条审计读数不被一坨 base64 顶成假象，不自己发明视觉 token 公式。
    """
    state = {'images': 0, 'image_bytes': 0}

    def walk(value):
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            # OpenAI 线格式（image_url.url）、Anthropic 线格式（source.data）、以及
            # 少数路由直接带 data 的写法，三种都算内联图片；其余字段照常计入字节。
            image_url = value.get('image_url')
            source = value.get('source')
            url = next((candidate for candidate in (
                image_url.get('url') if isinstance(image_url, dict) else None,
                source.get('data') if isinstance(source, dict) else None,
                value.get('data')) if isinstance(candidate, str) and candidate.startswith('data:')), None)
            if value.get('type') in ('image', 'image_url') and url is not None:
                payload = url.split(',', 1)[1] if ',' in url else url
                padding = payload.count('=') if len(payload) % 4 == 0 else 0
                state['images'] += 1
                state['image_bytes'] += (len(payload) // 4) * 3 - padding
                return {'type': value.get('type'), 'inline_image_omitted': f'{len(payload)} base64 chars'}
            return {k: walk(v) for k, v in value.items()}
        return value

    projected = walk(messages)
    return projected, {'inline_images': state['images'], 'inline_image_bytes': state['image_bytes']}


class TokenMeter:
    def __init__(self,cfg,evidence,lane):self.cfg,self.evidence,self.lane=cfg,evidence,lane

    def measure(self,body):
        counter=self.cfg.get('token_counter','conservative_bytes')
        if counter=='conservative_bytes':
            messages,images=_without_inline_images(body.get('messages',[]))
            return {'input_tokens':len(canonical({'messages':messages,'tools':body.get('tools',[])})), 'method':'UTF8_bytes_conservative_bound', 'exact_render_visible':False, **images}
        if counter not in ('llama_cpp', 'anthropic_count'):
            raise ValueError('UNKNOWN_TOKEN_COUNTER')
        http=LocalHttp(self.evidence)
        base=self.cfg['base_url'].removesuffix('/v1')
        try:
            if counter=='llama_cpp':
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
        # Observation only: DSH owns pressure compaction and provider-confirmed
        # overflow recovery. A separate preflight gate prevents both paths.
        try:
            measured=self.measure(body)
        except Exception as exc:
            measured={'input_tokens':None,'method':'unavailable','measurement_error':str(exc),'measurement_error_type':type(exc).__name__}
        effective=self.cfg.get('context_window',262144)
        output=body.get('max_completion_tokens',body.get('max_tokens',self.cfg.get('max_tokens',0)))
        limit=effective-output
        result={**measured,'effective_capacity':effective,'output_budget':output,'safety_margin':0,'input_limit':limit,'capacity_probe_override':capacity_override,'enforced':False}
        self.evidence.record('budget.checked',result)
        return result
