import reading from '../../../output_dir/product-design/assets/nuan-reading-v1.webp';
import type {ChatSnapshot} from './types';
import {publishedCare,visibleSections,careSectionLabels} from './carePresentation';
import {DemoIcon} from './DemoPages';
import {SourceRefs} from './SourceCitations';
export function OriginalChatWelcome(){return <section className="nuan-welcome" aria-label="暖暖陪你看懂资料"><div className="nuan-welcome-copy"><span className="nuan-welcome-kicker"><DemoIcon name="leaf"/>暖暖，陪你一起</span><h2>看懂一点，<br/>安心一点。</h2><p>看病后的疑问，一件一件聊。</p></div><img src={reading} width="100" height="110" alt="捧着笔记本的暖暖"/></section>;}
export default function OriginalChatGuide({snapshot,onEvidence}:{snapshot:ChatSnapshot;onEvidence:(id:string)=>void}){
 const ready=publishedCare(snapshot.report), sections=ready?visibleSections(snapshot.report):[];
 return <><OriginalChatWelcome/>
 <p className="nuan-conversation-caption"><strong>{snapshot.conversation.title}</strong><small>{ready?'已发布解读':'一起核对资料'}</small></p>
 <div id="chat-topic-action" className="nuan-message nuan-priority"><div className="nuan-message-body"><div className="nuan-message-label"><DemoIcon name="leaf"/>接下来，先关心这件事</div>{ready&&(snapshot.report.actions||[]).length?(snapshot.report.actions||[]).slice(0,3).map(a=><div key={a.action_id} className="nuan-date-card"><div><h3>{a.action_text}</h3>{a.due_at&&<span>{new Date(a.due_at).toLocaleString('zh-CN')}</span>}<p>{a.rationale}<SourceRefs refs={a.source_refs} onEvidence={onEvidence}/></p></div></div>):<p>从你最关心的问题开始。补充就医材料后，暖暖会陪你核对还不清楚的地方。</p>}</div></div>
 <div className="nuan-topic-grid">{(['summary','cost'] as const).map(topic=>{
 const topicSections=sections.filter(s=>topic==='cost'?s.section_type==='cost_explanation':['diagnosis_explanation','treatment_review','recovery_plan','next_visit_advice'].includes(s.section_type));
 return <details className="nuan-topic-details" id={'chat-topic-'+topic} key={topic}><summary><span className="nuan-topic-icon"><DemoIcon name={topic==='summary'?'file':'chat'}/></span><span className="nuan-topic-title">{topic==='summary'?'看病经过':'费用解读'}<small>{topic==='summary'?'把这次就医理清楚':'把票据费用看明白'}</small></span><span className="nuan-topic-cue"><span className="nuan-topic-cue-closed">点击展开</span><span className="nuan-topic-cue-open">收起内容</span><DemoIcon name="arrow"/></span></summary>{topicSections.map(s=><div className="nuan-message" key={s.section_type}><div className="nuan-message-body"><h3>{careSectionLabels[s.section_type]}</h3>{s.claims.map(c=><p key={c.claim_id}>{c.text}<SourceRefs refs={[...c.evidence_refs,...(c.knowledge_refs||[])]} onEvidence={onEvidence}/></p>)}</div></div>)}{!topicSections.length&&<p className="nuan-hint">{ready?'本次指引暂无这部分内容，可以继续问暖暖。':'尚无已发布的解读，请先补充材料或等待整理与复核。'}</p>}</details>;
 })}</div>
 {ready&&<div className="nuan-end">以上为本次就医的已发布解读</div>}</>;
}
