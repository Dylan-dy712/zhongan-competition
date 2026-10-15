import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/'});
for(const key of ['window','document','HTMLElement','sessionStorage','localStorage'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const {default:React,act}=await import('react');
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();
const root=createRoot(document.getElementById('root'));
const calls=[];
let pendingOld,releaseOld;
const state={a:{enabled:true,version:1,epoch:1},b:{enabled:false,version:0,epoch:0}};
const original='【合成原话】希望先说明步骤，不要省略限制。';
let conversationSettings={read_enabled:false,export_enabled:true,report_enabled:false,version:1};
globalThis.fetch=async(url,options={})=>{
  const path=new URL(url,'http://localhost').pathname;
  const method=options.method||'GET';const body=options.body?JSON.parse(options.body):undefined;
  calls.push({path,method,body});
  const person=path.includes('/members/a/')?'a':path.includes('/members/b/')?'b':null;
  if(person&&path.endsWith('/memory-settings')){
    if(person==='a'&&pendingOld)await pendingOld;
    if(method==='PATCH'){assert.equal(person,'b');assert.equal(body.expected_version,0);state.b={enabled:body.enabled,version:1,epoch:1};}
    return Response.json({...state[person],subject_id:person,purpose:'continuous_care_memory'});
  }
  if(person&&path.endsWith('/memories'))return Response.json({memories:[],candidates:[]});
  if(path==='/v1/conversations'&&method==='GET')return Response.json([{conversation_id:'b-chat',subject_id:'b',title:'合成来源对话'}]);
  if(path==='/v1/conversations/b-chat')return Response.json({conversation:{conversation_id:'b-chat',subject_id:'b',title:'合成来源对话',recall_enabled:false},turns:[{
    turn_id:'b-turn',input_kind:'user',status:'completed',question:original}],analysis:{}});
  if(path==='/v1/conversations/b-chat/memory-settings'){
    if(method==='PATCH'){
      assert.equal(body.expected_version,conversationSettings.version);
      conversationSettings={read_enabled:body.read_enabled,export_enabled:body.export_enabled,
        report_enabled:body.report_enabled,version:conversationSettings.version+1};
    }
    return Response.json(conversationSettings);
  }
  if(path==='/v1/me/members/b/memory-candidates'&&method==='POST'){
    assert.equal(body.source_turn_id,'b-turn');assert.equal(body.content,original);assert.equal(body.scope,'patient');
    assert.equal(body.actor_id,undefined);assert.equal(body.subject_id,undefined);
    return Response.json({candidate_id:'candidate-b',version:1});
  }
  if(path==='/v1/me/members/b/memory-candidates/candidate-b/confirm'&&method==='POST'){
    assert.equal(body.confirmation,true);assert.equal(body.expected_version,1);
    return Response.json({memory_id:'memory-b',version:1,status:'active'});
  }
  throw new Error('Unexpected synthetic request: '+method+' '+path);
};
const flush=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});
const render=async(person)=>{await act(async()=>root.render(React.createElement(modules.PatientMemory,{key:person,token:'synthetic',subjectId:person,name:person==='a'?'合成母亲':'合成孩子',onClose:()=>{}})));await flush();};
const button=text=>[...document.querySelectorAll('button')].find(item=>item.textContent===text);
const click=async node=>{assert.ok(node);await act(async()=>node.click());await flush();};
const select=async(label,value)=>{
  const node=[...document.querySelectorAll('label')].find(item=>item.textContent.startsWith(label))?.querySelector('select');
  assert.ok(node,label);await act(async()=>{node.value=value;node.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});await flush();
};
try{
  pendingOld=new Promise(resolve=>{releaseOld=resolve;});
  await render('a');await render('b');
  await act(async()=>releaseOld());pendingOld=null;await flush();
  assert.match(document.body.textContent,/合成孩子/);assert.doesNotMatch(document.body.textContent,/合成母亲/);
  assert.equal(document.querySelector('.memory-switch input').checked,false,'Delayed prior-patient response must not enable new patient');
  await click(document.querySelector('.memory-switch input'));
  assert.equal(state.b.enabled,true);
  await click(button('从已保存的用户消息添加记忆'));
  await select('来源对话','b-chat');await select('用户原话','b-turn');
  assert.equal(document.querySelector('.memory-editor textarea').value,original);
  assert.ok(button('确认为 合成孩子 保存'));
  const postsBefore=calls.filter(call=>call.method==='POST').length;
  await act(async()=>document.querySelector('.memory-editor').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
  assert.equal(calls.filter(call=>call.method==='POST').length-postsBefore,2,'Creating an unconfirmed candidate must precede explicit confirmation');
  assert.match(document.body.textContent,/已为 合成孩子 保存记忆/);
  assert.ok(!calls.some(call=>call.method!=='GET'&&call.path.includes('/members/a/')),'No write may use the prior patient namespace');
  await act(async()=>root.render(React.createElement(modules.PatientMemory,{key:'b-chat',token:'synthetic',subjectId:'b',name:'合成孩子',conversationId:'b-chat',onClose:()=>{}})));await flush();
  const switches=()=>[...document.querySelectorAll('.memory-conversation-settings input')];
  assert.equal(switches()[2].checked,false,'Report sharing defaults off independently');
  assert.equal(switches()[2].disabled,true,'Report sharing requires conversation read permission');
  await click(switches()[0]);
  assert.equal(conversationSettings.read_enabled,true);
  assert.equal(conversationSettings.report_enabled,false,'Enabling chat recall must not enable report sharing');
  await click(switches()[2]);assert.equal(conversationSettings.report_enabled,true);
  await click(switches()[0]);
  assert.equal(conversationSettings.report_enabled,false,'Stopping read permission must also stop report usage');
  console.log('Patient memory UI: patient switch isolation, separate consent and source-confirmation flow passed.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();}
