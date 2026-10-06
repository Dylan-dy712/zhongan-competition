import {useEffect,useRef,useState} from 'react';
import {createConversation,sendChatMessage,uploadChatDocument} from './api';
import {reading} from './CarePages';

function uuid() {
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

export default function ClaimIntake({token,subject,onOpen,onAuthorize}:{token:string;subject:string;onAuthorize:()=>void;onOpen:(id:string)=>Promise<void>}) {
  const [step,setStep]=useState(0);
  const [kind,setKind]=useState('住院医疗');
  const [diagnosis,setDiagnosis]=useState('');
  const [date,setDate]=useState('');
  const [files,setFiles]=useState<File[]>([]);
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const pending=useRef<{id:string;requestId:string;uploaded:Map<File,string>} | null>(null);
  const [finished,setFinished]=useState(false);
  const [locked,setLocked]=useState(false);
  const mounted=useRef(true);
  const running=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const submit=async()=>{
    if(running.current || !confirmed)return;
    running.current=true;
    setBusy(true);setError('');setLocked(true);
    pending.current ??= {id:uuid(),requestId:uuid(),uploaded:new Map()};
    const attempt=pending.current;
    try {
      await createConversation(token,attempt.id,subject);
      if(!mounted.current)return;
      for(const file of files)if(!attempt.uploaded.has(file)){
        const result=await uploadChatDocument(token,attempt.id,file);attempt.uploaded.set(file,result.document_id);
        if(!mounted.current)return;
      }
      await sendChatMessage(token,attempt.id,attempt.requestId,
        `请帮我整理本次就医资料，解释费用与需要补充的材料。就医类型：${kind}；就诊日期：${date || '待核对'}；我填写的诊断或症状：${diagnosis || '待核对'}。这些是个人补充信息，请以材料原文核对，不代表已确认事实。`,[...attempt.uploaded.values()]);
      if(mounted.current)setFinished(true);
    }catch(e){if(mounted.current)setError(e instanceof Error?e.message:'材料整理失败，请重试。');}
    finally{running.current=false;if(mounted.current)setBusy(false);}
  };
  if(finished)return <main className="claim-intake"><img src={reading} alt="暖暖" width="120"/><h1>资料已进入你的关怀空间</h1>
    <p>你可以继续查看分析进度，向暖暖提问，并在报告发布后阅读关怀指引。</p>
    <p>保险理赔申请尚未提交，正式理赔请通过保险公司的服务渠道办理。</p>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={async()=>{setBusy(true);try{await onOpen(pending.current!.id);}catch(e){setError(e instanceof Error?e.message:'打开失败，请重试。');}finally{setBusy(false);}}}>查看专属关怀</button></main>;
  return <main className="claim-intake"><span className="auth-brand">理赔准备 · 专属关怀</span><h1>准备本次理赔材料</h1>
    <p>把这次就医的事，一步步整理好。填写就医信息、添加材料，再核对本次资料。</p>
    <p aria-live="polite">{['① 填写信息','② 添加材料','③ 核对并开始关怀'][step]}</p>
    <form onSubmit={e=>{e.preventDefault();if(step<2)setStep(step+1);else void submit();}}>
      {step===0 && <><label>就医类型<select value={kind} onChange={e=>setKind(e.target.value)}><option>住院医疗</option><option>门急诊医疗</option></select></label>
        <label>诊断或症状（可选）<input maxLength={160} value={diagnosis} onChange={e=>setDiagnosis(e.target.value)}/></label>
        <label>就诊日期（可选）<input type="date" value={date} onChange={e=>setDate(e.target.value)}/></label></>}
      {step===1 && <><h2>病历、发票与费用清单</h2><small>支持 PDF、JPG、PNG，每份不超过 10 MB，最多 20 份。仅使用合成测试材料。</small>
        <input aria-label="添加就医材料" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={e=>{
          const selected=Array.from(e.target.files || []);e.target.value='';
          if(files.length+selected.length>20 || selected.some(f=>f.size===0 || f.size>10*1024*1024 || !/\.(pdf|jpe?g|png)$/i.test(f.name))){setError('请选择有效 PDF 或图片，每份不超过 10 MB，总数最多 20 份。');return;}
          setError('');setFiles([...files,...selected]);}}/>
        <ul>{files.map((file,i)=><li key={i}>{file.name} <button type="button" onClick={()=>setFiles(files.filter((_,j)=>i!==j))}>移除</button></li>)}</ul></>}
      {step===2 && <><p>{kind} · {date || '日期待核对'} · {diagnosis || '诊断待核对'}</p><p>共 {files.length} 份材料</p>
        <label className="auth-consent"><input type="checkbox" checked={confirmed} disabled={locked} onChange={e=>setConfirmed(e.target.checked)} required/><span>确认将上述合成材料上传并用于关怀分析。此操作不会向保险公司提交理赔申请。</span></label></>}
      {error && <p role="alert" className="auth-error">{error}</p>}
      <button disabled={busy || (step===1 && files.length===0) || (step===2 && (!confirmed || !subject))}>{busy?'正在整理材料…':step<2?'下一步':locked?'重试整理':'确认并开始关怀'}</button>
      {step>0 && <button type="button" disabled={busy || locked} onClick={()=>{setStep(step-1);setError('');}}>上一步</button>}
      {!subject && <button type="button" onClick={onAuthorize}>确认资料用途授权</button>}
      {!subject && <small>你可以先准备材料。开始关怀前，请到“我的”确认资料用途授权。</small>}
    </form></main>;
}
