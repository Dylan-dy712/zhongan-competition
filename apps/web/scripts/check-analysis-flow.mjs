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
const conversation={conversation_id:'analysis-ui',case_id:'case-ui',title:'合成分析流程',recall_enabled:false,updated_at:'2026-10-08T00:00:00Z'};
let phase='initial',run='run-1',uploads=0,submissions=[],turns=[],resolveSecond,resolveNarrative;
let delayNarrative=false,failNarrative=false,continuations=0;
const section={section_type:'cost_explanation',pending_count:1,items:[{text:'医疗总费用：120元',kind:'checked',evidence_refs:['source-ui']}]};
const state=()=>({conversation,turns,analysis:{status:phase==='initial'?'not_started':phase==='ready'?'waiting_review':phase==='failed'?'failed':phase==='queued'?'queued':'running',run_id:phase==='initial'?undefined:run,stage:phase==='ready'?'validate':phase},
  report:{status:'not_released'},material_report:{status:phase==='ready'?'available':phase==='failed'?'failed':phase,run_id:run,report_id:'material-ui',document_count:2,source_report_version:1,pending_count:1,notice:'合成自动核对提示',sections:[section]}});
globalThis.fetch=async(url,options={})=>{
 const path=new URL(url,'http://localhost').pathname;
 if(path==='/v1/conversations')return Response.json([conversation]);
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
   answer:{text:'我先帮你把这张票据理清楚。材料记载医疗总费用：120元。\n\n这张票据没有说明保险赔付金额，我们先把它与票据上的费用区分开。你最想先核对哪一项？',evidence_refs:['source-ui'],history_refs:[],analysis_run_id:run}}];
  return Response.json({turn_id:'continue-ui'});
 }
 if(path==='/v1/evidence/source-ui')return Response.json({evidence_id:'source-ui',document_version:1,page_index:0,text_span:{text:'医疗总费用：120元'}});
 if(path.endsWith('/messages'))return Response.json({turn_id:'follow-ui'});
 if(path==='/v1/conversations/analysis-ui')return Response.json(state());
 throw Error('Unexpected fixture request '+path);
};
sessionStorage.setItem('zhongan_chat_token','synthetic-test-only');
const modules=await loadTestModules(),root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>new Promise(r=>realTimeout(r,60)));
const click=async(text)=>{const node=[...document.querySelectorAll('button')].find(n=>!n.closest('[hidden]') && (n.textContent.trim()===text || n.getAttribute('aria-label')===text));assert.ok(node,text);await act(async()=>node.click());await flush();};
try{
 await act(async()=>root.render(React.createElement(modules.App)));await flush();
 const input=document.querySelector('[aria-label="选择文档文件"]');
 Object.defineProperty(input,'files',{value:[new File(['one'],'one.txt',{type:'text/plain'}),new File(['two'],'two.txt',{type:'text/plain'})]});
 await act(async()=>input.dispatchEvent(new dom.window.Event('change',{bubbles:true})));await flush();
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog').open,true);
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value,50,'Only acknowledged uploads count');
 assert.equal(submissions.length,0,'Analysis waits for all selected uploads');
 await act(async()=>resolveSecond());await flush();assert.equal(submissions.length,1);
 assert.deepEqual(submissions[0].document_ids,['doc-1','doc-2']);
 assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value,0);
 for(const [next,percent] of [['extract',20],['insights',40],['guidance',60],['validate',80]]){
  phase=next;await flush();const displayed=document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value;
  assert.ok(displayed>=percent+1 && displayed<percent+20,'Estimated progress stays within the actual stage');
  assert.match(document.querySelector('.chat-workspace > dialog.analysis-dialog').textContent,/预估进度/);
 }
 await click('收起进度，稍后查看');assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog').open,false);
 delayNarrative=true;phase='ready';await flush();await flush();
 await act(async()=>document.querySelector('.analysis-card').click());await flush();
 const waiting=document.querySelector('.chat-workspace > dialog.analysis-dialog');
 assert.equal(waiting.open,true,'Material readiness cannot dismiss progress before the text arrives');
 assert.ok(waiting.querySelector('progress').value>=95 && waiting.querySelector('progress').value<100,'Narrative generation remains below 100%');
 assert.match(waiting.textContent,/写好解读|把情况讲清楚/);
 assert.equal(document.querySelector('.analysis-narrative'),null);
 delayNarrative=false;await act(async()=>resolveNarrative());await flush();await flush();
 assert.equal(waiting.querySelector('progress').value,100,'100% requires the actual completed narrative');
 assert.equal(waiting.open,false,'Report arrival closes progress and immediately shows the text');
 assert.equal(window.location.hash,'#/chat','Analysis stays in the conversation');
 assert.match(document.body.textContent,/医疗总费用：120元/);
 assert.ok(document.querySelector('.analysis-narrative'),'AI free text is the report');
 assert.equal(document.querySelectorAll('.analysis-narrative-copy p').length,2,'Paragraphs follow the model text, not six fixed sections');
 assert.equal(document.querySelector('.material-report-content'),null);
 assert.doesNotMatch(document.body.textContent,/几项解释|当前没有通过自动核对|治疗经过资料待补充/);
 const sources=document.querySelector('.analysis-narrative-sources');assert.equal(sources.open,false);
 await act(async()=>sources.querySelector('summary').click());assert.equal(sources.open,true);
 await click('依据 1 ↗');assert.ok(document.querySelector('dialog.evidence-overlay'));
 await click('关闭');assert.equal(document.querySelector('dialog.evidence-overlay'),null);
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
 console.log('PASS: uploads, real stages, conversational AI report, adaptive paragraphs, collapsed source links, legacy route redirect, failure retry and completion. Synthetic fixtures only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();globalThis.setTimeout=realTimeout;}

