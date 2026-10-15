import {useEffect,useRef,useState} from 'react';
import {ApiError,getConversation,getEvidence,listConversations,listMedicalRecords,type MemberResponse} from './api';
import {EvidencePanel} from './CarePages';
import {DemoIcon} from './DemoPages';
import {hasMedicalRecord,memberReminders,type MemberReminder} from './reminderProjection';
import {SourceRefs} from './SourceCitations';
import type {ChatSnapshot,Conversation,Evidence,MedicalRecord,ReportSection} from './types';
import guide from '../../../output_dir/product-design/assets/reference-guide.webp';
import './home-reminders.css';

export type OpenHomeRecord=(id:string,destination:'chat'|'report',section?:ReportSection['section_type'])=>void;
type ReminderData={owner:string;snapshots:ChatSnapshot[];records:MedicalRecord[]};
const recent=(a:Conversation,b:Conversation)=>Date.parse(b.updated_at)-Date.parse(a.updated_at)||a.conversation_id.localeCompare(b.conversation_id);
const accessError=(error:unknown)=>error instanceof ApiError&&[401,403].includes(error.status);
const readError=(error:unknown)=>error instanceof ApiError?error.message:'提醒暂时没能更新，请稍后重试。';

export default function HomeReminders({token,member,onOpen,onClaim}:{token:string;member?:MemberResponse;onOpen:OpenHomeRecord;onClaim:()=>void}) {
  const owner=`${token}:${member?.subject_id||''}`;
  const [data,setData]=useState<ReminderData>(),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [retry,setRetry]=useState(0),[evidence,setEvidence]=useState<Evidence|null>(null),[sourceError,setSourceError]=useState('');
  const sourceRequest=useRef(0),cached=useRef(data);cached.current=data;
  useEffect(()=>{
    let active=true,request=0,timer:ReturnType<typeof setTimeout>|undefined;
    setData(previous=>previous?.owner===owner?previous:undefined);setEvidence(null);setLoading(true);setError('');
    const load=async()=>{
      const generation=++request;clearTimeout(timer);++sourceRequest.current;setEvidence(null);setSourceError('');setLoading(true);
      const current=cached.current?.owner===owner?cached.current:undefined;
      try {
        if(!member){setData({owner,snapshots:[],records:[]});return;}
        const [chatResult,profileResult]=await Promise.allSettled([listConversations(token,member.subject_id),listMedicalRecords(token,member.subject_id)]);
        if(!active||request!==generation)return;
        for(const result of [chatResult,profileResult])if(result.status==='rejected'&&accessError(result.reason))throw result.reason;
        if(chatResult.status==='rejected'&&profileResult.status==='rejected')throw chatResult.reason;
        const records=profileResult.status==='fulfilled'?profileResult.value.records.filter(record=>record.subject_id===member.subject_id):current?.records||[];
        const conversations=chatResult.status==='fulfilled'?chatResult.value.filter(item=>item.subject_id===member.subject_id).sort(recent):[];
        const anchors=records.slice(0,3).flatMap(record=>[...record.cases].sort((a,b)=>Date.parse(b.updated_at)-Date.parse(a.updated_at)).slice(0,2)
          .flatMap(batch=>[...batch.conversations].filter(item=>item.subject_id===member.subject_id).sort(recent).slice(0,1)));
        const allowed=new Set([...conversations,...anchors].map(item=>item.conversation_id));
        const remembered=(current?.snapshots||[]).filter(state=>hasMedicalRecord(state)&&(chatResult.status==='rejected'||allowed.has(state.conversation.conversation_id))).map(state=>state.conversation);
        const candidates=[...new Map([...conversations.slice(0,6),...anchors,...remembered].map(item=>[item.conversation_id,item])).values()].slice(0,12);
        const states:ChatSnapshot[]=[],failures:unknown[]=[];let next=0;
        const read=async()=>{
          while(active&&request===generation&&next<candidates.length){
            const expected=candidates[next++];
            try{
              const state=await getConversation(token,expected.conversation_id);
              if(state.conversation.subject_id!==member.subject_id||state.conversation.case_id!==expected.case_id||state.conversation.conversation_id!==expected.conversation_id)throw new Error('就医资料所属记录不一致，请重新加载。');
              states.push(state);
            }catch(error){
              failures.push(error);
              const saved=current?.snapshots.find(state=>state.conversation.conversation_id===expected.conversation_id);
              if(saved&&!accessError(error))states.push(saved);
            }
          }
        };
        await Promise.all(Array.from({length:Math.min(3,candidates.length)},read));
        if(!active||request!==generation)return;
        const denied=failures.find(accessError);if(denied)throw denied;
        states.sort((a,b)=>recent(a.conversation,b.conversation));
        setData({owner,snapshots:states,records});
        const partial=chatResult.status==='rejected'?chatResult.reason:profileResult.status==='rejected'?profileResult.reason:failures[0];
        setError(partial?readError(partial):'');
        if(states.some(state=>['queued','running'].includes(state.analysis.status))||records.some(record=>record.cases.some(batch=>['queued','running'].includes(batch.analysis_status))))timer=setTimeout(()=>void load(),3500);
      }catch(error){
        if(active&&request===generation){if(accessError(error))setData(undefined);setError(readError(error));}
      }finally{if(active&&request===generation)setLoading(false);}
    };
    const focus=()=>void load();void load();window.addEventListener('focus',focus);
    return()=>{active=false;++sourceRequest.current;clearTimeout(timer);window.removeEventListener('focus',focus);};
  },[token,member?.subject_id,retry,owner]);
  const showEvidence=async(id:string)=>{
    const request=++sourceRequest.current;setSourceError('');
    try{const value=await getEvidence(id,token);if(sourceRequest.current===request)setEvidence(value);}
    catch(error){if(sourceRequest.current===request)setSourceError(error instanceof Error?error.message:'原文暂时无法打开，请重试。');}
  };
  const current=data?.owner===owner?data:undefined;
  const reminders=memberReminders(current?.snapshots||[],current?.records||[]);
  const open=(reminder?:MemberReminder)=>{if(reminder?.conversationId)onOpen(reminder.conversationId,reminder.destination,reminder.section);else onClaim();};
  const primary=reminders.find(reminder=>reminder.conversationId);
  const processing=current?.snapshots.some(state=>['queued','running'].includes(state.analysis.status));
  return <section className="replica-guide home-reminders" aria-labelledby="home-reminders-title" aria-busy={loading}>
    <img className="replica-guide-art" src={guide} alt=""/><div className="replica-guide-label"><DemoIcon name="leaf"/>复诊与用药提醒</div>
    <h2 id="home-reminders-title">记好安排，照顾好自己</h2>
    <p className="home-reminder-context">{member?.name||'你的就医关怀'} · 就医档案与近期沟通</p>
    {loading&&<p className="home-reminder-update" role="status">正在读取就医档案与近期安排…</p>}
    {processing&&<p className="home-reminder-update" role="status">正在整理新材料，已有安排可继续查看。</p>}
    <div className="home-reminder-list">{reminders.map(reminder=><article className="home-reminder-item" key={reminder.id}>
      <strong className="home-reminder-label">{reminder.label}</strong>{reminder.time&&<p className="home-reminder-time">{reminder.time}</p>}
      <p className="home-reminder-text">{reminder.text}</p><div className="home-reminder-source"><span>{reminder.sourceLabel}</span><SourceRefs refs={reminder.refs} onEvidence={id=>void showEvidence(id)}/>
        {reminder.conversationId&&<button className="home-reminder-open" onClick={()=>open(reminder)}>查看相关记录<DemoIcon name="arrow"/></button>}
      </div>
    </article>)}</div>
    {error&&<div className="home-reminder-error" role="alert"><p>部分信息暂时未能更新，可先查看已读取的安排。{error}</p><button className="home-reminder-retry" onClick={()=>setRetry(n=>n+1)}>重新加载提醒</button></div>}
    {sourceError&&<p role="alert">{sourceError}</p>}
    <button className="replica-primary" onClick={()=>open(primary)}>{primary?'核对本次安排':'补充就医材料'}<DemoIcon name="arrow"/></button>
    {evidence&&current&&<EvidencePanel token={token} evidence={evidence} onClose={()=>setEvidence(null)}/>}
  </section>;
}
