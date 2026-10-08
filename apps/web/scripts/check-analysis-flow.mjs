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
let phase='initial',run='run-1',uploads=0,submissions=[],turns=[],resolveSecond;
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
 if(path.endsWith('/continue'))return Response.json({turn_id:'continue-ui'});
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
 phase='ready';await flush();assert.match(document.querySelector('.analysis-card').textContent,/报告已生成/);
 await act(async()=>document.querySelector('.analysis-card').click());await flush();
 assert.equal(window.location.hash,'#/report');assert.match(document.body.textContent,/医疗总费用：120元/);
 assert.match(document.body.textContent,/需要核实/);assert.equal(document.querySelector('.empty-report'),null,'Pending clinical report must not hide checked material report');
 await click('继续问这部分 →');assert.equal(window.location.hash,'#/chat');
 assert.match(document.querySelector('textarea').value,/费用/);
 phase='failed';await flush();await act(async()=>document.querySelector('.analysis-card').click());await flush();
 assert.match(document.querySelector('.chat-workspace > dialog.analysis-dialog').textContent,/生成没有完成/);
 await click('重新分析材料');assert.equal(submissions.length,2);
 assert.notEqual(submissions[0].request_id,submissions[1].request_id,'A new analysis uses a fresh submission identity');
 phase='ready';await flush();assert.equal(document.querySelector('.chat-workspace > dialog.analysis-dialog progress').value,100);
 await click('查看材料分析报告 →');assert.equal(window.location.hash,'#/report');
 console.log('PASS: real upload acknowledgments, deterministic submission, persisted stage percentages, dismiss/reopen, checked report beside pending clinical content, follow-up, failure retry and completion. Synthetic fixtures only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();globalThis.setTimeout=realTimeout;}

