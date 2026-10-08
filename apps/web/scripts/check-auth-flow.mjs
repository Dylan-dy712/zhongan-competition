import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/home'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();
let member={subject_id:'synthetic-subject',name:'合成用户',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:false};
const calls=[];let consent={version:0,status:'not_granted',notice_version:'account-care-v1',purpose:'case_guidance'};
let conversation=null,uploadCount=0,failUpload=true,claimReady=false,claimTurns=[],resolveClaimNarrative;
globalThis.fetch=async(url,options={})=>{
  const path=new URL(url,'http://localhost').pathname;
  const body=typeof options.body==='string'?JSON.parse(options.body):options.body;
  calls.push({path,body});
  if(path==='/v1/auth/register')return Response.json({access_token:'synthetic-token',user:{display_name:'合成用户'}});
  if(path==='/v1/auth/logout')return new Response(null,{status:204});
  if(path==='/v1/me/consents'){
    if(body)consent={...consent,version:consent.version+1,status:body.confirmation?'active':'revoked'};
    return Response.json(consent);
  }
  if(path==='/v1/me/members')return Response.json([member]);
  if(path==='/v1/me/members/synthetic-subject'){member={...member,...body,profile_completed:true};return Response.json(member);}
  if(path==='/v1/chat/subjects')return Response.json(consent.status==='active'?[{subject_id:'synthetic-subject',consent_id:'synthetic-consent'}]:[]);
  if(path==='/v1/conversations'){
    if(body){conversation={conversation_id:body.conversation_id,subject_id:body.subject_id,case_id:'synthetic-case',title:'合成资料',recall_enabled:body.recall_enabled,updated_at:new Date().toISOString()};return Response.json(conversation);}
    return Response.json(conversation?[conversation]:[]);
  }
  if(path.endsWith('/documents')){
    uploadCount++;
    if(uploadCount===2 && failUpload){failUpload=false;return Response.json({message:'合成上传中断'},{status:503});}
    return Response.json({document_id:'doc-'+uploadCount,source_ref:'synthetic'});
  }
  if(path.endsWith('/messages') || path.endsWith('/analyses'))return Response.json({status:'completed'});
  if(path.endsWith('/continue')){
    await new Promise(r=>resolveClaimNarrative=r);
    claimTurns=[{turn_id:'claim-narrative',input_kind:'analysis_ready',status:'completed',question:'合成测试',attachments:[],tool_events:[],answer:{text:'我看过你上传的资料了，咱们先把这次费用理清楚。',evidence_refs:[],history_refs:[],analysis_run_id:'claim-run'}}];
    return Response.json({turn_id:'claim-narrative'});
  }
  if(path.includes('/v1/conversations/'))return Response.json({conversation,turns:claimTurns,analysis:{status:claimReady?'waiting_review':'not_started',run_id:claimReady?'claim-run':undefined},report:{status:'not_generated'},material_report:claimReady?{status:'available',run_id:'claim-run',sections:[]}:undefined});
  if(path.endsWith('/deliveries'))return Response.json([]);
  throw Error('Unexpected test request '+path);
};
const root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>{await new Promise(r=>setTimeout(r,15));});
const visible=node=>!node.closest('[hidden]');
const button=text=>[...document.querySelectorAll('button')].find(n=>visible(n) && (n.textContent.trim().endsWith(text)||n.getAttribute('aria-label')===text));
async function click(text){const node=button(text);assert.ok(node,'Missing button '+text);assert.equal(node.disabled,false);await act(async()=>node.click());await flush();}
async function input(selector,value){const node=document.querySelector(selector);assert.ok(node,selector);await act(async()=>{
  Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(node,value);
  node.dispatchEvent(new dom.window.Event('input',{bubbles:true}));node.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});}
