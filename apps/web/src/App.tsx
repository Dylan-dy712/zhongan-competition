import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, askAssistant, getEvidence, getReport } from "./api";
import { demoEvidence, demoReport } from "./demo";
import type { AssistantAnswer, Evidence, Report, ReportSection } from "./types";

type View = "assistant" | "report" | "actions" | "profile";
type IconName = "chat"|"file"|"check"|"user"|"shield"|"spark"|"send"|"source"|"close"|"arrow"|"plus"|"heart"|"menu";
type Message = { id:string; role:"assistant"|"user"; text:string; citations?:AssistantAnswer["citations"]; uncertainty?:string|null };

const sectionNames:Record<ReportSection["section_type"],string>={diagnosis_explanation:"病情说明",treatment_review:"治疗回顾",cost_explanation:"费用解读",recovery_plan:"康复计划",emotional_support:"情绪关怀",next_visit_advice:"复诊提醒"};
const nav:{key:View;label:string;icon:IconName}[]=[{key:"assistant",label:"问暖暖",icon:"chat"},{key:"report",label:"关怀报告",icon:"file"},{key:"actions",label:"行动计划",icon:"check"},{key:"profile",label:"我的",icon:"user"}];

function Icon({name,size=22}:{name:IconName;size?:number}){
 const p:Record<IconName,ReactNode>={
  chat:<><path d="M5 18.5 3 21l.7-4A8 8 0 1 1 7 20"/><path d="M8 11h.01M12 11h.01M16 11h.01"/></>,
  file:<><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>,
  check:<path d="m5 12 4 4L19 6"/>,user:<><circle cx="12" cy="8" r="4"/><path d="M4 22a8 8 0 0 1 16 0"/></>,
  shield:<><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5z"/><path d="m9 12 2 2 4-5"/></>,
  spark:<><path d="m12 3 1.5 4.5L17 9l-4.5 1.5L11 15l-1.5-4.5L5 9l4.5-1.5z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></>,
  send:<><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></>,source:<><path d="M5 3h14v18H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
  close:<path d="M5 5l14 14M19 5 5 19"/>,arrow:<path d="m9 18 6-6-6-6"/>,plus:<path d="M12 5v14M5 12h14"/>,
  heart:<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.9-8.6a5.5 5.5 0 0 0-.1-7.8Z"/>,menu:<path d="M4 7h16M4 12h16M4 17h16"/>
 };
 return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{p[name]}</svg>
}

const welcome:Message={id:"welcome",role:"assistant",text:"你好，我是暖暖。我已经读完这份关怀报告。你可以直接告诉我最担心的事情，我会先查报告和原始依据，再用容易理解的话回答你。"};
const suggestions=["这次到底得了什么病？","回家后最需要注意什么？","这笔费用是怎么构成的？"];
function demoAnswer(q:string):AssistantAnswer{
 if(q.includes("费"))return{answer:"报告记录的医疗总费用是 8,426.37 元。现有材料没有拆分医保结算与个人自付，因此这两项需要以正式结算票据为准。",citations:[{claim_id:"c4",evidence_refs:["2f6580ce-8ed4-4d22-88f8-aeeef82adab6"]}],uncertainty:"医保报销和自付明细尚未出现在材料中。",model_id:"demo",prompt_version:"demo"};
 if(/注意|回家|恢复/.test(q))return{answer:"回家后先做好三件事：早晚记录体温、保证休息和适量饮水、联系医院确认复诊时间。活动量可以根据身体耐受逐步增加。",citations:[{claim_id:"c1",evidence_refs:["5bdcfedd-ef76-4740-a096-3d665e5a4d43"]}],uncertainty:"报告没有明确复诊日期，需要向原就诊机构确认。",model_id:"demo",prompt_version:"demo"};
 return{answer:"材料记录的主要诊断是社区获得性肺炎。简单说，就是肺部受到感染。本次住院进行了抗感染和对症治疗，出院记录显示病情好转、生命体征平稳。",citations:[{claim_id:"c1",evidence_refs:["5bdcfedd-ef76-4740-a096-3d665e5a4d43"]}],uncertainty:null,model_id:"demo",prompt_version:"demo"};
}

