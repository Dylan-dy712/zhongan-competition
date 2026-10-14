import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act} from 'react';
import {loadTestModules} from './test-modules.mjs';

const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/home'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
globalThis.requestAnimationFrame=callback=>setTimeout(callback,0);
dom.window.HTMLElement.prototype.scrollIntoView=function(){};
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const {createRoot}=await import('react-dom/client');
const modules=await loadTestModules();
const person={subject_id:'self',name:'合成本人',relationship:'self',profile_completed:true};
const family={...person,subject_id:'family',name:'合成家人',relationship:'parent'};
const conversation=(id,subject,date)=>({conversation_id:id,subject_id:subject,case_id:`case-${id}`,title:`合成就医-${id}`,updated_at:`2026-10-${date}T09:00:00+08:00`,created_at:`2026-10-${date}T09:00:00+08:00`,recall_enabled:false});
const old=conversation('old','self','10'),latest=conversation('latest','self','14'),blank=conversation('blank','self','15'),other=conversation('family','family','16');
const ref='00000000-0000-4000-8000-000000000001';
const followup='出院医嘱：2026年10月20日上午复诊，携带出院小结。';
const medication='合成用药甲：每次1片，每日2次，饭后口服，连续3天。';
const action={action_id:'action',report_id:'report',owner_role:'patient',status:'proposed',priority:1,action_text:'按医嘱复诊',source_refs:[ref],due_at:null,due_source:'unknown'};
const state=(record,medical=true)=>({conversation:record,turns:[],analysis:medical?{status:'waiting_review',run_id:`run-${record.conversation_id}`}:{status:'not_started'},report:{status:'not_released'},
  material_report:medical?{status:'available',run_id:`run-${record.conversation_id}`,sections:[
    {section_type:'next_visit_advice',items:[{text:record===latest?followup:'旧记录或家人的复诊安排',kind:'source',evidence_refs:[ref]}]},
    {section_type:'recovery_plan',items:[{text:medication,kind:'checked',evidence_refs:[ref]}]}
  ]}:undefined});
