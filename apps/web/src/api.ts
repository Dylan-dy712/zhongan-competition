import type { AssistantAnswer, Evidence, Report, Conversation, ChatSnapshot, ChatSubject, ChatTurn,
  DeliveryNotice, DeliveryReceipt, FeedbackType, FeedbackResult,
  RecommendationResponse } from "./types";
import type {SessionResponse,ConsentResponse,MemberInput,MemberResponse} from './api/generated/accounts';
export type {MemberInput,MemberResponse} from './api/generated/accounts';
import {conversationTitle} from './claimChatPresentation';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export type JudgeSample = {sample_id:string;version:string;title:string;summary:string;notice:string;data_origin:'official_deidentified';file_count:number;page_count:number;claim_info:Partial<import('./claimTemplate').ClaimForm>;documents:{id:string;name:string;page_count:number;document_type:string;sha256:string;media_type?:string;byte_size?:number}[]};
export type JudgeSampleFile = {file:File;category:'record'|'invoice';documentId:string;originalSize?:number};
const preparedSampleFiles=new Map<string,JudgeSampleFile>();
export async function getJudgeSample(token:string):Promise<JudgeSample|null> {
  const response=await apiFetch(`${API_BASE}/judge/sample`,{headers:{Authorization:`Bearer ${token}`}});
  if([403,404].includes(response.status))return null;
  const value=await response.json().catch(()=>null);
  if(!response.ok)throw new ApiError(value?.detail || value?.message || failureMessage(response.status),response.status);
  if(!value||!Array.isArray(value.documents)||typeof value.sample_id!=='string')return null;
  return value;
}
export async function getJudgeSampleOriginal(token:string,sample:JudgeSample,id:string,preview=false):Promise<File> {
  const item=sample.documents.find(d=>d.id===id);if(!item)throw new Error('示例资料不存在。');
  for(let attempt=0;;attempt++)try{
    const response=await apiFetch(`${API_BASE}/judge/sample/files/${encodeURIComponent(id)}?version=${encodeURIComponent(sample.version)}&sample_id=${encodeURIComponent(sample.sample_id)}${preview?'&preview=true':''}`,{headers:{Authorization:`Bearer ${token}`}},120000);
    if(!response.ok){const error=await response.json().catch(()=>null);throw new ApiError(error?.detail || failureMessage(response.status),response.status);}
    const data=await response.arrayBuffer(),type=response.headers.get('Content-Type')?.split(';')[0]||item.media_type||'application/pdf',bytes=new Uint8Array(data);
    const valid=type==='application/pdf'?String.fromCharCode(...bytes.slice(0,5))==='%PDF-':type==='image/png'?[137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v):type==='image/jpeg'&&bytes[0]===255&&bytes[1]===216&&bytes[2]===255&&bytes.at(-2)===255&&bytes.at(-1)===217;
    if(!data.byteLength||data.byteLength>10*1024*1024||!valid)throw new Error('示例文件暂时不可用，请重新选择。');
    return new File([data],item.name,{type});
  }catch(error){
    if(error instanceof ApiError||attempt===2)throw error instanceof Error&&['TimeoutError','AbortError'].includes(error.name)?new Error('示例资料载入超时，请重新准备，已完成的资料会保留。'):error;
    await new Promise(resolve=>setTimeout(resolve,(attempt+1)*500));
  }
}
export async function chooseJudgeSampleFiles(token:string,sample:JudgeSample,onProgress?:(completed:number,total:number)=>void):Promise<JudgeSampleFile[]> {
  let next=0,completed=0;const results:JudgeSampleFile[]=new Array(sample.documents.length);
  await Promise.all(Array.from({length:Math.min(3,sample.documents.length)},async()=>{
    while(next<sample.documents.length){
      const index=next++,item=sample.documents[index],key=JSON.stringify([token,sample.sample_id,sample.version,item.id,item.sha256]);
      let value=preparedSampleFiles.get(key);
      if(!value){
        const file=await getJudgeSampleOriginal(token,sample,item.id,item.media_type?.startsWith('image/'));
        value={file,documentId:item.id,originalSize:item.byte_size,category:['费用清单','医保结算单','医疗发票'].includes(item.document_type)?'invoice':'record'};
        preparedSampleFiles.set(key,value);if(preparedSampleFiles.size>60)preparedSampleFiles.delete(preparedSampleFiles.keys().next().value!);
      }
      results[index]=value;onProgress?.(++completed,sample.documents.length);
    }
  }));
  return results;
}
export async function attachJudgeSampleDocument(token:string,id:string,sample:JudgeSample,documentId:string):Promise<{document_id:string;source_ref:string}> {
  for(let attempt=0;;attempt++)try{
    return await chatRequest(`/v1/conversations/${id}/sample-documents`,token,'POST',{sample_id:sample.sample_id,version:sample.version,sample_document_id:documentId});
  }catch(error){
    if(attempt===2||(error instanceof ApiError&&![502,503,504].includes(error.status)))throw error;
    await new Promise(resolve=>setTimeout(resolve,(attempt+1)*500));
  }
}
export async function createJudgeSampleUploadCase(token:string,subjectId:string,sample:JudgeSample,key:string) {
  const consent=await getCareConsent(token,subjectId);
  if(consent.status!=='active'||!consent.consent_id)throw new Error('请先确认资料用途授权。');
  return chatRequest<{case_id:string}>('/v1/cases',token,'POST',{
    subject_id:subjectId,consent_id:consent.consent_id,source_ref:`judge-upload-sample:${sample.sample_id}`,
    data_origin:sample.data_origin,user_context:{judge_demo:true,sample_id:sample.sample_id,sample_version:sample.version,notice:sample.notice}
  },key);
}

