import {useEffect,useRef,useState} from 'react';
import {getFacts,getInsights,getMaterialQuality,type MaterialQuality} from './api';
import {CareRecommendations} from './CareRecommendations';
import {CareReport} from './CarePages';
import {MaterialReportContent} from './AnalysisFlow';
import AnalysisNarrative,{currentNarrative} from './AnalysisNarrative';
import {publishedCare} from './carePresentation';
import {SourceRefs} from './SourceCitations';
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

export default function EncounterOverview({token,snapshot,person,onEvidence,onAsk,onUpload,onReport,onRefresh,onReplace}:{token:string;snapshot:ChatSnapshot;person:string;onEvidence:(id:string)=>void;onAsk:(text:string)=>void;onUpload:()=>void;onReport:()=>void;onRefresh:()=>void;onReplace:(documentId:string,file:File)=>void}){
 const [tab,setTab]=useState('facts'),[facts,setFacts]=useState<ExtractedFact[]>([]),[insights,setInsights]=useState<Insight[]>([]),[error,setError]=useState(''),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0),[filter,setFilter]=useState('all');
 const replacementPicker=useRef<HTMLInputElement>(null),replacementId=useRef('');
 const [quality,setQuality]=useState<MaterialQuality[]>([]);
 const run=snapshot.analysis.run_id,caseId=snapshot.conversation.case_id;
 useEffect(()=>{let active=true;setFacts([]);setInsights([]);setQuality([]);setError('');if(!run)return;setBusy(true);
  void Promise.all([getFacts(token,caseId,run),getInsights(token,caseId,run),getMaterialQuality(token,caseId,run)]).then(([f,i,q])=>{if(active){setFacts(f);setInsights(i);setQuality(q);}}).catch(e=>{if(active)setError(e.message||'结果暂不可用');}).finally(()=>{if(active)setBusy(false);});return()=>{active=false;};
 },[token,caseId,run,snapshot.analysis.status,retry]);
 const catalog=[...new Set([...facts.flatMap(f=>[...f.evidence_ids,...f.alternatives.flatMap(a=>a.evidence_ids)]),...insights.flatMap(i=>[...i.evidence_ids,...i.knowledge_refs])])];
 const narrative=currentNarrative(snapshot.turns,run),visible=insights.filter(i=>i.judgment_status!=='rejected'&&i.review_status!=='rejected');
 const payload=JSON.stringify({case_id:caseId,run_id:run,facts},null,2);
 const [copyMessage,setCopyMessage]=useState('');
 const download=()=>{const url=URL.createObjectURL(new Blob([payload],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`structured-${run}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 return <main className="encounter-overview">
  <input ref={replacementPicker} hidden type="file" accept="image/jpeg,image/png" aria-label="替换已识别的模糊材料" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;
   if(!file.size||file.size>10*1024*1024||!(/\.(png|jpe?g)$/i.test(file.name))){setError('请选择不超过10MB的JPG或PNG照片。');return;}
   const normalized=file.type?file:new File([file],file.name,{type:/\.png$/i.test(file.name)?'image/png':'image/jpeg'});onReplace(replacementId.current,normalized);
  }}/>
  <header className="overview-hero"><small>本次就医总览</small><h1>{person}的就医资料</h1><p>{snapshot.conversation.title}</p><span>{snapshot.analysis.status==='completed'?'分析完成':snapshot.analysis.status==='waiting_review'?'部分内容待核对':'分析状态：'+snapshot.analysis.status}</span><p className="muted">{snapshot.report.report_version?`报告第 ${snapshot.report.report_version} 版`:'以本次材料分析结果为准'} · 补充材料后请重新分析</p></header>
  <nav className="overview-tabs" aria-label="本次就医内容">{[['facts','病历摘要'],['insights','需要关注'],['care','康复指引'],['quality','就医参考']].map(([key,label])=><button key={key} aria-current={tab===key?'page':undefined} onClick={()=>setTab(key)}>{label}</button>)}</nav>
  <div className="overview-content">{quality.filter(q=>q.quality.needs_reupload).map(q=><aside className="quality-warning" key={`${q.document_id}:${q.page_index}`}><strong>{q.name} · 第 {q.page_index+1} 页</strong><p>这份材料可能是{q.quality.material_type}，有 {q.quality.uncertain_lines} 处文字识别把握较低。已保留可读部分，不确定文字未用于确定事实或金额。</p><button onClick={()=>{replacementId.current=q.document_id;replacementPicker.current?.click();}}>重新上传这份{q.quality.material_type}</button></aside>)}
  {busy&&<p role="status">正在核对本次分析结果…</p>}{error&&<div role="alert"><p>{error}</p><button onClick={()=>setRetry(v=>v+1)}>重新加载</button></div>}
  {tab==='facts'&&<><header><h2>先把关键信息看清楚</h2><p>点击内容右上角的编号，可以查看对应材料。</p></header>
   {!facts.length&&!busy&&!error&&<p>尚无可展示的结构化结果。材料分析完成后可重新加载。</p>}
   <div className="fact-grid">{facts.map(fact=><article key={fact.field_id} className="fact-card"><header><h3>{labels[fact.fact_type]||fact.fact_type}</h3><small data-state={fact.status}>{states[fact.status]||fact.status}</small></header>
    {assertions[fact.assertion]&&<strong className="fact-qualifier">{assertions[fact.assertion]}</strong>}
    <FactValue fact={fact} catalog={catalog} onEvidence={onEvidence}/>
    {fact.missing_reason&&<p className="muted">{fact.missing_reason==='not_documented_in_parsed_materials'?'已解析材料中暂未找到，不代表实际没有发生。':fact.missing_reason}</p>}
    {fact.alternatives.map((candidate,i)=><p key={i}>来源中的另一种记录：{valueText(candidate.value)}<SourceRefs refs={candidate.evidence_ids} catalog={catalog} onEvidence={onEvidence}/></p>)}
    <details><summary>识别详情</summary><p>原文值：{fact.raw_value||'未提供'}</p><p>字段置信度：{fact.confidence_score===null?'未提供':`${Math.round(fact.confidence_score*100)}%`}</p><small>{fact.confidence_method||'未提供计算方式'} · 字段置信度不等于医学正确率</small></details>
    {['missing','unreadable','conflict'].includes(fact.status)&&<button onClick={onUpload}>补充相关材料</button>}
   </article>)}</div>
   <details className="structured-json"><summary>结构化 JSON 与字段置信度</summary><p>本页字段状态不能代替整体 F1 或缺失率评测。</p><div className="insight-actions"><button disabled={!facts.length} onClick={download}>下载 JSON</button><button disabled={!facts.length} onClick={()=>void navigator.clipboard.writeText(payload).then(()=>setCopyMessage('已复制')).catch(()=>setCopyMessage('复制不可用，请下载 JSON'))}>复制 JSON</button><small role="status">{copyMessage}</small></div><pre>{payload}</pre></details>
  </>}
  {tab==='insights'&&<><header><h2>这些地方，可以再核对一下</h2><p>待核实的疑点不代表已经发生医疗问题。</p></header><div className="care-recommend-chips">{[['all','全部'],...Object.entries(categories)].map(([key,label])=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{label} {key==='all'?visible.length:visible.filter(i=>i.category===key).length}</button>)}</div>
   {visible.filter(i=>filter==='all'||i.category===filter).map(item=><article className="pain-card" key={item.insight_id}><small>{categories[item.category]} · {item.review_status==='pending'?'待专业核对':item.judgment_status==='supported'?'有材料支持':'待核实'}</small><h3>{painNames[item.label]||'需要进一步核对'}</h3><p>{item.rationale}<SourceRefs refs={[...item.evidence_ids,...item.knowledge_refs]} catalog={catalog} onEvidence={onEvidence}/></p><p><strong>归类原因：</strong>{categoryReasons[item.category]}</p>{item.uncertainty&&<p>{item.uncertainty}</p>}
    <p><strong>下一步：</strong>{item.review_status==='pending'?'先核对原始材料，待专业复核后再确定后续安排。':item.suggested_action}</p><button onClick={()=>onAsk(`请结合本次材料解释“${painNames[item.label]||item.label}”，说明依据和仍需核实的部分。`)}>问问暖暖</button></article>)}
   {!visible.length&&!busy&&!error&&<p>本轮暂无可展示的痛点结果；这不等于已确认没有问题。</p>}
  </>}
  {tab==='care'&&<><header><h2>接下来，可以这样安排</h2><p>先看重要安排，再展开具体说明。</p></header>{publishedCare(snapshot.report)?<><CareReport report={snapshot.report} onEvidence={onEvidence}/><button className="care-primary" onClick={onReport}>查看完整指引与反馈</button></>:narrative?<AnalysisNarrative turn={narrative} onEvidence={onEvidence}/>:snapshot.material_report?.status==='available'?<MaterialReportContent report={snapshot.material_report} onEvidence={onEvidence} onAsk={onAsk}/>:<p>指引尚未准备好，可回到对话查看进度或继续核对材料。</p>}
   <div className="insight-actions"><button onClick={()=>onAsk('请帮我理清这次就医接下来需要做的事，并说明每项安排来自哪份材料。')}>看不懂，问问暖暖</button><button onClick={onRefresh}>重新分析本次材料</button></div>
  </>}
  {tab==='quality'&&<CareRecommendations token={token} initialDisease={inferredDisease(facts)}/>}
  </div>
 </main>;
}
