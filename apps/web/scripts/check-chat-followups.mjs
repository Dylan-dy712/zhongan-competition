import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/chat'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
globalThis.requestAnimationFrame=callback=>setTimeout(callback,0);
globalThis.cancelAnimationFrame=id=>clearTimeout(id);
const {default:React,act}=await import('react');
const {createRoot}=await import('react-dom/client');
const conversation={conversation_id:'synthetic-followup',subject_id:'synthetic-subject',case_id:'synthetic-case',has_interpretation_report:true,
  title:'合成补问验证',recall_enabled:true,created_at:'2026-10-16',updated_at:'2026-10-16'};
const suggestions=['票据上的医疗总费用是什么意思？','复查前需要准备哪些材料？','日常生活有哪些注意事项？'];
const answer={text:'【合成界面测试】这次就医材料已整理。',evidence_refs:[],history_refs:[],analysis_run_id:'synthetic-run',
  clarification_questions:[{field:'followup_time',question:'医生有交代什么时候复查吗？',options:[{label:'还不确定',message:'我还不确定复查时间。'}]}],
  suggested_questions:suggestions};
const turn={turn_id:'synthetic-report',request_id:'synthetic-analysis',question:'分析完成',input_kind:'analysis_ready',
  status:'completed',attachments:[],tool_events:[],answer,created_at:'2026-10-16',error_code:null};
const snapshot={conversation,turns:[turn],analysis:{status:'completed',run_id:'synthetic-run'},report:{status:'not_released'}};
let pending=null,fail=false;
const sent=[];
globalThis.fetch=async(url,options={})=>{
  const path=new URL(url,'http://localhost').pathname;
  if(path==='/judge/sample')return Response.json({}, {status:403});
  if(path==='/v1/me/members')return Response.json([{subject_id:conversation.subject_id,name:'合成用户',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:true}]);
  if(path==='/v1/chat/subjects')return Response.json([{subject_id:conversation.subject_id,consent_id:'synthetic-consent'}]);
  if(path==='/v1/conversations')return Response.json([conversation]);
  if(path===`/v1/conversations/${conversation.conversation_id}/documents`)return Response.json({document_id:'synthetic-attachment',source_ref:'synthetic.txt'});
  if(path===`/v1/conversations/${conversation.conversation_id}/messages`){
    const body=JSON.parse(options.body);sent.push(body);
    if(fail)return Response.json({message:'合成失败，可重试'},{status:503});
    if(pending)await pending.promise;
    snapshot.turns.push({...turn,turn_id:'synthetic-user-'+sent.length,request_id:body.request_id,input_kind:'user',question:body.message,
      answer:{...answer,patient_updates:body.message.includes('复查时间')?[{field:'followup_time',statement:body.message}]:[]}});
    return Response.json({answer:snapshot.turns.at(-1).answer});
  }
  if(path===`/v1/conversations/${conversation.conversation_id}`)return Response.json(snapshot);
  throw new Error('Unexpected synthetic request: '+path);
};
sessionStorage.setItem('zhongan_chat_token','synthetic-session');
localStorage.setItem('zhongan_last_conversation',conversation.conversation_id);
const modules=await loadTestModules();let root;
const flush=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
const click=async selector=>{const node=document.querySelector(selector);assert.ok(node,selector);await act(async()=>node.click());await flush();};
const type=async(node,value)=>act(async()=>{
  Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype,'value').set.call(node,value);
  node.dispatchEvent(new dom.window.Event('input',{bubbles:true}));
});
try{
  root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(modules.App)));await flush();
  assert.equal(document.querySelectorAll('.suggested-questions button').length,3);
  assert.match(document.querySelector('.narrative-bubble').textContent,/医生有交代什么时候复查吗/);
  assert.match(document.querySelector('.narrative-bubble').textContent,/你可以接着问/);
  await type(document.querySelector('.composer textarea'),'保留这条尚未发送的草稿');
  const picker=document.querySelector('[aria-label="选择文档文件"]');
  Object.defineProperty(picker,'files',{value:[new File(['synthetic'],'synthetic.txt',{type:'text/plain'})],configurable:true});
  await act(async()=>picker.dispatchEvent(new dom.window.Event('change',{bubbles:true})));await flush();
  assert.match(document.querySelector('.chat-draft-attachments').textContent,/synthetic.txt/);
  let release;pending={promise:new Promise(resolve=>{release=resolve;})};
  await click('.suggested-questions button');
  assert.equal(sent.length,1);assert.equal(sent[0].message,suggestions[0]);assert.deepEqual(sent[0].document_ids,[]);
  assert.ok([...document.querySelectorAll('.chat-followups button')].every(button=>button.disabled));
  await click('.suggested-questions button');assert.equal(sent.length,1,'Busy buttons cannot send twice');
  await act(async()=>release());pending=null;await flush();
  assert.equal(document.querySelector('.composer textarea').value,'保留这条尚未发送的草稿');
  assert.match(document.querySelector('.chat-draft-attachments').textContent,/synthetic.txt/);
  assert.equal(document.querySelectorAll('.chat-followups').length,1,'Only latest reply offers interactive follow-ups');
  await click('.clarification-choices button');
  assert.equal(sent.at(-1).message,'我还不确定复查时间。');
  assert.match(document.body.textContent,/已记录你的补充/);
  await act(async()=>[...document.querySelectorAll('.clarification-choices button')].find(node=>node.textContent==='我来补充').click());
  await type(document.querySelector('.clarification-form textarea'),'医生还没定时间，我会再确认');
  fail=true;
  await act(async()=>document.querySelector('.clarification-form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
  const failed=sent.at(-1);
  assert.equal(failed.message,'我补充一下复查时间：医生还没定时间，我会再确认');
  assert.equal(document.querySelector('.clarification-form textarea').value,'医生还没定时间，我会再确认','Failed send retains clarification draft');
  fail=false;
  await act(async()=>document.querySelector('.clarification-form').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
  assert.equal(sent.at(-1).request_id,failed.request_id,'Retry reuses the same durable request ID');
  assert.equal(document.querySelector('.composer textarea').value,'保留这条尚未发送的草稿');
  await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
  snapshot.turns=[{...turn,answer:{text:'兼容历史回答',evidence_refs:[],history_refs:[]}}];
  await act(async()=>root.render(React.createElement(modules.App)));await flush();
  assert.equal(document.querySelector('.chat-followups'),null);
  assert.match(document.body.textContent,/兼容历史回答/);
  console.log('PASS: report follow-ups, one-click send, uncertainty, custom answers, profile receipt, draft/attachment preservation, busy protection, idempotent retry and legacy replies. Synthetic DOM fixtures only.');
}finally{
  if(root)await act(async()=>root.unmount());await modules.close();dom.window.close();
}
