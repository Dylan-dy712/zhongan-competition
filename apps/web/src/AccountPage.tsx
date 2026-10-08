import {useEffect,useState} from 'react';
import {changeCareConsent,getCareConsent,listConversations,type CareConsent,type MemberResponse} from './api';
import {DemoIcon} from './DemoPages';
import {encounterGroups} from './carePresentation';
import type {Conversation} from './types';
import {MemberDialog,MemberEditor,MemberPicker,memberDescription,relationshipLabels} from './MemberControls';

export default function AccountPage({token,members,member,onSelect,onSaved,onRecords,onNew,onChanged,onLogout}:{
  token:string;members:MemberResponse[];member:MemberResponse;onSelect:(id:string)=>void;
  onSaved:(member:MemberResponse)=>Promise<void>;onRecords:(caseId?:string)=>void;onNew:()=>void;
  onChanged:(subjectId:string)=>Promise<void>;onLogout:()=>Promise<void>;
}) {
  const [consent,setConsent]=useState<CareConsent>();
  const [records,setRecords]=useState<Conversation[]>([]);
  const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [authorizationError,setAuthorizationError]=useState('');
  const [retry,setRetry]=useState(0);
  const [mode,setMode]=useState<'switch'|'manage'|'add'|'edit'>();
  const [editing,setEditing]=useState<MemberResponse>();
  useEffect(()=>{let active=true;setLoading(true);setConsent(undefined);setRecords([]);setError('');
    Promise.all([getCareConsent(token,member.subject_id),listConversations(token,member.subject_id)]).then(([value,items])=>{
      if(active){setConsent(value);setRecords(items);}
    }).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[token,member.subject_id,retry]);
  const recent=encounterGroups(records)[0];
  const saved=async(value:MemberResponse)=>{await onSaved(value);setMode(undefined);};
  return <main className="demo-pages"><div className="page demo-account">
    <p className="member-account-label">登录账号：{sessionStorage.getItem('zhongan_account_name')||'已连接账号'}</p>
    <section className="records-profile"><span className="records-profile-kicker">当前查看的健康档案</span>
      <div className="records-profile-top"><span className="records-avatar"><DemoIcon name="user"/></span><div className="records-person"><h1>{member.name} <span>{relationshipLabels[member.relationship]}</span></h1><p>{memberDescription(member)}</p></div></div>
      <p className="records-profile-saying">每个人的看病经历，都好好记下。</p><div className="member-actions"><button onClick={()=>setMode('switch')}>切换人员</button><button onClick={()=>{setEditing(member);setMode('edit');}}>编辑资料</button></div>
    </section>
    <section className="records-detail-card"><div className="member-section-head"><h2>最近就医记录</h2><button className="records-link" onClick={()=>onRecords()}>查看更多<DemoIcon name="arrow"/></button></div>
      {loading?<p role="status">正在加载 {member.name} 的记录…</p>:error?<><p className="auth-error" role="alert">{error}</p><button className="records-detail-action" onClick={()=>setRetry(n=>n+1)}>重新加载</button></>:recent?<>
        <h3 className="member-latest-title">{recent.items[0].title}</h3><p>最近更新 · {new Date(recent.items[0].updated_at).toLocaleDateString('zh-CN')}</p><p>已保存 {recent.items.length} 段对话</p>
        <button className="records-detail-action" onClick={()=>onRecords(recent.case_id)}>查看详情<DemoIcon name="arrow"/></button></>:<><h3>还没有就医记录</h3><p>为 {member.name} 整理材料，后续资料和对话会留在这里。</p><button className="records-detail-action" onClick={onNew}>整理就医材料<DemoIcon name="arrow"/></button></>}
    </section>
    <section className="records-detail-card"><h2>家庭成员管理</h2><p>已建立 {members.length} 位成员的档案</p><div className="member-actions"><button onClick={()=>setMode('add')}>添加家人</button><button onClick={()=>setMode('manage')}>管理家庭成员</button></div></section>
    <section className="records-detail-card"><h2>{member.name} 的资料用途授权</h2><p>仅用于整理主动提供的合成资料、生成单次关怀与保存相关对话。长期记忆、资源匹配与评测不在此授权中。</p>
      {consent&&<><p>状态：{consent.status==='active'?'已授权':consent.status==='revoked'?'已撤回':consent.status==='expired'?'已过期':'尚未授权'} · 版本 {consent.version}</p>
        <button className="records-detail-action" disabled={busy} onClick={async()=>{setBusy(true);setAuthorizationError('');try{
          setConsent(await changeCareConsent(token,consent.status!=='active',consent.version,member.subject_id));await onChanged(member.subject_id);setRetry(n=>n+1);
        }catch(e){setAuthorizationError(e instanceof Error?e.message:'授权更新失败。');setRetry(n=>n+1);}finally{setBusy(false);}}}>{consent.status==='active'?'撤回关怀授权':'确认并授权关怀'}</button></>}
      {authorizationError&&<p role="alert" className="auth-error">{authorizationError}</p>}
      <small>每位成员分别确认授权。撤回后停止后续关怀访问与处理，已保存的审计记录仍保留。</small>
    </section>
    <button className="member-logout" disabled={busy} onClick={()=>void onLogout()}>退出登录</button>
    {mode==='switch'&&<MemberPicker members={members} title="切换查看人员" onClose={()=>setMode(undefined)} onSelect={id=>{onSelect(id);setMode(undefined);}} onAdd={()=>setMode('add')}/>}
    {mode==='manage'&&<MemberDialog title="管理家庭成员" onClose={()=>setMode(undefined)}><h2>管理家庭成员</h2><div className="member-list">{members.map(value=><button key={value.subject_id} onClick={()=>{setEditing(value);setMode('edit');}}><strong>{value.name} · {relationshipLabels[value.relationship]}</strong><span>{memberDescription(value)} · 编辑资料</span></button>)}</div><button className="records-detail-action" onClick={()=>setMode('add')}>添加家人</button></MemberDialog>}
    {(mode==='add'||mode==='edit')&&<MemberDialog title={mode==='add'?'添加家人':'编辑人员资料'} onClose={()=>setMode(undefined)}><MemberEditor key={mode==='add'?'new':editing?.subject_id} token={token} member={mode==='edit'?editing:undefined} onSaved={saved} onCancel={()=>setMode(undefined)}/></MemberDialog>}
  </div></main>;
}
