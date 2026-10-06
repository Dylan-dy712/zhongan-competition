export type ClaimType = "case_fact" | "professional_explanation" | "patient_statement" | "service_suggestion" | "to_confirm";

export interface Claim {
  claim_id: string;
  text: string;
  claim_type: ClaimType;
  evidence_refs: string[];
  knowledge_refs: string[];
  source_refs: string[];
  review_status: "not_required" | "pending" | "approved" | "corrected" | "rejected";
}

export interface ReportSection {
  section_type: "diagnosis_explanation" | "treatment_review" | "cost_explanation" | "recovery_plan" | "emotional_support" | "next_visit_advice";
  claims: Claim[];
}

export interface CareAction {
  action_id: string;
  report_id: string;
  action_text: string;
  owner_role: "patient" | "caregiver" | "clinician" | "customer_service";
  due_at: string | null;
  due_source: string;
  status: string;
  priority: number;
  rationale: string;
  source_refs: string[];
}

export interface Report {
  report_id: string;
  case_id: string;
  run_id: string;
  report_version: number;
  status: string;
  sections: ReportSection[];
  actions: CareAction[];
  created_at: string;
  validation_errors: string[];
}

export interface Evidence {
  evidence_id: string;
  document_id: string;
  document_version: number;
  page_index: number | null;
  text_span: { text: string; start: number; end: number } | null;
  extraction_method: string;
}

export interface AssistantAnswer {
  answer: string;
  citations: { claim_id: string; evidence_refs: string[] }[];
  uncertainty: string | null;
  model_id: string;
  prompt_version: string;
}

export interface Conversation {
  conversation_id: string; case_id: string; title: string; recall_enabled: boolean;
  report_context_enabled?:boolean; report_context_version?:number;
  created_at: string; updated_at: string;
}
export interface ChatAnswer {text: string; evidence_refs: string[]; history_refs: string[]}
export interface ToolEvent {tool: string; status: string; run_id?: string}
export interface ChatTurn {
  turn_id: string; request_id: string; question: string;
  input_kind: 'user'|'analysis_ready';
  attachments: {document_id:string; name:string}[];
  status: 'running'|'completed'|'failed'; answer: ChatAnswer|null;
  tool_events: ToolEvent[]; created_at: string; error_code: string|null;
}
export interface ChatSnapshot {
  conversation: Conversation; turns: ChatTurn[];
  analysis: {status:string; run_id?:string; stage?:string; error?:unknown};
  report: {status:string; report_id?:string; report_version?:number; sections?:ReportSection[]; actions?:CareAction[]};
}
export interface ChatSubject {subject_id:string; consent_id:string}

export interface DeliveryNotice {
  outbox_id:string; case_id:string; report_id:string; report_version:number;
  message:string; channel:'app'; receipt_state:'pending'|'presented'|'read'; receipt_version:number;
}
export interface DeliveryReceipt {receipt_id:string; receipt_version:number; state:'presented'|'read'}
export type FeedbackType = 'helpful'|'not_helpful'|'inaccurate'|'needs_help';
export interface FeedbackResult {feedback_id:string; triage_status:'not_required'|'pending'|'resolved'}

export interface QualityRecommendation {
  candidate_id: string;
  entity_type: string;
  entity_name: string;
  eligible: boolean;
  match_reasons: {reason_code: string; text: string; metric_refs: string[]; need_refs: string[]}[];
  limitations: string[];
  ranking_allowed: boolean;
  rejection_reason: string | null;
  rank: number | null;
}

export interface RecommendationResponse {
  snapshot_id: string;
  data_origin: string;
  policy_status: string;
  results: QualityRecommendation[];
}
