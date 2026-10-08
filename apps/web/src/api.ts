import type { AssistantAnswer, Evidence, Report, Conversation, ChatSnapshot, ChatSubject, ChatTurn,
  DeliveryNotice, DeliveryReceipt, FeedbackType, FeedbackResult,
  RecommendationResponse } from "./types";
import type {SessionResponse,ConsentResponse,MemberInput,MemberResponse} from './api/generated/accounts';
export type {MemberInput,MemberResponse} from './api/generated/accounts';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

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
export const listConversations = (token: string,subjectId?:string) => chatRequest<Conversation[]>(`/v1/conversations${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:''}`, token);
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
export const startChatAnalysis = (token:string,id:string,requestId:string,message:string,documentIds:string[]=[]) =>
  chatRequest<{turn_id:string}>(`/v1/conversations/${id}/analyses`,token,'POST',{request_id:requestId,message,document_ids:documentIds});
export const createConversation = (token: string, conversationId: string, subjectId?: string, caseId?: string) =>
  chatRequest<Conversation>('/v1/conversations', token, 'POST', {conversation_id:conversationId, subject_id:subjectId || null, case_id:caseId || null,recall_enabled:false});

export type CareConsent=ConsentResponse;
export const getCareConsent=(token:string,subjectId?:string)=>chatRequest<CareConsent>(`/v1/me/consents${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:''}`,token);
export const changeCareConsent=(token:string,confirmation:boolean,expected_version:number,subjectId?:string)=>
  chatRequest<CareConsent>(`/v1/me/consents${subjectId?`?subject_id=${encodeURIComponent(subjectId)}`:''}`,token,'POST',{confirmation,expected_version},
    Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''));
export const getConversation = (token: string, id: string) => chatRequest<ChatSnapshot>(`/v1/conversations/${id}`, token);
export const getOlderTurns = (token: string, id: string, before: string) =>
  chatRequest<ChatTurn[]>(`/v1/conversations/${id}/turns?before=${encodeURIComponent(before)}`, token);
export const sendChatMessage = (token: string, id: string, requestId: string, message: string, documentIds: string[]) =>
  chatRequest(`/v1/conversations/${id}/messages`, token, 'POST', {request_id:requestId, message, document_ids:documentIds});
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
  needs: {need_id: string; metric_name: string}[]}) =>
  chatRequest<RecommendationResponse>('/v1/quality/recommendations', token, 'POST', body);
