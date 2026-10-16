import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react';
import {ApiError, continueAnalysis, createConversation, getConversation, getEvidence, getOlderTurns,
  listConversations, listSubjects, listMembers, sendChatMessage, uploadChatDocument,
  listDeliveries, recordDeliveryReceipt, submitCareFeedback} from './api';
import {startChatAnalysis} from './api';
import {replaceChatDocument} from './api';
import AnalysisFlow,{analysisView,type UploadProgress} from './AnalysisFlow';
import AnalysisNarrative,{currentNarrative} from './AnalysisNarrative';
import ChatFollowups from './ChatFollowups';
import MedicalServiceCards from './MedicalServices';
import type {ChatSnapshot, ChatSubject, ChatTurn, Conversation, Evidence, ToolEvent, DeliveryNotice, FeedbackType,ReportSection} from './types';
import {CareReport,EvidencePanel,brand} from './CarePages';
import {DemoHome,DemoIcon} from './DemoPages';
import {publishedCare,type CarePanel} from './carePresentation';
import {readCarePanel,useCareNavigation} from './careNavigation';
import {PageBoundary} from './PageBoundary';
import AuthPage from './AuthPage';
import ClaimIntake,{type JudgeSampleRequest} from './ClaimIntake';
import AccountPage from './AccountPage';
import {MemberEditor,MemberPicker,MemberConsentDialog} from './MemberControls';
import PersonalRecords from './PersonalRecords';
import type {MemberResponse,JudgeSample} from './api';
import {revokeSession} from './api';
import OriginalChatWelcome from './OriginalChatWelcome';
import {prepareChatFiles} from './chatFiles';
import {isClaimSubmission} from './claimChatPresentation';
import {uploadChatAttachment} from './api';
import {ChatDraftAttachments,ChatSentAttachments,ReportUploadDialog,type DraftAttachment} from './ChatUploads';
import PhotoReview from './PhotoReview';
import EncounterOverview from './EncounterOverview';
import DemoShowcase from './DemoShowcase';
import {SourceToken,CitedText} from './SourceCitations';
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
const toolLabels: Record<string,string> = {recommend_medical_services:'整理医疗服务',list_materials:'查看上传材料',start_analysis:'提交材料分析',
  search_knowledge:'查阅医护与费用知识',search_web:'联网查阅权威资料',
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
  const [claimSubject,setClaimSubject]=useState('');
  const [claimDirty,setClaimDirty]=useState(false);
  const [judgeSampleRequest,setJudgeSampleRequest]=useState<(JudgeSampleRequest&{subjectId:string})>();
  useEffect(()=>setJudgeSampleRequest(undefined),[token]);
  const [members,setMembers]=useState<MemberResponse[]>([]);
  const [viewSubject,setViewSubject]=useState('');
  const [recordCase,setRecordCase]=useState<string>();
  const [memberPicker,setMemberPicker]=useState<'chat'|'claim'|'report'>();
  const pendingReportMember=useRef('');
  const [consentMember,setConsentMember]=useState<string>();
  const memberEpoch=useRef(0);
  const memberCacheKey=useRef('');
  const viewMember=members.find(member=>member.subject_id===viewSubject)||members[0];
  const selfMember=members.find(member=>member.relationship==='self');
  const needsProfile=!!selfMember&&!selfMember.profile_completed;
  const selectViewMember=(id:string)=>{if(!members.some(member=>member.subject_id===id))return;
    setViewSubject(id);setRecordCase(undefined);if(memberCacheKey.current)localStorage.setItem(memberCacheKey.current,id);};
  const memberSaved=async(value:MemberResponse)=>{setMembers(items=>items.some(item=>item.subject_id===value.subject_id)?items.map(item=>item.subject_id===value.subject_id?value:item):[...items,value]);
    setViewSubject(value.subject_id);setRecordCase(undefined);if(memberCacheKey.current)localStorage.setItem(memberCacheKey.current,value.subject_id);
    if(value.relationship==='self'&&!selfMember?.profile_completed)setPanel('home');};
  const [caseInput,setCaseInput] = useState('');
  const [snapshot,setSnapshot] = useState<ChatSnapshot|null>(null);
  const [older,setOlder] = useState<ChatTurn[]>([]);
  const [hasOlder,setHasOlder] = useState(false);
  const [input,setInput] = useState('');
  const [attachments,setAttachments] = useState<{document_id:string; name:string}[]>([]);
  const [draftFiles,setDraftFiles]=useState<DraftAttachment[]>([]);
  const [sentMessages,setSentMessages]=useState<{turn:ChatTurn;files:DraftAttachment[]}[]>([]);
  const uploadedDrafts=useRef(new Map<string,string>());
  const [reportUploadConversation,setReportUploadConversation]=useState('');
  const [busy,setBusy] = useState(false);
  const [uploading,setUploading] = useState(false);
  const [photoReview,setPhotoReview]=useState<{files:File[];conversationId:string;replaceId?:string}|null>(null);
  const [analysisOpen,setAnalysisOpen]=useState(false);
  const [uploadProgress,setUploadProgress]=useState<UploadProgress>();
  const [analysisSubmitting,setAnalysisSubmitting]=useState(false);
  const [analysisError,setAnalysisError]=useState('');
  const observedAnalysis=useRef('');
  const analysisRequest=useRef<{id:string;message:string;docs:string[]}|null>(null);
  const pendingReportUpload=useRef<{files:File[];replaceId?:string;completed:Map<File,{document_id:string;name:string}>}|null>(null);
  const [error,setError] = useState('');
  const [pollError,setPollError] = useState('');
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
  const pendingSend = useRef<{id:string; text:string; docs:string[];draftKey:string}|null>(null);
  const connecting=useRef(false);

  const invalidateAccess = useCallback((e:unknown,id:string,generation:number,auth=token) => {
    if(!(e instanceof ApiError) || ![401,403,404].includes(e.status) || epoch.current!==generation || active.current!==id)return false;
    const fresh=++epoch.current;active.current='';busyRef.current=false;
    setLoadingConversation(false);setPollError('');
    setSnapshot(null);setOlder([]);setEvidence(null);setAttachments([]);setPhotoReview(null);setInput('');setDelivery(null);
    setDraftFiles([]);setSentMessages([]);uploadedDrafts.current.clear();setReportUploadConversation('');pendingReportUpload.current=null;
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
      setPollError('');
      if(currentNarrative(state.turns,state.analysis.run_id))setAnalysisError('');
      setHasOlder(state.turns.length === 50 && !olderExhausted.current);
    }
    return state;
  },[invalidateAccess]);

  const openConversation = useCallback(async (id:string, auth=token, destination:CarePanel='home', fromClaim=false) => {
    const generation = ++epoch.current;
    active.current = id;
    analysisRequest.current=null;pendingReportUpload.current=null;uploadingRef.current=false;
    olderExhausted.current = false;
    setSnapshot(null); setOlder([]); setAttachments([]);setPhotoReview(null); setInput(''); setEvidence(null); setError('');setPollError('');
    setDraftFiles([]);setSentMessages([]);uploadedDrafts.current.clear();setReportUploadConversation('');pendingReportUpload.current=null;
    busyRef.current=false;setBusy(false);setUploading(false);
    setLoadingConversation(true);setHasOlder(false);setDelivery(null);setFeedbackNotice('');
    setPanel(destination);setReportFocus(undefined); setHistoryOpen(false); pendingSend.current = null;
    try {
      const state=await refresh(id,auth,generation);
      if(epoch.current===generation){setAnalysisOpen(!!fromClaim && !!state.analysis.run_id);setAnalysisError('');setUploadProgress(undefined);}
      if (epoch.current===generation) localStorage.setItem('zhongan_last_conversation',id);
      if(epoch.current===generation)return state;
    } catch(e) {if(epoch.current===generation) setError(errorText(e));}
    finally {if(epoch.current===generation)setLoadingConversation(false);}
  },[refresh,token,setPanel]);

  const connect = useCallback(async (auth:string,failLoud=false) => {
    if (!auth.trim() || connecting.current) return;
    connecting.current=true;
    const generation=++epoch.current;
    setBusy(true); setError('');
    try {
      const [items,allowed,people] = await Promise.all([listConversations(auth),listSubjects(auth),listMembers(auth)]);
      if(epoch.current!==generation)return;
      sessionStorage.setItem('zhongan_chat_token',auth); setToken(auth); setConnected(true);
      setConversations(items); setSubjects(allowed); setSubject('');setMembers(people);
      memberCacheKey.current=`zhongan_view_member:${people.find(person=>person.relationship==='self')?.subject_id||''}`;
      const remembered=localStorage.getItem(memberCacheKey.current);
      setViewSubject(people.some(person=>person.subject_id===remembered)?remembered!:people[0]?.subject_id||'');
      const last = localStorage.getItem('zhongan_last_conversation');
      const chosen = items.find(x=>x.conversation_id===last) || items[0];
      if(chosen) await openConversation(chosen.conversation_id,auth,readCarePanel(window.location.hash));
      else if(failLoud)setPanel('home');
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
  useEffect(()=>{++evidenceRequest.current;setHistoryOpen(false);setEvidence(null);},[panel]);
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

  const prepareNewChat = (personId:string) => {
    setSubject(personId);
    ++epoch.current;active.current='';olderExhausted.current=false;
    busyRef.current=false;setBusy(false);setUploading(false);setLoadingConversation(false);
    setDelivery(null);setFeedbackNotice('');setHasOlder(false);setReportFocus(undefined);setCaseInput('');
    setSnapshot(null);setOlder([]);setAttachments([]);setPhotoReview(null);setInput('');setEvidence(null);setError('');
    setDraftFiles([]);setSentMessages([]);uploadedDrafts.current.clear();setReportUploadConversation('');
    setHistoryOpen(false);pendingSend.current=null;
    setPanel('chat');
  };

  const requestBusiness=(destination:'chat'|'claim',personId?:string)=>{
    if(busyRef.current||uploadingRef.current||analysisSubmitting)return;
    if(destination==='chat'){setMemberPicker(undefined);prepareNewChat(personId||'');return;}
    if(destination==='claim'&&panel==='claim')return;
    if(personId){
      if(claimSubject&&claimSubject!==personId&&claimDirty&&!window.confirm('切换就医人员将清除尚未提交的表单和材料，是否继续？'))return;
      if(claimSubject!==personId){setClaimDirty(false);setJudgeSampleRequest(undefined);}setClaimSubject(personId);setPanel('claim');
    }
    else setMemberPicker(destination);
  };
  const chooseBusinessMember=(id:string)=>{
    const destination=memberPicker;setMemberPicker(undefined);
    if(destination==='report')void createReportConversation(id);
    else if(destination)requestBusiness(destination,id);
  };
  const createReportConversation=async(personId:string,allowed:ChatSubject[]=subjects)=>{
    if(busyRef.current||uploadingRef.current||analysisSubmitting)return;
    if(!allowed.some(item=>item.subject_id===personId)){
      pendingReportMember.current=personId;setConsentMember(personId);return;
    }
    const generation=epoch.current;busyRef.current=true;setBusy(true);setError('');
    try{
      const created=await createConversation(token,requestId(),personId);
      if(epoch.current!==generation)return;
      setConversations(await listConversations(token));
      if(epoch.current!==generation)return;
      const opened=await openConversation(created.conversation_id,token,'chat');
      if(opened&&active.current===created.conversation_id)setReportUploadConversation(created.conversation_id);
    }catch(e){if(epoch.current===generation)setError(errorText(e));}
    finally{if(epoch.current===generation){busyRef.current=false;setBusy(false);}}
  };
  const startJudgeExperience=(sample:JudgeSample)=>{
    if(busyRef.current||uploadingRef.current||analysisSubmitting)return;
    if(!selfMember)throw new Error('请先完善本人资料，再开始评委体验。');
    const sameDraft=claimDirty&&claimSubject===selfMember.subject_id&&judgeSampleRequest?.subjectId===claimSubject
      &&judgeSampleRequest.sample.sample_id===sample.sample_id&&judgeSampleRequest.sample.version===sample.version;
    if(!sameDraft){
      if(claimDirty&&!window.confirm('用示例体验替换当前尚未提交的表单和材料？'))return;
      setJudgeSampleRequest({id:requestId(),subjectId:selfMember.subject_id,sample});
      setClaimDirty(false);
    }
    setClaimSubject(selfMember.subject_id);setMemberPicker(undefined);setPanel('claim');
  };
  const refreshAccess=async(changedSubject:string)=>{
    const generation=++memberEpoch.current;
    const [items,allowed]=await Promise.all([listConversations(token),listSubjects(token)]);
    if(memberEpoch.current!==generation)return;
    setConversations(items);setSubjects(allowed);
    if(pendingReportMember.current===changedSubject&&allowed.some(item=>item.subject_id===changedSubject)){
      pendingReportMember.current='';
      await createReportConversation(changedSubject,allowed);
      return;
    }
    if(snapshot?.conversation.subject_id===changedSubject&&active.current===snapshot.conversation.conversation_id&&!items.some(item=>item.conversation_id===snapshot.conversation.conversation_id)){
      ++epoch.current;active.current='';setSnapshot(null);setEvidence(null);setOlder([]);setAttachments([]);setPhotoReview(null);setInput('');setDelivery(null);
      setDraftFiles([]);setSentMessages([]);uploadedDrafts.current.clear();setReportUploadConversation('');
      pendingSend.current=null;careKeys.current.clear();localStorage.removeItem('zhongan_last_conversation');
    }
  };

  const completeNarrative=useCallback(async(id:string,generation:number,runId:string)=>{
    if(busyRef.current)return;
    busyRef.current=true;setBusy(true);setAnalysisError('');
    try {await continueAnalysis(token,id,runId);await refresh(id,token,generation);}
    catch(e){
      // A transport error or another tab's request is not a persisted failure.
      let recovered:ChatSnapshot|undefined;
      try{recovered=await refresh(id,token,generation);}catch{/* Keep the original request error. */}
      if(epoch.current===generation){
        if(recovered && (currentNarrative(recovered.turns,runId) || recovered.turns.some(t=>t.input_kind==='analysis_ready' && t.status==='running'))){
          setAnalysisError('');
        }else{setAnalysisError('解读暂时没能完成，你的材料已保存，可以重试。'+errorText(e));}
      }
    }
    finally{if(epoch.current===generation){busyRef.current=false;setBusy(false);
      void listConversations(token).then(items=>{if(epoch.current===generation)setConversations(items);}).catch(()=>{});
    }}
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
          void completeNarrative(id,generation,run.run_id!);
        }
      } catch(e) {if(!stopped && epoch.current===generation && active.current===id)setPollError('连接暂时中断，正在自动恢复。已保存的材料和解读不会受影响。');}
      if(!stopped)timer=setTimeout(tick,3500);
    };
    timer=setTimeout(tick,1500);
    return()=>{stopped=true;clearTimeout(timer);};
  },[connected,snapshot?.conversation.conversation_id,token,refresh,completeNarrative]);

  const titlesPending=conversations.some(item=>item.title_pending);
  useEffect(()=>{
    if(!connected||panel!=='chat'||!titlesPending)return;
    const generation=epoch.current;
    let stopped=false,timer:ReturnType<typeof setTimeout>;
    const tick=async()=>{
      try{const items=await listConversations(token);if(!stopped&&epoch.current===generation)setConversations(items);}
      catch{/* Keep readable titles during a transient title refresh failure. */}
      if(!stopped&&epoch.current===generation)timer=setTimeout(tick,5000);
    };
    timer=setTimeout(tick,5000);
    return()=>{stopped=true;clearTimeout(timer);};
  },[connected,panel,titlesPending,token,snapshot?.conversation.conversation_id]);

  const send = async (retry?:ChatTurn,quickMessage?:string):Promise<boolean> => {
    const id=active.current, generation=epoch.current;
    if(!id || busyRef.current || busy || uploading || loadingConversation || snapshot?.turns.some(t=>t.status==='running')) return false;
    const quick=quickMessage!==undefined;
    const localRetry=retry?.turn_id.startsWith('local:');
    const selected=retry ? sentMessages.find(item=>item.turn.request_id===retry.request_id)?.files || [] : quick ? [] : [...draftFiles];
    const text=quick ? quickMessage.trim() : retry?.question || input.trim() || (selected.length ? '请看看这些附件，帮我解释一下。' : '');
    if(!text)return false;
    const docs=retry ? retry.attachments.filter(x=>x.kind!=='chat_attachment').map(x=>x.document_id) : [];
    const attachmentIds=retry ? retry.attachments.filter(x=>x.kind==='chat_attachment').map(x=>x.document_id) : [];
    const draftKey=quick?'quick':retry?retry.turn_id:selected.map(file=>file.id).join(':');
    const previous=pendingSend.current;
    const req=retry?.request_id || (quick&&previous?.draftKey==='quick'&&previous.text===text?previous.id:requestId());
    pendingSend.current={id:req,text,docs,draftKey};busyRef.current=true;setBusy(true);setError('');
    // Capture the submission before any upload/model await. The composer is only a draft.
    if(!retry && !(quick&&sentMessages.some(item=>item.turn.request_id===req))){
      const turn:ChatTurn={turn_id:`local:${req}`,request_id:req,question:text,input_kind:'user',attachments:[],status:'running',answer:null,tool_events:[],created_at:new Date().toISOString(),error_code:null};
      setSentMessages(items=>[...items.slice(-19),{turn,files:selected}]);
      if(!quick){setInput('');setDraftFiles([]);}
    }else setSentMessages(items=>items.map(item=>item.turn.request_id===req?{...item,turn:{...item.turn,status:'running'}}:item));
    let sent=false;
    try {
      if(retry?.input_kind==='analysis_ready' && snapshot?.analysis.run_id) {
        await continueAnalysis(token,id,snapshot.analysis.run_id);
      } else {
        if((!retry||localRetry)&&selected.length){
          uploadingRef.current=true;setUploading(true);
          for(const item of selected){
            let attachmentId=uploadedDrafts.current.get(item.id);
            if(!attachmentId){const uploaded=await uploadChatAttachment(token,id,item.file);
              if(epoch.current!==generation)return false;
              attachmentId=uploaded.attachment_id;uploadedDrafts.current.set(item.id,attachmentId);}
            attachmentIds.push(attachmentId);
          }
          uploadingRef.current=false;setUploading(false);
        }
        await sendChatMessage(token,id,req,text,docs,attachmentIds);
      }
      sent=true;
      if(epoch.current===generation)pendingSend.current=null;
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation){
      setSentMessages(items=>items.map(item=>item.turn.request_id===req?{...item,turn:{...item.turn,status:'failed'}}:item));
      setError(errorText(e));
    }}
    finally {
      try {await refresh(id,token,generation);const items=await listConversations(token);if(epoch.current===generation)setConversations(items);}
      catch(e){if(epoch.current===generation)setError(errorText(e));}
      if(epoch.current===generation){busyRef.current=false;uploadingRef.current=false;setUploading(false);setBusy(false);}
    }
    return sent;
  };

  const startMaterialAnalysis=async(docs=attachments.map(a=>a.document_id),message=input.trim() || '请分析本次上传材料，整理就医经过、费用与待补充信息。',forceNew=false)=>{
    const id=active.current,generation=epoch.current;if(!id || busyRef.current)return;
    const previous=analysisRequest.current;
    const request=previous && previous.message===message && JSON.stringify(previous.docs)===JSON.stringify(docs)?previous:{id:requestId(),message,docs};
    analysisRequest.current=request;busyRef.current=true;setBusy(true);setAnalysisSubmitting(true);setAnalysisOpen(true);setAnalysisError('');
    try {
      await startChatAnalysis(token,id,request.id,message,docs,forceNew);
      if(epoch.current===generation){setAttachments([]);setPhotoReview(null);setInput('');analysisRequest.current=null;}
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation)setAnalysisError(errorText(e));}
    finally{
      try{await refresh(id,token,generation);}catch(e){if(epoch.current===generation)setAnalysisError(errorText(e));}
      if(epoch.current===generation){busyRef.current=false;setBusy(false);setAnalysisSubmitting(false);}
      if(epoch.current===generation)void listConversations(token).then(items=>{if(epoch.current===generation)setConversations(items);}).catch(()=>{});
    }
  };

  const upload = async(files:FileList|null) => {
    if(!files || !active.current || busyRef.current || busy || uploading)return;
    try{const selected=prepareChatFiles(files);
      setDraftFiles(current=>[...current,...selected.map(file=>({id:requestId(),file}))]);setError('');
    }catch(e){setError(errorText(e));}
    if(uploadInput.current)uploadInput.current.value='';if(photoInput.current)photoInput.current.value='';
  };
  const uploadAccepted = async(selected:File[],replaceId?:string) => {
    if(!active.current || busyRef.current || uploading)return;
    const id=active.current,generation=epoch.current;
    if(!selected.length)return;
    const previous=pendingReportUpload.current;
    const attempt=previous?.files===selected&&previous.replaceId===replaceId?previous:{files:selected,replaceId,completed:new Map<File,{document_id:string;name:string}>()};
    pendingReportUpload.current=attempt;
    uploadingRef.current=true;
    const uploaded=attachments.filter(item=>item.document_id!==replaceId);setUploading(true);setError('');setAnalysisError('');setAnalysisOpen(true);setUploadProgress({done:0,total:selected.length});
    try {
      for(const file of selected) {
        const doc=attempt.completed.get(file) || (replaceId?await replaceChatDocument(token,id,replaceId,file):await uploadChatDocument(token,id,file));
        if(epoch.current!==generation)return;
        attempt.completed.set(file,{document_id:doc.document_id,name:file.name});
        if(!uploaded.some(x=>x.document_id===doc.document_id))uploaded.push({document_id:doc.document_id,name:file.name});
        setAttachments([...uploaded]);setUploadProgress({done:selected.indexOf(file)+1,total:selected.length});
      }
      if(epoch.current===generation){pendingReportUpload.current=null;setUploadProgress(undefined);await startMaterialAnalysis(uploaded.map(a=>a.document_id));}
    } catch(e){if(!invalidateAccess(e,id,generation) && epoch.current===generation){setError(errorText(e));setAnalysisError(errorText(e));}}
    finally {if(epoch.current===generation){uploadingRef.current=false;setUploading(false);setUploadProgress(undefined);if(uploadInput.current)uploadInput.current.value='';if(photoInput.current)photoInput.current.value='';}}
  };

  const runDemo=async(file:File)=>{
    const person=viewMember?.subject_id;if(!person||busyRef.current)return;
    const generation=epoch.current;busyRef.current=true;setBusy(true);setError('');
    try{const created=await createConversation(token,requestId(),person);if(epoch.current!==generation)return;
      const document=await uploadChatDocument(token,created.conversation_id,file);if(epoch.current!==generation)return;
      await startChatAnalysis(token,created.conversation_id,requestId(),'请分析这份明确标识的合成演示材料，逐条引用依据并区分疑点与已确认事实。',[document.document_id]);
      if(epoch.current!==generation)return;setConversations(await listConversations(token));await openConversation(created.conversation_id,token,'overview');
    }catch(e){if(epoch.current===generation)setError(errorText(e));}finally{busyRef.current=false;setBusy(false);}
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
    setOlder([]);setAttachments([]);setPhotoReview(null);setEvidence(null);setError('');setPollError('');setHistoryOpen(false);pendingSend.current=null;
    setDraftFiles([]);setSentMessages([]);uploadedDrafts.current.clear();setReportUploadConversation('');pendingReportMember.current='';pendingReportUpload.current=null;
    setSubjects([]);setSubject('');setCaseInput('');setInput('');localStorage.removeItem('zhongan_last_conversation');
    ++memberEpoch.current;setClaimSubject('');setClaimDirty(false);setMembers([]);setViewSubject('');setMemberPicker(undefined);setRecordCase(undefined);
    if(memberCacheKey.current)localStorage.removeItem(memberCacheKey.current);memberCacheKey.current='';
    uploadingRef.current=false;analysisRequest.current=null;setAnalysisOpen(false);setAnalysisSubmitting(false);setUploadProgress(undefined);setAnalysisError('');
    setDelivery(null);setFeedbackNotice('');careKeys.current.clear();
    busyRef.current=false;setBusy(false);setUploading(false);setLoadingConversation(false);setPanel('home');
  };
  const signOut=async()=>{
    try {await revokeSession(token);logout();}
    catch(e){setError(errorText(e));}
  };
  const savedTurns=[...older,...(snapshot?.turns || [])].filter((t,i,all)=>all.findIndex(x=>x.turn_id===t.turn_id)===i);
  const turns=[...savedTurns,...sentMessages.filter(item=>!savedTurns.some(t=>t.request_id===item.turn.request_id)).map(item=>item.turn)];
  const latestAnswered=[...turns].reverse().find(t=>t.status==='completed'&&t.answer)?.turn_id;
  const narrative=currentNarrative(turns,snapshot?.analysis.run_id);
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
      <button className="new-chat new-report" disabled={working} onClick={()=>{setHistoryOpen(false);setMemberPicker('report');}}>＋ 新建解读报告</button>
      <button className="new-chat" disabled={working} onClick={()=>requestBusiness('chat')}>＋ 新建对话</button>
      <div className="history-list"><p>以前的对话</p>{conversations.length===0 && <p>还没有历史对话</p>}{conversations.map(c=><button disabled={working} key={c.conversation_id}
        className={active.current===c.conversation_id?'selected':''} onClick={()=>void openConversation(c.conversation_id,token,'chat')}>
        <strong title={c.title}>{c.title}</strong><span className="history-item-meta">{c.has_interpretation_report&&<span className="history-report-badge">解读报告</span>}<small>{new Date(c.updated_at).toLocaleDateString('zh-CN')}</small></span></button>)}</div>
      <button className="quiet-button" disabled={working} onClick={()=>void signOut()}>退出登录</button>
    </aside>;

  return <SourceToken.Provider value={token}><div className={`chat-shell ${panel==='chat'?'chat-view':''}`}>
    {connected && panel==='chat' && (mobileHistory ? historyOpen && <dialog id="history-dialog" ref={historyDialog} className="history-drawer" aria-label="历史对话"
      onKeyDown={e=>{if(e.key!=='Tab')return;const buttons=Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));const first=buttons[0],last=buttons.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}
      onCancel={e=>{e.preventDefault();setHistoryOpen(false);}} onClick={e=>{if(e.target===e.currentTarget)setHistoryOpen(false);}}>{historyPanel}</dialog> : historyPanel)}
    <section className={`chat-workspace ${panel==='chat'?'chat-original':''}`}>
      {connected && panel==='chat' && <div className="chat-page-actions">
        {mobileHistory && <button ref={historyTrigger} className="history-trigger" aria-haspopup="dialog" aria-controls="history-dialog" aria-expanded={historyOpen} onClick={()=>setHistoryOpen(true)}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 8a8 8 0 1 1-1 7M4 3v5h5"/><path d="M12 7v5l3 2"/></svg>历史对话</button>}
        <div className="nuan-header-identity"><strong>暖暖</strong><span>你的就医关怀助手</span></div>
        {snapshot && (publishedCare(snapshot.report) || narrative) && <button className="chat-guide-entry" onClick={()=>narrative?openNarrative():openReport()}>{narrative?'材料解读':'关怀指引'}</button>}
      </div>}
      {connected && !needsProfile && ['chat','report','overview'].includes(panel) && snapshot && <div className="member-identity">当前对话所属：{members.find(member=>member.subject_id===snapshot.conversation.subject_id)?.name||'当前人员'}</div>}
      {delivery && snapshot?.report.report_id===delivery.report_id && <div className="analysis-status care-notice" role="status">{delivery.message}
        {delivery.receipt_state==='read' ? <span>已查看</span> : <button onClick={()=>openReport()}>查看指引</button>}</div>}
      {(error || pollError) && <div role="alert" className="chat-error persistent-error">{error || pollError}<button aria-label="关闭提示" onClick={()=>{setError('');setPollError('');}}>×</button></div>}
      <PageBoundary resetKey={`${panel}:${snapshot?.conversation.conversation_id || ''}`}>
      {connected && !needsProfile && claimSubject && <div className="claim-panel" hidden={panel!=='claim'}><ClaimIntake key={`${token}:${claimSubject}`} token={token} sampleRequest={judgeSampleRequest?.subjectId===claimSubject?judgeSampleRequest:undefined} onDirty={setClaimDirty} subject={subjects.some(item=>item.subject_id===claimSubject)?claimSubject:''} visible={panel==='claim'} onExit={()=>setPanel('home')} onAuthorize={()=>setConsentMember(claimSubject)} onOpen={async (id,report=false)=>{
          const generation=epoch.current;const items=await listConversations(token);
          if(epoch.current!==generation)return;setConversations(items);await openConversation(id,token,'chat',true);if(report)openReport();}}/></div>}
      {!connected ? token ? <main className="start-screen" role="status"><h1>{busy?'正在连接服务…':'服务暂时不可用'}</h1><p>登录状态已保留，恢复连接后可继续。</p><button className="care-primary" disabled={busy} onClick={()=>void connect(token)}>{busy?'正在连接…':'重新连接'}</button></main> : <AuthPage onAuthenticated={auth=>connect(auth,true)}/>
      : needsProfile && selfMember ? <main className="member-onboarding"><MemberEditor token={token} member={selfMember} onboarding onSaved={memberSaved}/></main>
      : panel==='claim' ? claimSubject ? null : <main className="original-chat-start member-choice-page"><section className="member-start-card"><h1>选择就医资料所属人员</h1><p>为本人或家人提交材料，暖暖会分别整理。</p><button className="member-primary" onClick={()=>requestBusiness('claim')}>选择人员</button></section></main>
      : panel==='account' && viewMember ? <AccountPage key={viewMember.subject_id} token={token} members={members} member={viewMember}
          onSelect={selectViewMember} onSaved={memberSaved} onRecords={caseId=>{setRecordCase(caseId);setPanel('records');}}
          onNew={()=>requestBusiness('claim',viewMember.subject_id)} onLogout={signOut}/>
      : loadingConversation ? <main className="start-screen" role="status"><h1>正在打开就医记录…</h1></main>
      : panel==='records' && viewMember ? <PersonalRecords key={viewMember.subject_id} token={token} member={viewMember} selected={recordCase} onSelect={setRecordCase}
          currentCase={snapshot?.conversation.case_id} busy={working} onOpen={id=>void openConversation(id,token,'chat')}
          onNew={()=>requestBusiness('claim',viewMember.subject_id)} onAccount={()=>setPanel('account')}/>
      : panel==='demo' ? <DemoShowcase token={token} busy={working} canRun={subjects.some(s=>s.subject_id===viewMember?.subject_id)} onRun={file=>void runDemo(file)} onBack={()=>setPanel('home')}/>
      : panel==='home' ? <DemoHome token={token} member={viewMember} onOpen={(id,destination,section)=>{
          void openConversation(id,token,destination).then(()=>{if(active.current===id)setReportFocus(section);});
        }} onClaim={()=>requestBusiness('claim')} onJudgeExperience={startJudgeExperience} disabled={working}/>
      : !snapshot ? <main className="original-chat-start"><OriginalChatWelcome/><div className="nuan-message"><span className="nuan-avatar" aria-hidden="true">✦</span><div className="nuan-message-body"><p>你好，我是暖暖。你现在有什么想说的，我愿意听。想聊聊身体上的不舒服、心里的牵挂，或一起看看材料，都可以按你的节奏来。</p></div></div>
        <button className="claim-entry-link" onClick={()=>requestBusiness('claim')}>整理理赔资料，开启专属关怀</button>
        <div className="connect-form member-start-card"><label>咨询对象<select value={subject} onChange={e=>setSubject(e.target.value)}><option value="">请选择人员</option>
          {members.map(member=><option key={member.subject_id} value={member.subject_id}>{member.name}{subjects.some(item=>item.subject_id===member.subject_id)?'':'（待授权）'}</option>)}</select></label>
          <button disabled={busy || !subjects.some(item=>item.subject_id===subject)} onClick={()=>void newChat()}>{busy?'正在打开…':'开始新的对话'}</button>
          {subject&&!subjects.some(item=>item.subject_id===subject)&&<><small>请先确认该人员的关怀资料授权。</small><button onClick={()=>setConsentMember(subject)}>确认资料用途</button></>}</div></main>
      : panel==='overview' ? <EncounterOverview key={`${snapshot.conversation.case_id}:${snapshot.analysis.run_id}`} onBack={openNarrative} token={token} snapshot={snapshot} person={members.find(m=>m.subject_id===snapshot.conversation.subject_id)?.name||'当前人员'} onEvidence={id=>void showEvidence(id)} onAsk={text=>{setInput(text);setPanel('chat');}} onUpload={()=>{setPanel('chat');setInput('我需要补充本次就医材料。');}} onReplace={(documentId,file)=>setPhotoReview({files:[file],conversationId:snapshot.conversation.conversation_id,replaceId:documentId})} onReport={openReport} onRefresh={()=>{setPanel('chat');void startMaterialAnalysis([], '请重新分析本次材料，并为每条结论标明准确来源。',true);}}/>
      : panel==='report' ? <main className="chat-report"><h1>本次关怀指引</h1>
          {publishedCare(snapshot.report) ? <><p className="care-report-version">第 {snapshot.report.report_version} 版 · 已审核发布</p>
            <CareReport report={snapshot.report} initialSection={reportFocus} onEvidence={id=>void showEvidence(id)} disabled={working} onServiceAsk={message=>{setPanel('chat');return send(undefined,message);}}/>
            {snapshot.report.report_id && <div className="report-feedback"><p>这份指引对你有帮助吗？</p>
              <button disabled={feedbackBusy} onClick={()=>void feedback('helpful')}>有帮助</button>
              <button disabled={feedbackBusy} onClick={()=>void feedback('not_helpful')}>还不够清楚</button>
              <button disabled={feedbackBusy} onClick={()=>void feedback('inaccurate')}>内容需要核实</button>
              <button disabled={feedbackBusy} onClick={()=>void feedback('needs_help')}>我需要帮助</button>
              {feedbackNotice && <p role="status">{feedbackNotice}</p>}</div>}</>
          : <div className="empty-report"><p>暖暖会在对话里结合材料为你解释。</p>
            <button onClick={()=>setPanel('chat')}>回到对话</button></div>}</main>
      : <><main className="chat-scroll inline-report-thread"><OriginalChatWelcome/>
        {(snapshot.analysis.run_id || analysisSubmitting || uploadProgress || analysisError) && !narrative && <button className="analysis-card" onClick={()=>setAnalysisOpen(true)}><span className="analysis-card-icon" aria-hidden="true">✦</span><span className="analysis-card-copy"><strong>{progressView.title}</strong><small>{`${progressView.detail}${progressView.percent!==null?` · ${progressView.percent}%`:''}`}</small></span><span className="analysis-card-arrow" aria-hidden="true">›</span></button>}
        {hasOlder && turns.length>0 && <button className="load-history" onClick={()=>void loadOlder()}>查看更早的聊天</button>}
        <div className="nuan-chat-heading"><span><DemoIcon name="chat"/>和暖暖聊聊</span><small>有疑问，接着问</small></div>
        <div className="messages">{turns.length===0 && <div className="message-row assistant"><div className="avatar">✦</div><div className="message-bubble"><div className="nuan-reply-label"><DemoIcon name="leaf"/>暖暖</div><p>你好，我是暖暖。你可以从最想说的事情聊起，不用一下子把所有事情讲清楚。如果有看不懂的病历或发票，我也会陪你一点点看。</p></div></div>}
          {turns.map(t=><div className="chat-turn" key={t.turn_id} id={`turn-${t.turn_id}`}>
            {t.input_kind==='analysis_ready' ? <p className="analysis-continuation">材料已整理 · 暖暖为你解读</p> : isClaimSubmission(t) ? <p className="analysis-continuation">材料已提交 · 暖暖为你整理</p> : <div className="message-row user"><div className="message-bubble"><p>{t.question}</p>
            {sentMessages.find(item=>item.turn.request_id===t.request_id)?.files.length ? <ChatSentAttachments files={sentMessages.find(item=>item.turn.request_id===t.request_id)!.files}/> : t.attachments.map(a=><span className="attachment" key={a.document_id}>▤ {a.name}</span>)}</div></div>}
            <div className="message-row assistant"><span className="nuan-avatar" aria-hidden="true">✦</span><div className={`message-bubble ${t.input_kind==='analysis_ready'?'narrative-bubble':''}`}><div className="nuan-reply-label"><DemoIcon name="leaf"/>暖暖{t.input_kind==='analysis_ready' && <span>· 材料解读</span>}</div>{t.input_kind!=='analysis_ready' && <ToolActivity events={t.tool_events}/>}
              {t.answer ? <>{t.input_kind==='analysis_ready'?<AnalysisNarrative turn={t} onEvidence={id=>void showEvidence(id)} onServiceAsk={message=>send(undefined,message)} disabled={working}/>:<><p><CitedText text={t.answer.text} citations={t.answer.citations} sources={t.answer.knowledge_sources} onEvidence={id=>void showEvidence(id)}/></p></>}

                {t.answer.medical_services&&<MedicalServiceCards services={t.answer.medical_services} onAsk={message=>send(undefined,message)} disabled={working} canAskForLocation={t.turn_id===latestAnswered}/>}
                {!!t.answer.patient_updates?.length&&<small className="patient-update-notice">已记录你的补充 · 作为用户自述供后续交流参考</small>}
                {t.status==='completed'&&t.turn_id===latestAnswered&&<ChatFollowups answer={t.answer} disabled={working} onSend={message=>send(undefined,message)}/>}</>
                : t.status==='failed' ? <><p>{t.turn_id.startsWith('local:')?'这次消息没有发送成功，可以重试。':'这次回答没有完成，你的消息已保存。'}</p><button disabled={working} onClick={()=>void send(t)}>重试这条消息</button></>
                : <p role="status">{t.input_kind==='analysis_ready'?'材料已经整理好，暖暖正在结合你的资料写解读…':'暖暖正在认真看你说的话…'}</p>}
            </div></div></div>)}
        </div><div ref={bottom}/></main>
        <footer className="chat-footer">
          <ChatDraftAttachments files={draftFiles} busy={working} onRemove={id=>{setDraftFiles(current=>current.filter(file=>file.id!==id));uploadedDrafts.current.delete(id);}}/>
          <form className="composer" onSubmit={submit}>
            <input ref={uploadInput} aria-label="选择文档文件" hidden type="file" multiple onChange={e=>void upload(e.target.files)}/>
            <input ref={photoInput} aria-label="选择照片或图片" hidden type="file" multiple accept="image/jpeg,image/png" onChange={e=>void upload(e.target.files)}/>
            <details ref={uploadMenu} className="chat-upload-menu" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))e.currentTarget.open=false;}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.currentTarget.open=false;e.currentTarget.querySelector('summary')?.focus();}}}>
              <summary title="上传病历或发票" aria-label="上传病历或发票" aria-disabled={working} onClick={e=>{if(working)e.preventDefault();}}>＋</summary>
              <div className="chat-upload-options" aria-label="选择上传方式"><div className="upload-panel-heading"><p>添加图片或文件</p><small>选好后可补充问题，一起发送</small></div>
                <button className="upload-source-photo" type="button" aria-label="照片或图片" aria-describedby="upload-photo-hint" disabled={working} onClick={()=>{if(uploadMenu.current)uploadMenu.current.open=false;photoInput.current?.click();}}><span className="upload-source-icon"><UploadSourceIcon kind="image"/></span><span className="upload-source-copy"><strong>照片或图片</strong><small id="upload-photo-hint">从相册选择 · JPG、PNG</small></span><DemoIcon name="arrow"/></button>
                <button className="upload-source-document" type="button" aria-label="PDF / TXT 文件" aria-describedby="upload-document-hint" disabled={working} onClick={()=>{if(uploadMenu.current)uploadMenu.current.open=false;uploadInput.current?.click();}}><span className="upload-source-icon"><UploadSourceIcon kind="document"/></span><span className="upload-source-copy"><strong>PDF / TXT 文件</strong><small id="upload-document-hint">从文件中选择病历或票据</small></span><DemoIcon name="arrow"/></button>
                <small className="upload-panel-note"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true"><path d="M8 12v5a4 4 0 0 0 8 0V7a3 3 0 0 0-6 0v10a1 1 0 0 0 2 0V9"/></svg>支持多选 · 每份不超过 10MB</small>
              </div>
            </details>
            <textarea aria-label="给暖暖的消息" value={input} disabled={working} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}} rows={1} placeholder={draftFiles.length?'补充你想问的问题，和附件一起发送':'有哪里不清楚？问问暖暖'}/>
            <button className="send-button" aria-label="发送消息" disabled={working || (!input.trim()&&!draftFiles.length)}>{uploading?'…':busy?'…':<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6"/></svg>}</button>
          </form>
        </footer></>}
      </PageBoundary>
      {connected && snapshot && <AnalysisFlow open={analysisOpen && ['chat','report','overview'].includes(panel)} snapshot={analysisSubmitting || uploadProgress?null:snapshot} upload={uploadProgress} submitting={analysisSubmitting} error={analysisError} onClose={()=>setAnalysisOpen(false)} onReport={openNarrative} onRetry={()=>{if(pendingReportUpload.current)void uploadAccepted(pendingReportUpload.current.files,pendingReportUpload.current.replaceId);else if(material?.status==='available' && snapshot.analysis.run_id)void completeNarrative(active.current,epoch.current,snapshot.analysis.run_id);else void startMaterialAnalysis();}}/>}
      {connected && !needsProfile && panel!=='claim' && <nav className="care-navigation" aria-label="关怀页面"><button aria-current={panel==='home'?'page':undefined} onClick={()=>setPanel('home')}><DemoIcon name="leaf"/>首页</button>
        <button aria-current={panel==='chat'?'page':undefined} onClick={()=>snapshot?setPanel('chat'):requestBusiness('chat')}><DemoIcon name="chat"/>问暖暖</button>
        <button aria-current={['account','records'].includes(panel)?'page':undefined} onClick={()=>setPanel('account')}><DemoIcon name="user"/>我的</button>
        </nav>}
    </section>
    {connected && consentMember && members.find(m=>m.subject_id===consentMember) && <MemberConsentDialog key={consentMember} token={token} member={members.find(m=>m.subject_id===consentMember)!} onClose={()=>{setConsentMember(undefined);pendingReportMember.current='';}} onChanged={refreshAccess}/>}
    {connected && !needsProfile && memberPicker && <MemberPicker members={members} title={memberPicker==='report'?'选择解读报告所属人员':memberPicker==='claim'?'选择就医资料所属人员':'选择对话所属人员'} onSelect={chooseBusinessMember} onClose={()=>setMemberPicker(undefined)}/>}
    {connected&&snapshot&&reportUploadConversation===snapshot.conversation.conversation_id&&<ReportUploadDialog person={members.find(member=>member.subject_id===snapshot.conversation.subject_id)?.name||'当前人员'} onClose={()=>setReportUploadConversation('')} onSubmit={files=>{
      setReportUploadConversation('');
      if(files.some(file=>file.type.startsWith('image/')))setPhotoReview({files,conversationId:snapshot.conversation.conversation_id});
      else void uploadAccepted(files);
    }}/>}
    {photoReview&&snapshot&&photoReview.conversationId===snapshot.conversation.conversation_id&&<PhotoReview key={photoReview.conversationId} token={token} subjectId={snapshot.conversation.subject_id} files={photoReview.files} onCancel={()=>setPhotoReview(null)} onContinue={files=>{const replaceId=photoReview.replaceId;setPhotoReview(null);setPanel('chat');void uploadAccepted(files,replaceId);}}/>}
    {evidence && <EvidencePanel token={token} evidence={evidence} onClose={()=>setEvidence(null)}/>}
  </div></SourceToken.Provider>;
}