export async function authenticate(mode:'login'|'register',body:unknown):Promise<SessionResponse> {
  const response=await apiFetch(`${API_BASE}/v1/auth/${mode}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json().catch(()=>null);
  if(!response.ok)throw new ApiError(response.status===422?'请检查手机号、密码和授权信息。':result?.message || failureMessage(response.status),response.status);
  return result;
}

export async function revokeSession(token:string) {
  const response=await apiFetch(`${API_BASE}/v1/auth/logout`,{method:'POST',headers:{Authorization:`Bearer ${token}`}});
  if(!response.ok && response.status!==401)throw new Error('退出登录失败，请重试。');
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public traceId?: string) { super(message); }
}

async function apiFetch(url:string,options:RequestInit,timeoutMs?:number):Promise<Response> {
  const readOnly=!options.method || options.method==='GET';
  for(let attempt=0;;attempt++) {
    try {
      const response=await fetch(url,{...options,signal:AbortSignal.timeout(timeoutMs ?? (readOnly?15000:120000))});
      if(!readOnly || ![502,503,504].includes(response.status) || attempt===2)return response;
      await response.body?.cancel().catch(()=>{});
    } catch(e) {
      if(!readOnly || attempt===2){
        if(e instanceof Error && ['TimeoutError','AbortError'].includes(e.name))throw new Error('连接超时，请稍后重试。');
        throw e;
      }
    }
    await new Promise(resolve=>setTimeout(resolve,attempt===0?500:1500));
  }
}
function failureMessage(status:number){return [502,503,504].includes(status)?'服务暂时不可用，请稍后重试。':`请求失败（${status}）`;}

async function request<T>(path: string, token: string): Promise<T> {
  const response = await apiFetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(detail?.message || failureMessage(response.status), response.status, detail?.trace_id);
  }
  return response.json() as Promise<T>;
}

export const getReport = (caseId: string, version: number, token: string) =>
  request<Report>(`/v1/cases/${encodeURIComponent(caseId)}/reports/${version}`, token);

export const getEvidence = (evidenceId: string, token: string) =>
  request<Evidence>(`/v1/evidence/${encodeURIComponent(evidenceId)}`, token);

export async function askAssistant(caseId: string, reportVersion: number, question: string, token: string) {
  const response = await apiFetch(`${API_BASE}/v1/cases/${encodeURIComponent(caseId)}/assistant/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ question, report_version: reportVersion })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(detail?.message || failureMessage(response.status), response.status, detail?.trace_id);
  }
  return response.json() as Promise<AssistantAnswer>;
}

async function chatRequest<T>(path: string, token: string, method = 'GET', data?: unknown, idempotencyKey?:string,timeoutMs?:number): Promise<T> {
  const multipart = data instanceof FormData;
  const response = await apiFetch(`${API_BASE}${path}`, {
    method,
    headers: {Authorization: `Bearer ${token}`, ...(!multipart && data !== undefined ? {'Content-Type':'application/json'} : {}),
      ...(idempotencyKey ? {'Idempotency-Key':idempotencyKey} : {})},
    body: data === undefined ? undefined : multipart ? data : JSON.stringify(data),
  },timeoutMs);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(detail?.message || failureMessage(response.status), response.status, detail?.trace_id);
  }
  return response.json() as Promise<T>;
}
const presentConversation=(conversation:Conversation):Conversation=>({...conversation,title:conversationTitle(conversation.title)});
export const listConversations = async(token: string,subjectId?:string) =>
  (await chatRequest<Conversation[]>(`/v1/conversations${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:''}`, token)).map(presentConversation);
