import {useEffect,useRef} from 'react';
import type {ChatSnapshot,Conversation,ReportSection,Evidence} from './types';
import {actionTime,careSectionLabels,careStatus,encounterGroups,patientActions,publishedCare,visibleSections} from './carePresentation';
import brand from '../../../output_dir/product-design/assets/home-brand.webp';
import mascot from '../../../output_dir/product-design/assets/reference-mascot.webp';
import summaryArt from '../../../output_dir/product-design/assets/reference-summary.webp';
import costArt from '../../../output_dir/product-design/assets/reference-cost.webp';
import archive from '../../../output_dir/product-design/assets/care-archive-v1.webp';
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
export function CareHome({snapshot,onChat,onReport,onRecords}: {
  snapshot:ChatSnapshot;onChat:()=>void;onReport:(section?:ReportSection['section_type'])=>void;onRecords:()=>void;
}) {
  const status=careStatus(snapshot), action=patientActions(snapshot.report)[0];
  const sections=visibleSections(snapshot.report), published=publishedCare(snapshot.report);
  const summary=sections.find(section=>section.section_type==='diagnosis_explanation')?.claims[0]?.text;
  const cost=sections.find(section=>section.section_type==='cost_explanation')?.claims[0]?.text;
  return <main className="care-home">
    <section className="care-hero"><img className="care-brand" src={brand} alt="暖愈智护"/>
      <div className="care-hero-copy"><h1>看病之后，<br/><em>安心一点</em></h1><p>暖暖陪你看懂资料，记好安排。</p>
        <button className="care-episode" onClick={onRecords} aria-label="切换就医记录" title={snapshot.conversation.title}>{snapshot.conversation.title} <span>切换</span></button></div>
      <img className="care-mascot" src={mascot} alt="陪伴你的暖暖"/></section>
    <section className="care-next" aria-labelledby="care-next-title"><span className="care-kicker">本次关怀</span><h2 id="care-next-title">{status.title}</h2>
      <p>{status.text}</p>{action && <button className="care-featured-action" onClick={()=>onReport('next_visit_advice')}>
        <span className="care-action-symbol" aria-hidden="true">↗</span><span><strong>{action.action_text}</strong><small>{actionTime(action)} · 安排建议</small></span><span aria-hidden="true">›</span></button>}
      <button className="care-primary" onClick={()=>published?onReport():onChat()}>{published?'查看本次关怀':'问问暖暖'} <span aria-hidden="true">›</span></button>
      {published && <small>第 {snapshot.report.report_version} 版 · 已审核发布</small>}</section>
    <section className="care-home-sections" aria-labelledby="care-this-visit"><h2 id="care-this-visit">这次看病</h2>
      <div className="care-summary-links"><button onClick={()=>onReport('diagnosis_explanation')}><img src={summaryArt} alt=""/><strong>看病总结</strong><span>{summary || '资料核对后再一起看'}</span></button>
        <button onClick={()=>onReport('cost_explanation')}><img src={costArt} alt=""/><strong>费用说明</strong><span>{cost || '费用资料与解读待核对'}</span></button></div></section>
    <section className="care-ask"><img src={reading} alt=""/><div><h2>有不明白的，慢慢问</h2><p>从某一句病历、某一项费用开始。</p><button onClick={onChat}>带着资料问暖暖 <span aria-hidden="true">›</span></button></div></section>
  </main>;
}

export function CareRecords({conversations,currentCase,busy,onOpen,onNew}: {
  conversations:Conversation[];currentCase?:string;busy:boolean;onOpen:(id:string)=>void;onNew:()=>void;
}) {
  const groups=encounterGroups(conversations);
  return <main className="care-records"><section className="care-records-intro"><div><span className="care-kicker">就医记录</span><h1>每次看病，<br/>都好好记下。</h1><p>同一组就医资料的对话放在一起，资料和费用分别核对。</p></div><img src={archive} alt=""/></section>
    <div className="care-records-heading"><h2>当前可见 {groups.length} 组资料 · {conversations.length} 段对话</h2><button disabled={busy} onClick={onNew}>＋ 新的关怀对话</button></div>
    {!groups.length && <div className="care-empty"><h2>还没有就医记录</h2><p>开始一段对话，或者接续已有的授权案件。</p></div>}
    {groups.map(group=><section className="care-encounter" key={group.case_id}><div className="care-encounter-heading"><h2>{group.items[0].title}</h2>{currentCase===group.case_id && <span>正在查看</span>}</div>
      <p className="care-encounter-note">同一组就医资料 · {group.items.length} 段对话</p>{group.items.map(item=><button disabled={busy} key={item.conversation_id} onClick={()=>onOpen(item.conversation_id)}>
        <span><strong>{item.title}</strong><small>最近沟通 · {new Date(item.updated_at).toLocaleDateString('zh-CN')}</small></span><span aria-hidden="true">›</span></button>)}</section>)}
    <p className="care-records-note">这里的分组来自已授权案件，不据此推断病种或恢复情况。</p></main>;
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
