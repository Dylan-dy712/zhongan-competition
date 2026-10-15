import {useEffect,useRef,useState} from 'react';
import {prepareChatFiles} from './chatFiles';

export type DraftAttachment={id:string;file:File};
function FilePreview({file}:{file:File}){
 const [url,setUrl]=useState('');
 useEffect(()=>{if(!file.type.startsWith('image/'))return;const next=URL.createObjectURL(file);setUrl(next);return()=>URL.revokeObjectURL(next);},[file]);
 return url?<img src={url} alt={file.name}/>:<span className="chat-file-icon" aria-hidden="true">▤</span>;
}
export function ChatDraftAttachments({files,busy,onRemove,caption='可继续添加问题，一起发送'}:{files:DraftAttachment[];busy:boolean;onRemove:(id:string)=>void;caption?:string}){
 if(!files.length)return null;
 return <div className="chat-draft-attachments" aria-label="待发送附件">{files.map(item=><article key={item.id}>
  <FilePreview file={item.file}/><span><strong>{item.file.name}</strong><small>{busy?'正在发送…':caption}</small></span>
  <button type="button" aria-label={`移除附件 ${item.file.name}`} disabled={busy} onClick={()=>onRemove(item.id)}>×</button>
 </article>)}</div>;
}
export function ReportUploadDialog({person,onClose,onSubmit}:{person:string;onClose:()=>void;onSubmit:(files:File[])=>void}){
 const dialog=useRef<HTMLDialogElement>(null),picker=useRef<HTMLInputElement>(null);
 const [files,setFiles]=useState<DraftAttachment[]>([]),[error,setError]=useState('');
 const nextId=useRef(0);
 useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>{dialog.current?.close();previous?.focus?.();};},[]);
 return <dialog ref={dialog} className="report-upload-dialog" aria-labelledby="report-upload-title" onCancel={e=>{e.preventDefault();onClose();}}>
  <header><div><small>新建解读报告 · {person}</small><h2 id="report-upload-title">上传需要解读的材料</h2></div><button type="button" aria-label="关闭报告材料上传" onClick={onClose}>×</button></header>
  <p>选择病历、检查结果或费用票据，暖暖会为你整理成一份解读报告。</p>
  <input ref={picker} hidden type="file" multiple accept=".pdf,.txt,.jpg,.jpeg,.png" aria-label="选择报告材料" onChange={e=>{
    try{const selected=prepareChatFiles(e.target.files||[]);setFiles(current=>[...current,...selected.map(file=>({id:String(++nextId.current),file}))]);setError('');}
    catch(error){setError(error instanceof Error?error.message:'请选择支持的材料。');}e.target.value='';
  }}/>
  <button className="report-upload-pick" type="button" onClick={()=>picker.current?.click()}><span aria-hidden="true">＋</span>{files.length?'继续添加材料':'选择材料'}<small>JPG、PNG、PDF、TXT · 每份不超过 10MB</small></button>
  <ChatDraftAttachments files={files} busy={false} caption="报告材料，确认后开始解读" onRemove={id=>setFiles(current=>current.filter(file=>file.id!==id))}/>
  {error&&<p role="alert">{error}</p>}
  <footer><button type="button" onClick={onClose}>暂不上传</button><button className="care-primary" disabled={!files.length} onClick={()=>onSubmit(files.map(item=>item.file))}>上传并生成解读报告</button></footer>
 </dialog>;
}
