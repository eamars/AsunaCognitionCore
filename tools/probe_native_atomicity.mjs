// E24: exercise the installed DSH session/compaction implementation. Only
// the failing summarizer is substituted; this is not a live cognition test.
import assert from 'node:assert/strict';
import { mkdirSync,writeFileSync,readFileSync } from 'node:fs';
import { join } from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import LlmRuntime,{createUserMessage,createMessage,createToolResultMessage} from '@deepseek-ai/dsh-llm';
import { Session } from '@deepseek-ai/dsh-session';
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection';
import TokenMeter from '@deepseek-ai/dsh-token-meter';
import BasicCompactionEngine from '@deepseek-ai/dsh-compaction-basic';

const out=process.argv[2]; if(!out) throw Error('OUT_REQUIRED');mkdirSync(out,{recursive:false});
const ctx=new Context();new LlmRuntime(ctx);new SessionProjectionRegistry(ctx);new TokenMeter(ctx);
class FailingSummary extends BasicCompactionEngine {
  calls=0;
  async summarize(){this.calls++;throw Error('INJECTED_SUMMARY_UNAVAILABLE');}
}
const engine=new FailingSummary(ctx,{auto:false});
const session=Session.create('asuna-native-atomicity');
session.append('turn/start',{turn:1});
session.append('user/message',createUserMessage({source:{kind:'user'},content:[{type:'text',text:'Retain this original source '+ 'record '.repeat(100)}]}),{surfaceOp:'append'});
session.append('step/start',{turn:1,step:1});
session.append('request/header',{header:{config:{provider:'test-local-no-network',model:'test'}},reason:'initial'});
session.append('assistant/message',{turn:1,step:1,stream:[],message:createMessage({role:'assistant',source:{kind:'model',provider:'test-local-no-network',model:'test'},content:[{type:'tool-call',id:'pair-1',name:'read',arguments:'{}'}]})},{surfaceOp:'append'});
session.append('tool/call',{turn:1,step:1,callId:'pair-1',name:'read',arguments:'{}'});
session.append('tool/result',{turn:1,step:1,message:createToolResultMessage({callId:'pair-1',content:[{type:'text',text:'authoritative result '.repeat(100)}],isError:false})},{surfaceOp:'append'});
session.append('step/end',{turn:1,step:1});session.append('turn/end',{turn:1,reason:{kind:'completed'}});session.append('turn/start',{turn:2});
const agent={session,options:{provider:'test-local-no-network',model:'test'}};
const before=[...session.surface.nodes];const history=JSON.stringify(before.map(i=>session.eventAt(i)));
let status='FAIL';let error;
try{
  await assert.rejects(engine.compactRegion(before[0],before[1],agent),/not a balanced boundary/);
  assert.equal(engine.calls,0);
  await assert.rejects(engine.compactRegion(before[0],before.at(-1),agent),/INJECTED_SUMMARY_UNAVAILABLE/);
  assert.equal(engine.calls,1);assert.deepEqual(session.surface.nodes,before);
  assert.equal(JSON.stringify(before.map(i=>session.eventAt(i))),history);
  const events=session.snapshotEvents();assert.equal(events.filter(e=>e.type==='compaction/start').length,1);
  assert.match(events.findLast(e=>e.type==='compaction/end').data.error,/INJECTED_SUMMARY_UNAVAILABLE/);
  writeFileSync(join(out,'native-log.json'),JSON.stringify(events,null,2),{flag:'wx'});
  const restored=Session.create(session.id,JSON.parse(readFileSync(join(out,'native-log.json'),'utf8')),session.header);
  assert.deepEqual(restored.surface.nodes,before);
  assert.equal(JSON.stringify(before.map(i=>restored.eventAt(i))),history);status='PASS';
}catch(exc){error={type:exc.constructor.name,message:exc.message};}
const result={test_id:'PROBE-E24',status,mode:'installed_native_DSH_compaction_injected_summary_failure',assertions:{tool_pair_rejected_before_summary:engine.calls===1,source_history_retained:JSON.stringify(before.map(i=>session.eventAt(i)))===history},error,commands:[{argv:['node','tools/probe_native_atomicity.mjs',out],exit_code:status==='PASS'?0:1}],limitations:['Native log replay is tested; this probe alone does not cover the entire E24 queue/capacity/episode contract.']};
writeFileSync(join(out,'result.json'),JSON.stringify(result,null,2),{flag:'wx'});console.log(JSON.stringify(result));process.exitCode=status==='PASS'?0:1;
