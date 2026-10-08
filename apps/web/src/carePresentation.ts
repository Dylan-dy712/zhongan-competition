import type {CareAction, ChatSnapshot, Conversation, ReportSection} from './types';

export const careSectionLabels: Record<ReportSection['section_type'],string> = {
  diagnosis_explanation:'这次看病怎么回事', treatment_review:'治疗经过', cost_explanation:'这次看病的费用',
  recovery_plan:'回家后的安排', emotional_support:'也照顾一下自己的心情', next_visit_advice:'下次就医准备',
};
export type CarePanel = 'home'|'chat'|'report'|'records'|'claim'|'account';
export function publishedCare(report: ChatSnapshot['report']) {
  return report.status==='published' && !!report.report_id && Number.isInteger(report.report_version)
    && report.report_version!>0 && Array.isArray(report.sections);
}
export function visibleSections(report: ChatSnapshot['report']) {
  if(!publishedCare(report))return [];
  return report.sections!.map(section=>({...section,claims:section.claims.filter(claim=>
    ['approved','corrected','not_required'].includes(claim.review_status))})).filter(section=>section.claims.length);
}
export function patientActions(report: ChatSnapshot['report']):CareAction[] {
  if(!publishedCare(report))return [];
  return (report.actions || []).filter(action=>action.report_id===report.report_id
    && ['patient','caregiver'].includes(action.owner_role) && ['proposed','acknowledged','help_requested'].includes(action.status)
    && action.source_refs.length>0).sort((a,b)=>a.priority-b.priority || a.action_id.localeCompare(b.action_id));
}
export function actionTime(action:CareAction) {
  if(!action.due_at || action.due_source==='unknown' || !Number.isFinite(Date.parse(action.due_at)))return '时间待确认';
  return new Date(action.due_at).toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',timeZoneName:'short'});
}
export function careStatus(snapshot:ChatSnapshot) {
  if(snapshot.material_report?.status==='available')return {title:'材料已整理，暖暖在对话里为你解读',text:'结合你实际上传的材料，一件一件说清楚。'};
  if(snapshot.material_report?.status==='failed')return {title:'报告生成暂时没有完成',text:'材料已保存，回到对话可以重新分析。'};
  if(publishedCare(snapshot.report))return {title:'这次关怀，已经准备好',text:'先看最关心的一件事，也可以展开资料依据。'};
  if(snapshot.analysis.status==='failed')return {title:'材料分析暂时没有完成',text:'回到对话查看提示，补充材料或重试。'};
  if(['queued','running'].includes(snapshot.analysis.status))return {title:'正在整理这次看病的资料',text:'分析还在进行，关怀指引准备好后会在这里显示。'};
  if(['waiting_review','completed'].includes(snapshot.analysis.status) || snapshot.report.status==='not_released')
    return {title:'关怀内容还在核对中',text:'审核和发布完成后再阅读。现在也可以问暖暖，核对已有材料。'};
  return {title:'从你最关心的一件事开始',text:'补充这次看病的资料，暖暖会结合材料帮你梳理。'};
}
export function encounterGroups(conversations:Conversation[]) {
  const groups=new Map<string,Conversation[]>();
  for(const item of conversations)groups.set(item.case_id,[...(groups.get(item.case_id) || []),item]);
  const recent=(a:Conversation,b:Conversation)=>Date.parse(b.updated_at)-Date.parse(a.updated_at)
    || a.conversation_id.localeCompare(b.conversation_id);
  return [...groups].map(([case_id,items])=>({case_id,items:[...items].sort(recent)}))
    .sort((a,b)=>recent(a.items[0],b.items[0]));
}
