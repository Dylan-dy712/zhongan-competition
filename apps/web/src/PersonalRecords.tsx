import {useEffect,useState} from 'react';
import {listConversations,type MemberResponse} from './api';
import {DemoRecords} from './DemoPages';
import type {Conversation} from './types';

export default function PersonalRecords({token,member,selected,onSelect,...props}:{token:string;member:MemberResponse;selected?:string;onSelect:(caseId?:string)=>void;currentCase?:string;busy:boolean;onOpen:(id:string)=>void;onNew:()=>void;onAccount:()=>void}) {
  const [records,setRecords]=useState<Conversation[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;setLoading(true);setRecords([]);setError('');listConversations(token,member.subject_id).then(items=>{if(active)setRecords(items);})
    .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[token,member.subject_id,retry]);
  if(loading||error)return <main className="demo-pages"><div className="page"><button className="demo-back" onClick={props.onAccount}>‹ 返回我的</button><h1>{member.name} 的就医记录</h1>{loading?<p role="status">正在加载记录…</p>:<><p role="alert">{error}</p><button className="records-detail-action" onClick={()=>setRetry(n=>n+1)}>重新加载</button></>}</div></main>;
  return <DemoRecords {...props} conversations={records} personName={member.name} selected={selected} onSelect={onSelect}/>;
}
