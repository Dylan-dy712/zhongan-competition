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
  case_id?:string; source_name?:string; document_type?:string; media_type?:string;
  bbox?:[number,number,number,number]|null;
}

export interface AssistantAnswer {
  answer: string;
  citations: { claim_id: string; evidence_refs: string[] }[];
  uncertainty: string | null;
  model_id: string;
  prompt_version: string;
}

export interface Conversation {
  subject_id: string;
  conversation_id: string; case_id: string; title: string; recall_enabled: boolean;
  title_pending?:boolean;
  has_interpretation_report?:boolean;
  memory_export_enabled?:boolean; memory_settings_version?:number;
  report_context_enabled?:boolean; report_context_version?:number;
  created_at: string; updated_at: string;
}
export type PatientField='followup_time'|'followup_location'|'medication'|'allergy'|'recovery_status';
export interface ClarificationQuestion {field:PatientField;question:string;options:{label:string;message:string}[]}
export interface PatientUpdate {field:PatientField;statement:string}
export interface ChatAnswer {text: string; evidence_refs: string[]; history_refs: string[];
  memory_refs?:{memory_id:string;version:number;epoch:number}[];memory_status?:string;memory_unavailable?:boolean;
  clarification_questions?:ClarificationQuestion[];suggested_questions?:string[];patient_updates?:PatientUpdate[];
  service_guide?:{text:string;policy_status:'demo_assumed_midhigh'};medical_services?:MedicalServices;
  sample_preload?:boolean;
  guidance_delivery?:{status:'passed'|'needs_improvement'|'unchecked';notice?:string};
  prompt_version?:string; analysis_run_id?:string; knowledge_refs?:string[]; knowledge_sources?:KnowledgeSource[]; citations?:InlineCitation[]}
export interface MedicalServiceCard {
  id:string;kind:'benefit'|'hospital'|'online';title:string;subtitle:string;description:string;tags:string[];
  reasons:string[];details:{label:string;value:string}[];notice:string;
  source:{title:string;url:string;pages:string;address_url?:string};
  action:{kind:'benefit'|'hospital'|'online';label:string;target_id:string};
}
export interface MedicalServices {
  version:string;status:'available'|'needs_location'|'no_local_matches'|'urgent';policy_label:string;policy_notice:string;
  location_query:string;location_prompt:string;notice?:string;cards:MedicalServiceCard[];
}
export interface InlineCitation {quote:string;source_refs:string[]}
export interface KnowledgeSource {entry_id:string;title:string;source:string;source_path?:string;scope:string;version:string;reference_policy?:string;content?:string;retrieval_provider?:string;retrieved_at?:string;published_at?:string}
export interface ToolEvent {tool: string; status: string; run_id?: string}
export interface ChatTurn {
  turn_id: string; request_id: string; question: string;
  input_kind: 'user'|'analysis_ready';
  attachments: {document_id:string; name:string;kind?:'chat_attachment'}[];
  status: 'running'|'completed'|'failed'; answer: ChatAnswer|null;
  tool_events: ToolEvent[]; created_at: string; error_code: string|null;
}
export interface ChatSnapshot {
  conversation: Conversation; turns: ChatTurn[];
  analysis: {status:string; run_id?:string; stage?:string; error?:unknown;stage_results?:{parse?:{reused_pages?:number;processed_pages?:number}}};
  report: {status:string; report_id?:string; report_version?:number; sections?:ReportSection[]; actions?:CareAction[]};
  material_report?: MaterialReport;
}
export interface MaterialReport {
  status:string; report_id?:string; run_id?:string; source_report_version?:number;
  document_count?:number; pending_count?:number; notice?:string;
  sections?: {section_type:ReportSection['section_type']; pending_count:number;
    items:{text:string; kind:'checked'|'source'; evidence_refs:string[]}[]}[];
}
export interface ChatSubject {subject_id:string; consent_id:string}

export interface RecordValue {value:string;evidence_refs:string[]}
export interface RecordBatch {
  case_id:string;conversations:Conversation[];updated_at:string;
  profile:Partial<Record<'diagnosis'|'hospital'|'period'|'kind'|'summary',RecordValue>>;
  analysis_status:string;document_count:number;organization_status:'pending'|'ready'|'needs_confirmation'|'unavailable';
  version:number;relation:string;assignment_source:'provisional'|'ai'|'user';
  proposed_record_id:string|null;proposal_title?:string|null;reason?:string|null;
}
export interface MedicalRecord {
  record_id:string;subject_id:string;title:string;cases:RecordBatch[];updated_at:string;
  document_count:number;conversation_count:number;related_records:{record_id:string;title:string}[];
  portrait?:RecordBatch['profile'];
}
export interface MedicalRecordsResponse {records:MedicalRecord[];unorganized_count:number;processing_count:number}

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

export interface PhotoQuality {material_type:string;type_certainty:'likely'|'unknown';status:'checked'|'warning'|'partial';issues:string[];ocr_status:string;recognized_excerpt:string;notice:string}
export interface ExtractedFact {field_id:string;fact_type:string;value:unknown;raw_value:string|null;status:string;assertion:string;unit:string|null;confidence_score:number|null;confidence_method:string|null;evidence_ids:string[];missing_reason:string|null;alternatives:{value:unknown;evidence_ids:string[]}[]}
export interface Insight {insight_id:string;category:'clinical'|'cost'|'experience';label:string;severity:string;rationale:string;uncertainty:string|null;suggested_action:string;review_status:string;judgment_status:string;evidence_ids:string[];knowledge_refs:string[]}
export interface ProfileMetric {metric_name:string;label:string;value:number|null;unit:string;sample_count:number;missing_rate:number;window_start:string;window_end:string;comparison_allowed:boolean;limitations:string[];metric_ref:string}
export interface QualityProfile {entity_id:string;entity_type:string;display_name:string;cohort_filters:{disease_group:string;treatment_group:string;risk_group:string|null;payer_group:string|null};metrics:ProfileMetric[]}
export interface QualitySnapshot {snapshot_id:string;data_origin:string;dataset_version:string;policy:{status:string};profiles:QualityProfile[];limitations?:string[]}
