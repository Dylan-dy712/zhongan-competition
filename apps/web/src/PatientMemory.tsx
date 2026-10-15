import {useEffect,useState} from 'react';
import {MemberDialog} from './MemberControls';
import {getMemorySettings,changeMemorySettings,listMemories,createMemoryCandidate,confirmMemoryCandidate,
  dismissMemoryCandidate,revokeMemory,getConversationMemorySettings,changeConversationMemorySettings,
  listConversations,getConversation,type MemorySettingsResponse,type MemoryListResponse,type MemoryItemResponse,
  type MemoryCandidateResponse,type MemoryCandidateCreate,type ConversationMemoryResponse} from './api';
import type {ChatTurn,Conversation} from './types';
import './patient-memory.css';

const labels:Record<MemoryCandidateCreate['field_key'],string>={communication_style:'沟通方式',care_preference:'关怀偏好',
  followup_time:'复查时间自述',followup_location:'复查地点自述',medication:'用药自述',allergy:'过敏自述',recovery_status:'恢复情况自述'};
const dynamicFields=new Set(['medication','recovery_status','followup_time','followup_location']);
const operationKey=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');

export function PatientMemory({token,subjectId,name,conversationId,sourceTurn,onClose}:{
  token:string;subjectId:string;name:string;conversationId?:string;sourceTurn?:ChatTurn;onClose:()=>void;
}) {
  const [settings,setSettings]=useState<MemorySettingsResponse>();
  const [data,setData]=useState<MemoryListResponse>();
  const [conversation,setConversation]=useState<ConversationMemoryResponse>();
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[retry,setRetry]=useState(0);
  const [editing,setEditing]=useState(Boolean(sourceTurn));
  const [replacement,setReplacement]=useState<MemoryItemResponse>();
  const [sources,setSources]=useState<Conversation[]>([]),[sourceConversation,setSourceConversation]=useState(conversationId||'');
  const [turns,setTurns]=useState<ChatTurn[]>(sourceTurn?[sourceTurn]:[]),[sourceId,setSourceId]=useState(sourceTurn?.turn_id||'');
  const [content,setContent]=useState(sourceTurn?.question||'');
  const [field,setField]=useState<MemoryCandidateCreate['field_key']>('communication_style');
  const [scope,setScope]=useState<'patient'|'case'>('patient'),[expiry,setExpiry]=useState('');
  const [sourceSettings,setSourceSettings]=useState<ConversationMemoryResponse>();

  useEffect(()=>{let active=true;setError('');
    Promise.all([getMemorySettings(token,subjectId),listMemories(token,subjectId),
      conversationId?getConversationMemorySettings(token,conversationId):Promise.resolve(undefined)])
      .then(([state,items,current])=>{if(active){setSettings(state);setData(items);setConversation(current);}})
      .catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[token,subjectId,conversationId,retry]);

  useEffect(()=>{if(!editing)return;let active=true;
    listConversations(token,subjectId).then(items=>{if(active)setSources(items);}).catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[token,subjectId,editing]);

  useEffect(()=>{if(!editing||!sourceConversation)return;let active=true;setSourceSettings(undefined);
    Promise.all([getConversation(token,sourceConversation),getConversationMemorySettings(token,sourceConversation)])
      .then(([snapshot,state])=>{if(!active)return;
        if(snapshot.conversation.subject_id!==subjectId)throw new Error('来源不属于当前就诊人。');
        const available=snapshot.turns.filter(turn=>turn.input_kind==='user'&&turn.status==='completed');
        const extra=sourceTurn&&sourceConversation===conversationId?[sourceTurn]:[];
        setTurns([...new Map([...extra,...available].map(turn=>[turn.turn_id,turn])).values()]);setSourceSettings(state);})
      .catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[token,subjectId,sourceConversation,editing,retry,sourceTurn,conversationId]);

  const action=async(task:()=>Promise<unknown>,success:string)=>{
    if(busy)return;setBusy(true);setError('');setNotice('');
    try{await task();setNotice(success);setRetry(value=>value+1);}catch(e){setError(e instanceof Error?e.message:'操作失败，请重试。');}
    finally{setBusy(false);}
  };
  const confirm=async(item:MemoryCandidateResponse)=>action(()=>confirmMemoryCandidate(token,subjectId,item.candidate_id,
    {confirmation:true,expected_version:item.version},operationKey()),`已为 ${name} 保存。`);
  const beginEdit=(item?:MemoryItemResponse)=>{setReplacement(item);setEditing(true);setContent('');setSourceId('');
    setField(item?.field_key||'communication_style');setScope(item?.scope||'patient');setExpiry('');setError('');};
  const save=()=>action(async()=>{
    if(!sourceId||!content.trim())throw new Error('请选择来源消息，并保留需要保存的原文。');
    if(!sourceSettings?.export_enabled)throw new Error('请先允许来源对话产生记忆。');
    const selected=turns.find(turn=>turn.turn_id===sourceId);
    if(!selected||!selected.question.includes(content))throw new Error('内容必须保留来源消息的原文，请勿改写否定或时间。');
    if(dynamicFields.has(field)&&!expiry)throw new Error('请为这条有时间范围的信息设置有效期。');
    const candidate=await createMemoryCandidate(token,subjectId,{source_turn_id:sourceId,content,field_key:field,
      kind:['communication_style','care_preference'].includes(field)?'communication_preference':'confirmed_context',
      scope:dynamicFields.has(field)?'case':scope,expires_at:expiry?new Date(expiry).toISOString():null});
    await confirmMemoryCandidate(token,subjectId,candidate.candidate_id,{confirmation:true,expected_version:candidate.version,
      replaces_memory_id:replacement?.memory_id,replaces_version:replacement?.version},operationKey());
    setEditing(false);setReplacement(undefined);
  },`已为 ${name} ${replacement?'更正':'保存'}记忆。`);

  return <MemberDialog title={`${name} 的关怀记忆`} onClose={onClose}><section className="patient-memory" aria-label={`${name} 的关怀记忆`}>
    <p>只用于 {name} 的后续关怀，与其他家人的记忆分开。你可以查看来源、更正或停止使用；确认自述不代表医学核实。</p>
    {error&&<p role="alert" className="auth-error">{error}<button disabled={busy} onClick={()=>setRetry(value=>value+1)}>重新加载</button></p>}
    {notice&&<p role="status">{notice}</p>}
    {!settings&&!error&&<p role="status">正在加载记忆设置…</p>}
    {settings&&<>
      <label className="memory-switch"><input type="checkbox" checked={settings.enabled} disabled={busy} onChange={e=>{
        const enabled=e.target.checked;void action(()=>changeMemorySettings(token,subjectId,enabled,settings.version,operationKey()),
          enabled?`已开启 ${name} 的长期关怀记忆。请分别设置对话是否读入、是否可作为来源。`:'已停止长期记忆使用；本次已授权关怀仍可继续。');
      }}/><span>允许为 {name} 保存和使用经确认的长期记忆</span></label>
      <small>关闭后，已有记忆停止使用；重新开启不会自动恢复旧内容。此设置与本次关怀用途分开。</small>
      {conversation&&<div className="memory-conversation-settings"><h3>当前对话</h3>
        <label className="memory-switch"><input type="checkbox" disabled={busy||!settings.enabled} checked={conversation.read_enabled} onChange={e=>{
          const read=e.target.checked;void action(()=>changeConversationMemorySettings(token,conversationId!,read,conversation.export_enabled,conversation.version,read&&conversation.report_enabled),'已更新本对话的记忆读入设置。');
        }}/><span>本对话可以读取 {name} 已确认的记忆</span></label>
        <label className="memory-switch"><input type="checkbox" disabled={busy||!settings.enabled} checked={conversation.export_enabled} onChange={e=>{
          const exportEnabled=e.target.checked;void action(()=>changeConversationMemorySettings(token,conversationId!,conversation.read_enabled,exportEnabled,conversation.version,conversation.report_enabled),'已更新本对话的来源设置。');
        }}/><span>允许从本对话提出待确认记忆</span></label>
        <label className="memory-switch"><input type="checkbox" disabled={busy||!settings.enabled||!conversation.read_enabled} checked={conversation.report_enabled} onChange={e=>{
          const report=e.target.checked;void action(()=>changeConversationMemorySettings(token,conversationId!,conversation.read_enabled,conversation.export_enabled,conversation.version,report),'已更新报告使用记忆的授权；已有报告不会自动重写。');
        }}/><span>允许本对话生成的报告使用 {name} 已确认的记忆，并向有权限的报告复核人员提供这些来源</span></label>
        <small>默认关闭。开启后只对新生成的报告生效；关闭、过期或更正记忆后，依赖它的报告需要重新生成和复核。</small>
      </div>}
      {!editing&&<button className="member-add" disabled={busy||!settings.enabled} onClick={()=>beginEdit()}>从已保存的用户消息添加记忆</button>}
    </>}
    {editing&&settings?.enabled&&<form className="memory-editor" onSubmit={event=>{event.preventDefault();void save();}}>
      <h3>{replacement?'更正已有记忆':'确认要记住的内容'}</h3><p>为 <strong>{name}</strong> 保存。人物不明确、涉及其他家人的消息，请先回到对应就诊人的对话核实。</p>
      <label>来源对话<select value={sourceConversation} disabled={busy} onChange={e=>{setSourceConversation(e.target.value);setSourceId('');setContent('');}}>
        <option value="">请选择 {name} 的对话</option>{sources.map(item=><option key={item.conversation_id} value={item.conversation_id}>{item.title}</option>)}
      </select></label>
      {sourceSettings&&!sourceSettings.export_enabled&&<button type="button" className="member-add" disabled={busy} onClick={()=>void action(
        ()=>changeConversationMemorySettings(token,sourceConversation,sourceSettings.read_enabled,true,sourceSettings.version,sourceSettings.report_enabled),'已允许这段对话作为记忆来源。')}>允许此来源对话产生待确认记忆</button>}
      <label>用户原话<select value={sourceId} disabled={busy} onChange={e=>{setSourceId(e.target.value);setContent(turns.find(turn=>turn.turn_id===e.target.value)?.question||'');}}>
        <option value="">请选择来源消息</option>{turns.map(turn=><option key={turn.turn_id} value={turn.turn_id}>{turn.question.slice(0,70)}</option>)}
      </select></label>
      <label>记忆类型<select value={field} disabled={busy||Boolean(replacement)} onChange={e=>{const value=e.target.value as typeof field;setField(value);if(dynamicFields.has(value))setScope('case');}}>
        {Object.entries(labels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
      <label>需要保留的原文<textarea value={content} maxLength={1000} required minLength={2} disabled={busy} onChange={e=>setContent(e.target.value)}/></label>
      <label>适用范围<select value={scope} disabled={busy||dynamicFields.has(field)||Boolean(replacement)} onChange={e=>setScope(e.target.value as typeof scope)}>
        <option value="case">仅来源对应的这次就医</option><option value="patient">该就诊人的后续就医</option></select></label>
      <label>有效期{dynamicFields.has(field)?'（必填）':'（可选）'}<input type="datetime-local" value={expiry} required={dynamicFields.has(field)} disabled={busy} onChange={e=>setExpiry(e.target.value)}/></label>
      <div className="member-actions"><button type="submit" disabled={busy||!sourceSettings?.export_enabled}>确认为 {name} 保存</button><button type="button" disabled={busy} onClick={()=>{setEditing(false);setReplacement(undefined);}}>取消</button></div>
    </form>}
    {!!data?.candidates.length&&<div><h3>待你确认</h3>{data.candidates.map(item=><article className="memory-item" key={item.candidate_id}>
      <strong>{labels[item.field_key]}</strong><p>{item.content}</p><small>{item.scope==='patient'?'用于该就诊人的后续就医':'仅用于来源对应的这次就医'}{item.expires_at?` · 有效至 ${new Date(item.expires_at).toLocaleString('zh-CN')}`:''}</small>
      <div className="member-actions"><button disabled={busy||!settings?.enabled} onClick={()=>void confirm(item)}>确认为 {name} 保存</button><button disabled={busy} onClick={()=>void action(()=>dismissMemoryCandidate(token,subjectId,item.candidate_id,item.version),'已忽略候选。')}>不保存</button></div>
    </article>)}</div>}
    <div><h3>已保存的记忆</h3>{data&&!data.memories.length&&<p>还没有确认保存的记忆。</p>}{data?.memories.map(item=><article className="memory-item" key={item.memory_id}>
      <strong>{labels[item.field_key]}</strong><p>{item.content||'该记忆已停止使用，或来源当前不可用。'}</p>
      <small>{item.status==='active'?'使用中':item.status==='revoked'?'已停止使用':item.status==='expired'?'已过期':'来源当前不可用'} · 第 {item.version} 版 · {new Date(item.confirmed_at).toLocaleDateString('zh-CN')} · {item.scope==='patient'?'就诊人范围':'单次就医范围'}</small>
      {['active','expired','unavailable'].includes(item.status)&&<div className="member-actions">{item.status!=='unavailable'&&<button disabled={busy||!settings?.enabled} onClick={()=>beginEdit(item)}>用新的来源消息更正</button>}<button disabled={busy} onClick={()=>void action(()=>revokeMemory(token,subjectId,item.memory_id,item.version),'已停止使用；此操作不表示原对话或审计副本被物理删除。')}>停止使用</button></div>}
    </article>)}</div>
  </section></MemberDialog>;
}