export const listMedicalRecords=async(token:string,subjectId:string)=>{
  const result=await chatRequest<import('./types').MedicalRecordsResponse>(`/v1/medical-records?subject_id=${encodeURIComponent(subjectId)}`,token);
  return {...result,records:result.records.map(record=>({...record,title:conversationTitle(record.title),
    related_records:record.related_records.map(link=>({...link,title:conversationTitle(link.title)})),
    cases:record.cases.map(batch=>({...batch,proposal_title:batch.proposal_title?conversationTitle(batch.proposal_title):batch.proposal_title,
      conversations:batch.conversations.map(presentConversation)}))}))};
};
export const organizeMedicalRecords=(token:string,subjectId:string)=>chatRequest<{queued_count:number}>('/v1/medical-records/organize',token,'POST',{subject_id:subjectId});
export const changeMedicalRecord=(token:string,caseId:string,body:{mode:'join'|'separate'|'related';target_record_id?:string;expected_version:number})=>
  chatRequest<{version:number}>(`/v1/medical-records/cases/${encodeURIComponent(caseId)}`,token,'PATCH',body);
export const listMembers=(token:string)=>chatRequest<MemberResponse[]>('/v1/me/members',token);
export const saveMember=(token:string,body:MemberInput,subjectId?:string)=>chatRequest<MemberResponse>(
  `/v1/me/members${subjectId?`/${encodeURIComponent(subjectId)}`:''}`,token,subjectId?'PATCH':'POST',body);
export const listDeliveries = (token:string,caseId:string) =>
  chatRequest<DeliveryNotice[]>(`/v1/cases/${caseId}/deliveries`,token);
export const recordDeliveryReceipt = (token:string,id:string,state:'presented'|'read',version:number,key:string) =>
  chatRequest<DeliveryReceipt>(`/v1/deliveries/${id}/receipts`,token,'POST',{state,expected_version:version},key);
export const submitCareFeedback = (token:string,reportId:string,version:number,type:FeedbackType,key:string) =>
  chatRequest<FeedbackResult>('/v1/feedback',token,'POST',{report_id:reportId,report_version:version,type},key);
export const listSubjects = (token: string) => chatRequest<ChatSubject[]>('/v1/chat/subjects', token);
export const startChatAnalysis = (token:string,id:string,requestId:string,message:string,documentIds:string[]=[],forceNew=false) =>
  chatRequest<{turn_id:string}>(`/v1/conversations/${id}/analyses`,token,'POST',{request_id:requestId,message,document_ids:documentIds,force_new:forceNew});
export const createConversation = (token: string, conversationId: string, subjectId?: string, caseId?: string) =>
  chatRequest<Conversation>('/v1/conversations', token, 'POST', {conversation_id:conversationId, subject_id:subjectId || null, case_id:caseId || null,recall_enabled:false});

export type CareConsent=ConsentResponse;
export const getCareConsent=(token:string,subjectId?:string)=>chatRequest<CareConsent>(`/v1/me/consents${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:''}`,token);
export const changeCareConsent=(token:string,confirmation:boolean,expected_version:number,subjectId?:string)=>
  chatRequest<CareConsent>(`/v1/me/consents${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:''}`,token,'POST',{confirmation,expected_version},
    Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''));
export const getConversation = async(token: string, id: string) => {
  const result=await chatRequest<ChatSnapshot>(`/v1/conversations/${id}`, token);
  return {...result,conversation:presentConversation(result.conversation)};
};
export const getOlderTurns = (token: string, id: string, before: string) =>
  chatRequest<ChatTurn[]>(`/v1/conversations/${id}/turns?before=${encodeURIComponent(before)}`, token);
export const sendChatMessage = (token: string, id: string, requestId: string, message: string, documentIds: string[],attachmentIds:string[]=[]) =>
  chatRequest(`/v1/conversations/${id}/messages`, token, 'POST', {request_id:requestId, message, document_ids:documentIds,attachment_ids:attachmentIds});
