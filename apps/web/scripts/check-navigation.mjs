import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {JSDOM} from 'jsdom';
import {loadTestModules} from './test-modules.mjs';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';

// Render the actual React app with synthetic responses, including deferred requests.
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/home'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const calls=[];
const conversation={conversation_id:'synthetic-a',subject_id:'synthetic-subject',case_id:'case-a',title:'合成测试记录',
  updated_at:'2026-10-05T09:00:00+08:00',created_at:'2026-10-05T09:00:00+08:00',recall_enabled:false};
const snapshot={conversation,turns:[],analysis:{status:'completed'},report:{status:'published',report_id:'synthetic-report',report_version:1,
  actions:[],sections:[{section_type:'diagnosis_explanation',claims:[{claim_id:'synthetic-claim',text:'合成资料说明',
    review_status:'approved',claim_type:'case_fact',evidence_refs:['00000000-0000-4000-8000-000000000001']}]}]}};
let delayed=null;
let delayedEvidence=null;
globalThis.fetch=async url=>{
  const path=new URL(url,'http://localhost').pathname;calls.push(path);
  if(path==='/judge/sample')return Response.json({message:'普通用户没有评委示例资料'}, {status:403});
  if(path==='/v1/conversations')return Response.json([conversation]);
  if(path==='/v1/medical-records')return Response.json({records:[{record_id:'record-a',subject_id:conversation.subject_id,title:'合成就医记录',updated_at:conversation.updated_at,document_count:1,conversation_count:1,related_records:[],cases:[{case_id:conversation.case_id,conversations:[conversation],profile:{},updated_at:conversation.updated_at,document_count:1,organization_status:'ready',assignment_source:'ai',relation:'new_episode',version:1,analysis_status:'completed'}]}],unorganized_count:0,processing_count:0});
  if(path==='/v1/me/members')return Response.json([{subject_id:'synthetic-subject',name:'合成用户',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:true}]);
  if(path==='/v1/me/consents')return Response.json({subject_id:'synthetic-subject',status:'active',version:1});
  if(path==='/v1/chat/subjects')return Response.json([{subject_id:'synthetic-subject',consent_id:'synthetic-consent'}]);
  if(path==='/v1/cases/case-a/deliveries')return Response.json([]);
  if(path==='/v1/evidence/00000000-0000-4000-8000-000000000001')return delayedEvidence.promise;
  if(path==='/v1/conversations/synthetic-a')return delayed ? delayed.promise : Response.json(snapshot);
  throw new Error('Unexpected test request: '+path);
};
sessionStorage.setItem('zhongan_chat_token','synthetic-test-only');
const modules=await loadTestModules();
let root;
const flush=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,25));});
const button=text=>[...document.querySelectorAll('button')].find(node=>node.textContent.trim().endsWith(text));
const click=async text=>{const node=button(text);assert.ok(node,`Missing button: ${text}`);assert.equal(node.disabled,false);await act(async()=>node.click());await flush();};
try {
  const {App}=modules;
  root=createRoot(document.getElementById('root'));
  await act(async()=>root.render(React.createElement(App)));await flush();
  assert.match(document.body.textContent,/提交理赔材料/);
  assert.equal(button('复核工作台'),undefined);
  assert.equal(document.querySelector('.chat-sidebar'),null);
  assert.equal(document.querySelector('.history-toggle'),null);
  assert.equal(document.querySelector('.chat-header'),null);
  await click('首页');assert.match(document.body.textContent,/提交理赔材料/);
  assert.doesNotMatch(document.body.textContent,/没有医学审核角色/);
  assert.equal(document.querySelectorAll('.care-navigation [aria-current="page"]').length,1);
  await act(async()=>{window.location.hash='/review';});await flush();
  assert.match(document.body.textContent,/提交理赔材料/,'Removed review route must fall back to home');
  await click('首页');
  await click('问暖暖');assert.equal(window.location.hash,'#/chat');assert.ok(document.querySelector('.composer'));assert.ok(document.querySelector('.chat-sidebar'));
  assert.equal(document.querySelector('.nuan-topic-grid'),null,'Ordinary chat entry must not show claim-completion cards, even with a published report');
  assert.equal(document.querySelector('.nuan-quick-actions'),null);
  await act(async()=>window.history.back());await flush();assert.equal(window.location.hash,'#/home');
  assert.match(document.body.textContent,/提交理赔材料/);
  await click('问暖暖');await act(async()=>root.unmount());
  root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(App)));await flush();
  assert.equal(window.location.hash,'#/chat');assert.ok(document.querySelector('.composer'),'Reload must retain chat route');
  assert.equal(document.querySelector('.nuan-priority'),null,'Reload must not manufacture a claim-completion entry');
  await click('关怀指引');
  let resolveEvidence;delayedEvidence={promise:new Promise(r=>{resolveEvidence=r;})};
  await act(async()=>document.querySelector('[aria-label="查看来源 1"]').click());await click('首页');
  await act(async()=>resolveEvidence(Response.json({evidence_id:'00000000-0000-4000-8000-000000000001',document_version:1,page_index:0,text_span:{text:'合成证据'}})));
  await flush();assert.equal(document.querySelector('dialog.source-sheet'),null,'Late evidence must not reopen a modal on another page');
  assert.match(document.body.textContent,/提交理赔材料/);
  await click('问暖暖');
  await click('新建对话');assert.match(document.body.textContent,/开始新的对话/);
  assert.equal(document.querySelector('dialog'),null,'New chat must open directly without a member picker');
  assert.equal(document.querySelector('.connect-form select').value,'');
  assert.equal(button('开始新的对话').disabled,true,'A member must still be selected before starting');
  await click('我的');await click('查看更多');
  assert.ok(document.querySelector('.member-records-header'),'Secondary record list identifies the person');
  assert.equal(document.querySelector('.records-profile'),null,'Record list must not duplicate the profile card');
  const requestsBeforeView=calls.length;
  await click('关联历程');assert.equal(document.querySelectorAll('.medical-record-card').length,0);
  await click('全部');assert.ok(document.querySelector('.medical-record-card'));
  assert.equal(calls.length,requestsBeforeView,'Changing record arrangement must not reload the backend');
  await click('查看这次就医');assert.ok(document.querySelector('.records-detail'));
  let resolve;
  delayed={promise:new Promise(r=>{resolve=r;})};
  await click('合成测试记录');
  assert.match(document.body.textContent,/正在打开就医记录/);
  assert.doesNotMatch(document.body.textContent,/开始新的对话/,'Loading must not masquerade as a new case');
  await act(async()=>resolve(Response.json({message:'不可访问'},{status:404})));await flush();
  assert.doesNotMatch(document.body.textContent,/正在打开就医记录/,'Access failure must clear loading');
  await click('问暖暖');
  assert.equal(document.querySelector('dialog'),null);
  await act(async()=>{const select=document.querySelector('.connect-form select');select.value='synthetic-subject';select.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});
  assert.equal(button('开始新的对话').disabled,false,'Access failure must not leave controls locked');
  const {PageBoundary}=modules;
  const bad=()=>{throw new Error('Synthetic render failure');};
  await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
  const originalError=console.error;console.error=()=>{};
  try {await act(async()=>root.render(React.createElement(PageBoundary,{resetKey:'broken'},React.createElement(bad))));}
  finally {console.error=originalError;}
  assert.match(document.body.textContent,/这个页面暂时没能打开/);
  await act(async()=>root.render(React.createElement(PageBoundary,{resetKey:'healthy'},React.createElement('p',null,'可恢复页面'))));
  assert.match(document.body.textContent,/可恢复页面/);
  console.log('PASS: unique navigation, history back, reload, stale evidence suppression, slow conversation loading, access failure unlock, render failure recovery. Synthetic React DOM tests; no server data accessed.');
} finally {
  if(root)await act(async()=>root.unmount());
  await modules.close();dom.window.close();
}
