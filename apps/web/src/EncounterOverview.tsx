import {useEffect,useRef,useState} from 'react';
import {getFacts,getInsights,getMaterialQuality,type MaterialQuality} from './api';
import {CareRecommendations} from './CareRecommendations';
import {CareReport} from './CarePages';
import {MaterialReportContent} from './AnalysisFlow';
import {currentNarrative} from './AnalysisNarrative';
import {publishedCare} from './carePresentation';
import {SourceRefs,CitedText} from './SourceCitations';
import {overviewTabs,overviewNarrative,type OverviewTab} from './encounterPresentation';
import type {ChatSnapshot,ExtractedFact,Insight} from './types';
import './insights.css';
import {factValueText as valueText,isMoney} from './factPresentation';

const labels:Record<string,string>={diagnosis:'诊断',surgery:'手术／治疗',medication:'用药',stay_days:'住院天数',total_cost:'总费用',charge_item:'费用项目',admission:'入院',discharge:'出院',cost_breakdown:'费用构成'};
const states:Record<string,string>={observed:'已提取',derived:'推导结果',missing:'待补充',unreadable:'无法识别',conflict:'存在冲突',not_applicable:'不适用'};
const assertions:Record<string,string>={negated:'原文否定',suspected:'疑似／待排',historical:'既往',unknown:'性质待核实'};
const categories={clinical:'临床',cost:'费用',experience:'体验'};
const painNames:Record<string,string>={CLIN_MEDICATION_CONTEXT_REVIEW:'用药背景需要核对',CLIN_EXAM_JUSTIFICATION_REVIEW:'检查背景需要核对',COST_SELF_PAY_DEVIATION:'自付费用需要核对',COST_AMOUNT_RECONCILIATION:'费用金额需要核对',EXP_TERMINOLOGY_BARRIER:'医学术语不易理解',EXP_DISCHARGE_GUIDANCE_GAP:'出院安排需要补充'};
const categoryReasons:Record<string,string>={clinical:'涉及检查或用药等诊疗内容，需要结合医疗背景核对。',cost:'涉及收费、支付或金额对应关系。',experience:'涉及资料理解与出院后行动安排。'};
type CostValue={fields:{scope_ref:string;source_label:string;page_index:number|null;amount:{value:unknown;status:string;evidence_ids:string[];alternatives:{value:unknown;evidence_ids:string[]}[]}}[];limitations:string[]};
function FactValue({fact,catalog,onEvidence}:{fact:ExtractedFact;catalog:string[];onEvidence:(id:string)=>void}){
 if(fact.fact_type==='cost_breakdown'&&fact.value&&typeof fact.value==='object'&&'fields' in fact.value){
  const cost=fact.value as CostValue;
  return <div>{cost.fields.map((field,index)=><div key={`${field.scope_ref}:${index}`}><p><strong>{field.source_label}</strong>：{valueText(field.amount.value)}<SourceRefs refs={field.amount.evidence_ids} catalog={catalog} onEvidence={onEvidence}/></p>
   {field.amount.status==='conflict'&&<small>不同来源金额冲突，待核对。</small>}{field.amount.alternatives.map((a,i)=><p key={i}>{valueText(a.value)}<SourceRefs refs={a.evidence_ids} catalog={catalog} onEvidence={onEvidence}/></p>)}</div>)}<small>不同页面与不同支付口径不相加，不推算最终自付。</small></div>;
 }
 return <p>{valueText(fact.value)}{fact.value!==null&&fact.unit&&!isMoney(fact.value)?` ${({day:'天',CNY:'元'} as Record<string,string>)[fact.unit]||fact.unit}`:''}<SourceRefs refs={fact.evidence_ids} catalog={catalog} onEvidence={onEvidence}/></p>;
}
export function inferredDisease(facts:ExtractedFact[]){const text=facts.filter(f=>f.fact_type==='diagnosis'&&f.assertion==='present'&&f.status==='observed').map(f=>valueText(f.value)).join(' ');const found=[['FY','肺炎'],['FX','骨折'],['TN','糖尿病'],['GX','冠心病'],['YZ','腰椎间盘突出']].filter(([,name])=>text.includes(name));return found.length===1?found[0][0]:'';}

