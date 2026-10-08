import {useEffect,useRef,useState} from 'react';
import {saveMember,type MemberInput,type MemberResponse} from './api';
import './members.css';

export const relationshipLabels:Record<MemberInput['relationship'],string>={self:'本人',parent:'父母',spouse:'配偶',child:'子女',other:'其他'};
export function MemberAvatar({relationship='self'}:{relationship?:MemberInput['relationship']}) {
  return <span className="member-avatar" data-relation={relationship} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"><circle cx="12" cy="8" r="4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></svg></span>;
}
export function MemberList({members,onSelect,currentId,editing=false}:{members:MemberResponse[];onSelect:(id:string)=>void;currentId?:string;editing?:boolean}) {
  return <div className="member-list">{members.map(member=><button key={member.subject_id} className={currentId===member.subject_id?'selected':''} onClick={()=>onSelect(member.subject_id)}>
    <MemberAvatar relationship={member.relationship}/><span className="member-row-copy"><span className="member-row-name"><strong>{member.name}</strong><span className="member-relation">{relationshipLabels[member.relationship]}</span></span><span className="member-row-detail">{memberDescription(member)}</span></span><span className="member-row-action" aria-hidden="true">{editing?'编辑':currentId===member.subject_id?'当前':<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m9 5 7 7-7 7"/></svg>}</span>
  </button>)}</div>;
}
export function memberDescription(member:MemberResponse) {
  const gender=member.gender==='male'?'男':member.gender==='female'?'女':'性别未填写';
  if(!member.birth_date)return `${gender} · 年龄未填写`;
  const birth=new Date(`${member.birth_date}T00:00:00`),today=new Date();
  const age=today.getFullYear()-birth.getFullYear()-(today.getMonth()<birth.getMonth() || (today.getMonth()===birth.getMonth() && today.getDate()<birth.getDate())?1:0);
  return `${gender} · ${age}岁`;
}

export function MemberEditor({token,member,onSaved,onCancel,onboarding=false}:{token:string;member?:MemberResponse;onSaved:(member:MemberResponse)=>Promise<void>;onCancel?:()=>void;onboarding?:boolean}) {
  const [name,setName]=useState(member?.name||'');
  const [gender,setGender]=useState<MemberInput['gender']>(member?.gender||'unspecified');
  const [birth,setBirth]=useState(member?.birth_date||'');
  const [relationship,setRelationship]=useState<MemberInput['relationship']>(member?.relationship||'parent');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const today=new Date();const maxDate=`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  return <section className="member-editor"><MemberAvatar relationship={member?.relationship||'other'}/><span className="member-kicker">暖暖 · 家庭健康档案</span><h1>{onboarding?'完善本人资料':member?'编辑人员资料':'添加家人'}</h1><p>{onboarding?'先绑定自己，再为家人建立各自的档案。':'每个人的就医资料分别保存。'}</p>
    <form onSubmit={async e=>{e.preventDefault();if(busy)return;setBusy(true);setError('');try{
      if(!name.trim())throw new Error('请填写姓名。');
      const result=await saveMember(token,{name:name.trim(),gender,birth_date:birth||null,relationship},member?.subject_id);
      await onSaved(result);
    }catch(e){setError(e instanceof Error?e.message:'保存失败，请重试。');}finally{setBusy(false);}}}>
      <label>姓名<input autoFocus placeholder="请输入姓名" required maxLength={40} value={name} disabled={busy} onChange={e=>setName(e.target.value)}/></label>
      <label>性别<select value={gender} disabled={busy} onChange={e=>setGender(e.target.value as MemberInput['gender'])}><option value="unspecified">未填写</option><option value="male">男</option><option value="female">女</option></select></label>
      <label>出生日期（可选）<input type="date" max={maxDate} value={birth} disabled={busy} onChange={e=>setBirth(e.target.value)}/></label>
      <label>与本人关系<select value={relationship} disabled={busy||member?.relationship==='self'} onChange={e=>setRelationship(e.target.value as MemberInput['relationship'])}>
        {member?.relationship==='self'?<option value="self">本人</option>:Object.entries(relationshipLabels).filter(([key])=>key!=='self').map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      {error&&<p role="alert" className="auth-error">{error}</p>}
      <div className="member-actions">{onCancel&&<button type="button" disabled={busy} onClick={onCancel}>取消</button>}<button className="member-primary" disabled={busy}>{busy?'正在保存…':onboarding?'保存并进入首页':'保存资料'}</button></div>
    </form></section>;
}

export function MemberDialog({title,onClose,children}:{title:string;onClose:()=>void;children:React.ReactNode}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;dialog.current?.showModal();return()=>{dialog.current?.close();previous?.focus();};},[]);
  return <dialog ref={dialog} className="member-dialog" aria-label={title} onCancel={e=>{e.preventDefault();onClose();}}>
    <button className="member-close" aria-label="关闭" onClick={onClose}>×</button>{children}</dialog>;
}

export function MemberPicker({members,title,onSelect,onClose,onAdd,currentId}:{members:MemberResponse[];title:string;onSelect:(id:string)=>void;onClose:()=>void;onAdd?:()=>void;currentId?:string}) {
  return <MemberDialog title={title} onClose={onClose}><div className="member-picker-heading"><MemberAvatar/><span className="member-kicker">一人一份档案，关怀更清楚</span><h2>{title}</h2><p>{currentId?'切换后，查看对应人员的档案与就医记录。':'请选择本次资料对应的人员。'}</p></div><MemberList members={members} currentId={currentId} onSelect={onSelect}/>{onAdd&&<button className="member-add" onClick={onAdd}>＋ 添加家人</button>}<p className="member-picker-footnote">每个人的资料与对话分别保存</p></MemberDialog>;
}
