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
const calls=[];
const conversation={conversation_id:'synthetic-a',case_id:'case-a',title:'合成测试记录',
  updated_at:'2026-10-05T09:00:00+08:00',created_at:'2026-10-05T09:00:00+08:00',recall_enabled:false};
const snapshot={conversation,turns:[],analysis:{status:'completed'},report:{status:'published',report_id:'synthetic-report',report_version:1,
  actions:[],sections:[{section_type:'diagnosis_explanation',claims:[{claim_id:'synthetic-claim',text:'合成资料说明',
    review_status:'approved',claim_type:'case_fact',evidence_refs:['synthetic-evidence']}]}]}};
let delayed=null;
let delayedEvidence=null;
globalThis.fetch=async url=>{
  const path=new URL(url,'http://localhost').pathname;calls.push(path);
  if(path==='/v1/conversations')return Response.json([conversation]);
  if(path==='/v1/chat/subjects')return Response.json([{subject_id:'synthetic-subject',consent_id:'synthetic-consent'}]);
  if(path==='/v1/cases/case-a/deliveries')return Response.json([]);
  if(path==='/v1/evidence/synthetic-evidence')return delayedEvidence.promise;
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
  assert.match(document.body.textContent,/这次看病/);
  assert.equal(button('复核工作台'),undefined);
  assert.equal(document.querySelector('.chat-sidebar'),null);
  assert.equal(document.querySelector('.history-toggle'),null);
  assert.equal(document.querySelector('.chat-header'),null);
  await click('首页');assert.match(document.body.textContent,/这次看病/);
  assert.doesNotMatch(document.body.textContent,/没有医学审核角色/);
  assert.equal(document.querySelectorAll('.care-navigation [aria-current="page"]').length,1);
  await act(async()=>{window.location.hash='/review';});await flush();
  assert.match(document.body.textContent,/这次看病/,'Removed review route must fall back to home');
  await click('首页');
  await click('问暖暖');assert.equal(window.location.hash,'#/chat');assert.ok(document.querySelector('.composer'));assert.ok(document.querySelector('.chat-sidebar'));
  assert.equal(document.querySelector('.nuan-topic-grid'),null,'Ordinary chat entry must not show claim-completion cards, even with a published report');
  assert.equal(document.querySelector('.nuan-quick-actions'),null);
  await act(async()=>window.history.back());await flush();assert.equal(window.location.hash,'#/home');
  assert.match(document.body.textContent,/这次看病/);
  await click('问暖暖');await act(async()=>root.unmount());
  root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(App)));await flush();
  assert.equal(window.location.hash,'#/chat');assert.ok(document.querySelector('.composer'),'Reload must retain chat route');
  assert.equal(document.querySelector('.nuan-priority'),null,'Reload must not manufacture a claim-completion entry');
  await click('关怀指引');
  let resolveEvidence;delayedEvidence={promise:new Promise(r=>{resolveEvidence=r;})};
  await click('查看这段说明的资料依据');await click('首页');
  await act(async()=>resolveEvidence(Response.json({evidence_id:'synthetic-evidence',document_version:1,page_index:0,text_span:{text:'合成证据'}})));
  await flush();assert.equal(document.querySelector('dialog.evidence-overlay'),null,'Late evidence must not reopen a modal on another page');
  assert.match(document.body.textContent,/这次看病/);
  await click('问暖暖');
  await click('新的关怀对话');assert.match(document.body.textContent,/开始新的对话/);
  await click('就医记录');
  assert.ok(document.querySelector('.records-profile'),'Original archive profile must be mounted');
  const requestsBeforeView=calls.length;
  await click('按时间');assert.ok(document.querySelector('.records-timeline'));
  await click('按就医');assert.ok(document.querySelector('.records-group'));
  assert.equal(calls.length,requestsBeforeView,'Changing record arrangement must not reload the backend');
  await click('查看这次就医');assert.ok(document.querySelector('.records-detail'));
  let resolve;
  delayed={promise:new Promise(r=>{resolve=r;})};
  await click('合成测试记录');
  assert.match(document.body.textContent,/正在打开就医记录/);
  assert.doesNotMatch(document.body.textContent,/开始新的对话/,'Loading must not masquerade as a new case');
  await act(async()=>resolve(Response.json({message:'不可访问'},{status:404})));await flush();
  assert.doesNotMatch(document.body.textContent,/正在打开就医记录/,'Access failure must clear loading');
  await click('问暖暖');assert.equal(button('新的关怀对话').disabled,false,'Access failure must not leave controls locked');
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
