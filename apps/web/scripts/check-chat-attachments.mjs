import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/chat'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement','File'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;globalThis.requestAnimationFrame=fn=>fn();
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL;let revoked=0;
URL.createObjectURL=()=> 'blob:synthetic-image';URL.revokeObjectURL=()=>revoked++;
const {createRoot}=await import('react-dom/client');
let conversation={conversation_id:'attachment-ui',subject_id:'synthetic',case_id:'case-ui',title:'合成报告后的对话',title_pending:true,has_interpretation_report:true,updated_at:'2026-10-15'};
const originalTimeout=globalThis.setTimeout;
globalThis.setTimeout=(fn,ms,...args)=>originalTimeout(fn,ms===5000?20:ms,...args);
let titleLists=0;
let turns=[{turn_id:'report',request_id:'report-req',input_kind:'analysis_ready',question:'解释材料',attachments:[],tool_events:[],status:'completed',answer:{text:'合成报告正文。',history_refs:[],evidence_refs:[],analysis_run_id:'saved-run'}}];
let analysis={status:'completed',run_id:'saved-run'},failMessage=true,uploads=0;
let releaseUpload,releaseMessage;
const uploadGate=new Promise(resolve=>releaseUpload=resolve),messageGate=new Promise(resolve=>releaseMessage=resolve);
const calls=[];
globalThis.fetch=async(url,options={})=>{
 const path=new URL(url,'http://localhost').pathname;const body=typeof options.body==='string'?JSON.parse(options.body):options.body;
 calls.push({path,method:options.method||'GET',body});
 if(path==='/v1/conversations'){
  if(options.method==='POST'){conversation={...conversation,conversation_id:body.conversation_id,subject_id:body.subject_id,has_interpretation_report:false};turns=[];analysis={status:'not_started'};return Response.json(conversation);}
  if(++titleLists>1)conversation={...conversation,title:'票据内容与费用解读',title_pending:false};
  return Response.json([conversation]);
 }
 if(path==='/v1/chat/subjects')return Response.json([{subject_id:'synthetic'}]);
 if(path==='/v1/me/members')return Response.json([{subject_id:'synthetic',name:'合成用户',relationship:'self',profile_completed:true}]);
 if(path.endsWith('/deliveries'))return Response.json([]);
 if(path.endsWith('/attachments')){uploads++;await uploadGate;return Response.json({attachment_id:'attachment-'+uploads,name:'合成图片.png'});}
 if(path.endsWith('/messages')){
  await messageGate;
  if(failMessage){failMessage=false;return Response.json({message:'合成网络失败'}, {status:503});}
  turns.push({turn_id:'reply',request_id:body.request_id,question:body.message,input_kind:'user',status:'completed',tool_events:[{tool:'read_chat_attachments',status:'available'}],attachments:body.attachment_ids.map(document_id=>({document_id,name:'合成图片.png',kind:'chat_attachment'})),answer:{text:'这是针对图片和问题的正常回复。',history_refs:[],evidence_refs:[]}});
  return Response.json({turn_id:'reply'});
 }
 if(path==='/v1/conversations/'+conversation.conversation_id)return Response.json({conversation,turns,analysis,report:{status:'not_generated'}});
 throw Error('Unexpected fixture request: '+path);
};
sessionStorage.setItem('zhongan_chat_token','synthetic-only');
const modules=await loadTestModules(),root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>new Promise(r=>setTimeout(r,30)));
const button=text=>[...document.querySelectorAll('button')].find(node=>node.textContent.trim().endsWith(text)||node.getAttribute('aria-label')===text);
const click=async text=>{const node=button(text);assert.ok(node,text);assert.equal(node.disabled,false);await act(async()=>node.click());await flush();};
const select=async names=>{const input=document.querySelector('[aria-label="选择照片或图片"]');Object.defineProperty(input,'files',{configurable:true,value:names.map(name=>new File(['synthetic'],name,{type:'image/png'}))});await act(async()=>input.dispatchEvent(new dom.window.Event('change',{bubbles:true})));await flush();};
try{
 await act(async()=>root.render(React.createElement(modules.App)));await flush();
 await flush();
 assert.match(document.querySelector('.history-list').textContent,/票据内容与费用解读/,'Background AI titles refresh in the sidebar');
 assert.equal(document.querySelector('.history-report-badge')?.textContent,'解读报告','Saved report conversations show a separate report badge');
 assert.ok(button('新建解读报告'));assert.ok(button('新建对话'));
 const writes=()=>calls.filter(c=>c.method==='POST');
 await select(['合成图片.png']);await select(['额外图片.png','移除图片.png']);
 assert.equal(document.querySelectorAll('.chat-draft-attachments article').length,3);
 assert.equal(writes().length,0,'Picking local images must not upload, inspect, or submit analysis');
 assert.equal(document.querySelector('dialog.photo-review'),null,'Chat images do not start the report precheck');
 await click('移除附件 移除图片.png');assert.equal(document.querySelectorAll('.chat-draft-attachments article').length,2);
 const textarea=document.querySelector('.composer textarea');
 await act(async()=>{Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype,'value').set.call(textarea,'请解释图片里的两项内容');textarea.dispatchEvent(new dom.window.Event('input',{bubbles:true}));textarea.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});
 await click('发送消息');
 assert.equal(uploads,1,'Upload is still awaiting the network');
 assert.equal(document.querySelector('.chat-draft-attachments'),null,'Composer clears before upload finishes');
 assert.equal(textarea.value,'','Question clears immediately on submission');
 assert.equal(document.querySelectorAll('.chat-sent-attachments img').length,2,'Sent images move to the transcript');
 assert.equal([...document.querySelectorAll('.messages .message-row.user')].filter(n=>n.textContent.includes('请解释图片里的两项内容')).length,1);
 await act(async()=>releaseUpload());await flush();assert.equal(uploads,2);
 assert.equal(document.querySelector('.composer textarea').value,'','Question stays cleared while model response is pending');
 await act(async()=>releaseMessage());await flush();
 assert.equal(document.querySelectorAll('.chat-sent-attachments img').length,2,'Failed submission retains transcript previews for retry');
 await click('重试这条消息');
 const messages=calls.filter(c=>c.path.endsWith('/messages'));
 assert.equal(messages.length,2);assert.equal(messages[0].body.request_id,messages[1].body.request_id,'Retry retains message identity');
 assert.equal(uploads,2,'Retry reuses acknowledged uploads');
 assert.equal(messages[1].body.message,'请解释图片里的两项内容');assert.deepEqual(messages[1].body.attachment_ids,['attachment-1','attachment-2']);assert.deepEqual(messages[1].body.document_ids,[]);
 assert.equal(document.querySelector('.chat-draft-attachments'),null);assert.equal(textarea.value,'');
 assert.equal([...document.querySelectorAll('.messages .message-row.user')].filter(n=>n.textContent.includes('请解释图片里的两项内容')).length,1,'Persisted response replaces the local turn without duplicating it');
 assert.match(document.querySelector('.messages').textContent,/正常回复/);assert.ok(document.querySelector('.analysis-narrative'),'Saved report remains visible');
 assert.equal(calls.filter(c=>/\/analyses|\/documents|\/materials\/inspect/.test(c.path)).length,0,'Chat attachments never take the report pipeline');
 assert.ok(revoked>=3,'Removed/draft previews release their object URLs');
 await click('新建对话');
 await act(async()=>{const select=document.querySelector('.connect-form select');select.value='synthetic';select.dispatchEvent(new dom.window.Event('change',{bubbles:true}));});
 await click('开始新的对话');await select(['普通聊天图片.png']);
 assert.equal(document.querySelector('.history-report-badge'),null,'Ordinary image chats have no report badge');
 assert.equal(writes().filter(c=>c.path.endsWith('/attachments')).length,2,'A new ordinary chat also keeps its selection local');
 await click('发送消息');assert.equal(calls.filter(c=>c.path.endsWith('/messages')).length,3);
 assert.equal(document.querySelector('dialog.report-upload-dialog'),null);
 console.log('PASS: local image drafts, add/remove, combined question and images, retry identity/upload reuse, saved report preserved, ordinary chat sends no report requests. Synthetic only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;globalThis.setTimeout=originalTimeout;}
