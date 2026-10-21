import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {JSDOM} from 'jsdom';
import {loadTestModules} from './test-modules.mjs';
const values=JSON.parse(execFileSync('python',['-c',`import json
from services.api.app.medical_services import MedicalServiceArgs,recommend_services
from services.api.app.service_sessions import ServiceSessionArgs,manage_session
from services.api.app.medical_services import catalog
a=MedicalServiceArgs(routes=['benefits','offline','online'],needs=['followup'],location='上海市浦东新区')
b=MedicalServiceArgs(routes=['offline'],needs=['followup'])
c=MedicalServiceArgs(routes=['online'],needs=['consultation'],condition='oncology',visit_stage='established',location='上海市')
d=MedicalServiceArgs(routes=['online'],needs=['consultation'],online_purpose='followup')
clinical={'routes':['online'],'needs':['consultation']}
benefit=next(x['id'] for x in catalog()['benefits'] if x['need']=='checkup')
def session(previous=None,action='start',mode='benefit',fields=None,question='',department=None,condition='',age=30):
 fields=fields or {}
 args=ServiceSessionArgs(action=action,mode=mode,service_id=benefit,department=department,condition_name=condition,clinical={**clinical,'age_years':age},
  fields=[{'key':k,'value':v} for k,v in fields.items()])
 return manage_session(args,previous,list(fields.values())+[question],question)
bc=session();br=session(bc,'update',fields={'participant':'我本人','city':'上海市','preferred_time':'下周六上午'})
bb=session(br,'confirm',question='确认模拟预约')
dc=session(mode='doctor',department='gastroenterology');dr=session(dc,'update',fields={'symptoms':'胃胀','duration':'两周',
 'current_status':'轻微，没有加重','diagnosis_history':'以前诊断过慢性胃炎','doctor_preference':'消化内科，无特别偏好'})
da=session(dr,'confirm',question='确认接入模拟医生');de=session(da,'end')
variants={}
for disease in ['慢性咽炎','痛经','小儿腹泻','湿疹','腰肌劳损','风寒感冒']:
 age=8 if disease=='小儿腹泻' else 30
 ready=session(mode='doctor',condition=disease,age=age,fields={'symptoms':disease,'duration':'两周',
  'current_status':'稳定，无加重','diagnosis_history':'既往诊断过'+disease,'doctor_preference':'无特别偏好'})
 active=session(ready,'confirm',question='确认接入模拟医生',age=age)
 variants[disease]={'ready':ready,'active':active,'ended':session(active,'end')}
print(json.dumps({'available':recommend_services(a,['上海市浦东新区']),'missing':recommend_services(b,[]),
 'oncology':recommend_services(c,['上海市']),'clinical':recommend_services(d,[]),
 'sessions':{'collect':bc,'ready':br,'booked':bb,'doctor_collect':dc,'doctor_ready':dr,'doctor_active':da,'ended':de},'variants':variants},ensure_ascii=True))`],{cwd:new URL('../../../',import.meta.url),encoding:'utf8'}));
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
const sent=[];let response=values.available,sessionResponse=null,fail=false,release,hold=null;
globalThis.fetch=async(url,options={})=>{
 const path=new URL(url,'http://localhost').pathname;
 if(path==='/judge/sample')return Response.json({}, {status:403});
 if(path==='/v1/me/members')return Response.json([{subject_id:conversation.subject_id,name:'合成体验用户',relationship:'self',gender:'unspecified',birth_date:null,profile_completed:true}]);
 if(path==='/v1/chat/subjects')return Response.json([{subject_id:conversation.subject_id,consent_id:'synthetic-consent'}]);
 if(path==='/v1/conversations')return Response.json([conversation]);
 if(path===`/v1/conversations/${conversation.conversation_id}/messages`){
  const body=JSON.parse(options.body);sent.push(body);if(fail)return Response.json({message:'合成重试'},{status:503});if(hold)await hold;
  snapshot.turns.push({...initial,turn_id:'synthetic-service-'+sent.length,input_kind:'user',question:body.message,request_id:body.request_id,answer:{text:sessionResponse?.speaker==='doctor_simulation'?`这里是${sessionResponse.doctor_profile.label}咨询模拟，请补充目前最想了解的问题。`:'可以，我们先按这次需求看服务和就医地区。',evidence_refs:[],history_refs:[],...(sessionResponse?{service_session:sessionResponse,service_speaker:sessionResponse.speaker}:{medical_services:response})}});
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
  await click(`.chat-turn:last-child .medical-service-${kind} .medical-card-action`);
  assert.equal(document.querySelector('dialog.medical-preview'),null);
  assert.match(sent.at(-1).message,/当前聊天/);
  assert.equal(dom.window.location.hash,'#/chat');
  assert.equal(document.querySelector('.composer textarea').value,'保留的草稿');
 }
 assert.equal(sent.length,4,'Each service continues the current conversation without a modal');
 response=values.missing;await type(document.querySelector('.composer textarea'),'我想找附近适合复查的医院');await click('[aria-label="发送消息"]');
 assert.equal(document.querySelectorAll('.medical-location').length,1);
 await type(document.querySelector('.medical-location input'),'上海市浦东新区');
 fail=true;await act(async()=>document.querySelector('.medical-location').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
 const retry=sent.at(-1);assert.equal(document.querySelector('.medical-location input').value,'上海市浦东新区');
 fail=false;response=values.available;await act(async()=>document.querySelector('.medical-location').dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true})));await flush();
 assert.equal(sent.at(-1).request_id,retry.request_id);assert.match(sent.at(-1).message,/上海市浦东新区/);
 assert.equal(document.querySelector('.medical-location'),null,'Historical location prompts are not interactive after the new answer');
 const before=sent.length;await click('.chat-turn:last-child .medical-service-online .medical-card-action');
 assert.equal(sent.length,before+1);assert.match(sent.at(-1).message,/当前聊天咨询医生/);
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(modules.App)));await flush();
 assert.ok(document.querySelector('.medical-service-online'),'Persisted answers restore service cards');
 assert.equal(document.querySelector('.medical-preview'),null,'Preview state is not restored across sessions');
 response=values.oncology;await type(document.querySelector('.composer textarea'),'我想找肿瘤专科');await click('[aria-label="发送消息"]');
 let latest=document.querySelector('.chat-turn:last-child');
 assert.match(latest.textContent,/肿瘤相关需求优先线下专科/);
 assert.match(latest.textContent,/复旦大学附属肿瘤医院/);
 assert.match(latest.textContent,/历史名单/);
 assert.equal(latest.querySelector('.medical-service-online'),null);
 response=values.clinical;await type(document.querySelector('.composer textarea'),'我想线上复诊');await click('[aria-label="发送消息"]');
 latest=document.querySelector('.chat-turn:last-child');
 assert.match(latest.textContent,/是否已由线下医生明确诊断/);
 assert.equal(latest.querySelector('.medical-service-online'),null);
 const say=async(text)=>{await type(document.querySelector('.composer textarea'),text);await click('[aria-label="发送消息"]');};
 sessionResponse=values.sessions.collect;await say('想预约体检');
 assert.ok(document.querySelector('.chat-turn:last-child .service-session-collecting'));
 assert.equal(document.querySelector('.chat-turn:last-child .service-session-actions button:not(.service-session-return)'),null);
 sessionResponse=values.sessions.ready;await say('我本人，在上海市，下周六上午');
 assert.match(document.querySelector('.chat-turn:last-child .service-session').textContent,/下周六上午/);
 assert.doesNotMatch(document.querySelector('.chat-turn:last-child').textContent,/DEMO-/);
 const previousCount=sent.length;sessionResponse=values.sessions.booked;
 hold=new Promise(resolve=>{release=resolve;});await click('.chat-turn:last-child .service-session-actions button');
 assert.ok([...document.querySelectorAll('.service-session-actions button')].every(button=>button.disabled));
 await act(async()=>release());hold=null;await flush();
 assert.equal(sent.length,previousCount+1);assert.equal(sent.at(-1).message,'确认模拟预约');
 assert.match(document.querySelector('.chat-turn:last-child').textContent,/模拟预约已完成/);
 assert.match(document.querySelector('.chat-turn:last-child').textContent,/DEMO-/);
 assert.equal(document.querySelector('dialog.medical-preview'),null);
 sessionResponse=values.sessions.doctor_collect;await say('我想咨询肠胃医生');
 assert.equal(document.querySelector('.doctor-chat-status'),null);
 sessionResponse=values.sessions.doctor_ready;await say('胃胀两周，比较轻，确诊过胃炎，想找消化内科医生，无特别偏好');
 assert.match(document.querySelector('.chat-turn:last-child .service-session').textContent,/胃胀/);
 sessionResponse=values.sessions.doctor_active;await click('.chat-turn:last-child .service-session-actions button');
 assert.equal(sent.at(-1).message,'确认接入模拟医生');
 assert.match(document.querySelector('.chat-turn:last-child .nuan-reply-label').textContent,/内科.*消化方向医生.*AI模拟.*无真人接入/);
 assert.ok(document.querySelector('.doctor-chat-status'));
 assert.match(document.querySelector('.composer textarea').placeholder,/模拟医生/);
 await say('吃完饭后会更明显');
 assert.ok(document.querySelector('.chat-turn:last-child .doctor-simulation-row'));
 await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));
 await act(async()=>root.render(React.createElement(modules.App)));await flush();
 assert.ok(document.querySelector('.doctor-chat-status'),'Doctor simulation continues after reopening the conversation');
 sessionResponse=values.sessions.ended;await click('.doctor-chat-status button');
 assert.equal(document.querySelector('.doctor-chat-status'),null);
 assert.match(document.querySelector('.chat-turn:last-child .nuan-reply-label').textContent,/暖暖/);
 for(const [disease,variant] of Object.entries(values.variants)){
  sessionResponse=variant.ready;await say(`想咨询${disease}相关问题，已补充情况，请核对`);
  sessionResponse=variant.active;await click('.chat-turn:last-child .service-session-actions button');
  const label=document.querySelector('.chat-turn:last-child .nuan-reply-label').textContent;
  assert.ok(label.includes(variant.active.doctor_profile.label),`${disease}: server-selected direction is rendered`);
  assert.ok(!label.includes('消化方向'),`${disease}: must not reuse gastro role`);
  assert.match(document.querySelector('.chat-turn:last-child .service-doctor-scope').textContent,/未核实实时医生/);
  assert.ok(document.querySelector('.chat-turn:last-child .service-doctor-scope a[href^="https:"]'));
  if(disease==='湿疹')assert.match(label,/全科.*皮肤问题分诊/);
  sessionResponse=variant.ended;await click('.doctor-chat-status button');
 }
 assert.equal(dom.window.location.hash,'#/chat');
 console.log('PASS: inline booking, doctor handoff, six additional source-backed consultation directions, scope/source display, role restoration, and return to assistant. Backend-generated simulation fixtures; no provider calls.');
}finally{if(root)await act(async()=>root.unmount());await modules.close();dom.window.close();}
