import {useEffect,useRef,useState} from 'react';
import type {ChatSnapshot,ReportSection,Evidence} from './types';
import {actionTime,careSectionLabels,patientActions,visibleSections} from './carePresentation';
import brand from '../../../output_dir/product-design/assets/home-brand.webp';
import reading from '../../../output_dir/product-design/assets/nuan-reading-v1.webp';

import {SourceRefs} from './SourceCitations';
import {getEvidenceImage} from './api';
import {ReportServiceGuide} from './MedicalServices';
export {brand,reading};

export function EvidencePanel({evidence,onClose,token=''}:{evidence:Evidence;onClose:()=>void;token?:string}) {
  const dialog=useRef<HTMLDialogElement>(null),[image,setImage]=useState(''),[imageError,setImageError]=useState('');
  useEffect(()=>{let active=true,url='';const previous=document.activeElement as HTMLElement;dialog.current?.showModal();setImage('');setImageError('');
    if(token&&evidence.media_type?.startsWith('image/')&&evidence.case_id)void getEvidenceImage(token,evidence).then(value=>{url=value;if(active)setImage(value);else URL.revokeObjectURL(value);}).catch(()=>{if(active)setImageError('原图暂不可用，下面保留已识别的原文摘录。');});
    return()=>{active=false;if(url)URL.revokeObjectURL(url);dialog.current?.close();previous?.focus?.();};
  },[evidence.evidence_id,token]);
  const box=evidence.bbox;
  return <dialog ref={dialog} className="source-sheet" aria-labelledby="care-evidence-title" onCancel={e=>{e.preventDefault();onClose();}}>
    <header><div><small>用户上传的材料</small><h2 id="care-evidence-title">{evidence.source_name||'原始材料依据'}</h2></div><button onClick={onClose} aria-label="关闭原始依据">×</button></header>
    <p>{evidence.document_type||'就医材料'} · {evidence.page_index===null?'页码待核对':`第 ${evidence.page_index+1} 页`} · 材料版本 {evidence.document_version}</p>
    <blockquote>{evidence.text_span?.text || '此证据暂无文字片段。'}</blockquote>
    {image&&<div className="source-image"><img src={image} alt="来源材料原图"/>{box&&<span aria-label="原文所在区域" style={{left:`${box[0]*100}%`,top:`${box[1]*100}%`,width:`${(box[2]-box[0])*100}%`,height:`${(box[3]-box[1])*100}%`}}/>}</div>}
    {imageError&&<p role="status">{imageError}</p>}
  </dialog>;
}
export function CareReport({report,initialSection,onEvidence,onServiceAsk,disabled=false}: {
  report:ChatSnapshot['report'];initialSection?:ReportSection['section_type'];onEvidence:(id:string)=>void;
  onServiceAsk?:(message:string)=>Promise<boolean>;disabled?:boolean;
}) {
  const root=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!initialSection)return;
    const section=root.current?.querySelector<HTMLDetailsElement>(`[data-care-section="${initialSection}"]`);
    if(section){section.open=true;section.scrollIntoView({block:'start'});section.querySelector('summary')?.focus({preventScroll:true});}
  },[initialSection,report.report_id]);
  const actions=patientActions(report).slice(0,3);
  const catalog=[...new Set(visibleSections(report).flatMap(s=>s.claims.flatMap(c=>[...c.evidence_refs,...(c.knowledge_refs||[])])))];
  return <div ref={root} className="care-report-content">
    {actions.length>0 && <section className="care-report-actions" aria-labelledby="care-action-title"><h2 id="care-action-title">接下来，可以这样安排</h2><p>这些是本版指引中的建议，尚不表示已经执行。</p>
      {actions.map(action=><article key={action.action_id}><h3>{action.action_text}</h3><span>{actionTime(action)}</span><p>{action.rationale}<SourceRefs refs={action.source_refs} onEvidence={onEvidence}/></p></article>)}</section>}
    {visibleSections(report).map(section=><details key={section.section_type} data-care-section={section.section_type} className="care-report-section" open={section.section_type==='next_visit_advice'}>
      <summary>{careSectionLabels[section.section_type]}<span aria-hidden="true">＋</span></summary>
      {section.claims.map(claim=><article key={claim.claim_id}><p>{claim.text}<SourceRefs refs={[...claim.evidence_refs,...(claim.knowledge_refs||[])]} catalog={catalog} onEvidence={onEvidence}/></p>{claim.claim_type==='to_confirm' && <small className="care-confirm">需要向医院或医生确认</small>}
        </article>)}</details>)}
    <ReportServiceGuide onAsk={onServiceAsk} disabled={disabled}/>
  </div>;
}
