import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/chat'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement','File'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
globalThis.requestAnimationFrame=fn=>fn();
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const realTimeout=globalThis.setTimeout;
globalThis.setTimeout=(fn,ms,...args)=>realTimeout(fn,ms>=1500?20:ms,...args);
const conversation={conversation_id:'analysis-ui',subject_id:'synthetic',case_id:'case-ui',title:'合成分析流程',recall_enabled:false,updated_at:'2026-10-08T00:00:00Z'};
let phase='initial',run='run-1',uploads=0,submissions=[],turns=[],resolveSecond,resolveNarrative;
let delayNarrative=false,failNarrative=false,continuations=0,polls=0,pollOutage=false;
const section={section_type:'cost_explanation',pending_count:1,items:[{text:'医疗总费用：120元',kind:'checked',evidence_refs:['00000000-0000-4000-8000-000000000002']}]};
const state=()=>({conversation,turns,analysis:{status:phase==='initial'?'not_started':phase==='ready'?'waiting_review':phase==='failed'?'failed':phase==='queued'?'queued':'running',run_id:phase==='initial'?undefined:run,stage:phase==='ready'?'validate':phase},
  report:{status:'not_released'},material_report:{status:phase==='ready'?'available':phase==='failed'?'failed':phase,run_id:run,report_id:'material-ui',document_count:2,source_report_version:1,pending_count:1,notice:'合成自动核对提示',sections:[section]}});
