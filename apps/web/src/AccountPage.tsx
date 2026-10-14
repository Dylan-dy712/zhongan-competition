import {useEffect,useState} from 'react';
import {getConversation,getEvidence,listMedicalRecords,type MemberResponse} from './api';
import {encounterSummary,type EncounterSummary} from './encounterSummary';
import {DemoIcon} from './DemoPages';
import {encounterGroups} from './carePresentation';
import type {Conversation,MedicalRecord} from './types';
import {MemberDialog,MemberEditor,MemberPicker,MemberList,memberDescription,relationshipLabels} from './MemberControls';

export default function AccountPage({token,members,member,onSelect,onSaved,onRecords,onNew,onLogout}:{
  token:string;members:MemberResponse[];member:MemberResponse;onSelect:(id:string)=>void;
  onSaved:(member:MemberResponse)=>Promise<void>;onRecords:(caseId?:string)=>void;onNew:()=>void;
  onLogout:()=>Promise<void>;
}) {
  const [summary,setSummary]=useState<EncounterSummary>();
  const [records,setRecords]=useState<Conversation[]>([]);
  const [recordGroup,setRecordGroup]=useState<MedicalRecord>();
  const [loading,setLoading]=useState(true),[error,setError]=useState('');
  const [retry,setRetry]=useState(0);
  const [mode,setMode]=useState<'switch'|'manage'|'add'|'edit'>();
  const [editing,setEditing]=useState<MemberResponse>();
  useEffect(()=>{let active=true;setLoading(true);setSummary(undefined);setRecords([]);setError('');
    setRecordGroup(undefined);
    listMedicalRecords(token,member.subject_id).then(async result=>{
      if(!active)return;
      const items=result.records.flatMap(record=>record.cases.flatMap(batch=>batch.conversations));
      setRecords(items);
      const group=result.records[0];setRecordGroup(group);
      const portrait=group?.portrait||group?.cases.find(batch=>Object.keys(batch.profile).length)?.profile;
      const grouped:EncounterSummary={...(portrait?.diagnosis?{diagnosis:portrait.diagnosis.value,source:'material' as const}:{}),...(portrait?.hospital?{hospital:portrait.hospital.value}:{}),
        ...(portrait?.period?{period:portrait.period.value}:{}),...(portrait?.kind?{kind:portrait.kind.value}:{}),...(group?{documentCount:group.document_count}:{})};
      if(portrait)setSummary(grouped);
      const recent=encounterGroups(items)[0];
      if(!recent)return;
      try{
        const snapshot=await getConversation(token,recent.items[0].conversation_id);
        if(!active)return;
        setSummary({...encounterSummary(snapshot),...grouped});
        setLoading(false);
        const refs=snapshot.material_report?.status==='available'
          ? [...new Set(snapshot.material_report.sections?.filter(s=>s.section_type==='diagnosis_explanation'||s.section_type==='treatment_review').flatMap(s=>s.items.flatMap(i=>i.evidence_refs))||[])].slice(0,8):[];
        const evidence=await Promise.allSettled(refs.map(id=>getEvidence(id,token)));
        if(active)setSummary({...encounterSummary(snapshot,evidence.flatMap(result=>result.status==='fulfilled'&&result.value.text_span?.text?[result.value.text_span.text]:[])),...grouped});
      }catch{/* A summary failure must not hide the saved record or its detail link. */}
    }).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[token,member.subject_id,retry]);
  const recent=encounterGroups(records)[0];
  const saved=async(value:MemberResponse)=>{await onSaved(value);setMode(undefined);};
  return <main className="demo-pages"><div className="page demo-account">
    <p className="member-account-label">登录账号：{sessionStorage.getItem('zhongan_account_name')||'已连接账号'}</p>
    <section className="records-profile"><div className="member-profile-heading"><span className="records-profile-kicker">当前健康档案</span><button className="records-link" onClick={()=>setMode('manage')}>管理成员<DemoIcon name="arrow"/></button></div>
      <div className="records-profile-top"><span className="records-avatar"><DemoIcon name="user"/></span><div className="records-person"><h1>{member.name} <span>{relationshipLabels[member.relationship]}</span></h1><p>{memberDescription(member)}</p></div></div>
      <p className="records-profile-saying">已建立 {members.length} 位成员的档案，就医记录分别保存。</p><div className="member-actions member-profile-actions"><button onClick={()=>setMode('switch')}>切换人员</button><button onClick={()=>{setEditing(member);setMode('edit');}}>编辑资料</button><button onClick={()=>setMode('add')}>添加家人</button></div>
    </section>
    <section className="records-detail-card"><div className="member-section-head"><h2>最近就医记录</h2><button className="records-link" onClick={()=>onRecords()}>查看更多<DemoIcon name="arrow"/></button></div>
      {loading?<p role="status">正在加载 {member.name} 的记录…</p>:error?<><p className="auth-error" role="alert">{error}</p><button className="records-detail-action" onClick={()=>setRetry(n=>n+1)}>重新加载</button></>:recent?<>
        <h3 className="member-latest-title">{summary?.diagnosis||'本次就医资料'}</h3>
        <p className="member-visit-hospital"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 21V4h14v17M3 21h18M9 21v-5h6v5M9 9h6m-3-3v6"/></svg>{summary?.hospital||'医院信息待补充'}</p>
        <div className="member-visit-keywords">{summary?.kind&&<span>{summary.kind}</span>}{summary?.documentCount!==undefined&&<span>{summary.documentCount} 份材料</span>}{summary?.source==='intake'&&<span>诊断 / 症状为本人填写</span>}</div>
        <dl className="member-visit-meta">{summary?.period&&<div><dt>就医时间</dt><dd>{summary.period}</dd></div>}<div><dt>最近更新</dt><dd>{new Date(recent.items[0].updated_at).toLocaleDateString('zh-CN')}</dd></div></dl>
        <p className="member-visit-saved">{recordGroup?`已汇集 ${recordGroup.cases.length} 批资料 · ${recordGroup.conversation_count} 段对话`:`已保存 ${recent.items.length} 段对话`}{!summary?.diagnosis?' · 疾病信息待材料确认':''}</p>
        <button className="records-detail-action" onClick={()=>onRecords(recordGroup?.record_id||recent.case_id)}>查看详情<DemoIcon name="arrow"/></button></>:<><h3>还没有就医记录</h3><p>为 {member.name} 整理材料，后续资料和对话会留在这里。</p><button className="records-detail-action" onClick={onNew}>整理就医材料<DemoIcon name="arrow"/></button></>}
    </section>
    <button className="member-logout" onClick={()=>void onLogout()}>退出登录</button>
    {mode==='switch'&&<MemberPicker members={members} currentId={member.subject_id} title="切换查看人员" onClose={()=>setMode(undefined)} onSelect={id=>{onSelect(id);setMode(undefined);}} onAdd={()=>setMode('add')}/>}
    {mode==='manage'&&<MemberDialog title="管理家庭成员" onClose={()=>setMode(undefined)}><div className="member-picker-heading"><h2>管理家庭成员</h2><p>点击成员编辑资料</p></div><MemberList members={members} editing onSelect={id=>{setEditing(members.find(value=>value.subject_id===id));setMode('edit');}}/><button className="member-add" onClick={()=>setMode('add')}>添加家人</button></MemberDialog>}
    {(mode==='add'||mode==='edit')&&<MemberDialog title={mode==='add'?'添加家人':'编辑人员资料'} onClose={()=>setMode(undefined)}><MemberEditor key={mode==='add'?'new':editing?.subject_id} token={token} member={mode==='edit'?editing:undefined} onSaved={saved} onCancel={()=>setMode(undefined)}/></MemberDialog>}
  </div></main>;
}
