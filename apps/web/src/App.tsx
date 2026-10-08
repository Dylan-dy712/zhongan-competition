import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react';
import {ApiError, continueAnalysis, createConversation, getConversation, getEvidence, getOlderTurns,
  listConversations, listSubjects, sendChatMessage, uploadChatDocument,
  listDeliveries, recordDeliveryReceipt, submitCareFeedback} from './api';
import type {ChatSnapshot, ChatSubject, ChatTurn, Conversation, Evidence, ToolEvent, DeliveryNotice, FeedbackType,ReportSection} from './types';
import {CareReport,EvidencePanel,brand} from './CarePages';
import {DemoHome,DemoRecords,DemoIcon} from './DemoPages';
import {publishedCare,type CarePanel} from './carePresentation';
import {readCarePanel,useCareNavigation} from './careNavigation';
import {PageBoundary} from './PageBoundary';
import AuthPage from './AuthPage';
import ClaimIntake from './ClaimIntake';
import AccountPage from './AccountPage';
import {revokeSession} from './api';
import OriginalChatGuide,{OriginalChatWelcome} from './OriginalChatGuide';
import './chat.css';
import './care.css';
import './chat-original.css';

// randomUUID requires HTTPS in some browsers; retain a cryptographic HTTP development fallback.
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, x => x.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
const toolLabels: Record<string,string> = {list_materials:'查看上传材料',start_analysis:'提交材料分析',
  analysis_status:'查询分析进度',read_materials:'查阅原始依据',read_report:'读取分析报告',search_history:'查找以前的对话'};
const statusLabels: Record<string,string> = {not_started:'尚未分析',queued:'材料已排队',running:'正在分析材料',
  waiting_review:'材料已解析，部分结论待专业复核',completed:'材料分析已完成',failed:'材料分析失败',cancelled:'分析已取消',
  found:'已找到',empty:'暂无记录',available:'可读取',needs_materials:'需要补充材料',not_generated:'尚无报告',
  disabled:'历史回忆已关闭',published:'已发布',ready:'报告待发布',pending_review:'等待复核'};
const errorText = (e:unknown) => e instanceof Error ? e.message : '连接失败，请稍后重试。';

function ToolActivity({events}:{events:ToolEvent[]}) {
  return events.length > 0 ? <details className="tool-activity"><summary>已执行 {events.length} 项操作</summary>
    {events.map((e,i)=><div key={i}>{toolLabels[e.tool] || '处理请求'} · {statusLabels[e.status] || '操作已返回'}</div>)}
  </details> : null;
}