globalThis.fetch=async(url,options={})=>{
 const path=new URL(url,'http://localhost').pathname;
 if(path==='/v1/conversations')return Response.json([conversation]);
 if(path==='/v1/me/members')return Response.json([{subject_id:'synthetic',name:'合成分析用户',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:true}]);
 if(path==='/v1/chat/subjects')return Response.json([{subject_id:'synthetic'}]);
 if(path.endsWith('/deliveries'))return Response.json([]);
 if(path.endsWith('/documents')){uploads++;if(uploads===2)await new Promise(r=>resolveSecond=r);return Response.json({document_id:'doc-'+uploads});}
 if(path.endsWith('/analyses')){
  const body=JSON.parse(options.body);submissions.push(body);phase='queued';run='run-'+submissions.length;
  turns=[{turn_id:'turn-ui',request_id:body.request_id,question:body.message,input_kind:'user',status:'completed',answer:{text:'材料已收到',evidence_refs:[],history_refs:[]},attachments:[],tool_events:[{tool:'start_analysis',run_id:run,status:'queued'}]}];
  return Response.json({turn_id:'turn-ui'});
 }
 if(path.endsWith('/continue')){
  continuations++;
  if(delayNarrative)await new Promise(r=>resolveNarrative=r);
  if(failNarrative){failNarrative=false;return Response.json({detail:'合成解读失败'},{status:503});}
  turns=[...turns.filter(t=>t.input_kind!=='analysis_ready'),{turn_id:'continue-ui',input_kind:'analysis_ready',status:'completed',question:'解释材料',attachments:[],tool_events:[],
   answer:{text:'我先帮你把这张票据理清楚。材料记载医疗总费用：120元。\n\n这张票据没有说明保险赔付金额，我们先把它与票据上的费用区分开。你最想先核对哪一项？',evidence_refs:['00000000-0000-4000-8000-000000000002'],history_refs:[],citations:[{quote:'材料记载医疗总费用：120元。',source_refs:['00000000-0000-4000-8000-000000000002']}],analysis_run_id:run}}];
  return Response.json({turn_id:'continue-ui'});
 }
 if(path==='/v1/evidence/00000000-0000-4000-8000-000000000002')return Response.json({evidence_id:'00000000-0000-4000-8000-000000000002',document_version:1,page_index:0,text_span:{text:'医疗总费用：120元'}});
 if(path.endsWith('/messages'))return Response.json({turn_id:'follow-ui'});
 if(path==='/v1/conversations/analysis-ui'){polls++;if(pollOutage)return new Response('Bad gateway',{status:502});return Response.json(state());}
 throw Error('Unexpected fixture request '+path);
};
sessionStorage.setItem('zhongan_chat_token','synthetic-test-only');
const modules=await loadTestModules(),root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>new Promise(r=>realTimeout(r,60)));
const click=async(text)=>{const node=[...document.querySelectorAll('button')].find(n=>!n.closest('[hidden]') && (n.textContent.trim()===text || n.getAttribute('aria-label')===text));assert.ok(node,text);await act(async()=>node.click());await flush();};
try{
 await act(async()=>root.render(React.createElement(modules.App)));await flush();
 const input=document.querySelector('[aria-label="选择文档文件"]');
 Object.defineProperty(input,'files',{value:Array.from({length:25},(_,i)=>new File(['synthetic'],`${i+1}.txt`,{type:'text/plain'}))});
 await act(async()=>input.dispatchEvent(new dom.window.Event('change',{bubbles:true})));await flush();
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog').open,true);
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value,4,'Only acknowledged uploads count');
 assert.equal(submissions.length,0,'Analysis waits for all selected uploads');
 await act(async()=>resolveSecond());await flush();assert.equal(submissions.length,1);
 assert.deepEqual(submissions[0].document_ids,Array.from({length:25},(_,i)=>'doc-'+(i+1)));
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value,0);
 for(const [next,percent] of [['extract',20],['insights',40],['guidance',60],['validate',80]]){
  phase=next;await flush();const displayed=document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value;
  assert.ok(displayed>=percent+1 && displayed<percent+20,'Estimated progress stays within the actual stage');
  assert.match(document.querySelector('.chat-workspace > dialog.analysis-dialog').textContent,/预估进度/);
 }
 await click('收起进度，稍后查看');assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog').open,false);
 const pollsBeforeNarrative=polls;
 delayNarrative=true;phase='ready';await flush();await flush();
 await act(async()=>document.querySelector('.analysis-card').click());await flush();
 const waiting=document.querySelector('.chat-workspace > dialog.analysis-dialog');
 assert.equal(waiting.open,true,'Material readiness cannot dismiss progress before the text arrives');
 assert.ok(waiting.querySelector('progress').value>=95 && waiting.querySelector('progress').value<100,'Narrative generation remains below 100%');
 assert.match(waiting.textContent,/写好解读|把情况讲清楚/);
 assert.equal(document.querySelector('.analysis-narrative'),null);
 assert.ok(polls>pollsBeforeNarrative+1,'Progress polling continues while the narrative request waits');
 delayNarrative=false;await act(async()=>resolveNarrative());await flush();await flush();
 assert.equal(waiting.querySelector('progress').value,100,'100% requires the actual completed narrative');
 assert.equal(waiting.open,false,'Report arrival closes progress and immediately shows the text');
 assert.equal(window.location.hash,'#/chat','Analysis stays in the conversation');
 assert.match(document.body.textContent,/医疗总费用：120元/);
 assert.ok(document.querySelector('.analysis-narrative'),'AI free text is the report');
 assert.equal(document.querySelectorAll('.analysis-narrative-copy p').length,2,'Paragraphs follow the model text, not six fixed sections');
 assert.equal(document.querySelector('.material-report-content'),null);
 assert.doesNotMatch(document.body.textContent,/几项解释|当前没有通过自动核对|治疗经过资料待补充/);
 assert.equal(document.querySelector('.analysis-narrative-sources'),null,'Sources are attached to the supported sentence');
 const source=document.querySelector('.analysis-narrative .source-ref');assert.ok(source);
 await act(async()=>source.click());await flush();assert.ok(document.querySelector('dialog.source-sheet'));
 assert.match(document.querySelector('dialog.source-sheet').textContent,/医疗总费用：120元/);
 await click('关闭原始依据');assert.equal(document.querySelector('dialog.source-sheet'),null);
 await act(async()=>{window.location.hash='/report';});await flush();
 assert.equal(window.location.hash,'#/chat','Legacy material report route returns to the conversational analysis');
 await click('材料解读');assert.equal(window.location.hash,'#/chat');
 turns=turns.filter(t=>t.input_kind!=='analysis_ready');
 phase='failed';await flush();await act(async()=>document.querySelector('.analysis-card').click());await flush();
 assert.match(document.querySelector('.chat-workspace > dialog.analysis-dialog').textContent,/生成没有完成/);
 await click('重新分析材料');assert.equal(submissions.length,2);
 assert.notEqual(submissions[0].request_id,submissions[1].request_id,'A new analysis uses a fresh submission identity');
 failNarrative=true;phase='ready';await flush();await flush();
 assert.match(document.querySelector('.chat-workspace > dialog.analysis-dialog').textContent,/解读暂时没能完成/);
 const beforeRetry=continuations;
 await click('重新分析材料');await flush();
 assert.equal(submissions.length,2,'Retrying the narrative does not restart material analysis');
 assert.equal(continuations,beforeRetry+1,'Narrative failure can be retried explicitly');
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value,100);
 assert.equal(window.location.hash,'#/chat');assert.ok(document.querySelector('.analysis-narrative'));
 // A failed HTTP request may finish successfully on the server later.
 const savedNarrative=turns.find(t=>t.input_kind==='analysis_ready');
 turns=turns.filter(t=>t.input_kind!=='analysis_ready');phase='failed';await flush();
 await act(async()=>document.querySelector('.analysis-card').click());await flush();
 await click('重新分析材料');failNarrative=true;phase='ready';await flush();await flush();
 assert.match(document.querySelector('.chat-workspace > dialog.analysis-dialog').textContent,/解读暂时没能完成/);
 const callsBeforeRecovery=continuations;
 turns.push({...savedNarrative,answer:{...savedNarrative.answer,analysis_run_id:run}});await flush();await flush();
 assert.equal(continuations,callsBeforeRecovery,'A saved narrative is recovered without another model call');
 assert.ok(document.querySelector('.analysis-narrative'),'Late completion replaces the failure card with the saved report');
 assert.equal(modules.analysisView(state(),undefined,false,'旧的接口错误').kind,'ready');
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog').open,false);
 // Background connection errors disappear after successful recovery, without resubmitting AI work.
 const modelsBeforeOutage=continuations,analysesBeforeOutage=submissions.length;
 pollOutage=true;await act(async()=>new Promise(r=>realTimeout(r,900)));
 assert.match(document.body.textContent,/连接暂时中断，正在自动恢复/);
 assert.ok(document.querySelector('.analysis-narrative'),'Connection failure preserves the saved report');
 pollOutage=false;await act(async()=>new Promise(r=>realTimeout(r,900)));
 assert.doesNotMatch(document.body.textContent,/连接暂时中断，正在自动恢复/);
 assert.equal(continuations,modelsBeforeOutage);assert.equal(submissions.length,analysesBeforeOutage);
 assert.doesNotMatch(document.body.textContent,/服务暂时不可用/,'Saved report recovery clears its earlier generation failure');
 console.log('PASS: uploads, real stages, conversational AI report, adaptive paragraphs, inline source links, legacy route redirect, failure retry and completion. Synthetic fixtures only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();globalThis.setTimeout=realTimeout;}

