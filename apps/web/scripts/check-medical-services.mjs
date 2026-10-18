import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {JSDOM} from 'jsdom';
import {loadTestModules} from './test-modules.mjs';
const values=JSON.parse(execFileSync('python',['-c',`import json
from services.api.app.medical_services import MedicalServiceArgs,recommend_services
a=MedicalServiceArgs(routes=['benefits','offline','online'],needs=['followup'],location='上海市浦东新区')
b=MedicalServiceArgs(routes=['offline'],needs=['followup'])
print(json.dumps({'available':recommend_services(a,['上海市浦东新区']),'missing':recommend_services(b,[])},ensure_ascii=True))`],{cwd:new URL('../../../',import.meta.url),encoding:'utf8'}));
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/chat'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
globalThis.requestAnimationFrame=callback=>setTimeout(callback,0);globalThis.cancelAnimationFrame=id=>clearTimeout(id);
const {default:React,act}=await import('react');const {createRoot}=await import('react-dom/client');
const conversation={conversation_id:'synthetic-service-conversation',subject_id:'synthetic-subject',case_id:'synthetic-case',title:'合成服务验证',recall_enabled:false,created_at:'2026-10-16',updated_at:'2026-10-16'};
const base={text:'合成材料已整理，复查时可以带上已有报告。',evidence_refs:[],history_refs:[],analysis_run_id:'synthetic-run',
 suggested_questions:['我想了解中高端保单里有哪些医疗增值权益适合我。']};
const initial={turn_id:'synthetic-report',request_id:'synthetic-analysis',question:'解读材料',input_kind:'analysis_ready',status:'completed',attachments:[],tool_events:[],answer:base,created_at:'2026-10-16',error_code:null};
const snapshot={conversation,turns:[initial],analysis:{status:'completed',run_id:'synthetic-run'},report:{status:'not_released'}};
const sent=[];let response=values.available,fail=false,release,hold=null;
globalThis.fetch=async(url,options={})=>{
 const path=new URL(url,'http://localhost').pathname;
 if(path==='/judge/sample')return Response.json({}, {status:403});
 if(path==='/v1/me/members')return Response.json([{subject_id:conversation.subject_id,name:'合成体验用户',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:true}]);
 if(path==='/v1/chat/subjects')return Response.json([{subject_id:conversation.subject_id,consent_id:'synthetic-consent'}]);
 if(path==='/v1/conversations')return Response.json([conversation]);
 if(path===`/v1/conversations/${conversation.conversation_id}/messages`){
  const body=JSON.parse(options.body);sent.push(body);if(fail)return Response.json({message:'合成重试'},{status:503});if(hold)await hold;
  snapshot.turns.push({...initial,turn_id:'synthetic-service-'+sent.length,input_kind:'user',question:body.message,request_id:body.request_id,answer:{text:'可以，我们先按这次需求看服务和就医地区。',evidence_refs:[],history_refs:[],medical_services:response}});
  return Response.json({answer:snapshot.turns.at(-1).answer});
 }
 if(path===`/v1/conversations/${conversation.conversation_id}`)return Response.json(snapshot);
 throw new Error('Unexpected fixture request: '+path);
};
sessionStorage.setItem('zhongan_chat_token','synthetic-session');localStorage.setItem('zhongan_last_conversation',conversation.conversation_id);
const modules=await loadTestModules();let root;
const flush=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,25));});
const click=async(selector)=>{const node=document.querySelector(selector);assert.ok(node,selector);await act(async()=>node.click());await flush();};
const type=async(node,value)=>act(async()=>{const proto=node.tagName==='INPUT'?dom.window.HTMLInputElement.prototype:dom.window.HTMLTextAreaElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(node,value);node.dispatchEvent(new dom.window.Event('input',{bubbles:true}));});
try{
 root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(modules.App)));await flush();
 assert.equal(document.querySelector('.medical-guide-note').textContent,'需要下一步的就医帮助，也可以问我');
 assert.equal(document.querySelector('.medical-guide'),null,'Report invitation is plain text without a card');
 assert.equal(document.querySelectorAll('.medical-guide-actions button').length,0);
 assert.ok(document.querySelector('.clarification-section'),'Report keeps an optional supplement box without model questions');
 await type(document.querySelector('.composer textarea'),'保留的草稿');
 hold=new Promise(resolve=>{release=resolve;});await click('.suggested-questions button');
 assert.equal(sent.length,1);assert.match(sent[0].message,/中高端保单/);assert.deepEqual(sent[0].document_ids,[]);
 assert.ok([...document.querySelectorAll('.chat-followups button')].every(x=>x.disabled));
 await act(async()=>release());hold=null;await flush();
 assert.equal(document.querySelector('.composer textarea').value,'保留的草稿');
 assert.ok(document.querySelector('.medical-service-benefit'));assert.ok(document.querySelector('.medical-service-hospital'));assert.ok(document.querySelector('.medical-service-online'));
 for(const kind of ['benefit','hospital','online']){
  await click(`.medical-service-${kind} .medical-card-action`);
  assert.ok(document.querySelector('dialog.medical-preview').open);
  assert.match(document.querySelector('.medical-preview-notice').textContent,/尚未发起真实预约、问诊、支付或资料传送/);
  assert.equal(document.querySelectorAll('.medical-preview-steps li').length,3);
  await click('.medical-close');assert.equal(document.querySelector('.medical-preview'),null);
 }
 assert.equal(sent.length,1,'Preview clicks never submit appointments or chat messages');
 response=values.missing;await type(document.querySelector('.composer textarea'),'我想找附近适合复查的医院');await click('[aria-label="发送消息"]');
 assert.equal(document.querySelectorAll('.medical-location').length,1);
 await type(document.querySelector('.medical-location input'),'上海市浦东新区');
 fail=true;await act(async()=>document.querySelector('.medical-location').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
 const retry=sent.at(-1);assert.equal(document.querySelector('.medical-location input').value,'上海市浦东新区');
 fail=false;response=values.available;await act(async()=>document.querySelector('.medical-location').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
 assert.equal(sent.at(-1).request_id,retry.request_id);assert.match(sent.at(-1).message,/上海市浦东新区/);
 assert.equal(document.querySelector('.medical-location'),null,'Historical location prompts are not interactive after the new answer');
 const before=sent.length;await click('.chat-turn:last-child .medical-service-online .medical-card-action');
 await click('.medical-primary');assert.equal(sent.length,before+1);assert.match(sent.at(-1).message,/在线咨询前/);
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(modules.App)));await flush();
 assert.ok(document.querySelector('.medical-service-online'),'Persisted answers restore service cards');
 assert.equal(document.querySelector('.medical-preview'),null,'Preview state is not restored across sessions');
 console.log('PASS: report invitation, draft/busy protection, backend-generated cards, all simulated routes, location request/retry, history and preparation follow-up. Synthetic DOM fixture, no appointments.');
}finally{if(root)await act(async()=>root.unmount());await modules.close();dom.window.close();}