export default function App() {
  const [token,setToken] = useState(()=>sessionStorage.getItem('zhongan_chat_token') || '');
  const [connected,setConnected] = useState(false);
  const [conversations,setConversations] = useState<Conversation[]>([]);
  const [subjects,setSubjects] = useState<ChatSubject[]>([]);
  const [subject,setSubject] = useState('');
  const [caseInput,setCaseInput] = useState('');
  const [snapshot,setSnapshot] = useState<ChatSnapshot|null>(null);
  const [older,setOlder] = useState<ChatTurn[]>([]);
  const [hasOlder,setHasOlder] = useState(false);
  const [input,setInput] = useState('');
  const [attachments,setAttachments] = useState<{document_id:string; name:string}[]>([]);
  const [busy,setBusy] = useState(false);
  const [uploading,setUploading] = useState(false);
  const [error,setError] = useState('');
  const [evidence,setEvidence] = useState<Evidence|null>(null);
  const evidenceRequest=useRef(0);
  const [panel,setPanel] = useCareNavigation();
  const [loadingConversation,setLoadingConversation] = useState(false);
  const [reportFocus,setReportFocus] = useState<ReportSection['section_type']>();
  const [delivery,setDelivery] = useState<DeliveryNotice|null>(null);
  const [feedbackNotice,setFeedbackNotice] = useState('');
  const [feedbackBusy,setFeedbackBusy] = useState(false);
  const feedbackBusyRef = useRef(false);
  const careKeys = useRef(new Map<string,string>());
  const currentReport = useRef('');
  currentReport.current=snapshot?.report.report_id || '';
  const [historyOpen,setHistoryOpen] = useState(false);
  const active = useRef('');
  const epoch = useRef(0);
  const busyRef = useRef(false);
  const initialized = useRef(false);
  const olderExhausted = useRef(false);
  const resumed = useRef(new Set<string>());
  const uploadInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const pendingSend = useRef<{id:string; text:string; docs:string[]}|null>(null);
  const connecting=useRef(false);

  const invalidateAccess = useCallback((e:unknown,id:string,generation:number,auth=token) => {
    if(!(e instanceof ApiError) || ![401,403,404].includes(e.status) || epoch.current!==generation || active.current!==id)return false;
    const fresh=++epoch.current;active.current='';busyRef.current=false;
    setLoadingConversation(false);
    setSnapshot(null);setOlder([]);setEvidence(null);setAttachments([]);setInput('');setDelivery(null);
    setConversations([]);setSubjects([]);setSubject('');setCaseInput('');setFeedbackNotice('');setBusy(false);setUploading(false);
    localStorage.removeItem('zhongan_last_conversation');
    pendingSend.current=null;careKeys.current.clear();
    setError(e.status===401?'连接已失效，请重新连接。':'这次就医目前不可访问，已清除页面内容。');
    if(e.status===401 || e.status===403){sessionStorage.removeItem('zhongan_chat_token');setToken('');setConnected(false);}
    else void Promise.all([listConversations(auth),listSubjects(auth)]).then(([items,allowed])=>{
      if(epoch.current===fresh){setConversations(items);setSubjects(allowed);setSubject(allowed[0]?.subject_id || '');}
    }).catch(()=>{if(epoch.current===fresh)setError('当前记录不可访问，请重新连接后查看授权范围。');});
    return true;
  },[token]);

  const refresh = useCallback(async (id:string, auth:string, generation:number) => {
    let state:ChatSnapshot;
    try {state = await getConversation(auth,id);}
    catch(e) {
      invalidateAccess(e,id,generation,auth);
      throw e;
    }
    if (epoch.current === generation && active.current === id) {
      setSnapshot(state);
      setHasOlder(state.turns.length === 50 && !olderExhausted.current);
    }
    return state;
  },[invalidateAccess]);

  const openConversation = useCallback(async (id:string, auth=token, destination:CarePanel='home') => {
    const generation = ++epoch.current;
    active.current = id;
    olderExhausted.current = false;
    setSnapshot(null); setOlder([]); setAttachments([]); setInput(''); setEvidence(null); setError('');
    busyRef.current=false;setBusy(false);setUploading(false);
    setLoadingConversation(true);setHasOlder(false);setDelivery(null);setFeedbackNotice('');
    setPanel(destination);setReportFocus(undefined); setHistoryOpen(false); pendingSend.current = null;
    try {
      await refresh(id,auth,generation);
      if (epoch.current===generation) localStorage.setItem('zhongan_last_conversation',id);
    } catch(e) {if(epoch.current===generation) setError(errorText(e));}
    finally {if(epoch.current===generation)setLoadingConversation(false);}
  },[refresh,token,setPanel]);

  const connect = useCallback(async (auth:string,failLoud=false) => {
    if (!auth.trim() || connecting.current) return;
    connecting.current=true;
    const generation=++epoch.current;
    setBusy(true); setError('');
    try {
      const [items,allowed] = await Promise.all([listConversations(auth),listSubjects(auth)]);
      if(epoch.current!==generation)return;
      sessionStorage.setItem('zhongan_chat_token',auth); setToken(auth); setConnected(true);
      setConversations(items); setSubjects(allowed); setSubject(allowed[0]?.subject_id || '');
      const last = localStorage.getItem('zhongan_last_conversation');
      const chosen = items.find(x=>x.conversation_id===last) || items[0];
      if(chosen) await openConversation(chosen.conversation_id,auth,readCarePanel(window.location.hash));
      else if(failLoud || readCarePanel(window.location.hash)==='home') setPanel('claim');
    } catch(e) {if(epoch.current===generation){setError(errorText(e));setConnected(false);
      if(e instanceof ApiError && [401,403].includes(e.status)){sessionStorage.removeItem('zhongan_chat_token');sessionStorage.removeItem('zhongan_account_name');setToken('');}
      else {sessionStorage.setItem('zhongan_chat_token',auth);setToken(auth);}
    }if(failLoud)throw e;}
    finally {connecting.current=false;setBusy(false);}
  },[openConversation,setPanel]);

  useEffect(()=>{if(!initialized.current){initialized.current=true;if(token) void connect(token);}},[connect,token]);
  useEffect(()=>{if(panel==='chat')bottom.current?.scrollIntoView({behavior:'smooth'});},[snapshot?.turns.length,busy,panel]);
  useEffect(()=>{++evidenceRequest.current;setHistoryOpen(false);setEvidence(null);},[panel]);

  const careKey = (operation:string) => {
    const existing=careKeys.current.get(operation);
    if(existing) return existing;
    const key=requestId();careKeys.current.set(operation,key);return key;
  };
  useEffect(()=>{
    let cancelled=false;
    setDelivery(null);setFeedbackNotice('');
    const reportId=snapshot?.report.report_id,caseId=snapshot?.conversation.case_id,id=active.current,generation=epoch.current;
    if(!reportId || !caseId) return;
    void listDeliveries(token,caseId).then(items=>{
      if(!cancelled && epoch.current===generation) setDelivery(items.find(item=>item.report_id===reportId) || null);
    }).catch(e=>{
      if(!cancelled && epoch.current===generation && !invalidateAccess(e,id,generation))setError(errorText(e));
    });
    return ()=>{cancelled=true;};
  },[snapshot?.report.report_id,snapshot?.conversation.case_id,token,invalidateAccess]);
  useEffect(()=>{
    let cancelled=false;
    if(!delivery) return;
    const id=active.current,generation=epoch.current;
    const state=delivery.receipt_version===0 ? 'presented' :
      delivery.receipt_state==='presented' && panel==='report' ? 'read' : null;
    if(!state) return;
    void recordDeliveryReceipt(token,delivery.outbox_id,state,delivery.receipt_version,
      careKey(`receipt:${delivery.outbox_id}:${state}`)).then(result=>{
        if(!cancelled && epoch.current===generation && currentReport.current===delivery.report_id)setDelivery({...delivery,receipt_state:result.state,receipt_version:result.receipt_version});
      }).catch(e=>{
        if(!cancelled && epoch.current===generation && currentReport.current===delivery.report_id && !invalidateAccess(e,id,generation))setError(errorText(e));
      });
    return ()=>{cancelled=true;};
  },[delivery,token,panel,invalidateAccess]);
  const feedback = async (type:FeedbackType) => {
    if(feedbackBusyRef.current || !snapshot?.report.report_id || !snapshot.report.report_version)return;
    const report=snapshot.report,generation=epoch.current,id=active.current;
    feedbackBusyRef.current=true;setFeedbackBusy(true);setFeedbackNotice('');
    try{
      const result=await submitCareFeedback(token,report.report_id!,report.report_version!,type,
        careKey(`feedback:${report.report_id}:${type}`));
      if(epoch.current===generation && currentReport.current===report.report_id)setFeedbackNotice(result.triage_status==='pending' ?
        '反馈已记录，正在等待处理。' : '谢谢你的反馈，已记录。');
    }catch(e){
      if(epoch.current===generation && currentReport.current===report.report_id && !invalidateAccess(e,id,generation))setError(errorText(e));
    }finally{feedbackBusyRef.current=false;setFeedbackBusy(false);}
  };

  const newChat = async () => {
    if (busyRef.current || busy || uploading) return;
    const generation=epoch.current;
    busyRef.current=true;setBusy(true); setError('');
    try {
      const item = await createConversation(token,requestId(),subject,
        caseInput.trim() || undefined);
      if(epoch.current!==generation)return;
      const items=await listConversations(token);
      if(epoch.current!==generation)return;
      setConversations(items);
      await openConversation(item.conversation_id,token,'chat');
      setCaseInput('');
    } catch(e) {if(epoch.current===generation)setError(errorText(e));}
    finally {if(epoch.current===generation){busyRef.current=false;setBusy(false);}}
  };

  const prepareNewChat = () => {
    ++epoch.current;active.current='';olderExhausted.current=false;
    busyRef.current=false;setBusy(false);setUploading(false);setLoadingConversation(false);
    setDelivery(null);setFeedbackNotice('');setHasOlder(false);setReportFocus(undefined);setCaseInput('');
    setSnapshot(null);setOlder([]);setAttachments([]);setInput('');setEvidence(null);setError('');
    setHistoryOpen(false);pendingSend.current=null;
    setPanel('chat');
  };

  // Processing labels come from persisted backend events, never timed animations.
  useEffect(()=>{
    if(!connected || !active.current) return;
    const id=active.current, generation=epoch.current;
    let stopped=false, timer:ReturnType<typeof setTimeout>;
    const tick=async()=>{
      try {
        const state=await refresh(id,token,generation);
        if(stopped || epoch.current!==generation) return;
        const run=state.analysis;
        const shouldContinue=run.run_id && ['completed','waiting_review'].includes(run.status)
          && state.turns.some(t=>t.status==='completed' && t.tool_events.some(e=>e.tool==='start_analysis' && e.run_id===run.run_id));
        const key=`${id}:${run.run_id}`;
        if(shouldContinue && !busyRef.current && !state.turns.some(t=>t.status==='running') && !resumed.current.has(key)) {
          resumed.current.add(key);busyRef.current=true;setBusy(true);
          try {await continueAnalysis(token,id,run.run_id!);await refresh(id,token,generation);}
          catch(e){if(epoch.current===generation)setError(errorText(e));}
          finally{if(epoch.current===generation){busyRef.current=false;setBusy(false);}}
        }
      } catch(e) {if(!stopped && epoch.current===generation)setError(errorText(e));}
      if(!stopped)timer=setTimeout(tick,3500);
    };
    timer=setTimeout(tick,1500);
    return()=>{stopped=true;clearTimeout(timer);};
  },[connected,snapshot?.conversation.conversation_id,token,refresh]);

  const send = async (retry?:ChatTurn) => {
    const id=active.current, generation=epoch.current;
    if(!id || busyRef.current || busy || uploading) return;
    const text=retry?.question || input.trim() || (attachments.length ? '请帮我分析这些材料。' : '');
    if(!text)return;
    const docs=retry ? retry.attachments.map(x=>x.document_id) : attachments.map(x=>x.document_id);
    const previous=pendingSend.current;
    const req=retry?.request_id || (previous && previous.text===text && JSON.stringify(previous.docs)===JSON.stringify(docs) ? previous.id : requestId());
    pendingSend.current={id:req,text,docs};busyRef.current=true;setBusy(true);setError('');
    try {
      if(retry?.input_kind==='analysis_ready' && snapshot?.analysis.run_id) {
        await continueAnalysis(token,id,snapshot.analysis.run_id);
      } else {
        await sendChatMessage(token,id,req,text,docs);
      }
      if(epoch.current===generation){setInput('');setAttachments([]);pendingSend.current=null;}
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation)setError(errorText(e));}
    finally {
      try {await refresh(id,token,generation);if(epoch.current===generation)setConversations(await listConversations(token));}
      catch(e){if(epoch.current===generation)setError(errorText(e));}
      if(epoch.current===generation){busyRef.current=false;setBusy(false);}
    }
  };

  const upload = async(files:FileList|null) => {
    if(!files || !active.current || busyRef.current || busy || uploading)return;
    const id=active.current,generation=epoch.current;setUploading(true);setError('');
    try {
      if(files.length+attachments.length>20)throw new Error('一次最多附加20份材料。');
      for(const file of Array.from(files)) {
        if(file.size>10*1024*1024)throw new Error(`${file.name} 超过10MB，请拆分后上传。`);
        const doc=await uploadChatDocument(token,id,file);
        if(epoch.current===generation)setAttachments(v=>v.some(x=>x.document_id===doc.document_id)?v:[...v,{document_id:doc.document_id,name:file.name}]);
      }
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation)setError(errorText(e));}
    finally {if(epoch.current===generation){setUploading(false);if(uploadInput.current)uploadInput.current.value='';}}
  };

  const showEvidence = async(id:string) => {
    const generation=epoch.current,conversationId=active.current;setError('');setEvidence(null);
    const request=++evidenceRequest.current;
    try {const result=await getEvidence(id,token);if(epoch.current===generation && evidenceRequest.current===request)setEvidence(result);}
    catch(e){if(evidenceRequest.current===request && !invalidateAccess(e,conversationId,generation) && epoch.current===generation)setError(errorText(e));}
  };
  const loadOlder = async()=>{
    if(!snapshot || !hasOlder || !(older[0] || snapshot.turns[0]))return;
    const id=active.current,generation=epoch.current,first=older[0] || snapshot.turns[0];
    try {const rows=await getOlderTurns(token,id,first.turn_id);if(epoch.current===generation){setOlder(v=>[...rows,...v]);olderExhausted.current=rows.length<50;setHasOlder(rows.length===50);}}
    catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation)setError(errorText(e));}
  };
  const logout = ()=>{
    ++epoch.current;active.current='';sessionStorage.removeItem('zhongan_chat_token');
    sessionStorage.removeItem('zhongan_account_name');
    setToken('');setConnected(false);setConversations([]);setSnapshot(null);
    setOlder([]);setAttachments([]);setEvidence(null);setError('');setHistoryOpen(false);pendingSend.current=null;
    setSubjects([]);setSubject('');setCaseInput('');setInput('');localStorage.removeItem('zhongan_last_conversation');
    setDelivery(null);setFeedbackNotice('');careKeys.current.clear();
    busyRef.current=false;setBusy(false);setUploading(false);setLoadingConversation(false);setPanel('home');
  };
  const signOut=async()=>{
    try {await revokeSession(token);logout();}
    catch(e){setError(errorText(e));}
  };
  const turns=[...older,...(snapshot?.turns || [])].filter((t,i,all)=>all.findIndex(x=>x.turn_id===t.turn_id)===i);
  const working=busy || uploading || loadingConversation || !!snapshot?.turns.some(t=>t.status==='running');
  const submit=(e:FormEvent)=>{e.preventDefault();void send();};
  const openReport=(section?:ReportSection['section_type'])=>{setReportFocus(section);setPanel('report');};

  return <div className="chat-shell">
    {connected && panel==='chat' && <aside className={`chat-sidebar ${historyOpen?'is-open':''}`}>
      <div className="brand"><img src={brand} alt="暖愈智护"/></div>
      {connected && <><button className="new-chat" disabled={working} onClick={prepareNewChat}>＋ 新的关怀对话</button>
        <div className="history-list"><p>以前的对话</p>{conversations.map(c=><button disabled={working} key={c.conversation_id}
          className={active.current===c.conversation_id?'selected':''} onClick={()=>void openConversation(c.conversation_id)}>
          <strong>{c.title}</strong><small>{new Date(c.updated_at).toLocaleDateString('zh-CN')}</small></button>)}</div>
        <button className="quiet-button" disabled={working} onClick={()=>void signOut()}>退出登录</button></>}
    </aside>}
    <section className={`chat-workspace ${panel==='chat'?'chat-original':''}`}>
      {delivery && snapshot?.report.report_id===delivery.report_id && <div className="analysis-status care-notice" role="status">{delivery.message}
        {delivery.receipt_state==='read' ? <span>已查看</span> : <button onClick={()=>openReport()}>查看指引</button>}</div>}
      {error && <div role="alert" className="chat-error persistent-error">{error}<button aria-label="关闭提示" onClick={()=>setError('')}>×</button></div>}
      <PageBoundary resetKey={`${panel}:${snapshot?.conversation.conversation_id || ''}`}>
      {connected && <div className="claim-panel" hidden={panel!=='claim'}><ClaimIntake key={token} token={token} subject={subject} onExit={()=>setPanel('home')} onAuthorize={()=>setPanel('account')} onOpen={async id=>{
          const generation=epoch.current;const items=await listConversations(token);
          if(epoch.current!==generation)return;setConversations(items);await openConversation(id,token,'chat');}}/></div>}
      {!connected ? token ? <main className="start-screen" role="status"><h1>{busy?'正在连接服务…':'服务暂时不可用'}</h1><p>登录状态已保留，恢复连接后可继续。</p><button className="care-primary" disabled={busy} onClick={()=>void connect(token)}>{busy?'正在连接…':'重新连接'}</button></main> : <AuthPage onAuthenticated={auth=>connect(auth,true)}/>
      : panel==='claim' ? null
      : panel==='account' ? <AccountPage token={token} onLogout={signOut} onChanged={async()=>{
          const generation=++epoch.current;active.current='';setSnapshot(null);setEvidence(null);setOlder([]);setAttachments([]);setInput('');setDelivery(null);
          pendingSend.current=null;localStorage.removeItem('zhongan_last_conversation');
          const [items,allowed]=await Promise.all([listConversations(token),listSubjects(token)]);
          if(epoch.current!==generation)return;
          setConversations(items);setSubjects(allowed);setSubject(allowed[0]?.subject_id || '');}}/>
      : loadingConversation ? <main className="start-screen" role="status"><h1>正在打开就医记录…</h1></main>
      : panel==='records' ? <DemoRecords conversations={conversations} currentCase={snapshot?.conversation.case_id} busy={working}
          onOpen={id=>void openConversation(id)} onNew={()=>setPanel('claim')} onAccount={()=>setPanel('account')}/>
      : panel==='home' ? <DemoHome snapshot={snapshot} onChat={()=>setPanel('chat')} onReport={openReport} onClaim={()=>setPanel('claim')}/>
      : !snapshot ? <main className="original-chat-start"><OriginalChatWelcome/><div className="nuan-message"><span className="nuan-avatar" aria-hidden="true">✦</span><div className="nuan-message-body"><p>你好，我是暖暖。可以先聊聊，也可以上传材料。没有报告也能开始。</p></div></div>
        <button className="claim-entry-link" onClick={()=>setPanel('claim')}>整理理赔资料，开启专属关怀</button>
        <div className="connect-form">{subjects.length>1 && <label>关怀对象<select value={subject} onChange={e=>setSubject(e.target.value)}>
          {Array.from(new Map(subjects.map(s=>[s.subject_id,s])).values()).map((s,i)=><option key={s.subject_id} value={s.subject_id}>已授权对象 {i+1} · {s.subject_id.slice(0,8)}</option>)}</select></label>}
          <details><summary>接续已有案件（可选）</summary><input aria-label="已有案件ID" placeholder="已有案件 ID，不需要报告版本" value={caseInput} onChange={e=>setCaseInput(e.target.value)}/></details>
          <button disabled={busy || (!subjects.length && !caseInput)} onClick={()=>void newChat()}>{busy?'正在打开…':'开始新的对话'}</button>
          {!subjects.length && !caseInput && <small>请先到“我的”确认关怀资料授权，再开始对话。</small>}</div></main>
      : panel==='report' ? <main className="chat-report"><h1>本次关怀指引</h1>
          {publishedCare(snapshot.report) ? <><p className="care-report-version">第 {snapshot.report.report_version} 版 · 已审核发布</p>
            <CareReport report={snapshot.report} initialSection={reportFocus} onEvidence={id=>void showEvidence(id)}/>
            {snapshot.report.report_id && <div className="report-feedback"><p>这份指引对你有帮助吗？</p>
              <button disabled={feedbackBusy} onClick={()=>void feedback('helpful')}>有帮助</button>
              <button disabled={feedbackBusy} onClick={()=>void feedback('not_helpful')}>还不够清楚</button>
              <button disabled={feedbackBusy} onClick={()=>void feedback('inaccurate')}>内容需要核实</button>
              <button disabled={feedbackBusy} onClick={()=>void feedback('needs_help')}>我需要帮助</button>
              {feedbackNotice && <p role="status">{feedbackNotice}</p>}</div>}</>
          : <div className="empty-report"><p>{snapshot.report.status==='not_generated'?'还没有报告。你可以在对话中上传材料，让暖暖帮你分析。':'报告尚未发布，部分内容可能需要复核。你仍可以在对话中查阅材料、核对事实。'}</p>
            <button onClick={()=>setPanel('chat')}>回到对话</button></div>}</main>
      : <><main className="chat-scroll inline-report-thread"><OriginalChatGuide snapshot={snapshot} onEvidence={id=>void showEvidence(id)}/>
        {hasOlder && turns.length>0 && <button className="load-history" onClick={()=>void loadOlder()}>查看更早的聊天</button>}
        <div className="messages">{turns.length===0 && <div className="message-row assistant"><div className="avatar">✦</div><div className="message-bubble"><p>你好，我是暖暖。你可以告诉我现在最关心什么，也可以直接上传病历或发票，我会结合材料帮你梳理。</p></div></div>}
          {turns.map(t=><div className="chat-turn" key={t.turn_id} id={`turn-${t.turn_id}`}>
            {t.input_kind==='analysis_ready' ? <p className="analysis-continuation">材料分析结束 · 暖暖继续为你解释</p> : <div className="message-row user"><div className="message-bubble"><p>{t.question}</p>
            {t.attachments.map(a=><span className="attachment" key={a.document_id}>▤ {a.name}</span>)}</div></div>}
            <div className="message-row assistant"><span className="nuan-avatar" aria-hidden="true">✦</span><div className="message-bubble"><ToolActivity events={t.tool_events}/>
              {t.answer ? <><p>{t.answer.text}</p><div className="citation-group">{t.answer.evidence_refs.map(id=><button className="citation" key={id} onClick={()=>void showEvidence(id)}>查看原始依据</button>)}</div>
                {t.answer.history_refs.length>0 && <small className="history-reference">参考了 {t.answer.history_refs.length} 条你允许回忆的历史记录</small>}</>
                : t.status==='failed' ? <><p>这次回答没有完成，你的消息已保存。</p><button disabled={working} onClick={()=>void send(t)}>重试这条消息</button></>
                : <p role="status">正在结合对话处理你的请求…</p>}
            </div></div></div>)}
        </div><div ref={bottom}/></main>
        <footer className="chat-footer">{snapshot.analysis.run_id && ['queued','running'].includes(snapshot.analysis.status) && <div className="analysis-status" role="status">{statusLabels[snapshot.analysis.status] || snapshot.analysis.status}
          {['completed','waiting_review'].includes(snapshot.analysis.status) && <button disabled={working} onClick={()=>{setInput('请查看最新分析，继续帮我解释。');}}>继续了解</button>}</div>}
          <div className="upload-list">{attachments.map(a=><span className="attachment" key={a.document_id}>▤ {a.name} · 已上传</span>)}</div>
          <div className="nuan-quick-actions">{[['summary','看病经过'],['cost','费用解读'],['action','下一步安排']].map(([id,label])=><button key={id} onClick={()=>{const target=document.getElementById('chat-topic-'+id);if(target?.tagName==='DETAILS')target.setAttribute('open','');target?.scrollIntoView({behavior:'smooth',block:'start'});}}>{label}</button>)}</div><form className="composer" onSubmit={submit}><input ref={uploadInput} hidden type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={e=>void upload(e.target.files)}/>
            <button type="button" className="attach-button" title="上传病历或发票" aria-label="上传病历或发票" disabled={working} onClick={()=>uploadInput.current?.click()}>＋</button>
            <textarea aria-label="给暖暖的消息" value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}} rows={1} placeholder="哪一句没看懂？接着问暖暖"/>
            <button className="send-button" disabled={working || (!input.trim()&&!attachments.length)}>{uploading?'…':busy?'…':'↑'}</button>
          </form>
        </footer></>}
      </PageBoundary>
      {connected && panel==='chat' && <div className="chat-page-tools"><button onClick={()=>setHistoryOpen(v=>!v)}>历史对话</button>{snapshot && <button onClick={()=>openReport()}>关怀指引</button>}</div>}
      {connected && panel!=='claim' && <nav className="care-navigation" aria-label="关怀页面"><button aria-current={panel==='home'?'page':undefined} onClick={()=>setPanel('home')}><DemoIcon name="leaf"/>首页</button>
        <button aria-current={panel==='chat'?'page':undefined} onClick={()=>setPanel('chat')}><DemoIcon name="chat"/>问暖暖</button>
        <button aria-current={panel==='records'?'page':undefined} onClick={()=>setPanel('records')}><DemoIcon name="file"/>就医记录</button>
        <button aria-current={panel==='account'?'page':undefined} onClick={()=>setPanel('account')}><DemoIcon name="user"/>我的</button>
        </nav>}
    </section>
    {evidence && <EvidencePanel evidence={evidence} onClose={()=>setEvidence(null)}/>}
  </div>;
}
