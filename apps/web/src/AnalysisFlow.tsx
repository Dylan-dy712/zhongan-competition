import {useEffect,useRef,useId,useState} from 'react';
import {analysisSteps as steps,analysisStageIndex} from './analysisProgress';
import type {ChatSnapshot,MaterialReport} from './types';
import {careSectionLabels} from './carePresentation';
import {currentNarrative} from './AnalysisNarrative';
import mascot from '../../../output_dir/product-design/assets/reference-mascot.webp';
import './analysis-flow.css';
import {SourceRefs} from './SourceCitations';

function AnalysisIcon({kind}:{kind:string}) {
  const paths:Record<string,React.ReactNode>={
    parse:<><path d="M6 3h8l4 4v14H6V3Z"/><path d="M14 3v5h5M9 12h6M9 16h6"/></>,
    extract:<><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 10v4h6v-4M8 3h8"/></>,
    insights:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5M8 11l2 2 4-5"/></>,
    guidance:<><rect x="5" y="3" width="14" height="18" rx="1"/><path d="M9 7h6M9 11h6M9 15h4"/></>,
    validate:<><path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/></>,
    narrative:<><path d="M6 3h9l4 4v14H6V3Z"/><path d="M15 3v5h4M9 12h6M9 16h4"/></>,
    bulb:<><path d="M8 17c0-2-4-3-4-7a8 8 0 0 1 16 0c0 4-4 5-4 7M8 17h8l-1 4H9l-1-4ZM12 1V0M2 3l-2-2M22 3l2-2"/></>,
    chevron:<path d="m6 15 6-6 6 6"/>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind==='analysis'?'extract':kind]}</svg>;
}
export type UploadProgress={done:number;total:number};
export function analysisView(snapshot:ChatSnapshot|null,upload?:UploadProgress,submitting=false,error='') {
  if(!upload && !submitting && currentNarrative(snapshot?.turns || [],snapshot?.analysis.run_id))return {kind:'ready',title:'暖暖的解读已准备好',detail:'解读已出现在对话中，可以接着聊',percent:100,index:steps.length};
  if(error)return {kind:'failed',title:'这次分析没有完成',detail:error,percent:null,index:-1};
  if(upload)return {kind:'upload',title:'正在上传材料',detail:`已上传 ${upload.done} / ${upload.total} 份`,percent:Math.floor(upload.done/upload.total*100),index:-1};
  // A new submission must not inherit the previous run's completed/failed stage.
  if(submitting)return {kind:'processing',title:'正在提交分析任务',detail:'材料已收到，准备开始分析',percent:null,index:-1};
  const material=snapshot?.material_report;
  if(material?.status==='available')return {kind:'processing',title:'暖暖正在把情况讲清楚',detail:'正在写好解读并核对内容，准备好后会直接显示在对话里',percent:null,index:4};
  if((snapshot?.analysis.error as {code?:string}|undefined)?.code==='REPORT_MODEL_BALANCE_EXHAUSTED')return {kind:'failed',title:'分析服务暂不可用',detail:'材料已保存，无需重新上传。服务恢复后可以重新分析。',percent:null,index:-1};
  if(material?.status==='failed' || snapshot?.analysis.status==='failed')return {kind:'failed',title:'报告生成没有完成',detail:'材料已保存，可以重新分析。',percent:null,index:-1};
  if(snapshot?.analysis.status==='cancelled')return {kind:'failed',title:'这次分析已取消',detail:'材料已保存，可以重新分析。',percent:null,index:-1};
  const status=snapshot?.analysis.status;
  if(!status || status==='not_started')return {kind:'processing',title:'正在提交分析任务',detail:'材料已收到，准备开始分析',percent:null,index:-1};
  if(material?.status==='outdated')return {kind:'failed',title:'材料或授权已更新',detail:'请重新分析，生成与当前材料对应的报告。',percent:null,index:-1};
  if(status==='queued')return {kind:'processing',title:'材料已排队',detail:'等待分析服务开始处理',percent:null,index:-1};
  const index=analysisStageIndex(snapshot?.analysis.stage);
  const step=index>=0?steps.at(index):undefined;
  return {kind:'processing',title:step?`暖暖正在${step[1]}`:'暖暖正在处理材料',
    detail:index===1?'正在提取材料信息，同时核对需要关注的内容':index>=0?'正在结合材料逐项处理，请稍候':'正在同步当前处理步骤，请稍候',percent:null,index};
}

export function MaterialReportContent({report,onEvidence,onAsk}:{report:MaterialReport;onEvidence:(id:string)=>void;onAsk:(question:string)=>void}) {
  return <div className="material-report-content">
    <div className="material-report-meta"><span>✦ AI 材料分析</span><span>{report.document_count || 0} 份材料 · 第 {report.source_report_version || 1} 次报告</span></div>
    <p className="material-report-notice">{report.notice}</p>
    {(report.sections || []).map(section=><section className="material-report-section" key={section.section_type}>
      <h3>{careSectionLabels[section.section_type]}<span>{section.items.length?'已核对材料':'资料待补充'}</span></h3>
      {section.items.map((item,i)=><div className="material-report-item" key={i}>
        {item.kind==='source' && <small>材料原文 · 保留原文限定</small>}<p>{item.text}<SourceRefs refs={item.evidence_refs} onEvidence={onEvidence}/></p>

      </div>)}
      {!section.items.length && <p className="material-report-empty">当前没有通过自动核对的内容。可以补充相关材料或向暖暖核实。</p>}
      {section.pending_count>0 && <p className="material-pending">{section.pending_count} 项解释或结论需要核实，暂未作为确认结果展示。</p>}
      <button className="material-ask" onClick={()=>onAsk(`请结合我的材料，继续解释“${careSectionLabels[section.section_type]}”，说明哪些信息还需要核实。`)}>继续问这部分 →</button>
    </section>)}
  </div>;
}