function AssistantView({report,mode,token,onEvidence}:{report:Report;mode:"demo"|"live";token:string;onEvidence:(id:string)=>void}){
 const[messages,setMessages]=useState<Message[]>([welcome]),[input,setInput]=useState(""),[stage,setStage]=useState<string|null>(null),[error,setError]=useState("");const end=useRef<HTMLDivElement>(null);
 useEffect(()=>{ end.current?.scrollIntoView({behavior:"smooth"}); },[messages,stage]);
 const send=async(text=input)=>{const q=text.trim();if(!q||stage)return;setInput("");setError("");setMessages(v=>[...v,{id:crypto.randomUUID(),role:"user",text:q}]);
  try{setStage("正在读取已发布报告");await new Promise(r=>setTimeout(r,300));setStage("正在核对结论与证据");await new Promise(r=>setTimeout(r,360));setStage("正在组织回答");
   const a=mode==="demo"?await new Promise<AssistantAnswer>(r=>setTimeout(()=>r(demoAnswer(q)),560)):await askAssistant(report.case_id,report.report_version,q,token);
   setMessages(v=>[...v,{id:crypto.randomUUID(),role:"assistant",text:a.answer,citations:a.citations,uncertainty:a.uncertainty}])
  }catch(e){setError(e instanceof ApiError?e.message:"暂时无法回答，请稍后再试。")}finally{setStage(null)}
 };
 const submit=(e:FormEvent)=>{e.preventDefault();void send()};
 return <main className="assistant-page"><header className="assistant-head"><div><span className="live-dot"/><b>暖暖在线</b><small>基于已审核报告回答</small></div><span className="case-tag">报告 v{report.report_version}</span></header>
  <div className="conversation"><section className="conversation-intro"><div className="ai-orb"><Icon name="spark" size={30}/><i/><i/></div><p>AI 关怀助手</p><h1>有什么担心，<em>慢慢说给我听</em></h1><span>我会先查材料，再回答你</span></section>
   <div className="messages">{messages.map(m=><div className={"message-row "+m.role} key={m.id}>{m.role==="assistant"&&<div className="avatar"><Icon name="spark" size={17}/></div>}<div className="message-bubble"><p>{m.text}</p>{m.uncertainty&&<div className="uncertainty"><strong>还需要确认</strong>{m.uncertainty}</div>}{m.citations?.flatMap(c=>c.evidence_refs).map((id,i)=><button className="citation" key={id+i} onClick={()=>onEvidence(id)}><Icon name="source" size={15}/>查看原始依据 <Icon name="arrow" size={14}/></button>)}</div></div>)}
    {stage&&<div className="message-row assistant"><div className="avatar thinking"><Icon name="spark" size={17}/></div><div className="process-card"><div><span>{stage}</span><b><i/><i/><i/></b></div><section><i/><i/><i/></section><small>只使用你有权查看的内容</small></div></div>}{error&&<div className="chat-error">{error}</div>}<div ref={end}/>
   </div>
  </div>
  <div className="composer-wrap">{messages.length===1&&<div className="suggestions">{suggestions.map(s=><button onClick={()=>void send(s)} key={s}>{s}<Icon name="arrow" size={14}/></button>)}</div>}<form className="composer" onSubmit={submit}><button type="button" className="add-button" aria-label="添加材料"><Icon name="plus"/></button><textarea value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();void send()}}} placeholder="问问暖暖，例如：回家后要注意什么？" rows={1}/><button className="send-button" disabled={!input.trim()||!!stage} aria-label="发送"><Icon name="send"/></button></form><p className="composer-note"><Icon name="shield" size={13}/> AI 回答用于关怀解释，不能替代医生诊疗</p></div>
 </main>
}