async function submit(){await act(async()=>document.querySelector('form:not([hidden] form)').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();}
try{
  await act(async()=>root.render(React.createElement(modules.App)));await flush();
  await click('注册');
  await input('input[autocomplete="nickname"]','合成用户');await input('input[autocomplete="username"]','13900000001');
  const passwords=[...document.querySelectorAll('input[type="password"]')];
  assert.equal(document.querySelector('input[autocomplete="username"]').type,'tel');
  for(const field of passwords){assert.equal(field.hasAttribute('minlength'),false);assert.equal(field.hasAttribute('maxlength'),false);}
  await input('input[type="password"]','1');
  await act(async()=>{Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(passwords[1],'different-password');passwords[1].dispatchEvent(new dom.window.Event('input',{bubbles:true}));});
  await submit();assert.match(document.body.textContent,/两次输入的密码不一致/);assert.equal(calls.length,0);
  await act(async()=>{Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(passwords[1],'1');passwords[1].dispatchEvent(new dom.window.Event('input',{bubbles:true}));});
  await submit();assert.equal(calls.find(c=>c.path==='/v1/auth/register').body.care_consent,false);
  assert.equal(sessionStorage.getItem('zhongan_chat_token'),'synthetic-token');
  assert.match(document.body.textContent,/完善本人资料/);assert.equal(document.querySelector('.care-navigation'),null);
  await click('保存并进入首页');assert.equal(window.location.hash,'#/home');
  await click('提交理赔材料');await click('年龄未填写');
  assert.match(document.body.textContent,/申请医疗理赔/);
  const scroller=document.querySelector('.claim-main');scroller.scrollTop=240;
  const diagnosisControl=document.querySelector('[data-claim-field="diagnosis"]');
  await input('[data-claim-field="diagnosis"]','保留填写内容');
  const causeControl=document.querySelector('[data-claim-field="cause"]');causeControl.focus();
  await act(async()=>{causeControl.value='意外';causeControl.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});
  assert.equal(document.querySelector('[data-claim-field="diagnosis"]')===diagnosisControl,true);
  assert.equal(diagnosisControl.value,'保留填写内容');assert.equal(scroller.scrollTop,240);
  assert.equal(document.activeElement===causeControl,true);
  await input('[data-claim-field="diagnosis"]','');

  await click('确认资料用途授权');await click('确认并授权关怀');assert.match(document.body.textContent,/已授权/);
  await click('首页');await click('提交理赔材料');await click('年龄未填写');await click('下一步，上传材料');assert.match(document.body.textContent,/请填写病历上的诊断/);await click('填入示例信息');await click('下一步，上传材料');
  await click('下一步，核对申请');assert.match(document.body.textContent,/请补充/);
  const fileInput=document.querySelector('input[type="file"]');
  Object.defineProperty(fileInput,'files',{value:[new File(['synthetic-one'],'one.pdf',{type:'application/pdf'}),new File(['synthetic-two'],'two.pdf',{type:'application/pdf'})],configurable:true});
  await act(async()=>fileInput.dispatchEvent(new dom.window.Event('change',{bubbles:true})));for(const title of ['医疗费用发票','费用明细清单','医保结算单']){await click('添加'+title);document.querySelector('dialog').close();Object.defineProperty(fileInput,'files',{value:[new File(['synthetic'],'synthetic-'+title+'.pdf',{type:'application/pdf'})],configurable:true});await act(async()=>fileInput.dispatchEvent(new dom.window.Event('change',{bubbles:true})));}
  await click('下一步，核对申请');
  const confirmation=[...document.querySelectorAll('input[type="checkbox"]')].find(visible);await act(async()=>confirmation.click());
  await click('确认并开始关怀');assert.match(document.body.textContent,/合成上传中断/);
  await click('返回首页');await click('我的');await click('首页');await click('提交理赔材料');await click('年龄未填写');
  await click('重试整理');assert.match(document.body.textContent,/资料已进入你的关怀空间/);
  assert.equal(uploadCount,6,'Retry must not reupload first file');
  const creations=calls.filter(c=>c.path==='/v1/conversations' && c.body);
  assert.equal(creations.length,2);assert.equal(creations[0].body.conversation_id,creations[1].body.conversation_id);
  assert.equal(creations[0].body.recall_enabled,false);
  claimReady=true;await act(async()=>{await new Promise(r=>setTimeout(r,2100));});await flush();
  assert.ok(resolveClaimNarrative,'Claim intake starts the actual text generation before completing progress');
  const claimProgress=document.querySelector('.claim-react dialog.analysis-dialog');
  assert.equal(claimProgress.open,true);
  assert.ok(claimProgress.querySelector('progress').value>=95 && claimProgress.querySelector('progress').value<100);
  assert.equal(window.location.hash,'#/claim');
  await act(async()=>resolveClaimNarrative());await flush();await flush();
  assert.equal(window.location.hash,'#/chat','Claim report opens automatically once its text is ready');
  assert.ok(document.querySelector('.analysis-narrative'));
  assert.ok(document.querySelector('#chat-topic-action'),'Claim completion must show care cards');
  assert.ok(document.querySelector('#chat-topic-summary'));assert.ok(document.querySelector('#chat-topic-cost'));
  assert.ok(document.querySelector('.nuan-quick-actions'),'Claim cards must have working shortcuts');
  await click('首页');await click('问暖暖');
  assert.equal(document.querySelector('#chat-topic-action'),null,'Ordinary chat visits must not retain claim-entry cards');
  assert.equal(document.querySelector('.nuan-quick-actions'),null,'No shortcuts to absent cards');
  await click('新的关怀对话');await click('年龄未填写');await click('开始新的对话');
  assert.ok(document.querySelector('.composer'),'Ordinary new chat must still support messages');
  assert.equal(document.querySelector('.nuan-conversation-caption'),null);
  assert.equal(document.querySelector('.nuan-topic-grid'),null,'Ordinary new chat must not show claim cards');
  assert.equal(document.querySelector('.nuan-priority'),null);
  assert.equal(document.querySelector('.nuan-quick-actions'),null);
  await click('我的');await click('退出登录');assert.equal(sessionStorage.getItem('zhongan_chat_token'),null);
  assert.equal(sessionStorage.getItem('zhongan_account_name'),null);assert.ok(calls.some(c=>c.path==='/v1/auth/logout'));
  console.log('PASS: password confirmation, optional consent, account authorization, three-step upload, interrupted upload retry across navigation, default recall off, real API wiring, server logout. Synthetic DOM fixtures only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();}
