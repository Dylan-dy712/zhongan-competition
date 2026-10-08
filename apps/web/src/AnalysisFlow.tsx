import {useEffect,useRef,useId,useState} from 'react';
import {estimateWithinStage} from './analysisProgress';
import type {ChatSnapshot,MaterialReport} from './types';
import {careSectionLabels} from './carePresentation';
import './analysis-flow.css';

const steps=[['parse','识别材料'],['extract','提取信息'],['insights','核对疑点'],['guidance','生成报告'],['validate','校验来源']];
export type UploadProgress={done:number;total:number};
export function analysisView(snapshot:ChatSnapshot|null,upload?:UploadProgress,submitting=false,error='') {
  if(error)return {kind:'failed',title:'这次分析没有完成',detail:error,percent:null,index:-1};
  if(upload)return {kind:'upload',title:'正在上传材料',detail:`已上传 ${upload.done} / ${upload.total} 份`,percent:Math.floor(upload.done/upload.total*100),index:-1};
  const material=snapshot?.material_report;
  if(material?.status==='available')return {kind:'ready',title:'你的材料分析报告已生成',detail:'先看结果，有疑问可以接着问暖暖',percent:100,index:5};
  if(material?.status==='failed' || snapshot?.analysis.status==='failed')return {kind:'failed',title:'报告生成没有完成',detail:'材料已保存，可以重新分析。',percent:null,index:-1};
  if(snapshot?.analysis.status==='cancelled')return {kind:'failed',title:'这次分析已取消',detail:'材料已保存，可以重新分析。',percent:null,index:-1};
  const status=snapshot?.analysis.status;
  if(submitting || !status || status==='not_started')return {kind:'processing',title:'正在提交分析任务',detail:'材料已收到，准备开始分析',percent:0,index:-1};
  if(material?.status==='outdated')return {kind:'failed',title:'材料或授权已更新',detail:'请重新分析，生成与当前材料对应的报告。',percent:null,index:-1};
  if(status==='queued')return {kind:'processing',title:'材料已排队',detail:'等待分析服务开始处理',percent:0,index:-1};
  const index=Math.max(0,steps.findIndex(s=>s[0]===snapshot?.analysis.stage));
  return {kind:'processing',title:`暖暖正在${steps[index][1]}`,detail:'正在结合材料逐项处理，请稍候',percent:index*20,index};
}

export function MaterialReportContent({report,onEvidence,onAsk}:{report:MaterialReport;onEvidence:(id:string)=>void;onAsk:(question:string)=>void}) {
  return <div className="material-report-content">
    <div className="material-report-meta"><span>✦ AI 材料分析</span><span>{report.document_count || 0} 份材料 · 第 {report.source_report_version || 1} 次报告</span></div>
    <p className="material-report-notice">{report.notice}</p>
    {(report.sections || []).map(section=><section className="material-report-section" key={section.section_type}>
      <h3>{careSectionLabels[section.section_type]}<span>{section.items.length?'已核对材料':'资料待补充'}</span></h3>
      {section.items.map((item,i)=><div className="material-report-item" key={i}>
        {item.kind==='source' && <small>材料原文 · 保留原文限定</small>}<p>{item.text}</p>
        {item.evidence_refs.map(id=><button className="material-evidence" key={id} onClick={()=>onEvidence(id)}>查看原始依据 ↗</button>)}
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
  const estimating=view.kind==='processing' && view.index>=0 && view.percent!==null;
  const stageKey=`${snapshot?.conversation.conversation_id}:${snapshot?.analysis.run_id}:${view.kind}:${view.index}`;
  const clock=useRef({key:'',started:0});
  const [estimate,setEstimate]=useState({key:'',value:0,elapsed:0});
  useEffect(()=>{
    if(!open || !estimating || view.percent===null)return;
    if(clock.current.key!==stageKey)clock.current={key:stageKey,started:performance.now()};
    const tick=()=>{
      const elapsed=(performance.now()-clock.current.started)/1000;
      setEstimate({key:stageKey,value:estimateWithinStage(view.percent!,view.index,elapsed),elapsed});
    };
    tick();const timer=setInterval(tick,120);return()=>clearInterval(timer);
  },[open,estimating,stageKey,view.percent,view.index]);
  const estimated=estimate.key===stageKey?estimate.value:(view.percent || 0)+1;
  const displayed=estimating?Math.floor(estimated):view.percent;
  const waitingLong=estimating && estimate.key===stageKey && estimate.elapsed>60;
  useEffect(()=>{
    const node=dialog.current;if(!node || !open)return;
    const previous=document.activeElement as HTMLElement|null;
    if(!node.open)node.showModal();
    return()=>{if(node.open)node.close();if(previous?.isConnected)previous.focus();};
  },[open]);
  return <dialog ref={dialog} className="analysis-dialog" aria-labelledby={titleId} onCancel={e=>{e.preventDefault();onClose();}}>
    <button className="analysis-close" aria-label="关闭分析进度" onClick={onClose}>×</button>
    <div className={`analysis-emblem ${view.kind}`} aria-hidden="true">{view.kind==='ready'?'✓':view.kind==='failed'?'!':'✦'}</div>
    <span className="analysis-eyebrow">暖暖 · 陪你看清这次就医</span>
    <h2 id={titleId}>{view.title}</h2><p className="analysis-detail" role="status">{view.detail}</p>
    {displayed!==null && <><div className="analysis-percent"><strong>{displayed}<small>%</small></strong><span>{view.kind==='upload'?'上传进度':estimating?'预估进度':view.kind==='ready'?'分析完成':'等待开始'}</span></div>
      <div className={`analysis-progress-track ${view.kind==='processing' || view.kind==='upload'?'active':''}`}>
        <progress max="100" value={displayed} aria-label={view.kind==='upload'?'材料上传进度':estimating?'材料分析预估进度':'材料分析进度'} aria-valuetext={estimating?`预估 ${displayed}%，当前正在${steps[view.index][1]}`:undefined}/>
        <span className="analysis-progress-fill" style={{width:`${estimating?estimated:displayed}%`}} aria-hidden="true"/>
      </div>
      {view.kind==='processing' && <div className="analysis-live-note"><span aria-hidden="true"/>{waitingLong?'这一阶段需要多一点时间，后台仍在处理':'暖暖正在处理，分析还在继续'}</div>}
      {estimating && <p className="analysis-estimate-note">进度为平滑预估，具体阶段以实际分析为准</p>}</>}
    {view.kind!=='upload' && view.kind!=='failed' && <ol className="analysis-steps">{steps.map(([key,title],i)=><li key={key} className={i<view.index?'done':i===view.index?'current':''}><span>{i<view.index?'✓':i+1}</span>{title}<small>{i<view.index?'已完成':i===view.index?'进行中':'待开始'}</small></li>)}</ol>}
    {view.kind==='ready'?<><div className="analysis-ready-note">已整理 {snapshot?.material_report?.document_count || 0} 份材料{(snapshot?.material_report?.pending_count || 0)>0 && ' · 待核实内容已单独标注'}</div><button className="analysis-primary" onClick={onReport}>查看材料分析报告 →</button></>
      :view.kind==='failed'?<button className="analysis-primary" onClick={onRetry}>重新分析材料</button>
      :<><button className="analysis-secondary" onClick={onClose}>收起进度，稍后查看</button><p className="analysis-background-note">收起窗口后，后台会继续分析材料</p></>}
  </dialog>;
}
