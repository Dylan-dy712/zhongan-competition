import {useEffect,useRef,useState} from 'react';
import {changeMedicalRecord,getEvidence,listMedicalRecords,organizeMedicalRecords,type MemberResponse} from './api';
import {DemoIcon} from './DemoPages';
import {EvidencePanel} from './CarePages';
import {MemberDialog} from './MemberControls';
import {SourceRefs} from './SourceCitations';
import type {Evidence,MedicalRecord,MedicalRecordsResponse,RecordBatch} from './types';
import './medical-records.css';

const relationLabels:Record<string,string>={same_episode:'补充资料',follow_up:'后续复诊',new_episode:'新的就医',mixed:'资料归属待确认',uncertain:'资料归属待确认',independent:'本次就医'};
const date=(value:string)=>new Date(value).toLocaleDateString('zh-CN');
export default function PersonalRecords({token,member,selected,onSelect,busy,onOpen,onNew,onAccount,currentCase}:{token:string;member:MemberResponse;selected?:string;onSelect:(id?:string)=>void;currentCase?:string;busy:boolean;onOpen:(id:string)=>void;onNew:()=>void;onAccount:()=>void}) {
  const [data,setData]=useState<MedicalRecordsResponse>(),[error,setError]=useState(''),[loading,setLoading]=useState(true),[retry,setRetry]=useState(0);
  const [saving,setSaving]=useState(false),[notice,setNotice]=useState(''),[evidence,setEvidence]=useState<Evidence|null>(null);
  const [adjusting,setAdjusting]=useState<RecordBatch>(),[mode,setMode]=useState<'join'|'separate'|'related'>('join'),[target,setTarget]=useState('');
  const [filter,setFilter]=useState('all');
  const epoch=useRef(0),savingRef=useRef(false),sourceRequest=useRef(0);
  useEffect(()=>{
    const generation=++epoch.current;let request=0,timer:ReturnType<typeof setTimeout>|undefined;
    setLoading(true);setData(undefined);setError('');setEvidence(null);setAdjusting(undefined);
    const load=async()=>{
      const id=++request;clearTimeout(timer);
      try{const result=await listMedicalRecords(token,member.subject_id);if(epoch.current!==generation||id!==request)return;
        setData(result);setError('');
        if(result.processing_count||result.records.some(r=>r.cases.some(c=>['queued','running'].includes(c.analysis_status))))timer=setTimeout(()=>void load(),4000);
      }catch(e){if(epoch.current===generation&&id===request)setError(e instanceof Error?e.message:'记录暂时无法加载。');}
      finally{if(epoch.current===generation&&id===request)setLoading(false);}
    };
    const focus=()=>void load();void load();window.addEventListener('focus',focus);
    return()=>{++epoch.current;++sourceRequest.current;clearTimeout(timer);window.removeEventListener('focus',focus);};
  },[token,member.subject_id,retry]);
  const records=data?.records||[];
  const detail=records.find(r=>r.record_id===selected||r.cases.some(c=>c.case_id===selected));
  const visible=filter==='related'?records.filter(r=>r.related_records.length):records;
  const showEvidence=async(id:string)=>{
    const request=++sourceRequest.current;setError('');
    try{const value=await getEvidence(id,token);if(sourceRequest.current===request)setEvidence(value);}
    catch(e){if(sourceRequest.current===request)setError(e instanceof Error?e.message:'原文暂不可用。');}
  };
  const organize=async()=>{
    if(savingRef.current)return;const generation=epoch.current;savingRef.current=true;setSaving(true);setError('');
    try{const result=await organizeMedicalRecords(token,member.subject_id);if(generation!==epoch.current)return;
      setNotice(result.queued_count?'暖暖正在核对已有资料，同次治疗和复诊会整理到一起。':'当前就医记录已经整理。');setRetry(n=>n+1);
    }catch(e){if(generation===epoch.current)setError(e instanceof Error?e.message:'暂时没能开始整理。');}
    finally{savingRef.current=false;setSaving(false);}
  };
  const saveAssignment=async()=>{
    if(!adjusting||savingRef.current)return;const generation=epoch.current;savingRef.current=true;setSaving(true);setError('');
    try{await changeMedicalRecord(token,adjusting.case_id,{mode,target_record_id:mode==='separate'?undefined:target,expected_version:adjusting.version});
      if(generation!==epoch.current)return;setAdjusting(undefined);onSelect(undefined);setRetry(n=>n+1);
    }catch(e){if(generation===epoch.current)setError(e instanceof Error?e.message:'调整失败，请重新加载后再试。');}
    finally{savingRef.current=false;setSaving(false);}
  };
  const adjust=(batch:RecordBatch)=>{setAdjusting(batch);setMode(batch.proposed_record_id?'join':'separate');setTarget(batch.proposed_record_id||'');};
  const profile=(batch:RecordBatch,full=false)=><div className="medical-record-profile">
    {(['diagnosis','hospital','period','kind',...(full?['summary'] as const:[])] as const).map(key=>{const value=batch.profile[key];return value?<p key={key}><span>{({diagnosis:'诊断／就诊原因',hospital:'就医机构',period:'就医时间',kind:'资料类型',summary:'就医经过'} as const)[key]}</span><strong>{value.value}<SourceRefs refs={value.evidence_refs} onEvidence={id=>void showEvidence(id)}/></strong></p>:null;})}
  </div>;
  const batchView=(batch:RecordBatch)=><article className="medical-record-batch" key={batch.case_id}>
    <header><span>{relationLabels[batch.relation]||'本次资料'}</span><small>更新于 {date(batch.updated_at)}</small></header>
    {profile(batch,true)}
    {!Object.keys(batch.profile).length&&<p className="medical-record-muted">{['queued','running'].includes(batch.analysis_status)?'正在解读本批材料，完成后继续丰富这次就医记录。':'病情、机构和就医日期以本批材料为准，明确的信息会逐步补充。'}</p>}
    <div className="medical-record-batch-meta"><span>{batch.document_count} 份材料</span><span>{batch.assignment_source==='user'?'归属已由本人确认':batch.organization_status==='ready'?'AI 已整理':batch.organization_status==='needs_confirmation'?'归属待确认':batch.organization_status==='unavailable'?'暂未完成智能整理':'等待整理'}</span></div>
    {batch.organization_status==='needs_confirmation'&&<aside className="medical-record-proposal"><strong>{batch.proposal_title?`可能属于「${batch.proposal_title}」`:batch.relation==='mixed'?'本批资料可能涉及多次就医':'这批资料的归属还需要核对'}</strong><p>{batch.reason||'核对后可以归入已有记录，也可以单独保留。'}</p><button className="records-link" onClick={()=>adjust(batch)}>确认资料归属<DemoIcon name="arrow"/></button></aside>}
    <div className="medical-record-actions">{batch.conversations.map(c=><button className="records-detail-action" key={c.conversation_id} disabled={busy} onClick={()=>onOpen(c.conversation_id)}>{c.title}<DemoIcon name="arrow"/></button>)}<button className="records-link" disabled={saving} onClick={()=>adjust(batch)}>调整归属</button></div>
  </article>;
  const related=(record:MedicalRecord)=>record.related_records.length>0&&<div className="medical-record-related"><span>同一疾病历程中的其他就医</span>{record.related_records.map(link=><button className="records-link" key={link.record_id} onClick={()=>onSelect(link.record_id)}>{link.title}<DemoIcon name="arrow"/></button>)}</div>;
  return <main className="demo-pages"><div className={`page records-page medical-records ${detail?'records-detail':''}`}>
    <button className="demo-back" onClick={()=>detail?onSelect(undefined):onAccount()}>{detail?'‹ 返回就医记录':'‹ 返回我的'}</button>
    <header className="medical-record-header member-records-header"><small>{member.name} · 就医档案</small><h1>{detail?detail.title:'把每次就医，慢慢串起来'}</h1><p>{detail?'补充材料和后续复诊保留在同一份记录里，每次变化都有出处。':'同一次治疗持续补充，新的就医分别记录，相关经历彼此衔接。'}</p></header>
    {error&&<div className="medical-record-error" role="alert"><p>{error}</p><button className="records-link" onClick={()=>setRetry(n=>n+1)}>重新加载</button></div>}
    {notice&&<p role="status">{notice}</p>}
    {loading?<p role="status">正在加载 {member.name} 的记录…</p>:detail?<>
      <section className="medical-record-overview"><strong>{detail.cases.length} 批资料 · {detail.document_count} 份材料</strong><span>最近更新 {date(detail.updated_at)}</span><p>新资料补充到同次就医，原始报告和材料仍可分别查看。</p></section>
      {detail.portrait&&<section className="medical-record-card"><h2>这次就医档案</h2>{profile({...detail.cases[0],profile:detail.portrait},true)}</section>}
      {detail.cases.map(batchView)}{related(detail)}
      <button className="member-primary" disabled={busy||!detail.cases[0]?.conversations[0]} onClick={()=>onOpen(detail.cases[0].conversations[0].conversation_id)}>继续补充本次材料</button>
    </>:<>
      <div className="medical-record-toolbar"><span>{records.length} 份就医记录</span><div role="group" aria-label="就医记录范围"><button aria-pressed={filter==='all'} onClick={()=>setFilter('all')}>全部</button><button aria-pressed={filter==='related'} onClick={()=>setFilter('related')}>关联历程</button></div></div>
      {(!!data?.unorganized_count||!!data?.processing_count)&&<aside className="medical-record-organize"><div><strong>{data?.processing_count?'暖暖正在整理就医资料':'已有资料可以继续整理'}</strong><p>核对就医时间、病情和复诊关系，完善档案。</p></div><button className="records-link" disabled={saving||!!data?.processing_count} onClick={()=>void organize()}>{data?.processing_count?'正在整理…':saving?'正在开始…':'智能整理已有记录'}</button></aside>}
      {!records.length&&!error&&<section className="records-detail-card"><h2>还没有就医记录</h2><p>整理病历或处方后，暖暖会逐步建立这次就医的档案。</p><button className="records-detail-action" disabled={busy} onClick={onNew}>准备理赔材料<DemoIcon name="arrow"/></button></section>}
      {visible.map(record=><article className="medical-record-card" key={record.record_id} data-current={record.cases.some(c=>c.case_id===currentCase)}>
        <small>最近更新 {date(record.updated_at)}</small><button className="medical-record-title" onClick={()=>onSelect(record.record_id)}><h2>{record.title}</h2><DemoIcon name="arrow"/></button>
        {profile({...record.cases[0],profile:record.portrait||record.cases[0].profile})}<div className="medical-record-batch-meta"><span>{record.cases.length} 批资料持续汇集</span><span>{record.document_count} 份材料</span></div>
        {record.cases.some(c=>c.organization_status==='needs_confirmation')&&<p className="medical-record-attention">有资料归属需要你确认</p>}
        {related(record)}<button className="records-detail-action" onClick={()=>onSelect(record.record_id)}>查看这次就医<DemoIcon name="arrow"/></button>
      </article>)}
      {!!records.length&&!visible.length&&<p className="medical-record-muted">目前还没有关联到同一疾病历程的记录。</p>}
    </>}
    {evidence&&<EvidencePanel token={token} evidence={evidence} onClose={()=>setEvidence(null)}/>}
    {adjusting&&<MemberDialog title="调整就医资料归属" onClose={()=>{if(!saving)setAdjusting(undefined);}}><h2>这批资料应放在哪里？</h2><p>同次治疗和复诊可以放在一起。新的发作可单独记录，并关联原来的经历。</p>
      <div className="medical-record-options">{([['join','归入已有记录'],['separate','单独保留'],['related','仅关联，不合并']] as const).map(([value,label])=><label key={value}><input type="radio" name="record-mode" checked={mode===value} disabled={saving} onChange={()=>setMode(value)}/>{label}</label>)}</div>
      {mode!=='separate'&&<label className="medical-record-select">{mode==='join'?'选择归入的就医记录':'选择同一疾病历程的记录'}<select value={target} disabled={saving} onChange={e=>setTarget(e.target.value)}><option value="">请选择</option>{records.filter(r=>r.cases.some(c=>c.case_id!==adjusting.case_id)).map(record=><option key={record.record_id} value={record.record_id}>{record.title}</option>)}</select></label>}
      <div className="member-actions"><button disabled={saving} onClick={()=>setAdjusting(undefined)}>取消</button><button className="member-primary" disabled={saving||(mode!=='separate'&&!target)} onClick={()=>void saveAssignment()}>{saving?'正在保存…':'确认归属'}</button></div>
    </MemberDialog>}
  </div></main>;
}
