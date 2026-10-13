import {createContext,useContext,useEffect,useRef,useState} from 'react';
import {getKnowledgeSource} from './api';
import {emphasisParts} from './narrativeFormatting';
import type {InlineCitation,KnowledgeSource} from './types';
import './insights.css';

export const SourceToken=createContext('');
export function SourceRefs({refs,onEvidence,sources=[],catalog=refs}:{refs:string[];onEvidence:(id:string)=>void;sources?:KnowledgeSource[];catalog?:string[]}){
 const token=useContext(SourceToken),[selected,setSelected]=useState<string>();
 return <><sup className="source-refs">{[...new Set(refs)].map(id=><button type="button" key={id} className="source-ref" title="查看这条内容的来源" aria-label={`查看来源 ${Math.max(1,catalog.indexOf(id)+1)}`} onClick={()=>{
  if(/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(id))onEvidence(id);else setSelected(id);
 }}>{Math.max(1,catalog.indexOf(id)+1)}</button>)}</sup>
 {selected&&<KnowledgeSheet key={selected} id={selected} token={token} initial={sources.find(s=>s.entry_id===selected)} onClose={()=>setSelected(undefined)}/>}</>;
}
function KnowledgeSheet({id,token,initial,onClose}:{id:string;token:string;initial?:KnowledgeSource;onClose:()=>void}){
 const [source,setSource]=useState(initial),[error,setError]=useState(''),dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{let active=true;const previous=document.activeElement as HTMLElement;dialog.current?.showModal();
  if(!initial?.content)void getKnowledgeSource(token,id).then(value=>{if(active)setSource(value);}).catch(()=>{if(active)setError('该来源的详细摘录暂不可用，请稍后重试。');});
  return()=>{active=false;dialog.current?.close();previous?.focus?.();};
 },[id,token]);
 const web=source?.retrieval_provider==='volcengine';
 const original=web&&/^https?:\/\//.test(source.source)?source.source:undefined;
 return <dialog ref={dialog} className="source-sheet" aria-labelledby="knowledge-source-title" onCancel={e=>{e.preventDefault();onClose();}}>
  <header><div><small>{web?'网络参考资料':'医学知识来源'}</small><h2 id="knowledge-source-title">{source?.title||'正在查阅来源…'}</h2></div><button onClick={onClose} aria-label="关闭来源">×</button></header>
  {source&&<><p>{source.source||'参考资料名称待核对'}</p><p className="muted">资料版本：{source.version}</p><p>{source.scope}</p>
  {original&&<p><a href={original} target="_blank" rel="noopener noreferrer">查看原网页</a>{source.retrieved_at&&<small> · 获取时间：{new Date(source.retrieved_at).toLocaleString('zh-CN')}</small>}</p>}
  {source.content&&<blockquote>{source.content}</blockquote>}<small>{web?'公开网页用于一般解释，个人治疗安排以你的病历和医生医嘱为准。':'章节与页码以资料原有标注为准；未提供的位置不作推测。'}</small></>}
  {error&&<p role="alert">{error}</p>}
 </dialog>;
}

export function CitedText({text,citations=[],onEvidence,sources=[],catalog}:{text:string;citations?:InlineCitation[];onEvidence:(id:string)=>void;sources?:KnowledgeSource[];catalog?:string[]}){
 const parts=emphasisParts(text),plain=parts.map(p=>p.text).join('');
 const links=citations.map(c=>({citation:c,end:plain.indexOf(c.quote)+c.quote.length})).filter(({citation:c,end})=>plain.indexOf(c.quote)>=0&&plain.indexOf(c.quote)===plain.lastIndexOf(c.quote)&&end>0).sort((a,b)=>a.end-b.end);
 const cuts=[0,...new Set([...links.map(l=>l.end),plain.length])];
 const all=catalog||[...new Set(citations.flatMap(c=>c.source_refs))];
 const segment=(start:number,end:number)=>{let offset=0;return parts.map((part,index)=>{const left=Math.max(start,offset),right=Math.min(end,offset+part.text.length);const value=part.text.slice(Math.max(0,left-offset),Math.max(0,right-offset));offset+=part.text.length;return right>left?(part.strong?<strong key={index}>{value}</strong>:value):null;});};
 return <>{cuts.slice(1).map((end,i)=><span key={i}>{segment(cuts[i],end)}{links.filter(l=>l.end===end).map((link,j)=><SourceRefs key={j} refs={link.citation.source_refs} onEvidence={onEvidence} sources={sources} catalog={all}/>)}</span>)}</>;
}
