import {useEffect,useRef,useState} from 'react';
import {getConversation,getEvidence,listConversations,type MemberResponse} from './api';
import {EvidencePanel} from './CarePages';
import {DemoIcon} from './DemoPages';
import {encounterGroups,publishedCare} from './carePresentation';
import {hasMedicalRecord,homeReminders} from './reminderProjection';
import {SourceRefs} from './SourceCitations';
import type {ChatSnapshot,Evidence,ReportSection} from './types';
import guide from '../../../output_dir/product-design/assets/reference-guide.webp';
import './home-reminders.css';

export type OpenHomeRecord=(id:string,destination:'chat'|'report',section?:ReportSection['section_type'])=>void;

export default function HomeReminders({token,member,onOpen,onClaim}:{token:string;member?:MemberResponse;onOpen:OpenHomeRecord;onClaim:()=>void}) {
  const [snapshot,setSnapshot]=useState<ChatSnapshot|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [retry,setRetry]=useState(0),[evidence,setEvidence]=useState<Evidence|null>(null),[sourceError,setSourceError]=useState('');
  const sourceRequest=useRef(0);
  useEffect(()=>{
    let active=true,request=0,timer:ReturnType<typeof setTimeout>|undefined;
    setSnapshot(null);setEvidence(null);setLoading(true);setError('');
    const load=async()=>{
      const generation=++request;clearTimeout(timer);++sourceRequest.current;setEvidence(null);setSourceError('');
      try {
        const groups=member?encounterGroups((await listConversations(token,member.subject_id)).filter(item=>item.subject_id===member.subject_id)):[];
        let latest:ChatSnapshot|null=null;
        for(const group of groups){
          if(!active||request!==generation)return;
          const state=await getConversation(token,group.items[0].conversation_id);
          if(state.conversation.subject_id!==member?.subject_id || state.conversation.case_id!==group.case_id || state.conversation.conversation_id!==group.items[0].conversation_id)throw new Error('就医资料所属记录不一致，请重新加载。');
          // A newer empty chat must not replace the latest medical instructions.
          if(hasMedicalRecord(state)){latest=state;break;}
        }
        if(!active||request!==generation)return;
        setSnapshot(latest);setError('');
        if(latest&&['queued','running'].includes(latest.analysis.status))timer=setTimeout(()=>void load(),3500);
      }catch(e){if(active&&request===generation){setSnapshot(null);setError(e instanceof Error?e.message:'提醒暂时没能加载，请重试。');}}
      finally{if(active&&request===generation)setLoading(false);}
    };
    const focus=()=>void load();void load();window.addEventListener('focus',focus);
    return()=>{active=false;++sourceRequest.current;clearTimeout(timer);window.removeEventListener('focus',focus);};
  },[token,member?.subject_id,retry]);
  const showEvidence=async(id:string)=>{
    const request=++sourceRequest.current;setSourceError('');
    try{const value=await getEvidence(id,token);if(sourceRequest.current===request)setEvidence(value);}
    catch(e){if(sourceRequest.current===request)setSourceError(e instanceof Error?e.message:'原文暂时无法打开，请重试。');}
  };
  const reminders=snapshot?homeReminders(snapshot):[];
  const open=(section?:ReportSection['section_type'])=>{if(snapshot)onOpen(snapshot.conversation.conversation_id,publishedCare(snapshot.report)?'report':'chat',section);};
  const processing=snapshot&&['queued','running'].includes(snapshot.analysis.status);
  return <section className="replica-guide home-reminders" aria-labelledby="home-reminders-title" aria-busy={loading}>
    <img className="replica-guide-art" src={guide} alt=""/><div className="replica-guide-label"><DemoIcon name="leaf"/>复诊与用药提醒</div>
    <h2 id="home-reminders-title">记好安排，照顾好自己</h2>
    {loading?<p role="status">正在读取最近一次就医的安排…</p>:error?<><p role="alert">{error}</p><button className="replica-primary" onClick={()=>setRetry(n=>n+1)}>重新加载提醒<DemoIcon name="arrow"/></button></>:<>
      <p className="home-reminder-context">{member?.name}{snapshot?` · ${snapshot.conversation.title} · 最近更新 ${new Date(snapshot.conversation.updated_at).toLocaleDateString('zh-CN')}`:' · 尚无就医材料'}</p>
      {reminders.length?<div className="home-reminder-list">{reminders.slice(0,3).map(reminder=><article className="home-reminder-item" key={reminder.id}>
        <strong className="home-reminder-label">{reminder.label}</strong>{reminder.time&&<p className="home-reminder-time">{reminder.time}</p>}
        <p className="home-reminder-text">{reminder.text}</p><div className="home-reminder-source"><span>{publishedCare(snapshot!.report)?'本次已发布安排':'本次材料原文'}</span><SourceRefs refs={reminder.refs} onEvidence={id=>void showEvidence(id)}/></div>
      </article>)}</div>:<div className="home-reminder-empty"><strong>{processing?'正在整理本次医嘱':snapshot?'本次资料尚未找到复诊或用药安排':'先把出院医嘱、处方放进来'}</strong><p>{processing?'整理完成后，这里会显示材料里的复诊时间和用药要求。':snapshot?'可以补充出院医嘱或处方，核对复诊时间、服药频次与剂量。':'暖暖会结合你的就医材料，帮你记好复诊和服药要求。'}</p></div>}
      {sourceError&&<p role="alert">{sourceError}</p>}
      <button className="replica-primary" onClick={()=>snapshot?open(reminders[0]?.section):onClaim()}>{snapshot?'核对本次安排':'补充就医材料'}<DemoIcon name="arrow"/></button>
    </>}
    {evidence&&<EvidencePanel token={token} evidence={evidence} onClose={()=>setEvidence(null)}/>}
  </section>;
}