export default function AnalysisFlow({open,snapshot,upload,submitting,error,onClose,onReport,onRetry}:{open:boolean;snapshot:ChatSnapshot|null;upload?:UploadProgress;submitting?:boolean;error?:string;onClose:()=>void;onReport:()=>void;onRetry:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const titleId=useId();
  const view=analysisView(snapshot,upload,submitting,error);
  const processing=view.kind==='processing';
  const stageKey=`${snapshot?.conversation.conversation_id}:${snapshot?.analysis.run_id}:${view.kind}:${view.index}`;
  const clock=useRef({key:'',started:0});
  const [waiting,setWaiting]=useState({key:'',elapsed:0});
  useEffect(()=>{
    if(!open || !processing || view.index<0)return;
    if(clock.current.key!==stageKey)clock.current={key:stageKey,started:performance.now()};
    const tick=()=>{
      const elapsed=(performance.now()-clock.current.started)/1000;
      setWaiting({key:stageKey,elapsed});
    };
    tick();const timer=setInterval(tick,1000);return()=>clearInterval(timer);
  },[open,processing,stageKey,view.index]);
  const completedSteps=Math.max(0,view.index);
  const progressMax=processing?steps.length:100;
  const progressValue=processing?(view.index>=0?completedSteps:undefined):view.percent??undefined;
  const waitingLong=processing && waiting.key===stageKey && waiting.elapsed>60;
  useEffect(()=>{
    const node=dialog.current;if(!node || !open)return;
    const previous=document.activeElement as HTMLElement|null;
    if(!node.open)node.showModal();
    return()=>{if(node.open)node.close();if(previous?.isConnected)previous.focus();};
  },[open]);
  return <dialog ref={dialog} className="analysis-dialog" aria-labelledby={titleId} onCancel={e=>{e.preventDefault();onClose();}}>
    <button className="analysis-close" aria-label="关闭分析进度" onClick={onClose}>×</button>
    <header className="analysis-hero">
      <div className="analysis-hero-art" aria-hidden="true"><span className="analysis-orbit"/><span className="analysis-paper first"><AnalysisIcon kind="guidance"/></span><span className="analysis-paper second"><AnalysisIcon kind="parse"/></span><span className="analysis-spark">✦</span><img src={mascot} alt="" width="280" height="280"/></div>
      <div className="analysis-hero-copy"><div className={`analysis-emblem ${view.kind}`} aria-hidden="true">{view.kind==='ready'?'✓':view.kind==='failed'?'!':'✦'}</div>
        <span className="analysis-eyebrow">暖暖 · 陪你看清这次就医</span>
        <h2 id={titleId}>{view.title}</h2><p className="analysis-detail" role="status">{view.detail}</p>
      </div>
    </header>
    {(processing || view.percent!==null) && <section className="analysis-status-card" aria-label="材料分析进度与阶段">
      <div className="analysis-percent"><strong>{processing?completedSteps:view.percent}<small>{processing?`/ ${steps.length} 步`:'%'}</small></strong><span>{view.kind==='upload'?'上传进度':processing?'已完成步骤':'分析完成'}</span></div>
      <div className={`analysis-progress-track ${processing || view.kind==='upload'?'active':''} ${progressValue===undefined?'indeterminate':''}`}>
        <progress max={progressMax} value={progressValue} aria-label={view.kind==='upload'?'材料上传进度':processing?'材料分析已完成步骤':'材料分析进度'} aria-valuetext={processing?`已完成 ${completedSteps} / ${steps.length} 步，${view.index>=0?`当前正在${steps[view.index][1]}`:'等待处理状态'}`:undefined}/>
        <span className="analysis-progress-fill" style={progressValue===undefined?undefined:{width:`${progressValue/progressMax*100}%`}} aria-hidden="true"/>
      </div>
      {processing && <div className="analysis-live-panel"><div className="analysis-live-note"><span aria-hidden="true"/>{waitingLong?'这一步耗时较长，可以收起窗口稍后查看':'完成当前步骤后会自动继续'}</div>
        <p className="analysis-progress-note">按实际处理步骤更新，各步骤耗时不同</p></div>}
      {view.kind!=='upload' && <ol className="analysis-steps">{steps.map(([key,title],i)=>{
        const status=i<view.index?'done':i===view.index?'current':'pending';
        return <li key={key} className={status} aria-current={status==='current'?'step':undefined}>
          <span className="analysis-step-number" aria-hidden="true">{status==='done'?<svg viewBox="0 0 24 24" fill="none"><path d="m5 12 5 5 9-11" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/></svg>:i+1}</span>
          <div className="analysis-step-body"><span className="analysis-step-icon"><AnalysisIcon kind={key}/></span><span className="analysis-step-title">{title}</span><small>{status==='current'&&<span className="analysis-step-spinner" aria-hidden="true"/>}{status==='done'?'已完成':status==='current'?'进行中':'待开始'}</small></div>
        </li>;
      })}</ol>}
    </section>}
    {view.kind==='ready'?<><div className="analysis-ready-note">已整理 {snapshot?.material_report?.document_count || 0} 份材料</div><button className="analysis-primary" onClick={onReport}>回到对话看解读 →</button></>
      :view.kind==='failed'?<button className="analysis-primary" onClick={onRetry}>重新分析材料</button>
      :<><button className="analysis-secondary" onClick={onClose}><AnalysisIcon kind="bulb"/><span>收起进度，稍后查看</span><AnalysisIcon kind="chevron"/></button><p className="analysis-background-note">收起窗口后，后台会继续分析材料</p></>}
  </dialog>;
}
