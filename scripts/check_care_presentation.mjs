import assert from 'node:assert/strict';
import {publishedCare,visibleSections,patientActions,actionTime,careStatus,encounterGroups} from '../apps/web/src/carePresentation.ts';

const claim={claim_id:'synthetic-claim',text:'SYNTHETIC ONLY',review_status:'approved',claim_type:'case_fact',evidence_refs:['synthetic-evidence']};
const action={action_id:'action-a',report_id:'report-a',owner_role:'patient',status:'proposed',source_refs:['synthetic-evidence'],
  due_at:null,due_source:'unknown',priority:2,action_text:'synthetic action',rationale:'synthetic rationale'};
const report={status:'published',report_id:'report-a',report_version:1,sections:[{section_type:'diagnosis_explanation',claims:[claim]}],actions:[action]};
assert.equal(publishedCare(report),true);
for(const status of ['ready','pending_review','not_released','not_generated']){
  const hidden={...report,status};
  assert.equal(publishedCare(hidden),false);
  assert.deepEqual(visibleSections(hidden),[]);
  assert.deepEqual(patientActions(hidden),[]);
}
assert.equal(publishedCare({...report,report_id:undefined}),false);
assert.equal(publishedCare({...report,report_version:0}),false);
assert.deepEqual(visibleSections({...report,sections:[{section_type:'cost_explanation',claims:[{...claim,review_status:'pending'}]}]}),[]);
assert.equal(visibleSections({...report,sections:[{section_type:'cost_explanation',claims:[{...claim,review_status:'corrected'}]}]}).length,1);
const actions=[action,{...action,action_id:'action-b',priority:1},
  {...action,action_id:'foreign',report_id:'report-b'}, {...action,action_id:'doctor',owner_role:'clinician'},
  {...action,action_id:'done',status:'completed'}, {...action,action_id:'cancelled',status:'cancelled'},
  {...action,action_id:'unsupported',source_refs:[]}];
assert.deepEqual(patientActions({...report,actions}).map(x=>x.action_id),['action-b','action-a']);
assert.equal(actions[0].action_id,'action-a'); // Rendering never mutates authoritative order.
assert.equal(actionTime(action),'时间待确认');
assert.equal(actionTime({...action,due_at:'2026-10-12T08:00:00+08:00'}),'时间待确认');
assert.equal(actionTime({...action,due_at:'invalid',due_source:'medical_order'}),'时间待确认');
assert.notEqual(actionTime({...action,due_at:'2026-10-12T08:00:00+08:00',due_source:'medical_order'}),'时间待确认');
assert.match(careStatus({report:{status:'not_released'},analysis:{status:'completed'}}).title,/核对/);
assert.match(careStatus({report:{status:'not_generated'},analysis:{status:'running'}}).title,/正在/);
assert.match(careStatus({report:{status:'not_generated'},analysis:{status:'failed'}}).title,/没有完成/);
const conversations=[
  {case_id:'case-a',conversation_id:'a-old',title:'same title',updated_at:'2026-10-03T12:00:00+08:00'},
  {case_id:'case-b',conversation_id:'b',title:'same title',updated_at:'2026-10-03T05:30:00Z'},
  {case_id:'case-a',conversation_id:'a-new',title:'other chat',updated_at:'2026-10-03T06:00:00Z'},
];
const groups=encounterGroups(conversations);
assert.deepEqual(groups.map(group=>group.case_id),['case-a','case-b']);
assert.deepEqual(groups[0].items.map(item=>item.conversation_id),['a-new','a-old']);
assert.equal(conversations[0].conversation_id,'a-old');
assert.deepEqual(encounterGroups([]),[]);
console.log('PASS: published/approved visibility; report-bound patient actions; unknown due dates; analysis states; case-ID grouping with time-zone-aware order. Synthetic projection tests only.');
