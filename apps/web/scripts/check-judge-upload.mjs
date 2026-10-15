import assert from 'node:assert/strict';
import {loadTestModules} from './test-modules.mjs';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/home'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.confirm=()=>{throw Error('Fresh judge experience must not require an extra confirmation');};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL;
URL.createObjectURL=()=> 'blob:synthetic-preview';URL.revokeObjectURL=()=>{};
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();const {App}=modules;
const sample={sample_id:'synthetic-01',version:'v1',data_origin:'official_deidentified',title:'合成病例流程测试',summary:'测试',notice:'合成测试，非患者资料',file_count:4,page_count:13,
  claim_info:{kind:'住院医疗',cause:'待确认',diagnosis:'合成肩部损伤样例',start:'2026-09-20',end:'2026-09-25',total:'1200.00',social:'待确认',other:'待确认'},
  documents:[{id:'discharge',name:'合成出院记录.pdf',document_type:'出院记录',page_count:2},{id:'diagnosis',name:'合成诊断证明.pdf',document_type:'诊断证明',page_count:1},{id:'costs',name:'合成费用清单.pdf',document_type:'费用清单',page_count:5},{id:'outpatient',name:'合成复诊病历.pdf',document_type:'门诊病历',page_count:5}]};
const legacyTitle='这是一组主办方比赛样例的脱敏体验资料，不代表账号使用者本人病史。'.slice(0,30);
const calls=[];let uploadCount=0,failSecond=true,failSelection=true,conversation,turns=[];
globalThis.fetch=async(url,options={})=>{
  const p=new URL(url,'http://localhost').pathname;
  const body=typeof options.body==='string'?JSON.parse(options.body):options.body;
  calls.push({path:p,method:options.method||'GET',body});
  if(p==='/judge/sample')return options.headers.Authorization.includes('ordinary')?Response.json({}, {status:403}):Response.json(sample);
  if(p==='/v1/chat/subjects')return Response.json([{subject_id:'synthetic-subject',consent_id:'synthetic-consent'}]);
  if(p==='/v1/me/members')return Response.json([{subject_id:'synthetic-subject',relationship:'self',name:'合成评委',profile_completed:true}]);
  if(p==='/v1/medical-records')return Response.json({records:conversation?[{record_id:'synthetic-record',title:legacyTitle,
    cases:[{case_id:'synthetic-case',conversations:[conversation],proposal_title:legacyTitle}],related_records:[{record_id:'related-record',title:legacyTitle}]}]:[],unorganized_count:0,processing_count:0});
  if(p.startsWith('/judge/sample/files/')){
    assert.equal(new URL(url,'http://localhost').searchParams.get('version'),'v1');
    assert.equal(new URL(url,'http://localhost').searchParams.get('sample_id'),'synthetic-01');
    if(failSelection){failSelection=false;return {ok:true,arrayBuffer:async()=>{throw new DOMException('The user aborted a request.','AbortError');}};}
    return new Response('%PDF-1.4\nSynthetic '+p,{headers:{'Content-Type':'application/pdf'}});
  }
  if(p==='/v1/me/consents')return Response.json({status:'active',consent_id:'synthetic-consent'});
  if(p==='/v1/cases')return Response.json({case_id:'synthetic-case'});
  if(p==='/v1/conversations'){
    if(options.method==='POST')conversation={conversation_id:body.conversation_id,case_id:'synthetic-case',subject_id:'synthetic-subject',title:legacyTitle,created_at:'2026-10-01',updated_at:'2026-10-01'};
    return Response.json(options.method==='POST'?{}:conversation?[conversation]:[]);
  }
  if(conversation&&p==='/v1/conversations/'+conversation.conversation_id)return Response.json({conversation,turns,analysis:{status:'queued',run_id:'synthetic-run'},report:{status:'not_generated',actions:[],sections:[]}});
  if(p.endsWith('/documents')){
    uploadCount++;
    if(uploadCount===2&&failSecond){failSecond=false;return Response.json({message:'合成上传中断'},{status:500});}
    return Response.json({document_id:'synthetic-doc-'+uploadCount});
  }
  if(p.endsWith('/analyses')){
    const submitted={turn_id:'synthetic-turn',request_id:body.request_id,question:body.message,input_kind:'user',status:'completed',answer:{text:'材料已收到',evidence_refs:[],history_refs:[]},attachments:sample.documents.map((document,index)=>({document_id:body.document_ids[index],name:document.name})),tool_events:[{tool:'start_analysis',status:'queued',run_id:'synthetic-run'}]};
    turns=[submitted,{...submitted,turn_id:'ordinary-claim',question:body.message.replace(/^这是一组主办方比赛样例的脱敏体验资料，不代表账号使用者本人病史。/,'')},
      {...submitted,turn_id:'manual-followup',question:'我想确认用户填写的信息和材料分类是否正确。',attachments:[{document_id:'manual-doc',name:'自行补充的合成票据.pdf'}],tool_events:[]}];
    return Response.json({turn_id:'synthetic-turn'});
  }
  throw Error('Unexpected request '+p);
};
let root=createRoot(document.getElementById('root'));
const flush=()=>act(async()=>{await new Promise(r=>setTimeout(r,15));});
const button=text=>[...document.querySelectorAll('button')].find(node=>node.textContent.replace(/\s*→\s*$/,'').trim()===text||node.getAttribute('aria-label')===text);
async function click(text){const node=button(text);assert.ok(node,'Missing button '+text);assert.equal(node.disabled,false);await act(async()=>node.click());await flush();}
try{
  sessionStorage.setItem('zhongan_chat_token','synthetic-judge');
  await act(async()=>root.render(React.createElement(App)));await flush();
  assert.equal(document.querySelectorAll('.judge-sample-card').length,1);
  assert.doesNotMatch(document.body.textContent,/没有病例资料|没有病历资料/);
  assert.ok(!document.querySelector('.judge-sample-card').textContent.includes(sample.notice),'Private source metadata is not product copy');
  assert.equal(document.querySelector('.judge-sample-notice'),null);
  await click('开始评委体验');
  assert.equal(window.location.hash,'#/claim');
  assert.equal(document.querySelector('dialog.member-dialog'),null,'Judge experience selects the test account automatically');
  assert.equal(document.querySelector('.claim-react .judge-sample-card'),null,'No second import card in the claim form');
  assert.equal(document.querySelector('[data-claim-field="diagnosis"]').value,sample.claim_info.diagnosis);
  assert.equal(document.querySelector('[data-claim-field="total"]').value,sample.claim_info.total);
  assert.equal(document.querySelector('[data-claim-action="example"]'),null,'Prepared sample entry does not offer an unrelated placeholder diagnosis');
  assert.doesNotMatch(document.querySelector('.claim-main').textContent,/合成测试信息|演示保单|示例身份|虚构示例|演示占位/);
  assert.match(document.querySelector('[role="alert"]').textContent,/示例资料载入超时/);
  assert.equal(calls.filter(call=>call.method==='POST').length,0);
  await click('重新准备示例资料');
  for(const key of ['diagnosis','start','end','total'])assert.equal(document.querySelector(`[data-claim-field="${key}"]`).value,sample.claim_info[key]);
  const downloads=calls.filter(call=>call.path.startsWith('/judge/sample/files/')).length;
  await act(async()=>{const input=document.querySelector('[data-claim-field="diagnosis"]');input.value='已核对的合成诊断';input.dispatchEvent(new dom.window.Event('input',{bubbles:true}));});
  await act(async()=>document.querySelector('[data-claim-action="exit"]').click());await flush();await click('开始评委体验');
  assert.equal(document.querySelector('[data-claim-field="diagnosis"]').value,'已核对的合成诊断','Re-entry keeps edits and pending sample files');
  assert.equal(calls.filter(call=>call.path.startsWith('/judge/sample/files/')).length,downloads,'Re-entry does not download the same draft twice');
  await click('下一步，上传材料');
  assert.equal(document.querySelectorAll('.claim-file-tile').length,4);
  const groups=document.querySelectorAll('.claim-material');
  assert.equal(groups[0].querySelectorAll('.claim-file-tile').length,3,'Discharge, diagnosis and outpatient files stay in the medical record category');
  assert.equal(groups[1].querySelectorAll('.claim-file-tile').length,1);
  assert.match(document.body.textContent,/尚未提交/);
  assert.equal(calls.filter(call=>call.method==='POST').length,0,'Sample selection must stay in the browser');
  await click('查看合成出院记录.pdf');assert.ok(document.querySelector('iframe.claim-pdf-preview'));
  await click('关闭图片预览');
  await click('下一步，核对申请');
  assert.equal(button('确认提交材料').disabled,true,'Confirmation is required before real upload');
  await act(async()=>document.querySelector('.claim-consent input').click());
  await click('确认提交材料');assert.match(document.body.textContent,/合成上传中断/);
  await click('重试提交');assert.match(document.body.textContent,/本次提交已完成/);
  assert.equal(uploadCount,5,'Retry must preserve the successfully uploaded first file');
  assert.equal(calls.filter(call=>call.path==='/v1/cases').length,1,'Retry retains one case');
  const created=calls.find(call=>call.path==='/v1/cases').body;
  assert.equal(created.data_origin,'official_deidentified');assert.equal(created.user_context.judge_demo,true);
  assert.equal(created.user_context.notice,sample.notice,'Backend source metadata remains intact');
  const uploads=calls.filter(call=>call.path.endsWith('/documents'));
  assert.deepEqual(uploads.map(call=>call.body.get('file').name),['合成出院记录.pdf','合成诊断证明.pdf','合成诊断证明.pdf','合成费用清单.pdf','合成复诊病历.pdf']);
  assert.equal(calls.filter(call=>call.path.endsWith('/analyses')).length,0,'Successful upload must precede analysis');
  await click('查看相关报告');
  const analysis=calls.find(call=>call.path.endsWith('/analyses'));
  assert.equal(analysis.body.document_ids.length,4);assert.match(analysis.body.message,/不代表账号使用者本人病史/);
  assert.match(analysis.body.message,/用户填写的信息：.*已核对的合成诊断.*；材料分类：/,'The backend retains all form context');
  assert.equal(window.location.hash,'#/chat');
  assert.doesNotMatch(document.querySelector('.history-list').textContent,/主办方比赛样例|脱敏体验资料/,'Saved prompt-derived titles are presented naturally');
  const listed=await modules.api.listConversations('synthetic-judge');assert.equal(listed[0].title,'本次就医资料');
  const snapshot=await modules.api.getConversation('synthetic-judge',conversation.conversation_id);assert.equal(snapshot.conversation.title,'本次就医资料');
  const records=await modules.api.listMedicalRecords('synthetic-judge','synthetic-subject');
  const record=records.records[0];assert.equal(record.title,'本次就医资料');assert.equal(record.cases[0].conversations[0].title,'本次就医资料');assert.equal(record.cases[0].proposal_title,'本次就医资料');assert.equal(record.related_records[0].title,'本次就医资料');
  assert.equal(conversation.title,legacyTitle,'Display cleanup does not overwrite saved data');
  const checkChat=()=>{
    const messages=document.querySelector('.messages');assert.ok(messages);
    assert.equal(messages.querySelectorAll('.analysis-continuation').length,2,'Sample and ordinary claim submissions use the concise receipt');
    assert.match(messages.textContent,/材料已提交 · 暖暖为你整理/);
    assert.doesNotMatch(messages.textContent,/主办方比赛样例|用户填写的信息：|材料分类：|个人补充信息|"kind"|合成出院记录\.pdf|合成费用清单\.pdf/,'Internal prompts, JSON and generated attachment lists stay hidden');
    assert.match(messages.textContent,/我想确认用户填写的信息和材料分类是否正确。/,'Normal messages remain visible');
    assert.match(messages.textContent,/自行补充的合成票据\.pdf/,'Normal message attachments remain visible');
    assert.equal(turns[0].question,analysis.body.message,'Presentation does not alter saved analysis context');
  };
  checkChat();
  await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
  await act(async()=>root.render(React.createElement(App)));await flush();
  checkChat();
  await act(async()=>root.unmount());
  root=createRoot(document.getElementById('root'));
  sessionStorage.setItem('zhongan_chat_token','ordinary');window.location.hash='/home';conversation=undefined;
  await act(async()=>root.render(React.createElement(App)));await flush();
  assert.equal(document.querySelector('.judge-sample-card'),null,'Ordinary users do not receive the judge library');
  await click('提交理赔材料');
  await act(async()=>document.querySelector('dialog.member-dialog .member-list button').click());await flush();
  assert.equal(document.querySelector('[data-claim-field="diagnosis"]').value,'','Ordinary claim entry stays blank');
  assert.equal(document.querySelector('.claim-sample-status'),null);
  console.log('PASS: one-click judge entry, upload retry, explicit analysis, concise submission display for new and saved sample/ordinary claims, backend context and manual chat attachments preserved, ordinary account isolation.');
}finally{
  await act(async()=>root.unmount());dom.window.close();URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;
  await modules.close();
}
