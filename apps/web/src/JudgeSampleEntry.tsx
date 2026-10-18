import {useEffect,useRef,useState} from 'react';
import {getJudgeSample,type JudgeSample} from './api';
import './judge-sample.css';

export default function JudgeSampleEntry({token,onChoose,disabled=false}:{token:string;onChoose:(sample:JudgeSample)=>Promise<void>|void;disabled?:boolean}) {
  const [sample,setSample]=useState<JudgeSample|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const running=useRef(false);
  useEffect(()=>{let active=true;setSample(null);setError('');
    getJudgeSample(token).then(value=>{if(active)setSample(value);}).catch(()=>{});
    return()=>{active=false;};
  },[token]);
  if(!sample)return null;
  return <section className="judge-sample-card" aria-labelledby="judge-sample-title">
    <span className="judge-sample-label">评委专属体验</span>
    <h2 id="judge-sample-title">体验理赔材料与报告</h2>
    <p className="judge-sample-description">看懂病历与费用，记好后续就医安排。</p>
    <ul>{sample.documents.map(item=><li key={item.name}><span>{item.document_type}</span><small>{item.page_count} 页</small></li>)}</ul>
    <button className="judge-sample-primary" disabled={busy||disabled} onClick={async()=>{
      if(running.current)return;running.current=true;setBusy(true);setError('');
      try{await onChoose(sample);}
      catch(e){setError(e instanceof Error?e.message:'导入暂时中断，请重试。');}
      finally{running.current=false;setBusy(false);}
    }}>{busy?'正在进入体验…':'开始评委体验'}<span aria-hidden="true"> →</span></button>
    {error&&<p role="alert" className="judge-sample-error">{error}</p>}
    <small className="judge-sample-footnote">进入后可核对申请信息与材料，再确认上传。</small>
  </section>;
}