let latestState=state(latest),records=[old,other,blank,latest],failList=false,deferredList=null,deferredSnapshot=null,deferredSource=null;
const requests=[];
globalThis.fetch=async(url)=>{
  const parsed=new URL(url,'http://localhost'),path=parsed.pathname;requests.push(parsed);
  if(path==='/v1/me/members')return Response.json([person,family]);
  if(path==='/v1/chat/subjects')return Response.json([{subject_id:'self',consent_id:'consent'}]);
  if(path==='/v1/conversations'){
    if(parsed.search&&deferredList)return deferredList;
    if(parsed.search&&failList)return Response.json({message:'合成提醒读取失败'},{status:400});
    return Response.json(records);
  }
  if(path==='/v1/conversations/old')return Response.json(state(old));
  if(path==='/v1/conversations/blank')return Response.json(state(blank,false));
  if(path==='/v1/conversations/latest')return deferredSnapshot||Response.json(latestState);
  if(path==='/v1/conversations/family')return Response.json(state(other));
  if(path===`/v1/evidence/${ref}`)return deferredSource||Response.json({evidence_id:ref,document_id:'synthetic-doc',document_version:1,page_index:0,text_span:{text:followup}});
  throw new Error('Unexpected synthetic request '+url);
};
const flush=()=>act(async()=>{await new Promise(resolve=>setTimeout(resolve,25));});
const card=()=>document.querySelector('.home-reminders');
const button=text=>[...document.querySelectorAll('button')].find(node=>!node.closest('[hidden]')&&node.textContent.trim()===text);
async function click(node){assert.ok(node);await act(async()=>node.click());await flush();}
let root=createRoot(document.getElementById('root'));
async function render(member=person){await act(async()=>root.render(React.createElement(modules.HomeReminders,{key:member.subject_id,token:'synthetic-only',member,onOpen:()=>{},onClaim:()=>{}})));await flush();}
try {
  sessionStorage.setItem('zhongan_chat_token','synthetic-only');localStorage.setItem('zhongan_last_conversation','old');
  await act(async()=>root.render(React.createElement(modules.App)));await flush();
  assert.match(card().textContent,/2026年10月20日上午复诊/);
  assert.ok(card().textContent.includes(medication),'Full dosage, frequency, meals and duration remain unchanged');
  assert.doesNotMatch(card().textContent,/旧记录或家人的复诊安排/);
  assert.match(card().textContent,/合成本人/);
  assert.ok(requests.some(request=>request.searchParams.get('subject_id')==='self'),'Reminder reads must be scoped to selected member');
  assert.ok(requests.some(request=>request.pathname.endsWith('/blank')),'Newer empty chat is checked and skipped');
  await click(card().querySelector('.source-ref'));
  assert.match(document.querySelector('dialog.source-sheet').textContent,/2026年10月20日上午复诊/);
  await click(document.querySelector('[aria-label="关闭原始依据"]'));
  await click(button('核对本次安排'));
  assert.equal(window.location.hash,'#/chat');
  assert.match(document.querySelector('.history-list .selected').textContent,/合成就医-latest/,'Reminder opens its own record, not the remembered chat');
  await act(async()=>root.unmount());root=createRoot(document.getElementById('root'));

  const {homeReminders}=modules.reminderProjection;
  const published={...latestState,report:{status:'published',report_id:'report',report_version:1,sections:[],actions:[action,{...action,action_id:'done',status:'completed',action_text:'已完成的服药安排'},{...action,action_id:'foreign',report_id:'foreign'}]}};
  assert.deepEqual(homeReminders(published).map(item=>item.id),['action']);
  assert.equal(homeReminders(published)[0].time,'时间待确认');
  assert.deepEqual(homeReminders({...published,report:{...published.report,actions:[{...action,status:'cancelled'}]}}),[]);
  assert.deepEqual(homeReminders({...latestState,material_report:{...latestState.material_report,run_id:'old-run'}}),[]);
  assert.deepEqual(homeReminders({...latestState,material_report:{...latestState.material_report,status:'outdated'}}),[]);
  assert.deepEqual(homeReminders({...latestState,material_report:{...latestState.material_report,sections:[{section_type:'treatment_review',items:[{text:'住院期间口服合成用药乙',kind:'source',evidence_refs:[ref]}]}]}}),[]);
  assert.deepEqual(homeReminders({...latestState,material_report:{...latestState.material_report,sections:[{section_type:'recovery_plan',items:[{text:medication,kind:'checked',evidence_refs:[]}]}]}}),[]);
  const relative={...latestState,material_report:{...latestState.material_report,sections:[{section_type:'next_visit_advice',items:[{text:'出院后一周复诊，具体日期待确认。',kind:'source',evidence_refs:[ref]}]}]}};
  assert.equal(homeReminders(relative)[0].text,'出院后一周复诊，具体日期待确认。');assert.equal(homeReminders(relative)[0].time,undefined);
  const drops={...latestState,material_report:{...latestState.material_report,sections:[{section_type:'recovery_plan',items:[{text:'合成滴眼医嘱：按原处方滴眼，频次待确认。',kind:'source',evidence_refs:[ref]}]}]}};
  assert.equal(homeReminders(drops)[0].label,'用药医嘱');

  await render();
  latestState={...latestState,material_report:{...latestState.material_report,sections:[{section_type:'next_visit_advice',items:[{text:'最新医嘱：2026年10月22日复诊。',kind:'source',evidence_refs:[ref]}]}]}};
  await act(async()=>window.dispatchEvent(new dom.window.Event('focus')));await flush();
  assert.match(card().textContent,/2026年10月22日复诊/,'Focus refresh reads current instructions');

  failList=true;await act(async()=>window.dispatchEvent(new dom.window.Event('focus')));await flush();
  assert.match(card().textContent,/合成提醒读取失败/);assert.doesNotMatch(card().textContent,/尚无就医材料/);
  failList=false;await click(button('重新加载提醒'));assert.match(card().textContent,/2026年10月22日复诊/);

  let resolveSnapshot;deferredSnapshot=new Promise(resolve=>resolveSnapshot=resolve);
  await act(async()=>window.dispatchEvent(new dom.window.Event('focus')));await flush();
  records=[];await render(family);assert.match(card().textContent,/合成家人/);assert.match(card().textContent,/尚无就医材料/);
  await act(async()=>resolveSnapshot(Response.json(latestState)));await flush();deferredSnapshot=null;
  assert.doesNotMatch(card().textContent,/2026年10月22日复诊/,'Late response cannot replace another member reminders');

  let resolveList;deferredList=new Promise(resolve=>resolveList=resolve);await render();
  assert.match(card().textContent,/正在读取/);assert.doesNotMatch(card().textContent,/尚无就医材料/,'Loading must not masquerade as no records');
  await act(async()=>resolveList(Response.json([])));await flush();deferredList=null;
  assert.match(card().textContent,/尚无就医材料/);
  records=[latest];latestState={...latestState,analysis:{status:'running',run_id:'run-latest'},material_report:{status:'running'}};
  await act(async()=>window.dispatchEvent(new dom.window.Event('focus')));await flush();assert.match(card().textContent,/正在整理本次医嘱/);
  latestState=state(latest);await act(async()=>{await new Promise(resolve=>setTimeout(resolve,3600));});await flush();
  assert.match(card().textContent,/2026年10月20日上午复诊/,'In-progress instructions update when processing finishes');

  let resolveSource;deferredSource=new Promise(resolve=>resolveSource=resolve);await click(card().querySelector('.source-ref'));
  records=[];await render(family);await act(async()=>resolveSource(Response.json({evidence_id:ref,text_span:{text:'旧成员原文'}})));await flush();
  assert.equal(document.querySelector('dialog.source-sheet'),null,'Late evidence must not reopen after member switch');
  console.log('PASS: latest medical record binding; remembered/empty chats; member isolation; exact follow-up and medication text; source links and correct record navigation; current-run visibility; completed action filtering; loading/error/retry, focus/processing refresh and stale response suppression. Synthetic fixtures only.');
} finally {await act(async()=>root.unmount());await modules.close();dom.window.close();}
