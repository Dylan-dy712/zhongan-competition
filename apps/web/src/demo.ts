import type { Evidence, Report } from "./types";

const ids = {
  report: "b621dce0-70a0-468c-a848-f52921f485da",
  case: "fc4ceec4-9a01-41ea-97b5-4db7356f96ca",
  run: "c0731e04-2160-41a6-bdf0-407a79cbb05c",
  diagnosis: "5bdcfedd-ef76-4740-a096-3d665e5a4d43",
  cost: "2f6580ce-8ed4-4d22-88f8-aeeef82adab6"
};

const claim = (id: string, text: string, type: "case_fact" | "professional_explanation" | "service_suggestion" | "to_confirm", refs: string[] = []): any => ({
  claim_id: id, text, claim_type: type,
  evidence_refs: type === "case_fact" ? refs : [],
  knowledge_refs: type === "professional_explanation" ? ["FY-S1-001"] : [],
  source_refs: type === "service_suggestion" ? ["care-policy-v1"] : [],
  review_status: type === "professional_explanation" || type === "to_confirm" ? "approved" : "not_required"
});

export const demoReport: Report = {
  report_id: ids.report, case_id: ids.case, run_id: ids.run, report_version: 1,
  status: "published", created_at: "2026-09-25T15:30:00+08:00", validation_errors: [],
  sections: [
    { section_type: "diagnosis_explanation", claims: [
      claim("c1", "材料记录的主要诊断为社区获得性肺炎。它通常表示肺部受到感染，需要按医嘱完成治疗并观察呼吸和体温变化。", "case_fact", [ids.diagnosis]),
      claim("c2", "多数恢复过程需要时间，症状减轻后仍可能有一段乏力期。", "professional_explanation")
    ]},
    { section_type: "treatment_review", claims: [claim("c3", "本次住院完成了抗感染与对症治疗，出院记录显示总体情况稳定。", "case_fact", [ids.diagnosis])]},
    { section_type: "cost_explanation", claims: [claim("c4", "材料所列医疗总费用为 8,426.37 元；具体医保结算和自付金额以正式票据为准。", "case_fact", [ids.cost])]},
    { section_type: "recovery_plan", claims: [claim("c5", "保持充足休息与适量饮水，活动量可以根据耐受情况逐步增加。", "professional_explanation")]},
    { section_type: "emotional_support", claims: [claim("c6", "刚出院时对恢复速度感到担心很常见。把每天的体温和感受简单记下来，会更容易看见变化。", "service_suggestion")]},
    { section_type: "next_visit_advice", claims: [claim("c7", "复诊时间在现有材料中没有明确记录，请联系原就诊机构确认。若出现呼吸困难加重、口唇发紫或持续高热，请及时就医。", "to_confirm")]}
  ],
  actions: [
    { action_id: "a1", report_id: ids.report, source_refs: [ids.diagnosis], owner_role: "patient", action_text: "每天早晚测量体温并记录", due_at: null, due_source: "unknown", status: "proposed", priority: 1, rationale: "帮助观察恢复趋势" } as any,
    { action_id: "a2", report_id: ids.report, source_refs: ["FY-S7-001"], owner_role: "patient", action_text: "联系医院确认复诊时间", due_at: null, due_source: "unknown", status: "proposed", priority: 2, rationale: "现有材料没有明确复诊日期" } as any,
    { action_id: "a3", report_id: ids.report, source_refs: ["FY-S9-001"], owner_role: "caregiver", action_text: "留意呼吸困难等危险信号", due_at: null, due_source: "unknown", status: "proposed", priority: 3, rationale: "出现危险信号需要及时就医" } as any
  ]
};

export const demoEvidence: Record<string, Evidence> = {
  [ids.diagnosis]: { evidence_id: ids.diagnosis, document_id: "8a88bd0a-25ae-442b-bdef-cf3be1515246", document_version: 1, page_index: 1, extraction_method: "native_pdf_text", text_span: { start: 124, end: 167, text: "出院诊断：社区获得性肺炎。经抗感染及对症治疗，患者病情好转，生命体征平稳。" } },
  [ids.cost]: { evidence_id: ids.cost, document_id: "91f74b04-a72f-4ae5-b248-8ff72f84aa18", document_version: 1, page_index: 0, extraction_method: "native_pdf_text", text_span: { start: 82, end: 103, text: "医疗费用总额：8426.37元" } }
};
