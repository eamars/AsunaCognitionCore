"""Explicit debug replay: real HTTP/Mongo/group routing, fake model, no QQ sends."""
import json
import sys
import uuid
from types import SimpleNamespace

import httpx

from asuna.channels import Channels, ChannelServer
from asuna.chat import Chat
from asuna.config import ROOT, load
from asuna.coordinator import Coordinator
from asuna.evidence import Evidence, write_json
from asuna.host import prepare_channels
from asuna.lanes import FakeLane, LaneResult
from asuna.resources import workspace_grant
from asuna.router import Router
from asuna.state import Store
from asuna.ui import Workbench, UiBridge
from asuna.context import ContextBuilder
from asuna.sandbox import Sandbox
from asuna.state import Denied


def main():
    if sys.argv[1:] != ['--debug']: raise SystemExit('Explicit --debug required')
    run=uuid.uuid4().hex[:12]; config=load()
    config.pop('integration', None)
    base=ROOT/'.runtime/channels'/('group-probe-'+run)
    members={name:{'person_id':'replay:'+name,'workspace':str(base/'group'/name)} for name in ('A','B')}
    config['channels']={'replay':{'token':uuid.uuid4().hex,'account_id':'bot','routes':{
        'group':{'scene_id':'replay-group','target':{'type':'group','id':'group'},'members':members},
        'private':{'scene_id':'replay-private','target':{'type':'dm','id':'A'},'sender_id':'A','person_id':'replay:A','workspace':str(base/'private')},
        'private-b':{'scene_id':'replay-private-b','target':{'type':'dm','id':'B'},'sender_id':'B','person_id':'replay:B','workspace':str(base/'private-b')}}}}
    store=Store(config,'asuna_v2_test_group_'+run); store.migrate(); store.seed(); prepare_channels(store)
    evidence=Evidence(ROOT/'reports'/('group-probe-'+run))
    outputs=[]
    for n in range(5):
        outputs += [LaneResult('private thought'),LaneResult(json.dumps({'next':'speak','goal':'reply','constraints':[],'recall_query':'','speak_before_action':False})),LaneResult('public-'+str(n))]
    lane=FakeLane(store,outputs); coordinator=Coordinator(store,lane)
    app=SimpleNamespace(store=store,config=config,evidence=evidence,character=lane,router=Router(store,coordinator))
    chat=Chat(app,{**config['chat'],'persona':'P1'},emit=lambda _:None)
    server=ChannelServer(Channels(chat)); chat.worker.start()
    client=httpx.Client(base_url=f'http://127.0.0.1:{server.server.server_port}',trust_env=False,headers={'Authorization':'Bearer '+config['channels']['replay']['token']})
    def send(key,sender='A',**fields):
        body={'route_id':'group','account_id':'bot','sender_id':sender,'group_id':'group','event_id':key,'text':key,**fields}
        response=client.post('/v1/channels/replay/events',json=body);assert response.status_code==200,response.text
        chat.pending.join()
        return response.json(),body
    def ack():
        item=client.get('/v1/channels/replay/outbox').json()['items'][0]
        receipt={'attempt_id':item['attempt_id'],'status':'platform_accepted','platform_message_id':'ack-'+(item['reply_to'] or item['publication_id']),'response':{'replay':True}}
        assert client.post('/v1/channels/replay/outbox/'+item['publication_id']+'/receipt',json=receipt).status_code==200
        return item
    try:
        quiet,_=send('quiet-other',sender='B')
        assert not lane.calls and store.db.messages.find_one({'_id':'in-'+quiet['episode_id']})['processing_outcome']=='RECORDED_NO_WAKE'
        first,original=send('topic-A',mentioned_account_ids=['bot']); assert ack()['reply_to']=='topic-A'
        send('reply-to-other',sender='B',reply_to='quiet-other'); assert len(lane.calls)==3
        second,_=send('topic-B',sender='B',mentioned_account_ids=['bot']); ack()
        follow,_=send('clarify-A',reply_to='topic-A'); assert ack()['reply_to']=='clarify-A'
        direct,_=send('reply-to-character',sender='B',reply_to='ack-topic-B'); ack()
        assert len(lane.calls)==12
        assert client.post('/v1/channels/replay/events',json=original).json()['status']=='duplicate'
        chat.pending.join();assert len(lane.calls)==12
        context=store.db.episodes.find_one({'_id':follow['episode_id']})['context']['group_continuity_from_program']
        assert context['topic_id']==store.db.messages.find_one({'_id':'in-'+first['episode_id']})['event']['event_id']
        assert {m['text'] for m in context['related_messages']}=={'topic-A'}
        assert client.post('/v1/channels/replay/events',json={**original,'sender_id':'unknown'}).status_code==403
        assert client.post('/v1/channels/replay/events',json={**original,'group_id':'elsewhere'}).status_code==403
        assert workspace_grant(config,'replay-group','replay:A')['workspace'] != workspace_grant(config,'replay-group','replay:B')['workspace']
        long='完整原文'*300+'TAIL_CANARY'
        quiet_long,_=send('long-quiet',text=long)
        assert store.db.messages.find_one({'_id':'in-'+quiet_long['episode_id']})['text']==long
        view=Workbench(store, {'scene_id':'dm-a','person_id':'A','display_name':'小满'})
        public=view.snapshot('channel:replay-group')
        assert public['readOnly'] and not public['canSend']
        assert {m['authorLabel'] for m in public['messages'] if m['role']=='user'}=={'A','B'}
        assert len([m for m in public['messages'] if m['role']=='assistant'])==4
        assert len([r for r in public['records'] if r['kind']=='integration'])==4
        assert any(r['fields'].get('platform_message_id')=='ack-topic-A' for r in public['records'])
        # One harmless private canary must not enter another private/group scope.
        canary='PRIVATE_A_CANARY_'+run
        memory=store.put('memory_units',{'_id':'private-canary','scope_key':'scene:replay-private','policy_epoch':1,
            'character_id':'xiaoman','status':'active','body_markdown':canary,'epistemic_type':'reported_speech','source_event_ids':[]})
        builder=ContextBuilder(store)
        for scene,person in [('replay-group','replay:B'),('replay-private-b','replay:B')]:
            _,context,_=builder.prepare({'event_id':'scope-check','scene_id':scene,'person_id':person,'text':canary})
            assert canary not in json.dumps({k:v for k,v in context.items() if k!='event'})
            try:store.get('memory_units',memory['_id'],'scene:'+scene)
            except Denied:pass
            else:raise AssertionError('private memory escaped scope')
        assert store.get('memory_units',memory['_id'],'scene:replay-private')['body_markdown']==canary
        work=base/'group'/'B';(work/'public.txt').write_text('GROUP_PUBLIC',encoding='utf-8')
        (base/'private'/'private.txt').write_text(canary,encoding='utf-8')
        sandbox=Sandbox(work,allowed_root=work)
        code="from pathlib import Path; print(Path('/task/public.txt').read_text()); assert not Path('/task/../../private/private.txt').exists(); assert not Path('/mnt/c/workspace/asuna_cognition_core_v2/config/local.json').exists(); assert not Path('/integration/config.json').exists(); assert not Path('/skills').exists()"
        checked=sandbox.run(['python3','-c',code]);assert checked['exit_code']==0,checked
        # Owner instruction through the real UI HTTP bridge, never a forged QQ event.
        config['channels']['replay']['routes']['group']['operator_sender_id']='A'
        view.controller=chat;bridge=UiBridge(view)
        try:
            request=client.post(f'http://127.0.0.1:{bridge.server.server_port}/send',headers={'Authorization':'Bearer '+bridge.token},
                json={'conversation':'channel:replay-group','text':'向当前群主动说一句','integration':False})
            assert request.status_code==200,request.text
            chat.pending.join()
            item=ack();assert item['target']=={'type':'group','id':'group'} and item['reply_to'] is None
            row=store.db.messages.find_one({'_id':'in-'+request.json()['episode_id']})
            assert row['event']['adapter_id']=='owner-web' and row['event']['episode_kind']=='owner_group_prompt'
            assert row['event']['channel']['platform_event_id'] is None
            rendered=view.snapshot('channel:replay-group')
            assert rendered['channelPrompt'] and rendered['canSend']
            assert any(m['authorLabel']=='本机 owner 指令（非 QQ 来信）' for m in rendered['messages'])
        finally:bridge.close()
        result={'status':'PASS','scope':'LOCAL_HOST_REPLAY; fake cognition; no QQ','database':store.name,
                'checks':['persist quiet input once','do not wake for reply to others','two interleaved topics','reply to actual character message','frozen source reply target','dedupe','group and member denial','separate member workspaces','long input preserved','private canary scope and authorized reread','real sandbox excludes private and host config','owner Web prompt to group without forged QQ inbound'],'model_calls':len(lane.calls)}
        write_json(evidence.root/'result.json',result);print(json.dumps(result))
    finally:
        chat.stop();server.close();client.close();store.client.close()


if __name__=='__main__':main()
