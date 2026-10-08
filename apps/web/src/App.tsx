import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react';
import {ApiError, continueAnalysis, createConversation, getConversation, getEvidence, getOlderTurns,
  listConversations, listSubjects, sendChatMessage, uploadChatDocument,
  listDeliveries, recordDeliveryReceipt, submitCareFeedback} from './api';
import {startChatAnalysis} from './api';
import AnalysisFlow,{analysisView,type UploadProgress} from './AnalysisFlow';
import AnalysisNarrative,{currentNarrative} from './AnalysisNarrative';
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
import {prepareChatFiles} from './chatFiles';
import './chat.css';
import './care.css';
import './chat-original.css';
import './chat-theme.css';

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

function UploadSourceIcon({kind}:{kind:'image'|'document'}) {
  return <svg width="26" height="28" viewBox="0 0 28 30" fill="none" aria-hidden="true">
    {kind==='image' ? <><rect x="3" y="5" width="22" height="20" rx="5" stroke="currentColor" strokeWidth="1.7"/><circle cx="10" cy="11" r="2" fill="currentColor"/><path d="m4 21 6-6 5 5 4-4 5 5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></>
      : <><path d="M7 3h10l6 6v16a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" fill="#fff" stroke="currentColor" strokeWidth="1.5"/><path d="M17 3v6h6M9 13h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><rect x="3" y="17" width="22" height="9" rx="3" fill="currentColor"/><text x="14" y="23.6" textAnchor="middle" fill="#fff" fontSize="7" fontWeight="700" fontFamily="Arial,sans-serif">PDF</text></>}
  </svg>;
}

export default function App() {
  const [token,setToken] = useState(()=>sessionStorage.getItem('zhongan_chat_token') || '');
  const [connected,setConnected] = useState(false);
  const [conversations,setConversations] = useState<Conversation[]>([]);
  const [subjects,setSubjects] = useState<ChatSubject[]>([]);
  const [subject,setSubject] = useState('');
  const [caseInput,setCaseInput] = useState('');
  const [snapshot,setSnapshot] = useState<ChatSnapshot|null>(null);
  // Care cards belong to the claim-completion entry, not to ordinary chat visits.
  const [claimGuideConversation,setClaimGuideConversation] = useState('');
  const [older,setOlder] = useState<ChatTurn[]>([]);
  const [hasOlder,setHasOlder] = useState(false);
  const [input,setInput] = useState('');
  const [attachments,setAttachments] = useState<{document_id:string; name:string}[]>([]);
  const [busy,setBusy] = useState(false);
  const [uploading,setUploading] = useState(false);
  const [analysisOpen,setAnalysisOpen]=useState(false);
  const [uploadProgress,setUploadProgress]=useState<UploadProgress>();
  const [analysisSubmitting,setAnalysisSubmitting]=useState(false);
  const [analysisError,setAnalysisError]=useState('');
  const observedAnalysis=useRef('');
  const analysisRequest=useRef<{id:string;message:string;docs:string[]}|null>(null);
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
  const [mobileHistory,setMobileHistory]=useState(()=>window.matchMedia?.('(max-width:760px)').matches ?? false);
  const historyDialog=useRef<HTMLDialogElement>(null);
  const historyTrigger=useRef<HTMLButtonElement>(null);
  const active = useRef('');
  const epoch = useRef(0);
  const busyRef = useRef(false);
  const initialized = useRef(false);
  const olderExhausted = useRef(false);
  const resumed = useRef(new Set<string>());
  const uploadInput = useRef<HTMLInputElement>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const uploadMenu = useRef<HTMLDetailsElement>(null);
  const uploadingRef=useRef(false);
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

  const openConversation = useCallback(async (id:string, auth=token, destination:CarePanel='home', fromClaim=false) => {
    const generation = ++epoch.current;
    active.current = id;
    analysisRequest.current=null;uploadingRef.current=false;
    setClaimGuideConversation(fromClaim ? id : '');
    olderExhausted.current = false;
    setSnapshot(null); setOlder([]); setAttachments([]); setInput(''); setEvidence(null); setError('');
    busyRef.current=false;setBusy(false);setUploading(false);
    setLoadingConversation(true);setHasOlder(false);setDelivery(null);setFeedbackNotice('');
    setPanel(destination);setReportFocus(undefined); setHistoryOpen(false); pendingSend.current = null;
    try {
      const state=await refresh(id,auth,generation);
      if(epoch.current===generation){setAnalysisOpen(!!fromClaim && !!state.analysis.run_id);setAnalysisError('');setUploadProgress(undefined);}
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
  useEffect(()=>{if(panel==='chat' && snapshot?.turns.length)bottom.current?.scrollIntoView({behavior:'smooth'});},[snapshot?.turns.length,busy,panel]);
  useEffect(()=>{
    const run=snapshot?.analysis;
    const key=`${snapshot?.conversation.conversation_id}:${run?.run_id}`;
    if(run?.run_id && ['queued','running'].includes(run.status) && observedAnalysis.current!==key){
      observedAnalysis.current=key;setAnalysisError('');setAnalysisOpen(true);
    }
  },[snapshot?.analysis.run_id,snapshot?.analysis.status,snapshot?.conversation.conversation_id]);
  useEffect(()=>{++evidenceRequest.current;setHistoryOpen(false);setEvidence(null);if(panel!=='chat')setClaimGuideConversation('');},[panel]);
  useEffect(()=>{
    if(panel==='report' && snapshot && !publishedCare(snapshot.report))setPanel('chat');
  },[panel,snapshot,setPanel]);
  useEffect(()=>{
    const ready=currentNarrative(snapshot?.turns || [],snapshot?.analysis.run_id);
    if(analysisOpen && ready){
      setAnalysisOpen(false);
      if(panel==='chat')requestAnimationFrame(()=>document.getElementById(`turn-${ready.turn_id}`)?.scrollIntoView({behavior:'smooth',block:'start'}));
    }
  },[snapshot?.turns,snapshot?.analysis.run_id,analysisOpen,panel]);
  useEffect(()=>{
    const media=window.matchMedia?.('(max-width:760px)');
    if(!media)return;
    const update=()=>{setMobileHistory(media.matches);setHistoryOpen(false);};
    media.addEventListener('change',update);
    return()=>media.removeEventListener('change',update);
  },[]);
  useEffect(()=>{
    const dialog=historyDialog.current;
    if(!dialog || !historyOpen || !mobileHistory || !connected || panel!=='chat')return;
    dialog.showModal();
    return()=>{dialog.close();if(window.matchMedia?.('(max-width:760px)').matches)historyTrigger.current?.focus({preventScroll:true});};
  },[historyOpen,mobileHistory,connected,panel]);

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
    setClaimGuideConversation('');
    setPanel('chat');
  };

  const completeNarrative=useCallback(async(id:string,generation:number,runId:string)=>{
    busyRef.current=true;setBusy(true);setAnalysisError('');
    try {await continueAnalysis(token,id,runId);await refresh(id,token,generation);}
    catch(e){if(epoch.current===generation){setError(errorText(e));setAnalysisError('解读暂时没能完成，你的材料已保存，可以重试。');}}
    finally{if(epoch.current===generation){busyRef.current=false;setBusy(false);}}
  },[token,refresh]);

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
          && !currentNarrative(state.turns,run.run_id)
          && state.turns.some(t=>t.status==='completed' && t.tool_events.some(e=>e.tool==='start_analysis' && e.run_id===run.run_id));
        const key=`${id}:${run.run_id}`;
        if(shouldContinue && !busyRef.current && !uploadingRef.current && !state.turns.some(t=>t.status==='running') && !resumed.current.has(key)) {
          resumed.current.add(key);
          await completeNarrative(id,generation,run.run_id!);
        }
      } catch(e) {if(!stopped && epoch.current===generation)setError(errorText(e));}
      if(!stopped)timer=setTimeout(tick,3500);
    };
    timer=setTimeout(tick,1500);
    return()=>{stopped=true;clearTimeout(timer);};
  },[connected,snapshot?.conversation.conversation_id,token,refresh,completeNarrative]);

  const send = async (retry?:ChatTurn) => {
    const id=active.current, generation=epoch.current;
    if(!id || busyRef.current || busy || uploading) return;
    const text=retry?.question || input.trim() || (attachments.length ? '请帮我分析这些材料。' : '');
    if(!text)return;
    const docs=retry ? retry.attachments.map(x=>x.document_id) : attachments.map(x=>x.document_id);
    const previous=pendingSend.current;
    const req=retry?.request_id || (previous && previous.text===text && JSON.stringify(previous.docs)===JSON.stringify(docs) ? previous.id : requestId());
    pendingSend.current={id:req,text,docs};busyRef.current=true;setBusy(true);setError('');
    if(docs.length){setAnalysisOpen(true);setAnalysisError('');setAnalysisSubmitting(true);}
    try {
      if(retry?.input_kind==='analysis_ready' && snapshot?.analysis.run_id) {
        await continueAnalysis(token,id,snapshot.analysis.run_id);
      } else {
        if(docs.length)await startChatAnalysis(token,id,req,text,docs);
        else await sendChatMessage(token,id,req,text,docs);
      }
      if(epoch.current===generation){setInput('');setAttachments([]);pendingSend.current=null;}
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation)setError(errorText(e));}
    finally {
      try {await refresh(id,token,generation);if(epoch.current===generation)setConversations(await listConversations(token));}
      catch(e){if(epoch.current===generation)setError(errorText(e));}
      if(epoch.current===generation){busyRef.current=false;setBusy(false);setAnalysisSubmitting(false);}
    }
  };

  const startMaterialAnalysis=async(docs=attachments.map(a=>a.document_id),message=input.trim() || '请分析本次上传材料，整理就医经过、费用与待补充信息。')=>{
    const id=active.current,generation=epoch.current;if(!id || busyRef.current)return;
    const previous=analysisRequest.current;
    const request=previous && previous.message===message && JSON.stringify(previous.docs)===JSON.stringify(docs)?previous:{id:requestId(),message,docs};
    analysisRequest.current=request;busyRef.current=true;setBusy(true);setAnalysisSubmitting(true);setAnalysisOpen(true);setAnalysisError('');
    try {
      await startChatAnalysis(token,id,request.id,message,docs);
      if(epoch.current===generation){setAttachments([]);setInput('');analysisRequest.current=null;}
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation)setAnalysisError(errorText(e));}
    finally{
      try{await refresh(id,token,generation);}catch(e){if(epoch.current===generation)setAnalysisError(errorText(e));}
      if(epoch.current===generation){busyRef.current=false;setBusy(false);setAnalysisSubmitting(false);}
    }
  };

  const upload = async(files:FileList|null) => {
    if(!files || !active.current || busyRef.current || busy || uploading)return;
    const id=active.current,generation=epoch.current;
    let selected:File[];
    try{selected=prepareChatFiles(files,attachments.length);}catch(e){setError(errorText(e));return;}
    if(!selected.length)return;
    uploadingRef.current=true;
    const uploaded=[...attachments];setUploading(true);setError('');setAnalysisError('');setAnalysisOpen(true);setUploadProgress({done:0,total:selected.length});
    try {
      for(const file of selected) {
        const doc=await uploadChatDocument(token,id,file);
        if(epoch.current!==generation)return;
        if(!uploaded.some(x=>x.document_id===doc.document_id))uploaded.push({document_id:doc.document_id,name:file.name});
        setAttachments([...uploaded]);setUploadProgress({done:selected.indexOf(file)+1,total:selected.length});
      }
      if(epoch.current===generation){setUploadProgress(undefined);await startMaterialAnalysis(uploaded.map(a=>a.document_id));}
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation){setError(errorText(e));setAnalysisError(errorText(e));}}
    finally {if(epoch.current===generation){uploadingRef.current=false;setUploading(false);setUploadProgress(undefined);if(uploadInput.current)uploadInput.current.value='';if(photoInput.current)photoInput.current.value='';}}
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
  const narrative=currentNarrative(turns,snapshot?.analysis.run_id);
  const showClaimGuide=!!snapshot && claimGuideConversation===snapshot.conversation.conversation_id;
  const working=busy || uploading || loadingConversation || !!snapshot?.turns.some(t=>t.status==='running');
  const submit=(e:FormEvent)=>{e.preventDefault();void send();};
  const openNarrative=()=>{setAnalysisOpen(false);setPanel('chat');requestAnimationFrame(()=>{
    const target=narrative?document.getElementById(`turn-${narrative.turn_id}`):bottom.current;
    target?.scrollIntoView({behavior:'smooth',block:'start'});});};
  const openReport=(section?:ReportSection['section_type'])=>{
    if(!snapshot || !publishedCare(snapshot.report)){openNarrative();return;}
    setAnalysisOpen(false);setReportFocus(section);setPanel('report');};
  const material=snapshot?.material_report;
  const progressView=analysisView(snapshot,uploadProgress,analysisSubmitting,analysisError);
  const historyPanel=<aside className="chat-sidebar" aria-label="历史对话列表">
      <div className="history-panel-head"><div className="brand"><img src={brand} alt="暖愈智护"/></div><button className="history-close" autoFocus={mobileHistory} aria-label="关闭历史对话" onClick={()=>setHistoryOpen(false)}>×</button></div>
      <button className="new-chat" disabled={working} onClick={prepareNewChat}>＋ 新的关怀对话</button>
      <div className="history-list"><p>以前的对话</p>{conversations.length===0 && <p>还没有历史对话</p>}{conversations.map(c=><button disabled={working} key={c.conversation_id}
        className={active.current===c.conversation_id?'selected':''} onClick={()=>void openConversation(c.conversation_id,token,'chat')}>
        <strong>{c.title}</strong><small>{new Date(c.updated_at).toLocaleDateString('zh-CN')}</small></button>)}</div>
      <button className="quiet-button" disabled={working} onClick={()=>void signOut()}>退出登录</button>
    </aside>;

  return <div className={`chat-shell ${panel==='chat'?'chat-view':''}`}>
    {connected && panel==='chat' && (mobileHistory ? historyOpen && <dialog id="history-dialog" ref={historyDialog} className="history-drawer" aria-label="历史对话"
      onKeyDown={e=>{if(e.key!=='Tab')return;const buttons=Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));const first=buttons[0],last=buttons.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}
      onCancel={e=>{e.preventDefault();setHistoryOpen(false);}} onClick={e=>{if(e.target===e.currentTarget)setHistoryOpen(false);}}>{historyPanel}</dialog> : historyPanel)}
    <section className={`chat-workspace ${panel==='chat'?'chat-original':''}`}>
      {connected && panel==='chat' && <div className="chat-page-actions">
        {mobileHistory && <button ref={historyTrigger} className="history-trigger" aria-haspopup="dialog" aria-controls="history-dialog" aria-expanded={historyOpen} onClick={()=>setHistoryOpen(true)}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 8a8 8 0 1 1-1 7M4 3v5h5"/><path d="M12 7v5l3 2"/></svg>历史对话</button>}
        <div className="nuan-header-identity"><strong>暖暖</strong><span>你的就医关怀助手</span></div>
        {snapshot && (publishedCare(snapshot.report) || narrative) && <button className="chat-guide-entry" onClick={()=>narrative?openNarrative():openReport()}>{narrative?'材料解读':'关怀指引'}</button>}
      </div>}
      {delivery && snapshot?.report.report_id===delivery.report_id && <div className="analysis-status care-notice" role="status">{delivery.message}
        {delivery.receipt_state==='read' ? <span>已查看</span> : <button onClick={()=>openReport()}>查看指引</button>}</div>}
      {error && <div role="alert" className="chat-error persistent-error">{error}<button aria-label="关闭提示" onClick={()=>setError('')}>×</button></div>}
      <PageBoundary resetKey={`${panel}:${snapshot?.conversation.conversation_id || ''}`}>
      {connected && <div className="claim-panel" hidden={panel!=='claim'}><ClaimIntake key={token} token={token} subject={subject} visible={panel==='claim'} onExit={()=>setPanel('home')} onAuthorize={()=>setPanel('account')} onOpen={async (id,report=false)=>{
          const generation=epoch.current;const items=await listConversations(token);
          if(epoch.current!==generation)return;setConversations(items);await openConversation(id,token,'chat',true);if(report)openReport();}}/></div>}
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
      : !snapshot ? <main className="original-chat-start"><OriginalChatWelcome/><div className="nuan-message"><span className="nuan-avatar" aria-hidden="true">✦</span><div className="nuan-message-body"><p>你好，我是暖暖。你现在有什么想说的，我愿意听。想聊聊身体上的不舒服、心里的牵挂，或一起看看材料，都可以按你的节奏来。</p></div></div>
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
          : <div className="empty-report"><p>暖暖会在对话里结合材料为你解释。</p>
            <button onClick={()=>setPanel('chat')}>回到对话</button></div>}</main>
      : <><main className="chat-scroll inline-report-thread">{showClaimGuide ? <OriginalChatGuide snapshot={snapshot} onEvidence={id=>void showEvidence(id)}/> : <OriginalChatWelcome/>}
        {(snapshot.analysis.run_id || analysisSubmitting || uploadProgress || analysisError) && !narrative && <button className="analysis-card" onClick={()=>setAnalysisOpen(true)}><span className="analysis-card-icon" aria-hidden="true">✦</span><span className="analysis-card-copy"><strong>{progressView.title}</strong><small>{`${progressView.detail}${progressView.percent!==null?` · ${progressView.percent}%`:''}`}</small></span><span className="analysis-card-arrow" aria-hidden="true">›</span></button>}
        {hasOlder && turns.length>0 && <button className="load-history" onClick={()=>void loadOlder()}>查看更早的聊天</button>}
        <div className="nuan-chat-heading"><span><DemoIcon name="chat"/>和暖暖聊聊</span><small>有疑问，接着问</small></div>
        <div className="messages">{turns.length===0 && <div className="message-row assistant"><div className="avatar">✦</div><div className="message-bubble"><div className="nuan-reply-label"><DemoIcon name="leaf"/>暖暖</div><p>你好，我是暖暖。你可以从最想说的事情聊起，不用一下子把所有事情讲清楚。如果有看不懂的病历或发票，我也会陪你一点点看。</p></div></div>}
          {turns.map(t=><div className="chat-turn" key={t.turn_id} id={`turn-${t.turn_id}`}>
            {t.input_kind==='analysis_ready' ? <p className="analysis-continuation">材料已整理 · 暖暖为你解读</p> : <div className="message-row user"><div className="message-bubble"><p>{t.question}</p>
            {t.attachments.map(a=><span className="attachment" key={a.document_id}>▤ {a.name}</span>)}</div></div>}
            <div className="message-row assistant"><span className="nuan-avatar" aria-hidden="true">✦</span><div className={`message-bubble ${t.input_kind==='analysis_ready'?'narrative-bubble':''}`}><div className="nuan-reply-label"><DemoIcon name="leaf"/>暖暖{t.input_kind==='analysis_ready' && <span>· 材料解读</span>}</div>{t.input_kind!=='analysis_ready' && <ToolActivity events={t.tool_events}/>}
              {t.answer ? <>{t.input_kind==='analysis_ready'?<AnalysisNarrative turn={t} onEvidence={id=>void showEvidence(id)}/>:<><p>{t.answer.text}</p><div className="citation-group">{t.answer.evidence_refs.map(id=><button className="citation" key={id} onClick={()=>void showEvidence(id)}>查看原始依据</button>)}</div></>}
                {t.answer.history_refs.length>0 && <small className="history-reference">参考了 {t.answer.history_refs.length} 条你允许回忆的历史记录</small>}</>
                : t.status==='failed' ? <><p>这次回答没有完成，你的消息已保存。</p><button disabled={working} onClick={()=>void send(t)}>重试这条消息</button></>
                : <p role="status">{t.input_kind==='analysis_ready'?'材料已经整理好，暖暖正在结合你的资料写解读…':'暖暖正在认真看你说的话…'}</p>}
            </div></div></div>)}
        </div><div ref={bottom}/></main>
        <footer className="chat-footer">
          <div className="upload-list">{attachments.map(a=><span className="attachment" key={a.document_id}>▤ {a.name} · 已上传</span>)}</div>
          {showClaimGuide && <div className="nuan-quick-actions">{[['summary','看病经过'],['cost','费用解读'],['action','下一步安排']].map(([id,label])=><button key={id} onClick={()=>{const target=document.getElementById('chat-topic-'+id);if(target?.tagName==='DETAILS')target.setAttribute('open','');target?.scrollIntoView({behavior:'smooth',block:'start'});}}><DemoIcon name={id==='summary'?'file':id==='cost'?'chat':'leaf'}/>{label}</button>)}</div>}<form className="composer" onSubmit={submit}>
            <input ref={uploadInput} aria-label="选择文档文件" hidden type="file" multiple onChange={e=>void upload(e.target.files)}/>
            <input ref={photoInput} aria-label="选择照片或图片" hidden type="file" multiple accept="image/jpeg,image/png" onChange={e=>void upload(e.target.files)}/>
            <details ref={uploadMenu} className="chat-upload-menu" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))e.currentTarget.open=false;}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.currentTarget.open=false;e.currentTarget.querySelector('summary')?.focus();}}}>
              <summary title="上传病历或发票" aria-label="上传病历或发票" aria-disabled={working} onClick={e=>{if(working)e.preventDefault();}}>＋</summary>
              <div className="chat-upload-options" aria-label="选择上传方式"><div className="upload-panel-heading"><p>上传就医材料</p><small>补充资料，一起看得更清楚</small></div>
                <button className="upload-source-photo" type="button" aria-label="照片或图片" aria-describedby="upload-photo-hint" disabled={working} onClick={()=>{if(uploadMenu.current)uploadMenu.current.open=false;photoInput.current?.click();}}><span className="upload-source-icon"><UploadSourceIcon kind="image"/></span><span className="upload-source-copy"><strong>照片或图片</strong><small id="upload-photo-hint">从相册选择 · JPG、PNG</small></span><DemoIcon name="arrow"/></button>
                <button className="upload-source-document" type="button" aria-label="PDF / TXT 文件" aria-describedby="upload-document-hint" disabled={working} onClick={()=>{if(uploadMenu.current)uploadMenu.current.open=false;uploadInput.current?.click();}}><span className="upload-source-icon"><UploadSourceIcon kind="document"/></span><span className="upload-source-copy"><strong>PDF / TXT 文件</strong><small id="upload-document-hint">从文件中选择病历或票据</small></span><DemoIcon name="arrow"/></button>
                <small className="upload-panel-note"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><path d="M8 12v5a4 4 0 0 0 8 0V7a3 3 0 0 0-6 0v10a1 1 0 0 0 2 0V9"/></svg>支持多选 · 每份不超过 10MB</small>
              </div>
            </details>
            <textarea aria-label="给暖暖的消息" value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}} rows={1} placeholder="有哪里不清楚？问问暖暖"/>
            <button className="send-button" aria-label="发送消息" disabled={working || (!input.trim()&&!attachments.length)}>{uploading?'…':busy?'…':<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>}</button>
          </form>
        </footer></>}
      </PageBoundary>
      {connected && snapshot && <AnalysisFlow open={analysisOpen && ['chat','report'].includes(panel)} snapshot={analysisSubmitting || uploadProgress?null:snapshot} upload={uploadProgress} submitting={analysisSubmitting} error={analysisError} onClose={()=>setAnalysisOpen(false)} onReport={openNarrative} onRetry={()=>{if(material?.status==='available' && snapshot.analysis.run_id)void completeNarrative(active.current,epoch.current,snapshot.analysis.run_id);else void startMaterialAnalysis();}}/>}
      {connected && panel!=='claim' && <nav className="care-navigation" aria-label="关怀页面"><button aria-current={panel==='home'?'page':undefined} onClick={()=>setPanel('home')}><DemoIcon name="leaf"/>首页</button>
        <button aria-current={panel==='chat'?'page':undefined} onClick={()=>setPanel('chat')}><DemoIcon name="chat"/>问暖暖</button>
        <button aria-current={panel==='records'?'page':undefined} onClick={()=>setPanel('records')}><DemoIcon name="file"/>就医记录</button>
        <button aria-current={panel==='account'?'page':undefined} onClick={()=>setPanel('account')}><DemoIcon name="user"/>我的</button>
        </nav>}
    </section>
    {evidence && <EvidencePanel evidence={evidence} onClose={()=>setEvidence(null)}/>}
  </div>;
}
