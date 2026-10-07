import {useEffect,useRef} from 'react';
import type {ChatSnapshot,ReportSection,Evidence} from './types';
import {actionTime,careSectionLabels,patientActions,visibleSections} from './carePresentation';
import brand from '../../../output_dir/product-design/assets/home-brand.webp';
import reading from '../../../output_dir/product-design/assets/nuan-reading-v1.webp';

export {brand,reading};

export function EvidencePanel({evidence,onClose}:{evidence:Evidence;onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const node=dialog.current;if(node && !node.open){node.showModal();node.querySelector<HTMLButtonElement>('.close-evidence')?.focus();}return()=>node?.close();},[]);
  return <dialog ref={dialog} className="evidence-overlay" aria-labelledby="care-evidence-title" onCancel={e=>{e.preventDefault();onClose();}}>
    <button className="evidence-backdrop" aria-label="关闭原始依据" onClick={onClose}/>
    <article><button className="close-evidence" autoFocus onClick={onClose}>关闭</button><h2 id="care-evidence-title">原始材料依据</h2>
      <p>{evidence.page_index===null?'页码待核对':`第 ${evidence.page_index+1} 页`} · 材料版本 {evidence.document_version}</p>
      <blockquote>{evidence.text_span?.text || '此证据暂无文字片段。'}</blockquote></article>
  </dialog>;
}
export function CareReport({report,initialSection,onEvidence}: {
  report:ChatSnapshot['report'];initialSection?:ReportSection['section_type'];onEvidence:(id:string)=>void;
}) {
  const root=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!initialSection)return;
    const section=root.current?.querySelector<HTMLDetailsElement>(`[data-care-section="${initialSection}"]`);
    if(section){section.open=true;section.scrollIntoView({block:'start'});section.querySelector('summary')?.focus({preventScroll:true});}
  },[initialSection,report.report_id]);
  const actions=patientActions(report);
  return <div ref={root} className="care-report-content">
    {actions.length>0 && <section className="care-report-actions" aria-labelledby="care-action-title"><h2 id="care-action-title">接下来，可以这样安排</h2><p>这些是本版指引中的建议，尚不表示已经执行。</p>
      {actions.map(action=><article key={action.action_id}><h3>{action.action_text}</h3><span>{actionTime(action)}</span><p>{action.rationale}</p></article>)}</section>}
    {visibleSections(report).map(section=><details key={section.section_type} data-care-section={section.section_type} className="care-report-section" open={section.section_type==='next_visit_advice'}>
      <summary>{careSectionLabels[section.section_type]}<span aria-hidden="true">＋</span></summary>
      {section.claims.map(claim=><article key={claim.claim_id}><p>{claim.text}</p>{claim.claim_type==='to_confirm' && <small className="care-confirm">需要向医院或医生确认</small>}
        {claim.evidence_refs.map(id=><button className="citation" key={id} onClick={()=>onEvidence(id)}>查看这段说明的资料依据</button>)}</article>)}</details>)}
  </div>;
}
