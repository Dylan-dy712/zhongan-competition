import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {createConversation,startChatAnalysis,uploadChatDocument,createJudgeSampleUploadCase,chooseJudgeSampleFiles,getCareConsent,changeCareConsent,type JudgeSample} from './api';
import AnalysisFlow,{type UploadProgress} from './AnalysisFlow';
import {claimTemplate,initialClaimForm,validateClaimInfo,type ClaimFile,type ClaimForm} from './claimTemplate';
import './claim-original.css';
import './judge-sample.css';
import {syncClaimMarkup} from './claimDom';
import PhotoReview from './PhotoReview';
import CarePreparation from './CarePreparation';

function uuid() {
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

export type JudgeSampleRequest={id:string;sample:JudgeSample};

export default function ClaimIntake({token,subject,visible,onOpen,onAuthorize,onExit,onDirty,sampleRequest}:{sampleRequest?:JudgeSampleRequest;onDirty?:(dirty:boolean)=>void;token:string;subject:string;visible:boolean;onAuthorize:()=>void;onExit:()=>void;onOpen:(id:string,report?:boolean)=>Promise<void>}) {
  const [step,setStep]=useState(0);
  const form=useRef<ClaimForm>(initialClaimForm());
  const [files,setFiles]=useState<ClaimFile[]>([]);
  const [,redraw]=useState(0);
  const shell=useRef<HTMLDivElement>(null);
  const picker=useRef<HTMLInputElement>(null);
  const source=useRef<HTMLDialogElement>(null);
  const preview=useRef<HTMLDialogElement>(null);
  const [previewFile,setPreviewFile]=useState<ClaimFile|null>(null);
  const [previewPdf,setPreviewPdf]=useState('');
  const [judgeSample,setJudgeSample]=useState<JudgeSample|null>(null);
  const [sampleLoading,setSampleLoading]=useState(false),[sampleProgress,setSampleProgress]=useState(0);
  const [sampleError,setSampleError]=useState(''),[sampleRetry,setSampleRetry]=useState(0);
  useEffect(()=>{if(!previewFile||previewFile.url){setPreviewPdf('');return;}
    const url=URL.createObjectURL(previewFile.file);setPreviewPdf(url);
    return()=>URL.revokeObjectURL(url);
  },[previewFile]);
  const category=useRef('record');
  const [sourceCategory,setSourceCategory]=useState('');
  const fileRef=useRef(files);fileRef.current=files;
  useEffect(()=>()=>fileRef.current.forEach(f=>{if(f.url)URL.revokeObjectURL(f.url);}),[]);
  const [confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [progressOpen,setProgressOpen]=useState(false);
  const [progress,setProgress]=useState<UploadProgress>();
  const [submission,setSubmission]=useState(false);
  const pending=useRef<{id:string;requestId:string;uploaded:Map<File,string>;caseId?:string;analysisStarted?:boolean;requestLocked?:boolean;careConfirmed?:boolean} | null>(null);
  const [finished,setFinished]=useState(false);
  const [careStage,setCareStage]=useState<'receipt'|'materials'|'consent'>('receipt');
  const [supplements,setSupplements]=useState<ClaimFile[]>([]);
  const supplementRef=useRef(supplements);supplementRef.current=supplements;
  useEffect(()=>()=>supplementRef.current.forEach(f=>{if(f.url)URL.revokeObjectURL(f.url);}),[]);
  const [careAgreed,setCareAgreed]=useState(false);
  const [locked,setLocked]=useState(false);
  const [reviewPhotos,setReviewPhotos]=useState(false);
  useEffect(()=>{if(!visible)setReviewPhotos(false);},[visible]);
  const mounted=useRef(true);
  const running=useRef(false);
  const wasVisible=useRef(visible);
  useEffect(()=>{
    const entering=visible&&!wasVisible.current;wasVisible.current=visible;
    if(!entering||!finished||!pending.current?.analysisStarted||running.current)return;
    fileRef.current.forEach(f=>{if(f.url)URL.revokeObjectURL(f.url);});
    supplementRef.current.forEach(f=>{if(f.url)URL.revokeObjectURL(f.url);});
    form.current=initialClaimForm();pending.current=null;setJudgeSample(null);
    setFiles([]);setStep(0);setConfirmed(false);setFinished(false);setLocked(false);
    setCareStage('receipt');setSupplements([]);setCareAgreed(false);
    setError('');setProgressOpen(false);setProgress(undefined);setPreviewFile(null);
    onDirty?.(false);
  },[visible,finished,onDirty]);
  const viewReport=async()=>{
    const attempt=pending.current;if(!finished||!attempt||running.current||(!attempt.analysisStarted&&(careStage!=='consent'||!careAgreed)))return;
    running.current=true;setBusy(true);setError('');setSubmission(true);setProgressOpen(true);
    try{
      if(!attempt.analysisStarted){
        if(!attempt.careConfirmed){
          const consent=await getCareConsent(token,subject);
          await changeCareConsent(token,true,consent.version,subject);
          attempt.careConfirmed=true;
        }
        if(supplements.some(entry=>!attempt.uploaded.has(entry.file))){
          setProgress({done:supplements.filter(entry=>attempt.uploaded.has(entry.file)).length,total:supplements.length});
          for(const entry of supplements){
            if(attempt.uploaded.has(entry.file))continue;
            const result=await uploadChatDocument(token,attempt.id,entry.file);
            attempt.uploaded.set(entry.file,result.document_id);
            if(!mounted.current)return;
            setProgress({done:supplements.filter(item=>attempt.uploaded.has(item.file)).length,total:supplements.length});
          }
        }
        setProgress(undefined);
        const activeGroups=claimTemplate(form.current,files,step).groups;
        const entries=[...files.filter(f=>activeGroups.some(g=>g.id===f.category)),...supplements];
        attempt.requestLocked=true;
        await startChatAnalysis(token,attempt.id,attempt.requestId,
          `${judgeSample?'这是一组主办方比赛样例的脱敏体验资料，不代表账号使用者本人病史。':''}请帮我整理本次就医资料，解释费用与需要补充的材料。用户填写的信息：${JSON.stringify(form.current)}；材料分类：${JSON.stringify(activeGroups.map(group=>({category:group.title,count:entries.filter(entry=>entry.category===group.id).length})))}。这些是个人补充信息，请以材料原文核对，不代表已确认事实。`,[...new Set(attempt.uploaded.values())]);
        attempt.analysisStarted=true;
      }
      await onOpen(attempt.id);
      if(mounted.current)setProgressOpen(false);
    }catch(e){if(mounted.current)setError(e instanceof Error?e.message:'分析暂时没能开始，请重试。');}
    finally{running.current=false;if(mounted.current){setBusy(false);setSubmission(false);setProgress(undefined);}}
  };
  const openCare=()=>{
    if(running.current)return;
    if(pending.current?.analysisStarted){void viewReport();return;}
    setError('');setCareStage('materials');
  };
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{
    if(!sampleRequest)return;
    if(running.current){setSampleError('材料正在提交，请完成后再从首页开始体验。');return;}
    let active=true;const sample=sampleRequest.sample;
    fileRef.current.forEach(entry=>{if(entry.url)URL.revokeObjectURL(entry.url);});
    supplementRef.current.forEach(entry=>{if(entry.url)URL.revokeObjectURL(entry.url);});
    form.current={...initialClaimForm(),...sample.claim_info};pending.current=null;
    setJudgeSample(sample);setFiles([]);setStep(0);setConfirmed(false);setFinished(false);setLocked(false);
    setCareStage('receipt');setSupplements([]);setCareAgreed(false);
    setError('');setSampleError('');setSampleProgress(0);setSampleLoading(true);
    setPreviewFile(null);preview.current?.close();source.current?.close();setReviewPhotos(false);
    setProgressOpen(false);setProgress(undefined);
    chooseJudgeSampleFiles(token,sample,completed=>{if(active)setSampleProgress(completed);}).then(selected=>{
      if(active)setFiles(selected.map(entry=>({id:uuid(),name:entry.file.name,size:entry.file.size,category:entry.category,sample:true,url:null,file:entry.file})));
    }).catch(e=>{if(active)setSampleError(e instanceof Error?e.message:'示例资料准备中断，请重试。');})
      .finally(()=>{if(active)setSampleLoading(false);});
    return()=>{active=false;};
  },[token,sampleRequest,sampleRetry]);
  const submit=async(checkedFiles?:ClaimFile[])=>{
    if(running.current || !confirmed || !subject)return;
    const invalid=validateClaimInfo(form.current);if(invalid){setError(invalid);setStep(0);return;}
    const missing=claimTemplate(form.current,files,step).groups.filter(g=>g.required&&!files.some(f=>f.category===g.id));
    if(missing.length){setError('请补充：'+missing.map(g=>g.title).join('、'));setStep(1);return;}
    if(!checkedFiles&&!pending.current&&files.some(entry=>entry.url)){setReviewPhotos(true);return;}
    const selectedFiles=checkedFiles||files;
    running.current=true;
    setBusy(true);setError('');setLocked(true);
    pending.current ??= {id:uuid(),requestId:uuid(),uploaded:new Map()};
    const attempt=pending.current;
    try {
      if(judgeSample&&selectedFiles.every(entry=>entry.sample)&&!attempt.caseId){
        const created=await createJudgeSampleUploadCase(token,subject,judgeSample,'judge-upload:'+attempt.id);
        attempt.caseId=created.case_id;
      }
      await createConversation(token,attempt.id,subject,attempt.caseId);
      if(!mounted.current)return;
      const activeGroups=claimTemplate(form.current,files,step).groups;
      const entries=selectedFiles.filter(f=>activeGroups.some(g=>g.id===f.category));
      setProgress({done:attempt.uploaded.size,total:entries.length});
      for(const entry of entries){
        const file=entry.file;if(attempt.uploaded.has(file))continue;
        const result=await uploadChatDocument(token,attempt.id,file);attempt.uploaded.set(file,result.document_id);
        setProgress({done:attempt.uploaded.size,total:entries.length});
        if(!mounted.current)return;
      }
      if(mounted.current){setFinished(true);onDirty?.(false);}
    }catch(e){if(mounted.current)setError(e instanceof Error?e.message:'材料整理失败，请重试。');}
    finally{running.current=false;if(mounted.current){setBusy(false);setProgress(undefined);setSubmission(false);}}
  };
  const template=claimTemplate(form.current,files,step,finished,!!judgeSample);
  useEffect(()=>{onDirty?.(!finished?!!(judgeSample||files.length||step>0||locked):careStage!=='receipt'&&!pending.current?.analysisStarted);},[judgeSample,files.length,step,locked,finished,careStage,busy,onDirty]);
  const html=(locked&&!finished)||sampleLoading?template.html.replace(/<(input|select) /g,'<$1 disabled '):template.html;
  useLayoutEffect(()=>{if(shell.current)syncClaimMarkup(shell.current,html);},[html]);
  useLayoutEffect(()=>{shell.current?.querySelector('.claim-main')?.scrollTo?.(0,0);},[step]);
  const next=()=>{
    const invalid=validateClaimInfo(form.current);if(invalid){setError(invalid);return;}
    if(step===1){const missing=template.groups.filter(g=>g.required&&!files.some(f=>f.category===g.id));if(missing.length){setError('请补充：'+missing.map(g=>g.title).join('、'));return;}}
    setError('');setStep(step+1);shell.current?.querySelector('.claim-main')?.scrollTo?.(0,0);
  };
  return <main className="claim-react">
    {careStage!=='receipt'&&<CarePreparation stage={careStage} date={[form.current.start,form.current.kind==='住院医疗'?form.current.end:''].filter(Boolean).join(' 至 ')}
      files={files.filter(entry=>pending.current?.uploaded.has(entry.file))} supplements={supplements} uploaded={entry=>!!pending.current?.uploaded.has(entry.file)}
      busy={busy} locked={!!pending.current?.requestLocked} agreed={careAgreed} onAgree={setCareAgreed}
      onBack={()=>{setError('');setCareStage(careStage==='consent'?'materials':'receipt');}} onHome={onExit}
      onNext={()=>{setError('');setCareStage('consent');}} onConfirm={()=>void viewReport()}
      onPick={()=>{category.current='record';setSourceCategory('补充就医资料');source.current?.showModal();}}
      onRemove={entry=>{if(running.current||pending.current?.requestLocked||pending.current?.uploaded.has(entry.file))return;if(entry.url)URL.revokeObjectURL(entry.url);setSupplements(items=>items.filter(item=>item!==entry));setCareAgreed(false);setError('');}}
      onPreview={entry=>{setPreviewFile(entry);preview.current?.showModal();}}/>}
    {judgeSample&&!finished&&<p className="claim-sample-status" role="status">{sampleLoading?`申请信息已填好，正在准备示例材料（${sampleProgress}/${judgeSample.file_count}）…`:sampleError?'申请信息已填好，示例材料尚未准备完成。':'申请信息与示例材料已自动填好，尚未提交。核对后即可确认上传。'}</p>}
    {sampleError&&<p className="claim-error" role="alert">{sampleError} <button className="claim-text" disabled={sampleLoading||busy||locked} onClick={()=>setSampleRetry(value=>value+1)}>重新准备示例资料</button></p>}
    {reviewPhotos&&<PhotoReview token={token} subjectId={subject} files={files.map(f=>f.file)} onCancel={()=>setReviewPhotos(false)} onContinue={checked=>{
      const updated=files.map((entry,index)=>entry.file===checked[index]?entry:{...entry,file:checked[index],name:checked[index].name,size:checked[index].size,url:URL.createObjectURL(checked[index])});
      files.forEach((entry,index)=>{if(entry!==updated[index]&&entry.url)URL.revokeObjectURL(entry.url);});
      setFiles(updated);setReviewPhotos(false);void submit(updated);
    }}/>}
    <AnalysisFlow open={visible && progressOpen} snapshot={null} upload={progressOpen?progress:undefined} submitting={submission} error={error} onClose={()=>setProgressOpen(false)} onReport={()=>void viewReport()} onRetry={()=>void viewReport()}/>
    {progress && <p className="claim-text" role="status">正在上传材料：{progress.done} / {progress.total} 份</p>}
    <div className="claim-shell" hidden={careStage!=='receipt'} ref={shell} onInput={e=>{
      const input=e.target as HTMLInputElement;const key=input.dataset.claimField as keyof ClaimForm;
      if(key && key in form.current){form.current[key]=input.value;onDirty?.(true);}
    }} onChange={e=>{
      const input=e.target as unknown as HTMLSelectElement;const key=input.dataset.claimField as keyof ClaimForm;
      if(key && key in form.current){form.current[key]=input.value;onDirty?.(true);setConfirmed(false);if(input.tagName==='SELECT')redraw(n=>n+1);}
    }} onClick={e=>{
      const button=(e.target as HTMLElement).closest<HTMLButtonElement>('button');if(!button||button.disabled)return;
      const action=button.dataset.claimAction;
      if(action==='exit'){onExit();return;}
      if((locked && !finished)||sampleLoading)return;
      if(action==='example'){form.current={...initialClaimForm(),diagnosis:'肺炎（虚构示例）',start:'2026-09-20',end:'2026-09-25',total:'1200.00',social:'是'};redraw(n=>n+1);setError('');}
      else if(action?.startsWith('step-')){setStep(Number(action.slice(5)));setError('');setConfirmed(false);}
      else if(action?.startsWith('pick-')){category.current=action.slice(5);setSourceCategory(template.groups.find(g=>g.id===category.current)?.title||'理赔材料');source.current?.showModal();}
      else if(button.dataset.claimRemove){const removed=files.find(f=>f.id===button.dataset.claimRemove);if(removed?.url)URL.revokeObjectURL(removed.url);setFiles(files.filter(f=>f!==removed));setConfirmed(false);}
      else if(button.dataset.claimPreview){setPreviewFile(files.find(f=>f.id===button.dataset.claimPreview)||null);preview.current?.showModal();}
      else if(button.dataset.go && finished)openCare();
    }}/>
    {error && <p className="claim-error" role="alert">{error}</p>}
    <footer className="claim-shell claim-footer" hidden={careStage!=='receipt'}>
      {!finished && step===2 && <label className="claim-consent"><input type="checkbox" checked={confirmed} disabled={locked} onChange={e=>setConfirmed(e.target.checked)}/><span>我已核对信息，同意上传本次材料，用于资料整理与关怀分析<small>本次上传不会向保险公司提交理赔申请。</small></span></label>}
      {!subject && !finished && <button className="claim-text" onClick={onAuthorize}>确认资料用途授权</button>}
      {step>0 && !finished && <button className="claim-finish" disabled={locked||busy} onClick={()=>{setStep(step-1);setError('');}}>返回修改</button>}
      {finished&&<button className="claim-home" disabled={busy} onClick={onExit}>返回首页</button>}
      <button className="claim-primary" disabled={busy||(!finished&&(sampleLoading||!!sampleError||step===2&&(!confirmed||!subject)))} onClick={()=>{if(finished)openCare();else if(step<2)next();else void submit();}}>{busy?(finished?'正在开始分析…':'正在上传材料…'):finished?'查看就医关怀':step===0?'下一步，上传材料':step===1?'下一步，核对申请':locked?'重试提交':'确认提交材料'}</button>
    </footer>
    <input ref={picker} hidden aria-label="添加就医材料" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={e=>{
      if(running.current||pending.current?.requestLocked)return;
      const added=Array.from(e.target.files||[]).map(file=>file.type?file:new File([file],file.name,{type:/\.pdf$/i.test(file.name)?'application/pdf':/\.png$/i.test(file.name)?'image/png':'image/jpeg',lastModified:file.lastModified}));e.target.value='';
      if(added.some(f=>!f.size||f.size>10*1024*1024||!/\.(pdf|jpe?g|png)$/i.test(f.name))){setError('请选择有效 PDF 或图片，每份不超过 10 MB。');return;}
      const selected=added.map(file=>({id:uuid(),name:file.name,size:file.size,category:category.current,sample:false,url:/\.(jpe?g|png)$/i.test(file.name)?URL.createObjectURL(file):null,file}));
      if(finished){setSupplements(items=>[...items,...selected]);setCareAgreed(false);}
      else {setFiles([...files,...selected]);setConfirmed(false);}
      setError('');
    }}/>
    <dialog ref={source} className="claim-upload-dialog" aria-labelledby="claim-source-title" aria-describedby="claim-source-description" onClick={e=>{
      if(e.target!==e.currentTarget)return;
      const bounds=e.currentTarget.getBoundingClientRect();
      if(e.clientX<bounds.left||e.clientX>bounds.right||e.clientY<bounds.top||e.clientY>bounds.bottom)source.current?.close();
    }}>
      <div className="claim-source-heading"><div><span className="claim-source-category">{sourceCategory}</span><h2 id="claim-source-title">{finished?'补充看病资料':'添加理赔材料'}</h2></div><button type="button" className="claim-source-close" onClick={()=>source.current?.close()} aria-label="关闭材料来源"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div>
      <p id="claim-source-description" className="claim-source-description">请选择材料类型，支持一次选择多份</p>
      <div className="claim-source-options">
        <button type="button" className="claim-source-option" onClick={()=>{source.current?.close();picker.current!.accept='.jpg,.jpeg,.png';picker.current?.click();}}>
          <span className="claim-source-icon" aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8" cy="8" r="1.5"/><path d="m3 16 5-5 4 4 4-5 5 6"/></svg></span>
          <span className="claim-source-copy"><strong>从相册选择图片</strong><small>上传清晰的材料照片</small><span className="claim-source-format">JPG / PNG</span></span>
          <svg className="claim-source-arrow" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>
        </button>
        <button type="button" className="claim-source-option claim-source-pdf" onClick={()=>{source.current?.close();picker.current!.accept='.pdf';picker.current?.click();}}>
          <span className="claim-source-icon" aria-hidden="true"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8M8 17h5"/></svg></span>
          <span className="claim-source-copy"><strong>从文件选择 PDF</strong><small>上传已保存的电子材料</small><span className="claim-source-format">PDF</span></span>
          <svg className="claim-source-arrow" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>
        </button>
      </div>
      <div className="claim-source-note"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-5"/></svg><p>每份不超过 10 MB，数量不限<br/><span>确认前仅在本机预览</span></p></div>
    </dialog>
    <dialog ref={preview} className="claim-preview-dialog" aria-label="材料图片预览"><div className="claim-preview-head"><strong>{previewFile?.name}</strong><button aria-label="关闭图片预览" onClick={()=>{preview.current?.close();setPreviewFile(null);}}>×</button></div>{previewFile?.url ? <img src={previewFile.url} alt={previewFile.name}/> : previewPdf&&<iframe className="claim-pdf-preview" src={previewPdf} title={previewFile?.name||'资料预览'}/>}</dialog>
  </main>;
}
