import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import React,{act,useState} from 'react';
import {loadTestModules} from './test-modules.mjs';
const dom=new JSDOM('<div id="root"></div>',{url:'http://localhost/#/records'});
for(const key of ['window','document','sessionStorage','localStorage','HTMLElement'])globalThis[key]=dom.window[key];
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
dom.window.HTMLDialogElement.prototype.showModal=function(){this.open=true;};dom.window.HTMLDialogElement.prototype.close=function(){this.open=false;};
const {createRoot}=await import('react-dom/client'),modules=await loadTestModules();
const ref='00000000-0000-4000-8000-000000000001';
const member={subject_id:'self',name:'合成用户',relationship:'self',profile_completed:true};
const family={...member,subject_id:'family',name:'合成家人',relationship:'parent'};
const value=text=>({value:text,evidence_refs:[ref]});
const batch=(id,profile,extra={})=>({case_id:id,profile,conversations:[{conversation_id:'chat-'+id,title:'查看报告-'+id,case_id:id,subject_id:'self'}],updated_at:'2026-10-14T08:00:00Z',document_count:1,version:2,relation:'new_episode',analysis_status:'completed',organization_status:'ready',assignment_source:'ai',...extra});
const stay=batch('stay',{diagnosis:value('肺炎'),hospital:value('合成医院'),period:value('2026年9月20日至25日')});
const follow=batch('follow',{diagnosis:value('肺炎恢复期'),period:value('2026年10月1日')},{relation:'follow_up'});
const recurrence=batch('recurrence',{diagnosis:value('肺炎'),period:value('2026年10月20日')});
const injury=batch('injury',{diagnosis:value('桡骨骨折'),kind:value('门诊病历')});
const uncertain=batch('uncertain',{diagnosis:value('疑似肺炎')},{relation:'uncertain',organization_status:'needs_confirmation',proposed_record_id:'r-stay',proposal_title:'肺炎的这次治疗',reason:'缺少明确的原治疗日期，请确认是否为本次复诊。'});
const record=(id,title,cases,extra={})=>({record_id:id,title,cases,subject_id:'self',updated_at:'2026-10-14T08:00:00Z',document_count:cases.length,conversation_count:cases.length,related_records:[],...extra});
const first={records:[record('r-stay','肺炎的这次治疗',[follow,stay],{portrait:{...stay.profile,...follow.profile},related_records:[{record_id:'r-recurrence',title:'新一轮肺炎治疗'}]}),record('r-injury','摔伤门诊',[injury]),record('r-recurrence','新一轮肺炎治疗',[recurrence],{related_records:[{record_id:'r-stay',title:'肺炎的这次治疗'}]}),record('r-uncertain','待确认的复诊资料',[uncertain])],unorganized_count:1,processing_count:0};
let data=structuredClone(first),failure=false,delay=null,sourceDelay=null,patches=[],organizes=[],opened=[];
globalThis.fetch=async(url,options={})=>{
  const parsed=new URL(url,'http://localhost');
  if(parsed.pathname==='/v1/medical-records'){
    if(parsed.searchParams.get('subject_id')==='family')return Response.json({records:[],unorganized_count:0,processing_count:0});
    if(delay)return delay;
    return failure?Response.json({message:'合成读取失败'},{status:400}):Response.json(data);
  }
  if(parsed.pathname==='/v1/medical-records/organize'){organizes.push(JSON.parse(options.body));data.processing_count=1;return Response.json({queued_count:1});}
  if(parsed.pathname.startsWith('/v1/medical-records/cases/')){
    const body=JSON.parse(options.body);patches.push({path:parsed.pathname,body});
    data=structuredClone(first);data.records=data.records.filter(r=>r.record_id!=='r-uncertain');data.records[0].cases.push({...uncertain,assignment_source:'user',organization_status:'ready',proposed_record_id:null});data.records[0].document_count=3;
    return Response.json({version:3});
  }
  if(parsed.pathname==='/v1/evidence/'+ref)return sourceDelay||Response.json({evidence_id:ref,document_id:'doc',document_version:1,page_index:0,text_span:{text:'合成病历原文：疑似肺炎，具体治疗经过需核对。'}});
  throw Error('Unexpected fixture request '+url);
};
const root=createRoot(document.getElementById('root')),flush=()=>act(async()=>{await new Promise(r=>setTimeout(r,20));});
function Harness({person=member}){const [selected,setSelected]=useState();return React.createElement(modules.PersonalRecords,{key:person.subject_id,token:'synthetic',member:person,selected,onSelect:setSelected,busy:false,onOpen:id=>opened.push(id),onNew:()=>{},onAccount:()=>{}});}
const button=(text,scope=document)=>[...scope.querySelectorAll('button')].find(node=>node.textContent.trim()===text);
async function click(node){assert.ok(node);assert.equal(node.disabled,false);await act(async()=>node.click());await flush();}
try{
  await act(async()=>root.render(React.createElement(Harness)));await flush();
  assert.equal(document.querySelectorAll('.medical-record-card').length,4);
  const firstCard=document.querySelector('.medical-record-card');assert.match(firstCard.textContent,/肺炎恢复期/);assert.match(firstCard.textContent,/合成医院/,'A later report enriches the portrait without dropping earlier supported fields');
  assert.match(firstCard.textContent,/2 批资料持续汇集/);assert.equal(organizes.length,0,'Reading records does not launch paid organization');
  await click(button('肺炎的这次治疗'));
  assert.equal(document.querySelectorAll('.medical-record-batch').length,2);assert.match(document.body.textContent,/后续复诊/);
  await click(button('查看报告-stay'));assert.deepEqual(opened,['chat-stay'],'Every original report remains reachable');
  await click(document.querySelector('.medical-record-profile .source-ref'));assert.match(document.querySelector('dialog').textContent,/疑似肺炎/);await click(document.querySelector('[aria-label="关闭原始依据"]'));
  await click(button('新一轮肺炎治疗'));assert.equal(document.querySelectorAll('.medical-record-batch').length,1,'A recurrence is a separate episode');
  await click(button('‹ 返回就医记录'));await click(button('关联历程'));assert.equal(document.querySelectorAll('.medical-record-card').length,2);await click(button('全部'));
  await click(button('待确认的复诊资料'));await click(button('确认资料归属'));
  assert.equal(document.querySelector('select').value,'r-stay');await click(button('确认归属'));
  assert.deepEqual(patches,[{path:'/v1/medical-records/cases/uncertain',body:{mode:'join',target_record_id:'r-stay',expected_version:2}}]);
  assert.equal(document.querySelectorAll('.medical-record-card').length,3);assert.match(document.querySelector('.medical-record-card').textContent,/3 批资料持续汇集/);
  await click(button('智能整理已有记录'));assert.deepEqual(organizes,[{subject_id:'self'}]);assert.match(document.body.textContent,/暖暖正在整理/);
  data.processing_count=0;data.unorganized_count=0;await act(async()=>{await new Promise(r=>setTimeout(r,4100));});await flush();assert.equal(button('智能整理已有记录'),undefined);
  failure=true;await act(async()=>window.dispatchEvent(new dom.window.Event('focus')));await flush();assert.match(document.body.textContent,/合成读取失败/);failure=false;await click(button('重新加载'));
  let resolve;delay=new Promise(r=>resolve=r);await act(async()=>window.dispatchEvent(new dom.window.Event('focus')));await flush();
  await act(async()=>root.render(React.createElement(Harness,{person:family})));await flush();assert.match(document.body.textContent,/合成家人/);assert.match(document.body.textContent,/还没有就医记录/);
  await act(async()=>resolve(Response.json(first)));await flush();delay=null;assert.doesNotMatch(document.body.textContent,/肺炎的这次治疗/,'A stale member response cannot overwrite the selected person');
  await act(async()=>root.render(React.createElement(Harness)));await flush();
  let resolveSource;sourceDelay=new Promise(r=>resolveSource=r);await click(document.querySelector('.medical-record-card .source-ref'));
  await act(async()=>root.render(React.createElement(Harness,{person:family})));await flush();await act(async()=>resolveSource(Response.json({evidence_id:ref,text_span:{text:'上个成员的旧依据'}})));await flush();
  assert.equal(document.querySelector('dialog.source-sheet'),null);
  console.log('PASS: cumulative portrait, supplemental/follow-up grouping, separate related recurrence, original reports and sources, uncertainty confirmation, optimistic versioned correction, explicit historical organization, polling, error recovery and stale member/source suppression. Synthetic fixtures only.');
}finally{await act(async()=>root.unmount());await modules.close();dom.window.close();}
