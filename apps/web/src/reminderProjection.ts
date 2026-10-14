import {actionTime,patientActions,publishedCare,visibleSections} from './carePresentation';
import type {ChatSnapshot,ReportSection} from './types';

export type HomeReminder={
  id:string;text:string;label:string;time?:string;refs:string[];
  section:ReportSection['section_type'];
};

function reminderLabel(text:string) {
  const visit=/复诊|复查|随访|回院|就诊/.test(text);
  const medication=/服药|服用|用药|口服|餐前|餐后|饭前|饭后|注射|外用|吸入|滴眼|滴鼻|滴耳/.test(text);
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
