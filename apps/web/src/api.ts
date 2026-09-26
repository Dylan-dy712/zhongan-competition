import type { AssistantAnswer, Evidence, Report, Conversation, ChatSnapshot, ChatSubject, ChatTurn } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, public status: number, public traceId?: string) { super(message); }
}

async function request<T>(path: string, token: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(detail?.message || `请求失败（${response.status}）`, response.status, detail?.trace_id);
  }
  return response.json() as Promise<T>;
}

export const getReport = (caseId: string, version: number, token: string) =>
  request<Report>(`/v1/cases/${encodeURIComponent(caseId)}/reports/${version}`, token);

export const getEvidence = (evidenceId: string, token: string) =>
  request<Evidence>(`/v1/evidence/${encodeURIComponent(evidenceId)}`, token);

export async function askAssistant(caseId: string, reportVersion: number, question: string, token: string) {
  const response = await fetch(`${API_BASE}/v1/cases/${encodeURIComponent(caseId)}/assistant/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ question, report_version: reportVersion })
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(detail?.message || `请求失败（${response.status}）`, response.status, detail?.trace_id);
  }
  return response.json() as Promise<AssistantAnswer>;
}

async function chatRequest<T>(path: string, token: string, method = 'GET', data?: unknown): Promise<T> {
  const multipart = data instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {Authorization: `Bearer ${token}`, ...(!multipart && data !== undefined ? {'Content-Type':'application/json'} : {})},
    body: data === undefined ? undefined : multipart ? data : JSON.stringify(data),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(detail?.message || `请求失败（${response.status}）`, response.status, detail?.trace_id);
  }
  return response.json() as Promise<T>;
}
export const listConversations = (token: string) => chatRequest<Conversation[]>('/v1/conversations', token);
export const listSubjects = (token: string) => chatRequest<ChatSubject[]>('/v1/chat/subjects', token);
export const createConversation = (token: string, conversationId: string, subjectId?: string, caseId?: string) =>
  chatRequest<Conversation>('/v1/conversations', token, 'POST', {conversation_id:conversationId, subject_id:subjectId || null, case_id:caseId || null});
export const getConversation = (token: string, id: string) => chatRequest<ChatSnapshot>(`/v1/conversations/${id}`, token);
export const getOlderTurns = (token: string, id: string, before: string) =>
  chatRequest<ChatTurn[]>(`/v1/conversations/${id}/turns?before=${encodeURIComponent(before)}`, token);
export const sendChatMessage = (token: string, id: string, requestId: string, message: string, documentIds: string[]) =>
  chatRequest(`/v1/conversations/${id}/messages`, token, 'POST', {request_id:requestId, message, document_ids:documentIds});
export const continueAnalysis = (token: string, id: string, runId: string) =>
  chatRequest(`/v1/conversations/${id}/analyses/${runId}/continue`, token, 'POST');
export const setRecall = (token: string, id: string, enabled: boolean) =>
  chatRequest(`/v1/conversations/${id}/recall`, token, 'PATCH', {enabled});
export const uploadChatDocument = (token: string, id: string, file: File) => {
  const data = new FormData(); data.append('file', file);
  return chatRequest<{document_id:string; source_ref:string}>(`/v1/conversations/${id}/documents`, token, 'POST', data);
};
