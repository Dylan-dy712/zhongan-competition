import {actionTime,patientActions,publishedCare,visibleSections} from './carePresentation';
import type {ChatSnapshot,MedicalRecord,ReportSection} from './types';
import {isClaimSubmission} from './claimChatPresentation';

export type HomeReminder={
  id:string;text:string;label:string;time?:string;refs:string[];
  section:ReportSection['section_type'];
};

function reminderLabel(text:string) {
  const visit=/复诊|复查|随访|回院|就诊/.test(text);
  const medication=/服药|服用|用药|药物|处方|停药|换药|口服|餐前|餐后|饭前|饭后|注射|外用|吸入|滴眼|滴鼻|滴耳/.test(text);
  return visit&&medication?'复诊与用药':visit?'复诊安排':medication?'用药医嘱':undefined;
}

/** Preserve source wording, including relative dates, doses and uncertainty. */
export function homeReminders(snapshot:ChatSnapshot):HomeReminder[] {
  if(publishedCare(snapshot.report)) {
    const actions=patientActions(snapshot.report).flatMap(action=>{
      const label=reminderLabel(action.action_text);
      return label?[{id:action.action_id,text:action.action_text,label,time:actionTime(action),refs:action.source_refs,
        section:(label==='用药医嘱'?'recovery_plan':'next_visit_advice') as ReportSection['section_type']}]:[];
    });
    // Completed/cancelled actions must not reappear through a source-text fallback.
    if(snapshot.report.actions?.length)return actions;
    return visibleSections(snapshot.report).filter(section=>['next_visit_advice','recovery_plan'].includes(section.section_type))
      .flatMap(section=>section.claims.flatMap(claim=>{
        const label=reminderLabel(claim.text),refs=[...claim.evidence_refs,...(claim.source_refs||[])];
        return label&&refs.length?[{id:claim.claim_id,text:claim.text,label,refs,section:section.section_type}]:[];
      }));
  }
  const material=snapshot.material_report;
  if(material?.status!=='available' || (snapshot.analysis.run_id&&material.run_id!==snapshot.analysis.run_id))return [];
  const seen=new Set<string>();
  return (material.sections||[]).filter(section=>['next_visit_advice','recovery_plan'].includes(section.section_type))
    .flatMap(section=>section.items.flatMap((item,index)=>{
      const label=reminderLabel(item.text);
      if(!label || !item.evidence_refs.length || !['checked','source'].includes(item.kind) || seen.has(item.text))return [];
      seen.add(item.text);
      return [{id:`${section.section_type}:${index}`,text:item.text,label,refs:item.evidence_refs,section:section.section_type}];
    }));
}

export function hasMedicalRecord(snapshot:ChatSnapshot) {
  return !!snapshot.analysis.run_id || publishedCare(snapshot.report) || snapshot.material_report?.status==='available'
    || snapshot.turns.some(turn=>turn.attachments?.length>0);
}

export type MemberReminder=HomeReminder&{conversationId?:string;destination:'chat'|'report';sourceLabel:string};

/** Combine sourced instructions and recent concerns without turning chat into a prescription. */
export function memberReminders(snapshots:ChatSnapshot[],records:MedicalRecord[]):MemberReminder[] {
  const ordered=[...snapshots].sort((a,b)=>Date.parse(b.conversation.updated_at)-Date.parse(a.conversation.updated_at));
  const seenCases=new Set<string>(),seenText=new Set<string>(),instructions:MemberReminder[]=[];
  for(const snapshot of ordered){
    const caseId=snapshot.conversation.case_id;
    if(seenCases.has(caseId))continue;
    // A new run invalidates older extraction; completed/cancelled actions remain suppressed.
    seenCases.add(caseId);
    const sameRun=ordered.filter(item=>item.conversation.case_id===caseId
      &&(!snapshot.analysis.run_id||item.analysis.run_id===snapshot.analysis.run_id));
    for(const candidate of sameRun){
      const rows=homeReminders(candidate),published=publishedCare(candidate.report);
      if(rows.length){
        for(const row of rows){
          const key=row.text.normalize('NFKC').replace(/\s+/g,'');
          if(seenText.has(key))continue;seenText.add(key);
          instructions.push({...row,id:`${caseId}:${row.id}`,conversationId:candidate.conversation.conversation_id,
            destination:published?'report':'chat',sourceLabel:published?'已发布的关怀安排':'就医材料中的安排'});
        }
        break;
      }
      if(published&&candidate.report.actions?.length)break;
    }
  }
  // Give both follow-up and medication a place when multiple records contain instructions.
  const result:MemberReminder[]=[];
  const add=(row:MemberReminder|undefined)=>{if(row&&!result.some(item=>item.id===row.id))result.push(row);};
  add(instructions.find(row=>row.label.includes('复诊')));
  add(instructions.find(row=>row.label.includes('用药')));
  for(const row of instructions)if(result.length<3)add(row);
  for(const snapshot of ordered){
    if(result.length>=3)break;
    const concern=[...snapshot.turns].reverse().find(turn=>turn.input_kind==='user'&&!isClaimSubmission(turn)&&reminderLabel(turn.question));
    if(!concern)continue;
    const medication=/服药|服用|用药|药物|处方|口服|停药|换药/.test(concern.question);
    const label=medication?'用药待核对':'复诊待核对';
    if(result.some(row=>row.label===label))continue;
    add({id:`concern:${snapshot.conversation.conversation_id}`,label,
      text:medication?'你最近提到了用药问题。可回到这次对话继续核对，具体药名、剂量与疗程以处方或医生确认的内容为准。':'你最近提到了复诊安排。可回到这次对话核对时间、地点和需要携带的材料。',
      refs:[],section:medication?'recovery_plan':'next_visit_advice',conversationId:snapshot.conversation.conversation_id,destination:'chat',sourceLabel:'近期沟通 · 待核对'});
  }
  const record=[...records].sort((a,b)=>Date.parse(b.updated_at)-Date.parse(a.updated_at))[0];
  const profile=record?.portrait||record?.cases.find(batch=>Object.keys(batch.profile||{}).length)?.profile;
  const context=profile?.diagnosis?.evidence_refs.length?profile.diagnosis:profile?.hospital?.evidence_refs.length?profile.hospital:undefined;
  const related=record?.cases.flatMap(batch=>batch.conversations).find(conversation=>ordered.some(snapshot=>snapshot.conversation.conversation_id===conversation.conversation_id));
  const preparation:MemberReminder={id:'followup-preparation',label:'复诊准备',
    text:context?`结合资料中的「${context.value}」，下次就诊前可整理好近期病历、检查结果与想问医生的问题。`:'下次就诊前，可整理好近期病历、检查结果和想问医生的问题；复诊时间以医生确认的安排为准。',
    refs:context?.evidence_refs||[],section:'next_visit_advice',conversationId:related?.conversation_id,destination:'chat',sourceLabel:context?'结合你的就医档案':'就医准备'};
  if(result.length<3&&context)add(preparation);
  if(!result.some(row=>row.label.includes('复诊')))add(preparation);
  if(!result.some(row=>row.label.includes('用药'))&&result.length<3)add({id:'medication-preparation',label:'用药核对',
    text:'如果有正在使用的药物，可备好处方或药品信息，核对药名、剂量、频次和疗程；不清楚的地方向医生或药师确认。',
    refs:[],section:'recovery_plan',destination:'chat',sourceLabel:'用药准备'});
  return result.slice(0,3);
}