function EvidenceDrawer({evidence,onClose}:{evidence:Evidence|null;onClose:()=>void}){return <>{evidence&&<button className="drawer-mask" onClick={onClose} aria-label="关闭"/>}<aside className={"evidence-drawer "+(evidence?"open":"")}><header><div><span>原始材料</span><h2>这句话从哪里来</h2></div><button onClick={onClose}><Icon name="close"/></button></header>{evidence&&<><div className="paper"><b>第 {(evidence.page_index??0)+1} 页</b><p>{evidence.text_span?.text||"当前证据没有可展示的文字片段。"}</p></div><div className="evidence-meta"><span><Icon name="shield" size={16}/>已核对材料版本 {evidence.document_version}</span><small>{evidence.extraction_method==="native_pdf_text"?"原生 PDF 文字":"结构化材料"}</small></div></>}</aside></>}
function ReportView({report,onEvidence}:{report:Report;onEvidence:(id:string)=>void}){return <main className="content-page"><header className="title-block"><span>CARE REPORT · V{report.report_version}</span><h1>你的关怀报告</h1><p>六个部分都来自材料、专业知识或明确的待确认项。</p></header><div className="report-grid">{report.sections.map((s,i)=><article key={s.section_type} className="report-tile"><div className="tile-index">0{i+1}</div><h2>{sectionNames[s.section_type]}</h2>{s.claims.slice(0,1).map(c=><div key={c.claim_id}><p>{c.text}</p><div className="tile-foot"><span>{c.claim_type==="case_fact"?"本次材料":"关怀解释"}</span>{c.evidence_refs.map(id=><button onClick={()=>onEvidence(id)} key={id}>查看依据</button>)}</div></div>)}</article>)}</div></main>}
function ActionsView({report}:{report:Report}){const[done,setDone]=useState<string[]>([]);return <main className="content-page"><header className="title-block"><span>NEXT STEPS</span><h1>先做好这三件事</h1><p>把复杂的恢复计划，变成今天能完成的小事。</p></header><div className="action-list">{report.actions.map((a,i)=><button key={a.action_id} className={done.includes(a.action_id)?"done":""} onClick={()=>setDone(v=>v.includes(a.action_id)?v.filter(x=>x!==a.action_id):[...v,a.action_id])}><b>{String(i+1).padStart(2,"0")}</b><span><strong>{a.action_text}</strong><small>{a.rationale}</small></span><i><Icon name="check"/></i></button>)}</div></main>}
function ProfileView({mode,setMode,onLoad,loading,error}:{mode:"demo"|"live";setMode:(m:"demo"|"live")=>void;onLoad:(v:{token:string;caseId:string;version:number})=>void;loading:boolean;error:string}){const[t,setT]=useState(localStorage.getItem("zhongan_token")||""),[c,setC]=useState(""),[v,setV]=useState(1);return <main className="content-page"><header className="title-block"><span>PRIVACY & DATA</span><h1>数据与隐私</h1><p>真实模式只读取当前令牌获准访问的报告。</p></header><section className="mode-panel"><div className="mode-tabs"><button className={mode==="demo"?"active":""} onClick={()=>setMode("demo")}>合成演示</button><button className={mode==="live"?"active":""} onClick={()=>setMode("live")}>连接真实报告</button></div>{mode==="demo"?<div className="demo-info"><Icon name="shield"/><div><strong>当前是合成案例</strong><p>所有病情和金额均为虚构，只用于展示产品流程。</p></div></div>:<form onSubmit={e=>{e.preventDefault();localStorage.setItem("zhongan_token",t);onLoad({token:t,caseId:c,version:v})}}><label>访问令牌<input type="password" value={t} onChange={e=>setT(e.target.value)} required/></label><label>案件 ID<input value={c} onChange={e=>setC(e.target.value)} required/></label><label>报告版本<input type="number" min="1" value={v} onChange={e=>setV(+e.target.value)}/></label><button>{loading?"正在读取…":"进入关怀空间"}</button>{error&&<p className="form-error">{error}</p>}</form>}</section></main>}

export default function App(){const[view,setView]=useState<View>("assistant"),[mode,setMode]=useState<"demo"|"live">("demo"),[report,setReport]=useState(demoReport),[token,setToken]=useState(""),[evidence,setEvidence]=useState<Evidence|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
 const showEvidence=async(id:string)=>{if(mode==="demo"){setEvidence(demoEvidence[id]||null);return}try{setEvidence(await getEvidence(id,token))}catch(e){setError(e instanceof Error?e.message:"证据读取失败")}};
 const load=async({token:t,caseId,version}:{token:string;caseId:string;version:number})=>{setLoading(true);setError("");try{const r=await getReport(caseId,version,t);setReport(r);setToken(t);setView("assistant")}catch(e){setError(e instanceof ApiError?e.message:"连接失败")}finally{setLoading(false)}};
 return <div className="shell"><aside className="rail"><div className="logo"><span><Icon name="heart"/></span><div><strong>暖愈</strong><small>AI CARE</small></div></div><nav>{nav.map(n=><button key={n.key} className={view===n.key?"active":""} onClick={()=>setView(n.key)}><Icon name={n.icon}/><span>{n.label}</span></button>)}</nav><div className="rail-status"><span/><div><strong>{mode==="demo"?"合成演示":"安全连接"}</strong><small>{mode==="demo"?"不含真实个人信息":"数据已授权"}</small></div></div></aside><section className="workspace"><div className="mobile-bar"><div className="logo"><span><Icon name="heart"/></span><strong>暖愈</strong></div><button onClick={()=>setView("profile")}><Icon name="menu"/></button></div>{mode==="demo"&&<div className="demo-badge">DEMO · 合成案例</div>}{view==="assistant"&&<AssistantView report={report} mode={mode} token={token} onEvidence={showEvidence}/>} {view==="report"&&<ReportView report={report} onEvidence={showEvidence}/>} {view==="actions"&&<ActionsView report={report}/>} {view==="profile"&&<ProfileView mode={mode} setMode={m=>{setMode(m);if(m==="demo")setReport(demoReport)}} onLoad={load} loading={loading} error={error}/>}</section><EvidenceDrawer evidence={evidence} onClose={()=>setEvidence(null)}/><nav className="mobile-nav">{nav.map(n=><button key={n.key} className={view===n.key?"active":""} onClick={()=>setView(n.key)}><Icon name={n.icon}/><span>{n.label}</span></button>)}</nav></div>}
