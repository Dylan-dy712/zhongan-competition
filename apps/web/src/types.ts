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
