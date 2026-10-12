import {useEffect,useRef,useState} from 'react';
import {inspectPhoto} from './api';
import type {PhotoQuality} from './types';
import './insights.css';

type Entry={file:File;url?:string;quality?:PhotoQuality;error?:string;accepted:boolean;checking:boolean};
export default function PhotoReview({files,token,subjectId,onCancel,onContinue}:{files:File[];token:string;subjectId:string;onCancel:()=>void;onContinue:(files:File[])=>void}){
 const [entries,setEntries]=useState<Entry[]>(()=>files.map(file=>({file,accepted:!file.type.startsWith('image/'),checking:file.type.startsWith('image/')})));
 const dialog=useRef<HTMLDialogElement>(null),picker=useRef<HTMLInputElement>(null),replaceIndex=useRef(0),alive=useRef(true),urls=useRef(entries.flatMap(e=>e.url?[e.url]:[]));
 const versions=useRef(files.map(()=>0));
 const checks=useRef(new Map<File,Promise<PhotoQuality>>());
 async function check(file:File,index:number){
  const version=++versions.current[index];
  try{let promise=checks.current.get(file);if(!promise){promise=inspectPhoto(token,subjectId,file);checks.current.set(file,promise);}const quality=await promise;if(alive.current&&versions.current[index]===version)setEntries(items=>items.map((e,i)=>i===index?{...e,quality,checking:false,accepted:quality.status==='checked'}:e));}
  catch(error){if(alive.current&&versions.current[index]===version)setEntries(items=>items.map((e,i)=>i===index?{...e,checking:false,error:error instanceof Error?error.message:'检查暂不可用'}:e));}
 }
 useEffect(()=>{alive.current=true;const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();
  setEntries(items=>items.map(entry=>{if(!entry.file.type.startsWith('image/'))return entry;const url=URL.createObjectURL(entry.file);urls.current.push(url);return {...entry,url};}));
  void (async()=>{for(let i=0;i<files.length&&alive.current;i++)if(files[i].type.startsWith('image/'))await check(files[i],i);})();
  return()=>{alive.current=false;urls.current.forEach(url=>URL.revokeObjectURL(url));urls.current=[];dialog.current?.close();previous?.focus?.();};
 },[]);
 const checking=entries.some(e=>e.checking),ready=entries.every(e=>e.accepted&&!e.checking);
 return <dialog ref={dialog} className="source-sheet photo-review" aria-labelledby="photo-review-title" onCancel={e=>{e.preventDefault();onCancel();}}>
  <header><div><small>上传前核对</small><h2 id="photo-review-title">把材料看清楚，再往下走</h2></div><button onClick={onCancel} aria-label="关闭照片检查">×</button></header>
  <p>照片会用于清晰度与文字预检，确认后才纳入本次就医材料。替换照片不会重复计入费用。</p>
  <div className="photo-review-list">{entries.map((entry,index)=><article key={index} className="photo-review-item">
   {entry.url&&<img src={entry.url} alt={`${entry.file.name} 缩略图`}/>}
   <div><strong>{entry.file.name}</strong>
   {entry.checking?<p role="status">正在检查照片与识别材料类型…</p>:entry.quality?<>
    <p>{entry.quality.type_certainty==='likely'?`识别为：可能是${entry.quality.material_type}`:'暂未确定材料类型'} · {entry.quality.status==='checked'?'预检完成':'建议核对'}</p>
    {entry.quality.issues.length>0&&<p className="quality-warning">这张{entry.quality.type_certainty==='likely'?`可能是${entry.quality.material_type}的照片`:'材料照片'}需要核对：{entry.quality.issues.join('；')}。建议重新上传清晰照片。</p>}
    {entry.quality.recognized_excerpt&&<details><summary>已识别的部分文字</summary><blockquote>{entry.quality.recognized_excerpt}</blockquote></details>}
    <small>{entry.quality.notice}</small>
   </>:entry.error?<p role="alert">{entry.error}。尚未确认图片清晰度，可重试检查或暂时继续。</p>:<p>文档将在分析时识别。</p>}
   {!entry.checking&&entry.url&&<div className="insight-actions"><button onClick={()=>{replaceIndex.current=index;picker.current?.click();}}>重新上传这张</button>
    {entry.error&&<button onClick={()=>{checks.current.delete(entry.file);setEntries(items=>items.map((e,i)=>i===index?{...e,checking:true,error:undefined}:e));void check(entry.file,index);}}>重试检查</button>}
    {!entry.accepted&&<button onClick={()=>setEntries(items=>items.map((e,i)=>i===index?{...e,accepted:true}:e))}>暂时继续，保留可读部分</button>}{entry.accepted&&<small>已确认使用</small>}</div>}
   </div></article>)}</div>
  <p className="muted">拍摄时请将纸张放平、靠近文字、避免反光，并保留完整页面。预检不能保证每个字段准确。</p>
  <footer><button onClick={onCancel}>返回修改</button><button className="care-primary" disabled={!ready||checking} onClick={()=>onContinue(entries.map(e=>e.file))}>{checking?'正在检查…':'确认材料，继续上传'}</button></footer>
  <input ref={picker} hidden type="file" accept="image/jpeg,image/png" aria-label="替换模糊照片" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;const index=replaceIndex.current;
   if(!file.size||file.size>10*1024*1024||!/^image\/(jpeg|png)$/.test(file.type)){setEntries(items=>items.map((item,i)=>i===index?{...item,error:'请选择不超过10MB的JPG或PNG照片',accepted:false}:item));return;}
   const url=URL.createObjectURL(file);urls.current.push(url);setEntries(items=>items.map((item,i)=>i===index?{file,url,accepted:false,checking:true}:item));void check(file,index);
  }}/>
 </dialog>;
}
