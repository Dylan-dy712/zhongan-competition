"""Opt-in configured-provider smoke using fixed synthetic text, never an official KR score.

Run manually with LLM_* configured. No test double/fallback and no credentials,
provider payloads or patient data are emitted. Synthetic inputs are fixed below.
"""
import json
from uuid import uuid4

from services.api.app.cost_breakdown import report_cost_context
from services.api.app.report_builder import SECTION_TYPES, map_report_sources, validate_and_complete
from services.api.app.report_llm import PROMPT_VERSION, draft_report
from services.api.app.review_service import REVIEWABLE_REPORT_ERRORS


def main():
    material=('合成测试出院小结，不是真实患者资料。\n出院诊断：肺炎\n住院天数：5天\n'
              '住院用药：头孢曲松\n出院医嘱：不适随诊\n医疗总费用：2000元\n'
              '药品费：800元\n检查费：1200元\n个人自费：100元\n现金支付：300元')
    context={'concern':'看到两个支付金额，不确定自己到底付了多少，也担心恢复慢'}
    sources={'case:user_context':str(context)}
    ref=str(uuid4())
    evidence={ref:material}
    result=draft_report(material,[],context,report_cost_context([{'evidence_id':ref,'text':material}]))
    if result['status']!='completed':
        raise RuntimeError('configured report provider did not produce a valid six-section draft')
    sections,actions,errors=validate_and_complete(map_report_sources(result['draft'],evidence,sources),
                                                 evidence,set(),sources)
    hard_errors=sorted(set(errors)-REVIEWABLE_REPORT_ERRORS)
    user_claims=[c for s in sections for c in s.claims if c.claim_type=='patient_statement'
                 and c.source_refs==['case:user_context'] and not c.evidence_refs]
    user_actions=[a for a in actions if 'case:user_context' in a['source_refs']]
    cost_claims=[c for s in sections if s.section_type=='cost_explanation' for c in s.claims
                 if c.claim_type=='case_fact' and str(c.evidence_refs[0])==ref]
    passed=(not hard_errors and bool(user_claims) and bool(user_actions) and bool(cost_claims)
            and {s.section_type for s in sections}==set(SECTION_TYPES)
            and all(a.get('due_at') is None for a in actions))
    print(json.dumps({'mode':'fixed-synthetic-text/real-provider','prompt_version':PROMPT_VERSION,
        'status':'passed' if passed else 'failed','sections':len(sections),'user_claims_retained':len(user_claims),
        'user_actions_retained':len(user_actions),'cost_claims_with_evidence':len(cost_claims),
        'hard_errors':hard_errors,'review_errors':sorted(set(errors)&REVIEWABLE_REPORT_ERRORS),
        'official_kr_verified':False}))
    if not passed:
        raise SystemExit(1)


if __name__=='__main__':
    main()
