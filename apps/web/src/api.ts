import type { AssistantAnswer, Evidence, Report } from "./types";

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
