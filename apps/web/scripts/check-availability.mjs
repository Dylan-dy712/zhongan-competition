import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {createRoot} from 'react-dom/client';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/home'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
const modules=await loadTestModules();let root;
try {
  const {api,App}=modules;
  const snapshot={conversation:{conversation_id:'synthetic',subject_id:'synthetic-subject',case_id:'synthetic-case',title:'合成就医资料',recall_enabled:false,created_at:'2026-10-01',updated_at:'2026-10-01'},turns:[],analysis:{status:'not_started'},report:{status:'not_released'}};
  const timeout=AbortSignal.timeout,timeouts=[];
  try{
    AbortSignal.timeout=ms=>{timeouts.push(ms);return timeout(ms);};
    globalThis.fetch=async()=>Response.json(snapshot);
    await api.getConversation('synthetic','synthetic');
    await api.sendChatMessage('synthetic','synthetic','request','hello',[]);
    await api.continueAnalysis('synthetic','synthetic','run');
    assert.deepEqual(timeouts,[15000,120000,450000],'Narrative browser timeout covers model repair and gateway wait');
  }finally{AbortSignal.timeout=timeout;}
  let calls=0;
  globalThis.fetch=async()=>++calls<3?new Response('upstream unavailable',{status:502}):Response.json(snapshot);
  assert.equal((await api.getConversation('synthetic','synthetic')).conversation.conversation_id,'synthetic');assert.equal(calls,3);
  calls=0;globalThis.fetch=async()=>{if(++calls===1)throw new TypeError('Synthetic network outage');return Response.json([]);};
  assert.deepEqual(await api.listConversations('synthetic'),[]);assert.equal(calls,2);
  calls=0;globalThis.fetch=async()=>{calls++;return new Response('',{status:401});};
  await assert.rejects(api.listConversations('synthetic'),e=>e.status===401);assert.equal(calls,1);
  calls=0;globalThis.fetch=async()=>{calls++;return new Response('<html>Bad gateway</html>',{status:502});};
  await assert.rejects(api.sendChatMessage('synthetic','synthetic','request','hello',[]),e=>e.status===502);assert.equal(calls,1,'Writes must not be replayed');
  await assert.rejects(api.authenticate('login',{}),e=>e.status===502&&e.message.includes('暂时不可用'));assert.equal(calls,2,'Login must not be replayed');
  sessionStorage.setItem('zhongan_chat_token','synthetic-session');sessionStorage.setItem('zhongan_account_name','合成验证');
  root=createRoot(document.getElementById('root'));
  await act(async()=>{root.render(React.createElement(App));await new Promise(r=>setTimeout(r,20));});
  await act(async()=>{await new Promise(r=>setTimeout(r,2400));});
  assert.match(document.body.textContent,/服务暂时不可用/);
  assert.equal(sessionStorage.getItem('zhongan_chat_token'),'synthetic-session');
  assert.equal(sessionStorage.getItem('zhongan_account_name'),'合成验证');
  globalThis.fetch=async url=>Response.json(new URL(url,'http://localhost').pathname==='/v1/me/members'?[{subject_id:'synthetic-subject',name:'合成验证',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:true}]:[]);
  const retry=[...document.querySelectorAll('button')].find(b=>b.textContent==='重新连接');assert.ok(retry);
  await act(async()=>{retry.click();await new Promise(r=>setTimeout(r,20));});
  assert.match(document.body.textContent,/提交理赔材料/,'Manual reconnect must recover the actual app');
  await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
  globalThis.fetch=async()=>new Response('',{status:401});
  await act(async()=>{root.render(React.createElement(App));await new Promise(r=>setTimeout(r,20));});
  assert.equal(sessionStorage.getItem('zhongan_chat_token'),null,'Expired authentication must still clear the session');
  assert.match(document.body.textContent,/欢迎回来/);
  console.log('PASS: bounded read recovery, no write replay, HTML gateway errors, preserved session, manual recovery and expired authentication.');
} finally {if(root)await act(async()=>root.unmount());await modules.close();dom.window.close();}
