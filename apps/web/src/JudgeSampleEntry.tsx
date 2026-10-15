import {useEffect,useRef,useState} from 'react';
import {getJudgeSample,chooseJudgeSampleFiles,type JudgeSample,type JudgeSampleFile} from './api';
import './judge-sample.css';

export default function JudgeSampleEntry({token,onChoose,prepareFiles=false,disabled=false}:{token:string;onChoose:(sample:JudgeSample,files:JudgeSampleFile[])=>Promise<void>|void;prepareFiles?:boolean;disabled?:boolean}) {
  const [sample,setSample]=useState<JudgeSample|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [completed,setCompleted]=useState(0);
  const running=useRef(false);
  useEffect(()=>{let active=true;setSample(null);setError('');
    getJudgeSample(token).then(value=>{if(active)setSample(value);}).catch(()=>{});
    return()=>{active=false;};
  },[token]);
  if(!sample)return null;
  return <section className="judge-sample-card" aria-labelledby="judge-sample-title">
    <span className="judge-sample-label">评委专属体验</span>
    <h2 id="judge-sample-title">没有病例资料？用示例体验</h2>
    <p className="judge-sample-description">{sample.title}</p>
    <ul>{sample.documents.map(item=><li key={item.name}><span>{item.document_type}</span><small>{item.page_count} 页</small></li>)}</ul>
    <p className="judge-sample-notice">{sample.notice} 共 {sample.file_count} 份资料、{sample.page_count} 页，体验选择文件、上传、识别与报告生成。</p>
    <button className="judge-sample-primary" disabled={busy||disabled} onClick={async()=>{
      if(running.current)return;running.current=true;setBusy(true);setError('');setCompleted(0);
      try{const files=prepareFiles?await chooseJudgeSampleFiles(token,sample,setCompleted):[];await onChoose(sample,files);}
      catch(e){setError(e instanceof Error?e.message:'导入暂时中断，请重试。');}
      finally{running.current=false;setBusy(false);}
    }}>{busy?`正在选择示例资料（${completed}/${sample.file_count}）…`:prepareFiles?'导入示例病例':'用示例体验上传流程'}<span aria-hidden="true"> →</span></button>
    {error&&<p role="alert" className="judge-sample-error">{error}</p>}
    <small className="judge-sample-footnote">确认提交后才上传，点击查看报告后开始识别与分析。</small>
  </section>;
}
