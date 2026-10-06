import {useEffect,useRef,useState} from 'react';
import {createConversation,sendChatMessage,uploadChatDocument} from './api';
import {claimTemplate,initialClaimForm,validateClaimInfo,type ClaimFile,type ClaimForm} from './claimTemplate';
import './claim-original.css';

function uuid() {
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

export default function ClaimIntake({token,subject,onOpen,onAuthorize}:{token:string;subject:string;onAuthorize:()=>void;onOpen:(id:string)=>Promise<void>}) {
  const [step,setStep]=useState(0);
  const form=useRef<ClaimForm>(initialClaimForm());
  const [files,setFiles]=useState<ClaimFile[]>([]);
  const [,redraw]=useState(0);
  const shell=useRef<HTMLDivElement>(null);
  const picker=useRef<HTMLInputElement>(null);
  const source=useRef<HTMLDialogElement>(null);
  const preview=useRef<HTMLDialogElement>(null);
  const [previewFile,setPreviewFile]=useState<ClaimFile|null>(null);
  const category=useRef('record');
  const fileRef=useRef(files);fileRef.current=files;
  useEffect(()=>()=>fileRef.current.forEach(f=>{if(f.url)URL.revokeObjectURL(f.url);}),[]);
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
    if(running.current || !confirmed || !subject)return;
    const invalid=validateClaimInfo(form.current);if(invalid){setError(invalid);setStep(0);return;}
    const missing=claimTemplate(form.current,files,step).groups.filter(g=>g.required&&!files.some(f=>f.category===g.id));
    if(missing.length){setError('请补充：'+missing.map(g=>g.title).join('、'));setStep(1);return;}
    running.current=true;
    setBusy(true);setError('');setLocked(true);
    pending.current ??= {id:uuid(),requestId:uuid(),uploaded:new Map()};
    const attempt=pending.current;
    try {
      await createConversation(token,attempt.id,subject);
      if(!mounted.current)return;
      const activeGroups=claimTemplate(form.current,files,step).groups;
      for(const entry of files.filter(f=>activeGroups.some(g=>g.id===f.category))){
        const file=entry.file;if(attempt.uploaded.has(file))continue;
        const result=await uploadChatDocument(token,attempt.id,file);attempt.uploaded.set(file,result.document_id);
        if(!mounted.current)return;
      }
      await sendChatMessage(token,attempt.id,attempt.requestId,
        `请帮我整理本次就医资料，解释费用与需要补充的材料。用户填写的信息：${JSON.stringify(form.current)}；材料分类：${JSON.stringify(files.map(f=>({name:f.name,category:f.category})))}。这些是个人补充信息，请以材料原文核对，不代表已确认事实。`,[...attempt.uploaded.values()]);
      if(mounted.current)setFinished(true);
    }catch(e){if(mounted.current)setError(e instanceof Error?e.message:'材料整理失败，请重试。');}
    finally{running.current=false;if(mounted.current)setBusy(false);}
  };
  const template=claimTemplate(form.current,files,step,finished);
  const next=()=>{
    const invalid=validateClaimInfo(form.current);if(invalid){setError(invalid);return;}
    if(step===1){const missing=template.groups.filter(g=>g.required&&!files.some(f=>f.category===g.id));if(missing.length){setError('请补充：'+missing.map(g=>g.title).join('、'));return;}}
    setError('');setStep(step+1);shell.current?.querySelector('.claim-main')?.scrollTo?.(0,0);
  };
  return <main className="claim-react">
    <div className="claim-shell" ref={shell} dangerouslySetInnerHTML={{__html:locked&&!finished?template.html.replace(/<(input|select) /g,'<$1 disabled '):template.html}} onInput={e=>{
      const input=e.target as HTMLInputElement;const key=input.dataset.claimField as keyof ClaimForm;
      if(key && key in form.current){form.current[key]=input.value;}
    }} onChange={e=>{
      const input=e.target as unknown as HTMLSelectElement;const key=input.dataset.claimField as keyof ClaimForm;
      if(key && key in form.current){form.current[key]=input.value;setConfirmed(false);if(input.tagName==='SELECT')redraw(n=>n+1);}
    }} onClick={e=>{
      const button=(e.target as HTMLElement).closest<HTMLButtonElement>('button');if(!button||button.disabled)return;
      if(locked && !finished)return;
      const action=button.dataset.claimAction;
      if(action==='example'){form.current={...initialClaimForm(),diagnosis:'肺炎（虚构示例）',start:'2026-09-20',end:'2026-09-25',total:'1200.00',social:'是'};redraw(n=>n+1);setError('');}
      else if(action?.startsWith('step-')){setStep(Number(action.slice(5)));setError('');setConfirmed(false);}
      else if(action?.startsWith('pick-')){category.current=action.slice(5);source.current?.showModal();}
      else if(button.dataset.claimRemove){const removed=files.find(f=>f.id===button.dataset.claimRemove);if(removed?.url)URL.revokeObjectURL(removed.url);setFiles(files.filter(f=>f!==removed));setConfirmed(false);}
      else if(button.dataset.claimPreview){setPreviewFile(files.find(f=>f.id===button.dataset.claimPreview)||null);preview.current?.showModal();}
      else if(button.dataset.go && finished)void onOpen(pending.current!.id).catch(e=>setError(e instanceof Error?e.message:'打开失败，请重试。'));
    }}/>
    {error && <p className="claim-error" role="alert">{error}</p>}
    <footer className="claim-shell claim-footer">
      {!finished && step===2 && <label className="claim-consent"><input type="checkbox" checked={confirmed} disabled={locked} onChange={e=>setConfirmed(e.target.checked)}/><span>我已核对信息，同意将合成材料上传并用于关怀分析<small>不会向保险公司提交理赔申请。</small></span></label>}
      {!subject && !finished && <button className="claim-text" onClick={onAuthorize}>确认资料用途授权</button>}
      {step>0 && !finished && <button className="claim-finish" disabled={locked||busy} onClick={()=>{setStep(step-1);setError('');}}>返回修改</button>}
      <button className="claim-primary" disabled={busy||(!finished&&step===2&&(!confirmed||!subject))} onClick={()=>{if(finished)void onOpen(pending.current!.id).catch(e=>setError(e instanceof Error?e.message:'打开失败'));else if(step<2)next();else void submit();}}>{busy?'正在整理材料…':finished?'查看专属关怀':step===0?'下一步，上传材料':step===1?'下一步，核对申请':locked?'重试整理':'确认并开始关怀'}</button>
    </footer>
    <input ref={picker} hidden aria-label="添加就医材料" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={e=>{
      const added=Array.from(e.target.files||[]);e.target.value='';
      if(files.length+added.length>20||added.some(f=>!f.size||f.size>10*1024*1024||!/\.(pdf|jpe?g|png)$/i.test(f.name))){setError('请选择有效 PDF 或图片，每份不超过 10 MB，总数最多 20 份。');return;}
      setFiles([...files,...added.map(file=>({id:uuid(),name:file.name,size:file.size,category:category.current,sample:false,url:/\.(jpe?g|png)$/i.test(file.name)?URL.createObjectURL(file):null,file}))]);setError('');setConfirmed(false);
    }}/>
    <dialog ref={source} className="claim-upload-dialog" aria-label="选择材料来源"><div className="claim-preview-head"><strong>添加理赔材料</strong><button onClick={()=>source.current?.close()} aria-label="关闭材料来源">×</button></div>
      <button className="claim-source-option" onClick={()=>{source.current?.close();picker.current!.accept='.jpg,.jpeg,.png';picker.current?.click();}}>从相册选择图片<small>JPG、PNG 格式</small></button>
      <button className="claim-source-option" onClick={()=>{source.current?.close();picker.current!.accept='.pdf';picker.current?.click();}}>从文件选择 PDF<small>选择已保存的 PDF</small></button><p>每份不超过 10 MB，确认前仅本机预览。</p></dialog>
    <dialog ref={preview} className="claim-preview-dialog" aria-label="材料图片预览"><div className="claim-preview-head"><strong>{previewFile?.name}</strong><button aria-label="关闭图片预览" onClick={()=>preview.current?.close()}>×</button></div>{previewFile?.url && <img src={previewFile.url} alt={previewFile.name}/>}</dialog>
  </main>;
}