export default function EncounterOverview({token,snapshot,person,onEvidence,onAsk,onUpload,onReport,onRefresh,onReplace,onBack,initialTab='facts'}:{onBack:()=>void;initialTab?:OverviewTab;token:string;snapshot:ChatSnapshot;person:string;onEvidence:(id:string)=>void;onAsk:(text:string)=>void;onUpload:()=>void;onReport:()=>void;onRefresh:()=>void;onReplace:(documentId:string,file:File)=>void}){
 const [tab,setTab]=useState<OverviewTab>(initialTab),[facts,setFacts]=useState<ExtractedFact[]>([]),[insights,setInsights]=useState<Insight[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0),[filter,setFilter]=useState('all');
 const replacementPicker=useRef<HTMLInputElement>(null),replacementId=useRef('');
 const [loadErrors,setLoadErrors]=useState<Record<string,string>>({});
 const [quality,setQuality]=useState<MaterialQuality[]>([]);
 const run=snapshot.analysis.run_id,caseId=snapshot.conversation.case_id;
 useEffect(()=>{let active=true;setFacts([]);setInsights([]);setQuality([]);setError('');setLoadErrors({});setBusy(!!run);if(!run)return;
  const load=async(kind:string,fetcher:()=>Promise<unknown>,apply:(value:any)=>void)=>{
   try{const value=await fetcher();if(active)apply(value);}
   catch(e){if(active)setLoadErrors(old=>({...old,[kind]:e instanceof Error?e.message:'暂时无法加载'}));}
  };
  void Promise.allSettled([load('facts',()=>getFacts(token,caseId,run),setFacts),load('insights',()=>getInsights(token,caseId,run),setInsights),load('quality',()=>getMaterialQuality(token,caseId,run),setQuality)]).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};
 },[token,caseId,run,snapshot.analysis.status,retry]);
 const catalog=[...new Set([...facts.flatMap(f=>[...f.evidence_ids,...f.alternatives.flatMap(a=>a.evidence_ids)]),...insights.flatMap(i=>[...i.evidence_ids,...i.knowledge_refs])])];
 const narrative=currentNarrative(snapshot.turns,run),visible=insights.filter(i=>i.judgment_status!=='rejected'&&i.review_status!=='rejected');
 const sections=overviewNarrative(narrative?.answer?.text||'');
 const sources=narrative?.answer?.knowledge_sources||[];
 const referenced=new Set(narrative?.answer?.citations?.flatMap(c=>c.source_refs)||[]);
 const prose=(kind:OverviewTab)=>sections[kind].length>0&&<section className="overview-ai-content" aria-label={`${overviewTabs.find(t=>t[0]===kind)?.[1]}的AI解读`}><small>暖暖已生成的解读 · 保留原文和来源</small>{sections[kind].map((block,i)=><article className="overview-ai-point" key={i}>{[block.text,...block.paragraphs].map((text,j)=><p key={j}><CitedText text={text} citations={narrative?.answer?.citations} sources={sources} onEvidence={onEvidence}/></p>)}</article>)}</section>;
 const materialFor=(types:string[])=>snapshot.material_report?.status==='available'?{...snapshot.material_report,sections:snapshot.material_report.sections?.filter(s=>types.includes(s.section_type))}:undefined;
 const payload=JSON.stringify({case_id:caseId,run_id:run,facts},null,2);
 const [copyMessage,setCopyMessage]=useState('');
 const download=()=>{const url=URL.createObjectURL(new Blob([payload],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`structured-${run}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 return <main className="encounter-overview">
  <input ref={replacementPicker} hidden type="file" accept="image/jpeg,image/png" aria-label="替换已识别的模糊材料" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;
   if(!file.size||file.size>10*1024*1024||!(/\.(png|jpe?g)$/i.test(file.name))){setError('请选择不超过10MB的JPG或PNG照片。');return;}
   const normalized=file.type?file:new File([file],file.name,{type:/\.png$/i.test(file.name)?'image/png':'image/jpeg'});onReplace(replacementId.current,normalized);
  }}/>
  <button className="overview-back" onClick={onBack}>‹ 返回暖暖解读</button><header className="overview-hero"><small>本次就医总览</small><h1>{person}的就医资料</h1><p>{snapshot.conversation.title}</p><span>{snapshot.analysis.status==='completed'?'分析完成':snapshot.analysis.status==='waiting_review'?'部分内容待核对':'分析状态：'+snapshot.analysis.status}</span><p className="muted">{snapshot.report.report_version?`报告第 ${snapshot.report.report_version} 版`:'以本次材料分析结果为准'} · 补充材料后请重新分析</p></header>
  <button className="care-primary" disabled={snapshot.analysis.status==='queued'||snapshot.analysis.status==='running'} onClick={onRefresh}>重新生成解读</button>
  <nav className="overview-tabs" aria-label="本次就医内容">{overviewTabs.map(([key,label])=><button key={key} aria-current={tab===key?'page':undefined} onClick={()=>setTab(key)}>{label}</button>)}</nav>
  <div className="overview-content">{quality.filter(q=>q.quality.needs_reupload).map(q=><aside className="quality-warning" key={`${q.document_id}:${q.page_index}`}><strong>{q.name} · 第 {q.page_index+1} 页</strong><p>这份材料可能是{q.quality.material_type}，有 {q.quality.uncertain_lines} 处文字识别把握较低。已保留可读部分，不确定文字未用于确定事实或金额。</p><button onClick={()=>{replacementId.current=q.document_id;replacementPicker.current?.click();}}>重新上传这份{q.quality.material_type}</button></aside>)}
  {busy&&<p role="status">正在加载补充资料，已生成的解读可先查看。</p>}
  {loadErrors[tab]&&<div role="alert"><p>补充资料暂时无法加载，已生成的解读仍可查看。</p><button onClick={()=>setRetry(v=>v+1)}>重新加载资料</button></div>}{error&&<div role="alert"><p>{error}</p><button onClick={()=>setRetry(v=>v+1)}>重新加载</button></div>}
  {tab==='facts'&&<><header><h2>先把关键信息看清楚</h2><p>点击内容右上角的编号，可以查看对应材料。</p></header>
   {prose('facts')}
   {!narrative&&materialFor(['diagnosis_explanation','treatment_review','cost_explanation'])&&<MaterialReportContent report={materialFor(['diagnosis_explanation','treatment_review','cost_explanation'])!} onEvidence={onEvidence} onAsk={onAsk}/>}
   {!facts.length&&!narrative&&!busy&&!error&&<p>本次摘要尚未生成，可返回对话查看分析进度。</p>}
   <details className="overview-extracted"><summary>查看材料中提取的字段（{facts.length} 项）</summary>
   <div className="fact-grid">{facts.map(fact=><article key={fact.field_id} className="fact-card"><header><h3>{labels[fact.fact_type]||fact.fact_type}</h3><small data-state={fact.status}>{states[fact.status]||fact.status}</small></header>
    {assertions[fact.assertion]&&<strong className="fact-qualifier">{assertions[fact.assertion]}</strong>}
    <FactValue fact={fact} catalog={catalog} onEvidence={onEvidence}/>
    {fact.missing_reason&&<p className="muted">{fact.missing_reason==='not_documented_in_parsed_materials'?'已解析材料中暂未找到，不代表实际没有发生。':fact.missing_reason}</p>}
    {fact.alternatives.map((candidate,i)=><p key={i}>来源中的另一种记录：{valueText(candidate.value)}<SourceRefs refs={candidate.evidence_ids} catalog={catalog} onEvidence={onEvidence}/></p>)}
    <details><summary>识别详情</summary><p>原文值：{fact.raw_value||'未提供'}</p><p>字段置信度：{fact.confidence_score===null?'未提供':`${Math.round(fact.confidence_score*100)}%`}</p><small>{fact.confidence_method||'未提供计算方式'} · 字段置信度不等于医学正确率</small></details>
    {['missing','unreadable','conflict'].includes(fact.status)&&<button onClick={onUpload}>补充相关材料</button>}
   </article>)}</div>
   </details><details className="structured-json"><summary>结构化 JSON 与字段置信度</summary><p>本页字段状态不能代替整体 F1 或缺失率评测。</p><div className="insight-actions"><button disabled={!facts.length} onClick={download}>下载 JSON</button><button disabled={!facts.length} onClick={()=>void navigator.clipboard.writeText(payload).then(()=>setCopyMessage('已复制')).catch(()=>setCopyMessage('复制不可用，请下载 JSON'))}>复制 JSON</button><small role="status">{copyMessage}</small></div><pre>{payload}</pre></details>
  </>}
  {tab==='insights'&&<><header><h2>这些地方，可以再核对一下</h2><p>把解读中需要确认的地方放在一起，方便继续核对。</p></header>{prose('insights')}<div className="care-recommend-chips">{[['all','全部'],...Object.entries(categories)].map(([key,label])=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{label} {key==='all'?visible.length:visible.filter(i=>i.category===key).length}</button>)}</div>
   {filter==='all'&&facts.filter(f=>['conflict','unreadable'].includes(f.status)).map(fact=><article className="pain-card" key={fact.field_id}><small>材料信息待核对</small><h3>{labels[fact.fact_type]||'本次材料'} · {states[fact.status]}</h3><FactValue fact={fact} catalog={catalog} onEvidence={onEvidence}/>{fact.alternatives.map((candidate,i)=><p key={i}>另一份记录：{valueText(candidate.value)}<SourceRefs refs={candidate.evidence_ids} catalog={catalog} onEvidence={onEvidence}/></p>)}<p>保留各来源的不同记录，确认前不合并为单一结论。</p></article>)}
   {visible.filter(i=>filter==='all'||i.category===filter).map(item=><article className="pain-card" key={item.insight_id}><small>{categories[item.category]} · {item.review_status==='pending'?'待专业核对':item.judgment_status==='supported'?'有材料支持':'待核实'}</small><h3>{painNames[item.label]||'需要进一步核对'}</h3><p>{item.rationale}<SourceRefs refs={[...item.evidence_ids,...item.knowledge_refs]} catalog={catalog} onEvidence={onEvidence}/></p><p><strong>归类原因：</strong>{categoryReasons[item.category]}</p>{item.uncertainty&&<p>{item.uncertainty}</p>}
    <p><strong>下一步：</strong>{item.review_status==='pending'?'先核对原始材料，待专业复核后再确定后续安排。':item.suggested_action}</p><button onClick={()=>onAsk(`请结合本次材料解释“${painNames[item.label]||item.label}”，说明依据和仍需核实的部分。`)}>问问暖暖</button></article>)}
   {!visible.length&&!busy&&<p className="overview-note">本次没有已专业复核的独立疑点条目。上方展示解读中已有的提醒，不代表已确认医疗问题。</p>}
   <button onClick={()=>onAsk('请结合本次解读，帮我逐项核对还需要确认的信息，并标明来源。')}>继续核对这些问题</button>
  </>}
  {tab==='care'&&<><header><h2>接下来，可以这样安排</h2><p>集中查看已有解读中的恢复、复诊与后续安排。</p></header>{publishedCare(snapshot.report)?<><CareReport report={snapshot.report} initialSection="recovery_plan" onEvidence={onEvidence}/><button className="care-primary" onClick={onReport}>查看完整指引与反馈</button></>:sections.care.length?prose('care'):materialFor(['recovery_plan','next_visit_advice'])?.sections?.some(s=>s.items.length)?<MaterialReportContent report={materialFor(['recovery_plan','next_visit_advice'])!} onEvidence={onEvidence} onAsk={onAsk}/>:<section className="overview-note"><h3>本次解读尚未列出具体康复安排</h3><p>可以向暖暖补充出院医嘱或询问后续安排；页面不会自行补写用药、活动强度或复诊时间。</p><button onClick={onBack}>查看完整解读</button></section>}
   <div className="insight-actions"><button onClick={()=>onAsk('请结合已有材料说明康复和复诊安排，区分明确医嘱与需要向医生确认的事项，并标明来源。')}>向暖暖确认后续安排</button><button onClick={onUpload}>补充出院医嘱</button></div>
  </>}
  {tab==='quality'&&<><header><h2>下次就医，带着这些问题</h2><p>查看解读中已有的就诊提醒和实际引用的参考资料。</p></header>{prose('quality')}
   {!sections.quality.length&&<section className="overview-note"><p>当前解读未单独列出就诊准备。可以把本次材料带给医生，进一步确认康复和复诊安排。</p><button onClick={()=>onAsk('请根据这次材料，整理下次就医需要向医生确认的问题，并说明每个问题的依据。')}>请暖暖整理问诊问题</button></section>}
   {sources.filter(s=>referenced.has(s.entry_id)).length>0&&<section className="overview-reference"><h3>本次解读引用的参考资料</h3>{sources.filter(s=>referenced.has(s.entry_id)).map(source=><article key={source.entry_id}><h4>{source.title}<SourceRefs refs={[source.entry_id]} sources={sources} onEvidence={onEvidence}/></h4><p>{source.source}</p><small>{source.scope} · {source.version}</small></article>)}</section>}
   <details className="overview-institutions"><summary>查看机构信息与比较依据</summary><CareRecommendations token={token} initialDisease={inferredDisease(facts)}/></details>
  </>}
  </div>
 </main>;
}
