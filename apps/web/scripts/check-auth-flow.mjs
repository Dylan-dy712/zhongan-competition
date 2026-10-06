import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/claim'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();
const calls=[];let consent={version:0,status:'not_granted',notice_version:'account-care-v1',purpose:'case_guidance'};
let conversation=null,uploadCount=0,failUpload=true;
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
  if(path==='/v1/chat/subjects')return Response.json(consent.status==='active'?[{subject_id:'synthetic-subject',consent_id:'synthetic-consent'}]:[]);
  if(path==='/v1/conversations'){
    if(body){conversation={conversation_id:body.conversation_id,case_id:'synthetic-case',title:'合成资料',recall_enabled:body.recall_enabled,updated_at:new Date().toISOString()};return Response.json(conversation);}
    return Response.json(conversation?[conversation]:[]);
  }
  if(path.endsWith('/documents')){
    uploadCount++;
    if(uploadCount===2 && failUpload){failUpload=false;return Response.json({message:'合成上传中断'},{status:503});}
    return Response.json({document_id:'doc-'+uploadCount,source_ref:'synthetic'});
  }
  if(path.endsWith('/messages'))return Response.json({status:'completed'});
  if(path.includes('/v1/conversations/'))return Response.json({conversation,turns:[],analysis:{status:'not_started'},report:{status:'not_generated'}});
  if(path.endsWith('/deliveries'))return Response.json([]);
  throw Error('Unexpected test request '+path);
};
const root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>{await new Promise(r=>setTimeout(r,15));});
const visible=node=>!node.closest('[hidden]');
const button=text=>[...document.querySelectorAll('button')].find(n=>visible(n) && n.textContent.trim().endsWith(text));
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
  await click('我的');await click('确认并授权关怀');assert.match(document.body.textContent,/已授权/);
  await click('首页');await click('整理理赔资料，开启专属关怀');await click('下一步');
  const fileInput=document.querySelector('input[type="file"]');
  Object.defineProperty(fileInput,'files',{value:[new File(['synthetic-one'],'one.pdf',{type:'application/pdf'}),new File(['synthetic-two'],'two.pdf',{type:'application/pdf'})],configurable:true});
  await act(async()=>fileInput.dispatchEvent(new dom.window.Event('change',{bubbles:true})));await click('下一步');
  const confirmation=[...document.querySelectorAll('input[type="checkbox"]')].find(visible);await act(async()=>confirmation.click());
  await click('确认并开始关怀');assert.match(document.body.textContent,/合成上传中断/);
  await click('我的');await click('首页');await click('整理理赔资料，开启专属关怀');
  await click('重试整理');assert.match(document.body.textContent,/资料已进入你的关怀空间/);
  assert.equal(uploadCount,3,'Retry must not reupload first file');
  const creations=calls.filter(c=>c.path==='/v1/conversations' && c.body);
  assert.equal(creations.length,2);assert.equal(creations[0].body.conversation_id,creations[1].body.conversation_id);
  assert.equal(creations[0].body.recall_enabled,false);
  await click('查看专属关怀');assert.equal(window.location.hash,'#/chat');
  await click('我的');await click('退出登录');assert.equal(sessionStorage.getItem('zhongan_chat_token'),null);
  assert.equal(sessionStorage.getItem('zhongan_account_name'),null);assert.ok(calls.some(c=>c.path==='/v1/auth/logout'));
  console.log('PASS: password confirmation, optional consent, account authorization, three-step upload, interrupted upload retry across navigation, default recall off, real API wiring, server logout. Synthetic DOM fixtures only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();}