export const uploadChatAttachment=(token:string,id:string,file:File)=>{
  const data=new FormData();data.append('file',file);
  return chatRequest<{attachment_id:string;name:string}>(`/v1/conversations/${id}/attachments`,token,'POST',data);
};
export const continueAnalysis = (token: string, id: string, runId: string) =>
  chatRequest(`/v1/conversations/${id}/analyses/${runId}/continue`, token, 'POST',undefined,undefined,450000);
export const setRecall = (token: string, id: string, enabled: boolean) =>
  chatRequest(`/v1/conversations/${id}/recall`, token, 'PATCH', {enabled});
export const setReportContext = (token:string,id:string,enabled:boolean) =>
  chatRequest(`/v1/conversations/${id}/report-context`,token,'PATCH',{enabled});
export const uploadChatDocument = (token: string, id: string, file: File) => {
  const data = new FormData(); data.append('file', file);
  return chatRequest<{document_id:string; source_ref:string}>(`/v1/conversations/${id}/documents`, token, 'POST', data);
};
export const requestRecommendations = (token: string, body: {disease_group: string; treatment_group: string;
  risk_group: string | null; payer_group: string | null;
  needs: {need_id: string; metric_name: string}[]},demo=false) =>
  chatRequest<RecommendationResponse>(demo?'/v1/quality/demo/recommendations':'/v1/quality/recommendations', token, 'POST', body);

export const inspectPhoto=(token:string,subjectId:string,file:File)=>{
  const data=new FormData();data.append('file',file);data.append('subject_id',subjectId);
  return chatRequest<import('./types').PhotoQuality>('/v1/materials/inspect',token,'POST',data,undefined,120000);
};
export const getFacts=(token:string,caseId:string,runId:string)=>chatRequest<import('./types').ExtractedFact[]>(`/v1/cases/${encodeURIComponent(caseId)}/facts?run_id=${encodeURIComponent(runId)}`,token);
export const getInsights=(token:string,caseId:string,runId:string)=>chatRequest<import('./types').Insight[]>(`/v1/cases/${encodeURIComponent(caseId)}/insights?run_id=${encodeURIComponent(runId)}`,token);
export const getKnowledgeSource=(token:string,id:string)=>chatRequest<import('./types').KnowledgeSource>(`/v1/knowledge/${encodeURIComponent(id)}`,token);
export const listQualitySnapshots=(token:string)=>chatRequest<{snapshot_id:string}[]>('/v1/quality/snapshots',token);
export const getQualitySnapshot=(token:string,id:string)=>chatRequest<import('./types').QualitySnapshot>(`/v1/quality/snapshots/${encodeURIComponent(id)}`,token);
export async function getEvidenceImage(token:string,evidence:import('./types').Evidence){
  const path=`/v1/evidence/${encodeURIComponent(evidence.evidence_id)}/page-image`;
  const response=await apiFetch(`${API_BASE}${path}`,{headers:{Authorization:`Bearer ${token}`}});
  if(!response.ok)throw new ApiError('原图暂不可用',response.status);
  const candidates:unknown=JSON.parse(response.headers.get('X-Evidence-Regions')||'[]');
  const regions:Array<[number,number,number,number]>=Array.isArray(candidates)?candidates.filter((box):box is [number,number,number,number]=>
    Array.isArray(box)&&box.length===4&&box.every(value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1)
    &&box[0]<box[2]&&box[1]<box[3]):[];
  return {url:URL.createObjectURL(await response.blob()),regions};
}

export const getDemoQuality=(token:string)=>chatRequest<import('./types').QualitySnapshot>('/v1/quality/demo',token);

export const getMaterialQuality=(token:string,caseId:string,runId:string)=>chatRequest<MaterialQuality[]>(`/v1/cases/${encodeURIComponent(caseId)}/material-quality?run_id=${encodeURIComponent(runId)}`,token);
export interface MaterialQuality {document_id:string;name:string;page_index:number;quality:{material_type:string;type_certainty:string;uncertain_lines:number;readable_lines:number;needs_reupload:boolean}}
export const replaceChatDocument=(token:string,conversationId:string,documentId:string,file:File)=>{
 const data=new FormData();data.append('file',file);
 return chatRequest<{document_id:string;source_ref:string}>(`/v1/conversations/${encodeURIComponent(conversationId)}/documents/${encodeURIComponent(documentId)}/replacement`,token,'POST',data);
};
